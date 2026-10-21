# scripts/cert_3b/mutations_var.py
"""PANEL-MODELS-3b-FIX: mutation campaign on Panel VAR internals (OWN mutants).

Довыход зоны, исключённой в кампании 3b (акт §5): живой дефект dummy-блока
делал оракульный канал постоянно красным в зоне VAR-восстановления. После
фикса (ячейковый dummy-блок, commit-fix PANEL-MODELS-3b-FIX) оба канала
имеют ЗЕЛЁНУЮ базу:
  ORACLE -- scripts/cert_3b/oracle_backend.py: 95/95 PASS (baseline failed-set = {})
  REPO    -- tests/unit/test_panel_models.py + tests/api/test_panel_execution.py
Мутант KILLED, если хотя бы один канал краснеет; ALIVE -- оба зелёные.

Мутант PMV-07 -- ТРИПВАЙР исторического дефекта (ячейковая запись -> колоночная):
обязан убиваться пинами/O-проверками (доказательство, что находка Cert 3b §4
теперь покрыта регрессионно).

No-op контроли: CTL-V01 (комментарий), CTL-V02 (неактивная ветка),
CTL-V03 (перестановка независимых строк) -- обязаны быть ALIVE.

md5-паспорт, побайтовое восстановление, финальная сверка дерева --
прецедент scripts/cert_3b/mutations.py.
"""
from __future__ import annotations

import hashlib
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

FILES = {
    "panel_models": REPO / "app" / "modeling" / "panel_models.py",
}

REPO_CHANNEL = [sys.executable, "-m", "pytest",
                "tests/unit/test_panel_models.py",
                "tests/api/test_panel_execution.py",
                "-x", "-q", "--no-header", "-p", "no:cacheprovider"]
ORACLE_CHANNEL = [sys.executable, "scripts/cert_3b/oracle_backend.py"]

# ── мутанты: (id, file, old, new, ожидание) ─────────────────────────────────
MUTANTS = [
    # ── гейты fit_panel_var ──
    ("PMV-01", "panel_models",
     'if frame.balance != BALANCED:\n        reasons.append(\n            "Panel VAR требует',
     'if False:\n        reasons.append(\n            "Panel VAR требует', "KILL"),
    ("PMV-02", "panel_models", "if frame.n_entities < MIN_ENTITIES_PANEL_VAR:",
     "if frame.n_entities < MIN_ENTITIES_PANEL_VAR - 1:", "KILL"),
    ("PMV-03", "panel_models", "if frame.n_dates_common < need:",
     "if frame.n_dates_common < need - 1:", "KILL"),
    # ── сборка дизайна ──
    ("PMV-04", "panel_models",
     "wide = _frame_matrix(subset, variables).reshape(n, t_common, k)",
     "wide = _frame_matrix(subset, variables).reshape(t_common, n, k)", "KILL"),
    ("PMV-05", "panel_models", "targets = wide[:, lags:, :]",
     "targets = wide[:, lags + 1:, :]", "KILL"),
    ("PMV-06", "panel_models",
     "wide[:, lags - ell: t_common - ell, :] for ell in range(1, lags + 1)",
     "wide[:, lags - ell: t_common - ell - 1, :] for ell in range(1, lags + 1)",
     "KILL"),
    # PMV-07: ТРИПВАЙР исторического дефекта Cert 3b §4 (колоночная запись).
    ("PMV-07", "panel_models", "dummies[index, index - 1] = 1.0",
     "dummies[:, index - 1] = 1.0", "KILL"),
    ("PMV-08", "panel_models", "dummies[index, index - 1] = 1.0",
     "dummies[index - 1, index - 1] = 1.0", "KILL"),
    # PMV-09: np.zeros((n, n)) при ячейковом цикле = drop_first-дамми +
    # нулевой столбец. Оценки (A/base/интерсепты) инвариантны (pinv
    # аннигилирует нулевой столбец), НО df_res считается по числу колонок
    # -> residual_variance_by_equation смещается ~1% -> убит df-пином
    # остаточной дисперсии (история: выживший до добавления пина,
    # убит после -- пин закрывает и PMV-16/17, и df-семантику PMV-09).
    ("PMV-09", "panel_models", "dummies = np.zeros((n, max(n - 1, 0)))",
     "dummies = np.zeros((n, n))", "KILL"),
    ("PMV-10", "panel_models",
     "[*design_blocks, const_block, dummy_block], axis=2,",
     "[*design_blocks, dummy_block, const_block], axis=2,", "KILL"),
    # ── разбор params ──
    ("PMV-11", "panel_models", "block = params[(ell - 1) * k: ell * k, :]",
     "block = params[ell * k: (ell + 1) * k, :]", "KILL"),
    ("PMV-12", "panel_models",
     "float(block[variables.index(var), variables.index(eq)])",
     "float(block[variables.index(eq), variables.index(var)])", "KILL"),
    ("PMV-13", "panel_models",
     "float(params[k * lags, variables.index(eq)]) for eq in variables",
     "float(params[k * lags + 1, variables.index(eq)]) for eq in variables",
     "KILL"),
    ("PMV-14", "panel_models",
     "float(params[k * lags + index, variables.index(eq)])",
     "float(params[k * lags + index - 1, variables.index(eq)])", "KILL"),
    ("PMV-15", "panel_models", "entity_intercepts[str(uniques[index])] = {",
     "entity_intercepts[str(uniques[index - 1])] = {", "KILL"),
    # ── R2 / дисперсии / last_states ──
    ("PMV-16", "panel_models", "df_res = len(y_flat) - x_flat.shape[1]",
     "df_res = len(y_flat) - x_flat.shape[1] - 1", "KILL"),
    ("PMV-17", "panel_models",
     "ss_res = float(np.sum((y_flat[:, eq_index] - fitted_eq) ** 2))",
     "ss_res = 0.0", "KILL"),
    ("PMV-18", "panel_models", "for t in range(t_common - lags, t_common)",
     "for t in range(t_common - lags, t_common - 1)", "KILL"),
    ("PMV-19", "panel_models",
     "{var: float(wide[:, t, j].mean()) for j, var in enumerate(variables)}",
     "{var: float(wide[:, t, j].mean() + 1.0) for j, var in enumerate(variables)}",
     "KILL"),
    # ── предупреждение малого T ──
    ("PMV-20", "panel_models", "if t_common < 3 * k * (lags + 2):",
     "if False:", "KILL"),
    # ── panel_var_forecast: рекурсия ──
    ("PMV-21", "panel_models", "if horizon < 1:", "if horizon < 0:", "KILL"),
    ("PMV-22", "panel_models", "value = intercepts[eq]",
     "value = result.base_intercept[eq]", "KILL"),
    ("PMV-23", "panel_models", "previous = state[-ell]",
     "previous = state[-ell - 1]", "KILL"),
    ("PMV-24", "panel_models",
     "result.entity_intercepts[e][eq] for e in result.entity_intercepts",
     "0.0 * result.entity_intercepts[e][eq] for e in result.entity_intercepts",
     "KILL"),
    ("PMV-25", "panel_models", "for ell in range(1, result.lags + 1):",
     "for ell in range(2, result.lags + 1):", "KILL"),
    ("PMV-26", "panel_models", "state.append(new_values)",
     "state.append(state[-1])", "KILL"),
    # ── no-op контроли (обязаны быть ALIVE) ──
    ("CTL-V01", "panel_models",
     "    dummy_block = np.repeat(dummies[:, None, :], t_common - lags, axis=1)",
     "    # PANEL-MODELS-3b-FIX: no-op control CTL-V01\n"
     "    dummy_block = np.repeat(dummies[:, None, :], t_common - lags, axis=1)",
     "ALIVE-CTL"),
    ("CTL-V02", "panel_models",
     "    )\n\n    warnings_list = []\n    if warn:\n        warnings_list.append(warn)",
     "    )\n\n    warnings_list = []\n    if False:\n"
     "        warnings_list.append('CTL-V02 inactive branch')\n"
     "    if warn:\n        warnings_list.append(warn)",
     "ALIVE-CTL"),
    ("CTL-V03", "panel_models",
     "    dummy_block = np.repeat(dummies[:, None, :], t_common - lags, axis=1)\n"
     "    const_block = np.ones((n, t_common - lags, 1))",
     "    const_block = np.ones((n, t_common - lags, 1))\n"
     "    dummy_block = np.repeat(dummies[:, None, :], t_common - lags, axis=1)",
     "ALIVE-CTL"),
]


def md5(data: bytes) -> str:
    return hashlib.md5(data).hexdigest()


def run(cmd: list[str], cwd: Path, timeout: int) -> tuple[int, str]:
    proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True,
                          timeout=timeout)
    return proc.returncode, (proc.stdout + proc.stderr)[-20000:]


def oracle_failed_ids(cwd: Path) -> set[str]:
    """Множество проваленных проверок оракула (база после фикса = {})."""
    rc, out = run(ORACLE_CHANNEL, cwd, timeout=600)
    ids: set[str] = set()
    for line in out.splitlines():
        if line.startswith("FAILED:"):
            ids = {x.strip() for x in line[len("FAILED:"):].split(",") if x.strip()}
    if not ids:
        for line in out.splitlines():
            parts = line.split()
            if len(parts) >= 2 and parts[1] == "FAIL" and parts[0].startswith("O"):
                ids.add(parts[0])
    if not ids and rc != 0:
        return {"<ORACLE-CRASH>"}
    return ids


def main() -> int:
    import os
    # Срез кампании (MUT_RANGE="a:b") -- для запуска частями в лимитах
    # песочницы; полный протокол собирается из частей, паспорта одни.
    lo, hi = (int(x) for x in os.environ.get("MUT_RANGE", "0:%d" % len(MUTANTS)).split(":"))
    subset = MUTANTS[lo:hi]
    print(f"RANGE {lo}:{hi} -> {len(subset)} mutants")
    original: dict[str, bytes] = {k: p.read_bytes() for k, p in FILES.items()}
    originals_md5 = {k: md5(v) for k, v in original.items()}
    print(f"PASSPORTS (md5 original, FIXED tree): {originals_md5}")
    baseline_ids = oracle_failed_ids(REPO)
    print(f"ORACLE BASELINE (fixed tree, all-green): {sorted(baseline_ids)}")
    if baseline_ids:
        print("ОШИБКА: база оракула не зелёная -- кампания запрещена")
        return 2
    results: list[tuple[str, str, str, float, str]] = []
    restore_failures = 0

    for mid, fkey, old, new, expectation in subset:
        data = original[fkey]
        count = data.count(old.encode("utf-8"))
        if count != 1:
            results.append((mid, "BAD-MUTANT", f"occurrences={count}", 0.0, old[:40]))
            print(f"{mid:8s} BAD-MUTANT occurrences={count} -- пропущен")
            continue
        mutated = data.replace(old.encode("utf-8"), new.encode("utf-8"), 1)
        FILES[fkey].write_bytes(mutated)
        passport = md5(FILES[fkey].read_bytes())
        started = time.monotonic()
        channels: list[str] = []
        try:
            mutant_ids = oracle_failed_ids(REPO)
            if mutant_ids != baseline_ids:
                channels.append("ORACLE")
        except subprocess.TimeoutExpired:
            channels.append("ORACLE-TIMEOUT")
        try:
            rc_r, out_r = run(REPO_CHANNEL, REPO, timeout=600)
            if rc_r != 0:
                channels.append("REPO")
        except subprocess.TimeoutExpired:
            channels.append("REPO-TIMEOUT")
        duration = time.monotonic() - started
        FILES[fkey].write_bytes(original[fkey])
        restored = md5(FILES[fkey].read_bytes()) == originals_md5[fkey]
        if not restored:
            restore_failures += 1
        status = "KILLED" if channels else "ALIVE"
        note = ""
        if expectation == "ALIVE-CTL" and status == "ALIVE":
            note = "control-ALIVE OK"
        elif expectation == "KILL" and status == "ALIVE":
            note = "SURVIVOR -- разбор в акте"
        results.append((mid, status, "+".join(channels) or "-",
                        duration, note))
        print(f"{mid:8s} {status:6s} channel={'+'.join(channels) or '-':12s} "
              f"{duration:6.1f}s md5={passport[:8]} {note}")

    print("\n=== SUMMARY ===")
    killed = [r for r in results if r[1] == "KILLED"]
    alive = [r for r in results if r[1] == "ALIVE"]
    bad = [r for r in results if r[1] == "BAD-MUTANT"]
    print(f"TOTAL {len(results)} | KILLED {len(killed)} | ALIVE {len(alive)} "
          f"| BAD {len(bad)} | RESTORE-FAIL {restore_failures}")
    for mid, status, ch, _, note in alive:
        print(f"  ALIVE: {mid} ({note or 'unexpected'})")
    clean = all(md5(FILES[k].read_bytes()) == originals_md5[k] for k in FILES)
    print(f"TREE RESTORED BYTE-EXACT: {clean}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
