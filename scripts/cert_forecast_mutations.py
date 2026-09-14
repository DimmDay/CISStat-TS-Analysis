# scripts/cert_forecast_mutations.py
# Независимый сертификационный аудит Task FORECAST-1: мутационные тесты.
# Каждый мутант -- точечная порча вычислительного ядра/контракта; мутант
# KILLED, если целевые тесты падают, SURVIVED -- дыра в тестовом покрытии.
# Запуск: python scripts/cert_forecast_mutations.py [--fast]
#   --fast: только юнит-тесты + оракулы (без API-мутантов на TestClient).
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path("/home/z/my-project/CISStat-TS-Analysis")
PY = "/home/z/.venv/bin/python"
ORACLES = "scripts/cert_forecast_oracles.py"

# (id, file_rel, old, new, test_targets, description)
MUTANTS: list[tuple[str, str, str, str, str, str]] = [
    (
        "MUT-01", "apps/api/forecasting.py",
        "        if step in low_by_step:\n            lower[step - 1] = low_by_step[step]\n            upper[step - 1] = high_by_step[step]",
        "        if step in low_by_step:\n            lower[step - 1] = low_by_step[last_validated]\n            upper[step - 1] = high_by_step[last_validated]",
        "tests/unit/test_forecasting.py",
        "Эмпирический интервал: квантиль своего шага -> квантиль последнего шага для ВСЕХ",
    ),
    (
        "MUT-02", "apps/api/forecasting.py",
        "        low[step] = float(np.quantile(residuals, alpha / 2))\n        high[step] = float(np.quantile(residuals, 1 - alpha / 2))",
        "        low[step] = float(np.quantile(residuals, 1 - alpha / 2))\n        high[step] = float(np.quantile(residuals, alpha / 2))",
        "tests/unit/test_forecasting.py",
        "Эмпирический метод: перепутаны нижняя/верхняя квантили",
    ),
    (
        "MUT-03", "apps/api/forecasting.py",
        "    return covered / total if total else None",
        "    return 1.0 if total else None",
        "tests/unit/test_forecasting.py",
        "Coverage: всегда 1.0 (маскирует реальные промахи интервала)",
    ),
    (
        "MUT-04", "apps/api/forecasting.py",
        "    if not np.allclose(refit_point, registry_point, rtol=_PARITY_RTOL, atol=_PARITY_ATOL):",
        "    if False and not np.allclose(refit_point, registry_point, rtol=_PARITY_RTOL, atol=_PARITY_ATOL):",
        "tests/unit/test_forecasting.py",
        "Паритет-гейт отключён (дрейф зеркала не ловится)",
    ),
    (
        "MUT-05", "apps/api/forecasting.py",
        "    if (\n        validated_horizon is not None\n        and horizon > int(validated_horizon)\n        and ci_method != \"empirical_oof_quantile\"\n    ):\n        warnings.append(",
        "    if (\n        validated_horizon is not None\n        and horizon > int(validated_horizon)\n        and ci_method != \"empirical_oof_quantile\"\n        and False\n    ):\n        warnings.append(",
        "tests/unit/test_forecasting.py",
        "Мягкое предупреждение о горизонте удалено (analytic/simulation)",
    ),
    (
        "MUT-06", "apps/api/forecasting.py",
        "    lower = np.quantile(trajectories_arr, alpha / 2, axis=1)\n    upper = np.quantile(trajectories_arr, 1 - alpha / 2, axis=1)",
        "    lower = np.quantile(trajectories_arr, alpha, axis=1)\n    upper = np.quantile(trajectories_arr, 1 - alpha / 2, axis=1)",
        "tests/unit/test_forecasting.py",
        "Симуляция: нижний квантиль alpha/2 -> alpha (сужение интервала)",
    ),
    (
        "MUT-07", "apps/api/forecasting.py",
        "    mask = detect_outlier_mask(combined, method, param)\n    return [bool(flag) for flag in mask.to_numpy()[len(history_values):]]",
        "    mask = detect_outlier_mask(combined, method, param)\n    return [False] * len(point_values)",
        "tests/unit/test_forecasting.py",
        "Аномалии: все флаги False (детектор отключён)",
    ),
    (
        "MUT-08", "apps/api/forecasting_contract.py",
        "NEURAL_ALPHA_WHITELIST = {0.01, 0.05, 0.10}",
        "NEURAL_ALPHA_WHITELIST = {0.01, 0.05, 0.10, 0.20}",
        "tests/unit/test_forecasting_contract.py",
        "Нейро-whitelist расширен вне сертифицированного набора",
    ),
    (
        "MUT-09", "apps/api/forecasting_contract.py",
        "PLATFORM_DEFAULT_ALPHA = 0.05",
        "PLATFORM_DEFAULT_ALPHA = 0.5",
        "tests/unit/test_forecasting_contract.py",
        "Платформенная alpha по умолчанию 0.05 -> 0.5",
    ),
    (
        "MUT-10", "apps/api/final_fit.py",
        "        for state in reversed(self.transform_states):",
        "        for state in self.transform_states:",
        "tests/unit/test_final_fit.py",
        "Инверсия цепочки: порядок трансформаций не разворачивается",
    ),
    (
        "MUT-11", "apps/api/final_fit.py",
        "        if self.scaler is not None:\n            restored = self.scaler.inverse_transform(restored.reshape(-1, 1)).ravel()",
        "        if False and self.scaler is not None:\n            restored = self.scaler.inverse_transform(restored.reshape(-1, 1)).ravel()",
        "tests/unit/test_final_fit.py",
        "Инверсия скейлера пропущена",
    ),
    (
        "MUT-12", "apps/api/routers/forecasting_session.py",
        "    if model_info.get(\"selection_kind\") == \"ensemble\":",
        "    if False and model_info.get(\"selection_kind\") == \"ensemble\":",
        "tests/api/test_forecasting_session.py::test_forecast_rejects_ensemble_card_honestly",
        "Ensemble-гейт снят (карта ансамбля должна получать 422)",
    ),
    (
        "MUT-13", "apps/api/routers/forecasting_session.py",
        "    card_fingerprint = (card.get(\"data_summary\") or {}).get(\"fingerprint\")\n    if card_fingerprint != context.get(\"fingerprint\"):",
        "    card_fingerprint = (card.get(\"data_summary\") or {}).get(\"fingerprint\")\n    if False and card_fingerprint != context.get(\"fingerprint\"):",
        "tests/api/test_forecasting_session.py::test_forecast_stale_card_fails_with_409",
        "Freshness-гейт fingerprint снят (stale-карта должна получать 409)",
    ),
    (
        "MUT-14", "apps/api/routers/forecasting_session.py",
        "        picks = [unique[0], unique[-1]] if len(unique) > 1 else [unique[0]]",
        "        picks = [unique[0]] if len(unique) > 1 else [unique[0]]",
        "tests/api/test_forecasting_session.py::test_forecast_sensitivity_fan_uses_param_space_corners",
        "Веер чувствительности: только первый угол каждой оси",
    ),
    (
        "MUT-15", "apps/api/routers/forecasting_session.py",
        "    if event.event_type == \"forecast_exported\":\n        # §10.5: экспорт -- естественное терминальное действие этапа\n        # (derived-статус из данных, как tuning в Моделировании).\n        session.stages[\"forecasting\"] = \"done\"",
        "    if event.event_type == \"forecast_exported\":\n        # §10.5: экспорт -- естественное терминальное действие этапа\n        # (derived-статус из данных, как tuning в Моделировании).\n        pass",
        "tests/api/test_forecasting_session.py::test_forecast_export_csv_contains_history_and_forecast_columns",
        "forecast_exported больше не завершает этап (§10.5 сломан)",
    ),
]


def run_cmd(cmd: list[str], timeout: int = 420) -> tuple[int, str]:
    proc = subprocess.run(
        cmd, cwd=REPO, capture_output=True, text=True, timeout=timeout,
    )
    return proc.returncode, (proc.stdout + proc.stderr)[-3000:]


def main() -> int:
    fast = "--fast" in sys.argv
    results: list[tuple[str, str, str]] = []
    backup_dir = REPO / ".cert_mutation_backup"
    backup_dir.mkdir(exist_ok=True)

    try:
        for mutant_id, file_rel, old, new, targets, description in MUTANTS:
            if fast and "/routers/" in file_rel:
                print(f"[SKIP] {mutant_id} (API-мутант, --fast)")
                continue
            src = REPO / file_rel
            backup = backup_dir / src.name
            if not backup.exists():
                shutil.copy2(src, backup)

            text = src.read_text(encoding="utf-8")
            if text.count(old) != 1:
                results.append((mutant_id, "MISSED", f"якорь не уникален ({text.count(old)}x): {description}"))
                print(f"[MISSED] {mutant_id}: якорь не уникален ({text.count(old)}x)")
                continue

            src.write_text(text.replace(old, new), encoding="utf-8")
            try:
                cmd = [PY, "-m", "pytest", "-q", "-p", "no:cacheprovider", "--no-header", "-x"]
                cmd += targets.split()
                code, output = run_cmd(cmd)
                pytest_killed = code != 0
                oracle_code, oracle_out = run_cmd([PY, ORACLES])
                oracle_killed = oracle_code != 0
                if pytest_killed and not oracle_killed:
                    attribution = "pytest"
                elif oracle_killed and not pytest_killed:
                    attribution = "ORACLE-ONLY (тесты коллеги пропустили)"
                elif pytest_killed and oracle_killed:
                    attribution = "pytest+oracle"
                else:
                    attribution = "none"
                if pytest_killed or oracle_killed:
                    results.append((mutant_id, "KILLED", f"[{attribution}] {description}"))
                    print(f"[KILLED] {mutant_id} [{attribution}]: {description}")
                else:
                    results.append((mutant_id, "SURVIVED", description))
                    print(f"[SURVIVED] {mutant_id}: {description} !!! ДЫРА В ПОКРЫТИИ")
            finally:
                shutil.copy2(backup, src)
    finally:
        for name in {p.name for p in backup_dir.iterdir()}:
            shutil.copy2(backup_dir / name, REPO / "apps/api" / name)
        shutil.rmtree(backup_dir, ignore_errors=True)

    killed = sum(1 for _, status, _ in results if status == "KILLED")
    survived = sum(1 for _, status, _ in results if status == "SURVIVED")
    missed = sum(1 for _, status, _ in results if status == "MISSED")
    print(f"\n=== MUTATION SUMMARY: {killed} KILLED / {survived} SURVIVED / {missed} MISSED ===")
    return 1 if survived or missed else 0


if __name__ == "__main__":
    raise SystemExit(main())
