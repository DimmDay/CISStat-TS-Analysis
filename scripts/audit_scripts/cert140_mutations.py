# scripts/audit_scripts/cert140_mutations.py
"""Мутационное тестирование сертификации Task 140 (N-HiTS vertical slice).

Протокол сертификаций Task 138/139 (cert138/cert139_mutations.py):
- каждая мутация -- минимальная точечная правка КОДА (одна строка /
  выражение), применяемая с проверкой "ровно одно вхождение";
- прогон kill-подмножества в СВЕЖЕМ subprocess (in-process недействителен);
- после каждой мутации файл восстанавливается из git, хэш сверяется --
  рабочее дерево обязано остаться байт-чистым;
- вердикт KILLED (упало >= 1 тестов kill-подмножества) / SURVIVED.

Kill-подмножество едино для всех мутаций -- cert140_oracles.py
(34 независимых оракула аудитора на СОБСТВЕННЫХ данных; в каждом
случае проверено, какой оракул убивает какую мутацию).

Классы мутаций: гейт окна (M01), пол MIN_TRAIN (M02), NaN-гейт входа
(M03), clamp-инвариант (M04), выходной isfinite (M05), capacity
passthrough (M06), contract-wrap (M07), env fail-closed (M08/M09),
alias (M10), interpolation-kwargs (M11), freq-метаданные (M12), выбор
interval-колонок (M13), intervals.method (M14), реестр (M15/M17),
dispatch (M16), память-гейт Task 138c (M18), yaml-ось (M19), контроль
длины прогноза (M20), анти-тампер бюджета (M21/M22).

Запуск: OMP_NUM_THREADS=1 python3 scripts/audit_scripts/cert140_mutations.py
Батч-режим: ... cert140_mutations.py M01 M02 ... (урок Task 139 --
фоновые кампании ОС убивает, гонять foreground батчами).
"""
from __future__ import annotations

import hashlib
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

ORACLE_SUBSET = ["scripts/audit_scripts/cert140_oracles.py"]

# (id, файл, old, new, kill-подмножество)
MUTATIONS = [
    # -- nhits.py: гейты и fail-closed --
    ("M01", "apps/api/model_impls/nhits.py",
     'if nobs < normalized["input_size"] + int(horizon):',
     'if nobs < normalized["input_size"]:', ORACLE_SUBSET),
    ("M02", "apps/api/model_impls/nhits.py",
     "if nobs < NHITS_MIN_TRAIN:",
     "if nobs < 5:", ORACLE_SUBSET),
    ("M03", "apps/api/model_impls/nhits.py",
     "    if not np.isfinite(vector).all():",
     "    if False and not np.isfinite(vector).all():", ORACLE_SUBSET),
    ("M04", "apps/api/model_impls/nhits.py",
     "    if not ((lower_arr <= point).all() and (point <= upper_arr).all()):",
     "    if False and ((lower_arr <= point).all() and (point <= upper_arr).all()):",
     ORACLE_SUBSET),
    ("M05", "apps/api/model_impls/nhits.py",
     "    if not (np.isfinite(point).all() and np.isfinite(lower).all()",
     "    if False and (np.isfinite(point).all() and np.isfinite(lower).all()",
     ORACLE_SUBSET),
    ("M06", "apps/api/model_impls/nhits.py",
     "        raise\n    except NeuralContractError as exc:",
     "        pass\n    except NeuralContractError as exc:", ORACLE_SUBSET),
    ("M07", "apps/api/model_impls/nhits.py",
     '        raise ValueError(f"N-HiTS: {exc}") from exc\n\n    model_name = "NHITS"',
     '        raise\n\n    model_name = "NHITS"', ORACLE_SUBSET),
    ("M08", "apps/api/model_impls/nhits.py",
     "    if value < 1:", "    if value < 0:", ORACLE_SUBSET),
    ("M09", "apps/api/model_impls/nhits.py",
     "        return NHITS_MAX_STEPS", "        return NHITS_MAX_STEPS + 7",
     ORACLE_SUBSET),
    ("M10", "apps/api/model_impls/nhits.py",
     '            alias="NHITS",', '            alias="NHITSX",', ORACLE_SUBSET),
    ("M11", "apps/api/model_impls/nhits.py",
     '            "n_pool_kernel_size": [2, 2, 1],',
     '            "n_pool_kernel_size": [2, 1, 1],', ORACLE_SUBSET),
    ("M12", "apps/api/model_impls/nhits.py",
     '{"kind": "integer", "value": 1}',
     '{"kind": "integer", "value": 12}', ORACLE_SUBSET),
    ("M13", "apps/api/model_impls/nhits.py",
     'lower = _interval_column(preds, model_name, "lo", float(plan.levels[0]))',
     'lower = _interval_column(preds, model_name, "lo", float(plan.levels[-1]))',
     ORACLE_SUBSET),
    ("M14", "apps/api/model_impls/nhits.py",
     '            "method": "conformal",', '            "method": "quantile",',
     ORACLE_SUBSET),
    ("M20", "apps/api/model_impls/nhits.py",
     "    if len(point) != int(horizon):",
     "    if False and len(point) != int(horizon):", ORACLE_SUBSET),
    ("M21", "apps/api/model_impls/nhits.py",
     "NHITS_MAX_STEPS = 300", "NHITS_MAX_STEPS = 99", ORACLE_SUBSET),
    ("M22", "apps/api/model_impls/nhits.py",
     "NHITS_MIN_TRAIN = 30", "NHITS_MIN_TRAIN = 200", ORACLE_SUBSET),
    # -- проводка: реестр / dispatch / runtime / yaml --
    ("M15", "apps/api/model_execution.py",
     'model_id="nhits", family_id="neural",',
     'model_id="nhitsx", family_id="neural",', ORACLE_SUBSET),
    ("M16", "apps/api/routers/models.py",
     'implementations["nhits"] = run_nhits_backtest',
     'implementations["nhitsx"] = run_nhits_backtest', ORACLE_SUBSET),
    ("M17", "apps/api/model_execution.py",
     'adapter_id="neuralforecast-nhits",',
     'adapter_id="neuralforecast-nbeats",', ORACLE_SUBSET),
    ("M18", "apps/api/model_impls/neural_runtime.py",
     "    ensure_neural_memory_capacity()\n"
     "    try:\n        import neuralforecast as _neuralforecast_module",
     "    try:\n        import neuralforecast as _neuralforecast_module",
     ORACLE_SUBSET),
    ("M19", "rules/modeling.yaml",
     'interpolation_config: ["hierarchical", "light"]\n          hidden_size: [32, 64]',
     'interpolation_config: ["hierarchical", "light"]\n          hidden_size: [32]',
     ORACLE_SUBSET),
]


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git_head_sha(rel: str) -> str:
    out = subprocess.run(
        ["git", "show", f"HEAD:{rel}"], cwd=REPO, capture_output=True
    )
    if out.returncode != 0:
        raise RuntimeError(f"git show failed for {rel}: {out.stderr.decode()}")
    return hashlib.sha256(out.stdout).hexdigest()


def _apply(rel: str, old: str, new: str) -> None:
    path = REPO / rel
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(
            f"{rel}: ожидалось ровно 1 вхождение, найдено {count}:\n{old[:120]}"
        )
    path.write_text(text.replace(old, new), encoding="utf-8")


def _restore(rel: str, expected_sha: str) -> None:
    path = REPO / rel
    subprocess.run(["git", "checkout", "--", rel], cwd=REPO, check=True)
    if _sha(path) != expected_sha:
        raise RuntimeError(f"{rel}: восстановление не байт-чистое")


def _run_kill_subset(subset: list[str]) -> tuple[bool, str]:
    """Свежий subprocess: pytest kill-подмножества; True == все зелёные."""
    cmd = [sys.executable, "-m", "pytest", *subset, "-q", "--no-header",
           "-p", "no:cacheprovider", "--tb=no"]
    proc = subprocess.run(cmd, cwd=REPO, capture_output=True, text=True,
                          env={**os.environ, "OMP_NUM_THREADS": "1"})
    tail = (proc.stdout or "").strip().splitlines()[-1:] or ["<no output>"]
    return proc.returncode == 0, tail[0][:160]


def main() -> int:
    only = set(sys.argv[1:])
    batch = [m for m in MUTATIONS if not only or m[0] in only]
    print(f"Мутационная кампания Task 140: {len(batch)}/{len(MUTATIONS)} мутаций"
          f"{'' if not only else ' (батч: ' + ' '.join(sorted(only)) + ')'}")
    results: list[tuple[str, str, str]] = []
    for mid, rel, old, new, subset in batch:
        path = REPO / rel
        baseline_sha = _sha(path)
        head_sha = _git_head_sha(rel)
        if baseline_sha != head_sha:
            raise RuntimeError(f"{rel}: рабочее дерево не совпадает с HEAD "
                               "-- кампания запускается только на чистом дереве")
        try:
            _apply(rel, old, new)
            ok, tail = _run_kill_subset(subset)
            verdict = "SURVIVED" if ok else "KILLED"
        finally:
            _restore(rel, baseline_sha)
        results.append((mid, verdict, tail))
        print(f"{mid} {verdict:>8}  | {tail}", flush=True)

    killed = sum(1 for _, verdict, _ in results if verdict == "KILLED")
    print(f"\nИтог: {killed}/{len(results)} KILLED")
    survivors = [mid for mid, verdict, _ in results if verdict == "SURVIVED"]
    print("Survivors:", survivors or "нет")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
