# scripts/audit_scripts/cert139_mutations.py
"""Мутационное тестирование сертификации Task 139 (N-BEATS vertical slice).

Протокол сертификации Task 138 (cert138_mutations.py):
- каждая мутация -- минимальная точечная правка КОДА (одна строка /
  выражение), применяемая с проверкой "ровно одно вхождение";
- прогон kill-подмножества тестов в СВЕЖЕМ subprocess (in-process пробы
  недействительны -- урок сертификации Task 138);
- после каждой мутации файл восстанавливается из git и хэш сверяется --
  рабочее дерево обязано остаться байт-чистым;
- вердикт KILLED (упало >= 1 тестов kill-подмножества) / SURVIVED.

Классы мутаций: гейты (M1/M2), анти-тампер бюджета (M3/M4), fail-closed
env (M5), bool-коэрция (M6), bounds-пиннинг (M7), стековая альтернатива
(M8), clamp-инвариант (M9), выходной isfinite (M10), сид-проводка (M11),
env-проводка бюджета (M12), реестр (M13/M15), dispatch (M14), capacity
guard (M16/M17/M18), честный 503 (M19), alias (M20), выбор interval-
колонок (M21).

Запуск: OMP_NUM_THREADS=1 python3 scripts/audit_scripts/cert139_mutations.py
"""
from __future__ import annotations

import hashlib
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

ORACLE_SUBSET = [
    "tests/unit/test_nbeats_adapter.py",
    "tests/unit/test_nbeats_integration_paths.py",
    "scripts/audit_scripts/cert139_oracles.py",
]
CAPACITY_SUBSET = ORACLE_SUBSET + [
    "tests/unit/test_neural_capacity_guard.py",
]
REGISTRY_SUBSET = ORACLE_SUBSET + [
    "tests/unit/test_model_execution_contract.py",
]
API_SUBSET = [
    "tests/api/test_models_backtest_neural_capacity.py",
    "tests/unit/test_nbeats_integration_paths.py",
]

# (id, файл, old, new, kill-подмножество)
MUTATIONS = [
    ("M01", "apps/api/model_impls/nbeats.py",
     "NBEATS_MIN_TRAIN = 30", "NBEATS_MIN_TRAIN = 5", ORACLE_SUBSET),
    ("M02", "apps/api/model_impls/nbeats.py",
     'if nobs < normalized["input_size"] + int(horizon):',
     'if nobs < normalized["input_size"]:', ORACLE_SUBSET),
    ("M03", "apps/api/model_impls/nbeats.py",
     "NBEATS_MAX_STEPS = 300", "NBEATS_MAX_STEPS = 250", ORACLE_SUBSET),
    ("M04", "apps/api/model_impls/nbeats.py",
     "NBEATS_MAX_STEPS = 300", "NBEATS_MAX_STEPS = 99", ORACLE_SUBSET),
    ("M05", "apps/api/model_impls/nbeats.py",
     "    if value < 1:", "    if value < 0:", ORACLE_SUBSET),
    ("M06", "apps/api/model_impls/nbeats.py",
     "if isinstance(value, bool) or not isinstance(value, (int, np.integer)):",
     "if not isinstance(value, (int, np.integer)):", ORACLE_SUBSET),
    ("M07", "apps/api/model_impls/nbeats.py",
     "HIDDEN_SIZE_BOUNDS = (8, 128)", "HIDDEN_SIZE_BOUNDS = (8, 256)",
     ORACLE_SUBSET),
    ("M08", "apps/api/model_impls/nbeats.py",
     '"stack_types": ["trend", "seasonality"],',
     '"stack_types": ["identity", "identity"],', ORACLE_SUBSET),
    ("M09", "apps/api/model_impls/nbeats.py",
     "if not ((lower_arr <= point).all() and (point <= upper_arr).all()):",
     "if False and not ((lower_arr <= point).all() and (point <= upper_arr).all()):",
     ORACLE_SUBSET),
    ("M10", "apps/api/model_impls/nbeats.py",
     "if not (np.isfinite(point).all() and np.isfinite(lower).all()\n"
     "            and np.isfinite(upper).all()):",
     "if False and not (np.isfinite(point).all() and np.isfinite(lower).all()\n"
     "            and np.isfinite(upper).all()):", ORACLE_SUBSET),
    ("M11", "apps/api/model_impls/nbeats.py",
     "seed=int(random_state), max_steps=_resolve_max_steps(),",
     "seed=0, max_steps=_resolve_max_steps(),", ORACLE_SUBSET),
    ("M12", "apps/api/model_impls/nbeats.py",
     "max_steps=_resolve_max_steps(),", "max_steps=NBEATS_MAX_STEPS,",
     ORACLE_SUBSET),
    ("M20", "apps/api/model_impls/nbeats.py",
     'alias="NBEATS",', 'alias="NBEATSX",', ORACLE_SUBSET),
    ("M21", "apps/api/model_impls/nbeats.py",
     'lower = _interval_column(preds, model_name, "lo", float(plan.levels[0]))',
     'lower = _interval_column(preds, model_name, "lo", float(plan.levels[-1]))',
     ORACLE_SUBSET),
    ("M13", "apps/api/model_execution.py",
     'model_id="nbeats", family_id="neural",\n'
     '        adapter_id="neuralforecast-nbeats", executor=_nbeats_executor,\n'
     "        actions=_TUNABLE, engine=\"neuralforecast\",",
     'model_id="nbeats", family_id="neural",\n'
     '        adapter_id="neuralforecast-nbeats", executor=_nbeats_executor,\n'
     '        actions=frozenset({"backtest", "diagnostics"}), engine="neuralforecast",',
     REGISTRY_SUBSET),
    ("M15", "apps/api/model_execution.py",
     '# gate реестр<->dispatch остаётся точным в обеих средах.\n'
     '        input_kind="univariate",\n'
     "        supports_prediction_intervals=True,\n"
     "        deterministic=True,\n"
     '        dependency_group="neural",',
     '# gate реестр<->dispatch остаётся точным в обеих средах.\n'
     '        input_kind="univariate",\n'
     "        supports_prediction_intervals=True,\n"
     "        deterministic=False,\n"
     '        dependency_group="neural",', REGISTRY_SUBSET),
    ("M14", "apps/api/routers/models.py",
     'implementations["lstm"] = run_lstm_backtest\n'
     '        implementations["nbeats"] = run_nbeats_backtest',
     'implementations["lstm"] = run_lstm_backtest', REGISTRY_SUBSET),
    ("M19", "apps/api/routers/models.py",
     "raise HTTPException(status_code=503, detail=str(exc)) from exc",
     "raise HTTPException(status_code=500, detail=str(exc)) from exc",
     API_SUBSET),
    ("M16", "apps/api/neural_resources.py",
     "if available_mb is None or available_mb >= required_mb:",
     "if available_mb is None or available_mb > required_mb:",
     CAPACITY_SUBSET),
    ("M17", "apps/api/neural_resources.py",
     'NEURAL_MIN_MEMORY_MB: int = _RESOURCE_POLICIES["standard"]["memory_limit_mb"]',
     'NEURAL_MIN_MEMORY_MB: int = _RESOURCE_POLICIES["low"]["memory_limit_mb"]',
     CAPACITY_SUBSET),
    ("M18", "apps/api/model_impls/neural_runtime.py",
     "    ensure_neural_memory_capacity()\n"
     "    try:\n        import neuralforecast as _neuralforecast_module",
     "    try:\n        import neuralforecast as _neuralforecast_module",
     CAPACITY_SUBSET),
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
                          env={**__import__("os").environ,
                               "OMP_NUM_THREADS": "1"})
    tail = (proc.stdout or "").strip().splitlines()[-1:] or ["<no output>"]
    return proc.returncode == 0, tail[0][:160]


def main() -> int:
    only = set(sys.argv[1:])
    batch = [m for m in MUTATIONS if not only or m[0] in only]
    print(f"Мутационная кампания Task 139: {len(batch)}/{len(MUTATIONS)} мутаций"
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
        print(f"{mid} {verdict:>8}  | {tail}")

    killed = sum(1 for _, verdict, _ in results if verdict == "KILLED")
    print(f"\nИтог: {killed}/{len(results)} KILLED")
    survivors = [mid for mid, verdict, _ in results if verdict == "SURVIVED"]
    print("Survivors:", survivors or "нет")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
