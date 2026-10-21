# scripts/cert_3b/mutations.py
"""PANEL-MODELS-3b certification: mutation campaign (OWN mutants, two channels).

Каждый мутант -- точечная байтовая замена (ровно 1 вхождение, md5-паспорт,
побайтовое восстановление). Каналы:
  ORACLE -- scripts/cert_3b/oracle_backend.py (свои данные, exit != 0 => KILL)
  REPO    -- tests/unit/test_panel_models.py + tests/api/test_panel_execution.py
             (exit != 0 => KILL)
Мутант KILLED, если хотя бы один канал краснеет; ALIVE -- оба зелёные.

ОБЛАСТЬ: только файлы этапа 3b (panel_models.py, движок panel_entity в
backtesting.py, реестр/executor, model_impls/panel_entity.py, dispatch,
rules/modeling.yaml). VAR-внутренности fit_panel_var ИСКЛЮЧЕНЫ из кампании:
живой дефект dummy-блока (см. акт) делает оракульный канал постоянно красным
в зоне VAR-восстановления -- мутационная валидация VAR отложена до фикса.

No-op контроли: CTL-B01 (комментарий), CTL-B02 (неактивная ветка),
CTL-B03 (перестановка независимых строк) -- обязаны быть ALIVE.
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
    "backtesting": REPO / "apps" / "api" / "backtesting.py",
    "model_execution": REPO / "apps" / "api" / "model_execution.py",
    "panel_entity_impl": REPO / "apps" / "api" / "model_impls" / "panel_entity.py",
    "routers_models": REPO / "apps" / "api" / "routers" / "models.py",
    "modeling_yaml": REPO / "rules" / "modeling.yaml",
}

REPO_CHANNEL = [sys.executable, "-m", "pytest",
                "tests/unit/test_panel_models.py",
                "tests/api/test_panel_execution.py",
                "-x", "-q", "--no-header", "-p", "no:cacheprovider"]
ORACLE_CHANNEL = [sys.executable, "scripts/cert_3b/oracle_backend.py"]

# ── мутанты: (id, file, old, new, ожидание) ─────────────────────────────────
# expectation: "KILL" | "EQUIV" (равносильный, документируется) | "ALIVE-CTL"

MUTANTS = [
    # ── гейты FE/RE и капы ──
    ("PM-B01", "panel_models", "frame.n_entities < MIN_ENTITIES_FE_RE",
     "frame.n_entities < MIN_ENTITIES_FE_RE - 1", "KILL"),
    ("PM-B02", "panel_models", 'frame.t_per_entity["min"] < MIN_T_PER_ENTITY_FE_RE',
     'frame.t_per_entity["min"] < MIN_T_PER_ENTITY_FE_RE - 1', "KILL"),
    ("PM-B03", "panel_models", "if n_exog < 1:", "if n_exog < 0:", "KILL"),
    ("PM-B04", "panel_models", "if n_entities > CAPACITY_REFUSE_ENTITIES:",
     "if n_entities > CAPACITY_REFUSE_ENTITIES + 10000:", "KILL"),
    ("PM-B05", "panel_models", "if n_entities > CAPACITY_WARN_ENTITIES:",
     "if n_entities > CAPACITY_WARN_ENTITIES + 10000:", "KILL"),
    # ── FE: within-арифметика, эффекты, R2, кластерная V ──
    ("PM-B06", "panel_models",
     'y_w = (y - grouped[target].transform("mean").to_numpy(dtype=float))',
     "y_w = (y - 0.0)", "KILL"),
    ("PM-B07", "panel_models",
     "float(y_means.loc[entity_value] - row @ beta)",
     "float(y_means.loc[entity_value])", "KILL"),
    ("PM-B08", "panel_models", "r2_within = float(fitted.rsquared)",
     "r2_within = float(fitted.rsquared) * 0.5", "KILL"),
    ("PM-B09", "panel_models",
     "between = sm.OLS(y_means.to_numpy(dtype=float), "
     "sm.add_constant(x_means[exog].to_numpy(dtype=float))).fit()",
     "between = sm.OLS(y_means.to_numpy(dtype=float), "
     "x_means[exog].to_numpy(dtype=float)).fit()", "KILL"),
    ("PM-B10", "panel_models", "df_res = len(y_w) - frame.n_entities - len(exog)",
     "df_res = len(y_w)", "KILL"),
    ("PM-B11", "panel_models",
     'fitted = ols.fit(cov_type="cluster", cov_kwds={"groups": codes})',
     'fitted = ols.fit(cov_type="HC1")', "KILL"),
    ("PM-B12", "panel_models",
     "[np.ones(len(data)), x, dummies] if dummies.size else [np.ones(len(data)), x]",
     "[x, dummies] if dummies.size else [x]", "KILL"),
    ("PM-B13", "panel_models", "FE_CROSS_VALIDATION_TOLERANCE = 1e-8",
     "FE_CROSS_VALIDATION_TOLERANCE = 1e100", "EQUIV"),
    # ── RE: Swamy-Arora ──
    ("PM-B14", "panel_models", "sigma_u2 = 0.0", "pass", "KILL"),
    ("PM-B15", "panel_models",
     "thetas = 1.0 - np.sqrt(sigma_e2 / (sigma_e2 + t_sizes.to_numpy() * sigma_u2))",
     "thetas = 1.0 - np.sqrt(sigma_e2 / (sigma_e2 + sigma_u2))", "KILL"),
    ("PM-B16", "panel_models", "entity_offset = result.intercept",
     "entity_offset = result.entity_effects[entity]", "KILL"),
    # ── Хаусман (Мундлак) ──
    ("PM-B17", "panel_models", "gamma_slice = slice(1 + n_x, 1 + 2 * n_x)",
     "gamma_slice = slice(1, 1 + n_x)", "KILL"),
    ("PM-B18", "panel_models",
     '"fixed_effects" if p_value < significance_level else "random_effects"',
     '"random_effects" if p_value < significance_level else "fixed_effects"',
     "KILL"),
    ("PM-B19", "panel_models", "if frame.n_entities < MIN_ENTITIES_HAUSMAN:",
     "if frame.n_entities < 0:", "KILL"),
    ("PM-B20", "panel_models",
     "if not np.isfinite(statistic) or statistic < 0.0:", "if False:", "EQUIV"),
    # ── folds ──
    ("PM-B29", "panel_models", "train_end = test_start - 1 - gap",
     "train_end = test_start - 1", "KILL"),
    ("PM-B30", "panel_models",
     "test_end = len(dates) - (horizon + gap) * (n_folds - fold_index)",
     "test_end = len(dates) - (horizon + gap) * (n_folds - fold_index - 1)",
     "KILL"),
    ("PM-B31", "panel_models", "max(horizon * n_folds, min_train)",
     "min_train", "KILL"),
    ("PM-B32", "panel_models", "if len(dates) < needed:", "if False:", "KILL"),
    ("PM-B33", "panel_models",
     "else 3 * len(frame.value_columns) * 2  # эвристика VAR(1) как базовая",
     "else 3  # эвристика VAR(1) как базовая", "KILL"),
    # ── движок run_panel_entity_backtest_plan ──
    ("PM-B34", "backtesting", "sub_frame = build_panel_frame(\n                train_df,",
     "sub_frame = build_panel_frame(\n                data,", "KILL"),
    ("PM-B35", "backtesting", "for value in entity_test[name]]",
     "for value in entity_test[name] * 2]", "KILL"),
    ("PM-B36", "backtesting",
     "pooled_mase_scale = float(np.median(mase_scales)) if mase_scales else None",
     "pooled_mase_scale = float(np.max(mase_scales)) if mase_scales else None",
     "KILL"),
    ("PM-B37", "backtesting", 'series["train_target"], seasonal_period,',
     'series["actual"], seasonal_period,', "KILL"),
    ("PM-B38", "backtesting",
     'if execution_contract.get("input_kind") != "panel_entity":',
     'if execution_contract.get("input_kind") == "panel_entity":', "KILL"),
    # ── реестр / executor ──
    ("ME-B40", "model_execution",
     'adapter_id="panel-within-ols", executor=_panel_entity_executor,\n'
     '        actions=_BACKTEST_DIAGNOSTICS, engine="statsmodels",\n'
     '        required_packages=("statsmodels",),\n'
     '        input_kind="panel_entity",',
     'adapter_id="panel-within-ols", executor=_panel_entity_executor,\n'
     '        actions=_BACKTEST_DIAGNOSTICS, engine="statsmodels",\n'
     '        required_packages=("statsmodels",),\n'
     '        input_kind="panel",', "KILL"),
    ("ME-B41", "model_execution",
     'исполняются ТОЛЬКО панельным движком run_panel_entity_backtest_plan: "',
     'исполняются ТОЛЬКО панельным движком run_panel_backtest_plan: "', "KILL"),
    # ── отказной модуль / dispatch / каталог ──
    ("PE-B42", "panel_entity_impl", "(checkpoint panel_entry)",
     "(checkpoint modeling_entry)", "KILL"),
    ("RM-B43", "routers_models", '"panel_fe": run_panel_entity_backtest_refusal,',
     '"panel_fe": run_var_backtest,', "KILL"),
    ("YM-B44", "modeling_yaml", 'condition: "model.family == \'panel\'"',
     'condition: "model.family == \'never\'"', "KILL"),
    ("YM-B45", "modeling_yaml",
     "min_series: 5              # минимум сущностей панели",
     "min_series: 1              # минимум сущностей панели", "KILL"),
    # ── no-op контроли (обязаны быть ALIVE) ──
    ("CTL-B01", "panel_models",
     "#: Допуск кросс-валидации within vs dummies-реализации (спека §3b, R3).",
     "#: Допуск кросс-валидации within vs dummies-реализации (спека §3b, R3). CTL",
     "ALIVE-CTL"),
    ("CTL-B02", "panel_models",
     "ковариация между-членов сингулярна",
     "ковариация между-членов вырождена", "ALIVE-CTL"),
    ("CTL-B03", "panel_models",
     "    y_means = grouped[target].mean()\n    x_means = grouped[exog].mean()\n"
     "    effects: Dict[str, float] = {}\n    for entity_value in x_means.index:",
     "    x_means = grouped[exog].mean()\n    y_means = grouped[target].mean()\n"
     "    effects: Dict[str, float] = {}\n    for entity_value in x_means.index:",
     "ALIVE-CTL"),
]


def md5(data: bytes) -> str:
    return hashlib.md5(data).hexdigest()


def run(cmd: list[str], cwd: Path, timeout: int) -> tuple[int, str]:
    proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True,
                          timeout=timeout)
    return proc.returncode, (proc.stdout + proc.stderr)[-20000:]


def oracle_failed_ids(cwd: Path) -> set[str]:
    """Множество проваленных проверок оракула (дефект-осведомлённая база).

    Парсится итоговая строка "FAILED: O30a, O32, ..." (полный список) --
    построчный парс как fallback. Полный stdout (20000 хвост) страховка.
    """
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
    original: dict[str, bytes] = {k: p.read_bytes() for k, p in FILES.items()}
    originals_md5 = {k: md5(v) for k, v in original.items()}
    print(f"PASSPORTS (md5 original): {originals_md5}")
    baseline_ids = oracle_failed_ids(REPO)
    print(f"ORACLE BASELINE (clean tree, defect-aware): {sorted(baseline_ids)}")
    results: list[tuple[str, str, str, float, str]] = []
    restore_failures = 0

    for mid, fkey, old, new, expectation in MUTANTS:
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
        # побайтовое восстановление
        FILES[fkey].write_bytes(original[fkey])
        restored = md5(FILES[fkey].read_bytes()) == originals_md5[fkey]
        if not restored:
            restore_failures += 1
        status = "KILLED" if channels else "ALIVE"
        if channels == ["ORACLE"]:
            diff_ids = sorted(mutant_ids ^ baseline_ids)
            note_ids = f"oracle-diff={diff_ids}"
        note = ""
        if expectation == "ALIVE-CTL" and status == "ALIVE":
            note = "control-ALIVE OK"
        elif expectation == "EQUIV" and status == "ALIVE":
            note = "equivalent (documented)"
        elif expectation == "KILL" and status == "ALIVE":
            note = "SURVIVOR -- разбор в акте"
        results.append((mid, status, "+".join(channels) or "-",
                        duration, note))
        print(f"{mid:8s} {status:6s} channel={'+'.join(channels) or '-':12s} "
              f"{duration:6.1f}s {note}")

    print("\n=== SUMMARY ===")
    killed = [r for r in results if r[1] == "KILLED"]
    alive = [r for r in results if r[1] == "ALIVE"]
    bad = [r for r in results if r[1] == "BAD-MUTANT"]
    print(f"TOTAL {len(results)} | KILLED {len(killed)} | ALIVE {len(alive)} "
          f"| BAD {len(bad)} | RESTORE-FAIL {restore_failures}")
    for mid, status, ch, _, note in alive:
        print(f"  ALIVE: {mid} ({note or 'unexpected'})")
    # финальная проверка чистоты дерева
    clean = all(md5(FILES[k].read_bytes()) == originals_md5[k] for k in FILES)
    print(f"TREE RESTORED BYTE-EXACT: {clean}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
