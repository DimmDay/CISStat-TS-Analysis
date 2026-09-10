# scripts/audit_scripts/cert137_mutations.py
"""Certification of Task 137 -- mutation probes (apply -> targeted RED-check -> revert -> git-diff).

Протокол предшественников (cert134135, cert136): каждая мутация применяется
к чистому дереву, прогоняется целевой тест-подсет, мутация откатывается,
чистота дерева верифицируется git diff.  KILLED = тесты поймали мутацию;
SURVIVED = пробел тест-привязки (характеризуется в записи сертификации).
"""
from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
PYTHON = sys.executable

CONTRACT = "apps/api/neural_contract.py"
RUNTIME = "apps/api/model_impls/neural_runtime.py"
YAML = "rules/modeling.yaml"

FAST_CONTRACT = [PYTHON, "-m", "pytest", "tests/unit/test_neural_contract.py", "-q",
                 "-p", "no:cacheprovider", "-x", "--no-header", "-q"]


@dataclass
class Mutation:
    mid: str
    description: str
    file: str
    old: str
    new: str
    cmd: list[str]
    expected: str  # "KILLED" | "SURVIVED"


MUTATIONS: list[Mutation] = [
    Mutation("M1", "to_long_format: снят NaN-гейт keep-колонки", CONTRACT,
             "        if values.isna().any():\n            raise NeuralContractError(\n                f\"exog-колонка '{column}' содержит NaN\"\n            )",
             "        if False:\n            raise NeuralContractError(\n                f\"exog-колонка '{column}' содержит NaN\"\n            )",
             FAST_CONTRACT, "SURVIVED"),
    Mutation("M2", "to_long_format: снят гейт дубликатов (unique_id, ds)", CONTRACT,
             "    duplicated = long.duplicated([\"unique_id\", \"ds\"], keep=False)\n    if duplicated.any():",
             "    duplicated = long.duplicated([\"unique_id\", \"ds\"], keep=False)\n    if False:",
             FAST_CONTRACT, "KILLED"),
    Mutation("M3", "validate_long_format: числовая ветка nunique>1 -> >2", CONTRACT,
             "            if diffs.nunique() > 1:\n                raise NeuralContractError(\n                    f\"серия '{series_id}': временная сетка нерегулярна; \"",
             "            if diffs.nunique() > 2:\n                raise NeuralContractError(\n                    f\"серия '{series_id}': временная сетка нерегулярна; \"",
             FAST_CONTRACT, "SURVIVED"),
    Mutation("M4", "build_exogenous_plan: снят гейт пересечения ролей", CONTRACT,
             "    if len(set(all_declared)) != len(all_declared):",
             "    if False and len(set(all_declared)) != len(all_declared):",
             FAST_CONTRACT, "KILLED"),
    Mutation("M5", "build_exogenous_plan: снят гейт константности static", CONTRACT,
             "        counts = long_frame.groupby(\"unique_id\")[column].nunique(dropna=False)\n        if (counts > 1).any():",
             "        counts = long_frame.groupby(\"unique_id\")[column].nunique(dropna=False)\n        if False and (counts > 1).any():",
             FAST_CONTRACT, "KILLED"),
    Mutation("M6", "build_exogenous_plan: конечность hist/futr -> True", CONTRACT,
             "        if not np.isfinite(values).all():\n            raise NeuralContractError(\n                f\"exog-колонка '{column}' содержит NaN/Inf/нечисловые \"",
             "        if False and not np.isfinite(values).all():\n            raise NeuralContractError(\n                f\"exog-колонка '{column}' содержит NaN/Inf/нечисловые \"",
             FAST_CONTRACT, "KILLED"),
    Mutation("M7a", "validate_future_exogenous_frame: равенство -> нижняя граница", CONTRACT,
             "    if len(future_frame) != required_rows:",
             "    if len(future_frame) < required_rows:",
             FAST_CONTRACT, "SURVIVED"),
    Mutation("M7b", "validate_future_exogenous_frame: снят per-series гейт horizon", CONTRACT,
             "    if \"unique_id\" in future_frame.columns:\n        per_series = future_frame.groupby(\"unique_id\").size()\n        if (per_series != int(horizon)).any():",
             "    if False and \"unique_id\" in future_frame.columns:\n        per_series = future_frame.groupby(\"unique_id\").size()\n        if (per_series != int(horizon)).any():",
             FAST_CONTRACT, "SURVIVED"),
    Mutation("M8", "NeuralTrainingConfig: потолок max_steps 10_000 -> 999_999", CONTRACT,
             "        if not isinstance(self.max_steps, int) or not 1 <= self.max_steps <= NEURAL_MAX_STEPS_BOUND:",
             "        if not isinstance(self.max_steps, int) or not 1 <= self.max_steps <= 999_999:",
             FAST_CONTRACT, "SURVIVED"),
    Mutation("M9", "NeuralTrainingConfig: снят гейт patience>0 требует val_size>0", CONTRACT,
             "        if self.early_stopping_patience > 0 and self.val_size <= 0:",
             "        if False and self.early_stopping_patience > 0 and self.val_size <= 0:",
             FAST_CONTRACT, "KILLED"),
    Mutation("M10", "fold_seed: коэффициент step 104_729 -> 104_731", CONTRACT,
             "    mixed = (seed * 1_000_003 + fold_index * 7_919 + step * 104_729 + 137)",
             "    mixed = (seed * 1_000_003 + fold_index * 7_919 + step * 104_731 + 137)",
             FAST_CONTRACT, "SURVIVED"),
    Mutation("M11", "interval_levels_for_alpha: alpha/2 -> alpha (односторонняя)", CONTRACT,
             "    lo = round(100.0 * alpha / 2.0, 6)",
             "    lo = round(100.0 * alpha, 6)",
             FAST_CONTRACT, "KILLED"),
    Mutation("M12", "resolve_probabilistic_loss: whitelist расширен 'mape'", CONTRACT,
             "NEURAL_ALLOWED_LOSSES: tuple[str, ...] = (\n    \"quantile\", \"mqloss\", \"mae\", \"mse\", \"huber\",\n)",
             "NEURAL_ALLOWED_LOSSES: tuple[str, ...] = (\n    \"quantile\", \"mqloss\", \"mae\", \"mse\", \"huber\", \"mape\",\n)",
             FAST_CONTRACT, "SURVIVED"),
    Mutation("M13", "resolve_neural_device: тихое CPU-понижение вместо отказа", CONTRACT,
             "    if requires_gpu and not gpu:\n        raise NeuralRuntimeUnavailableError(",
             "    if False and requires_gpu and not gpu:\n        raise NeuralRuntimeUnavailableError(",
             FAST_CONTRACT, "KILLED"),
    Mutation("M14", "load_checkpoint: снят sha256 анти-тампер", CONTRACT,
             "        digest = sha256(payload).hexdigest()\n        if digest != pointer.get(\"sha256\"):",
             "        digest = sha256(payload).hexdigest()\n        if False and digest != pointer.get(\"sha256\"):",
             FAST_CONTRACT, "KILLED"),
    Mutation("M15", "CHECKPOINT_MAX_BYTES 512MB -> 5GB (значение не прижато)", CONTRACT,
             "CHECKPOINT_MAX_BYTES = 512 * 1024 * 1024",
             "CHECKPOINT_MAX_BYTES = 5 * 1024 * 1024 * 1024",
             FAST_CONTRACT, "SURVIVED"),
    Mutation("M16", "_assert_json_safe: float isfinite -> пропуск", CONTRACT,
             "    if isinstance(value, float):\n        if not np.isfinite(value):",
             "    if isinstance(value, float):\n        if False and not np.isfinite(value):",
             FAST_CONTRACT, "SURVIVED"),
    Mutation("M17", "seed_neural_runtime: снят torch.manual_seed", RUNTIME,
             "    torch.manual_seed(seed)\n    seeded[\"torch\"] = True",
             "    seeded[\"torch\"] = True",
             [PYTHON, "-m", "pytest",
              "tests/unit/test_neural_runtime.py::test_seed_neural_runtime_seeds_torch",
              "-q", "-p", "no:cacheprovider", "--no-header"], "KILLED"),
    Mutation("M18", "budget_kwargs: accelerator игнорирует device (жёстко cpu)", RUNTIME,
             "        \"accelerator\": device,",
             "        \"accelerator\": \"cpu\",",
             [PYTHON, "-m", "pytest",
              "tests/unit/test_neural_runtime.py::test_budget_kwargs_explicit_device_accelerator",
              "-q", "-p", "no:cacheprovider", "--no-header"], "KILLED"),
    Mutation("M19", "train_and_forecast: seed ПОСЛЕ конструирования модели", RUNTIME,
             "    seed = fold_seed(config.seed, fold_index=fold_index)\n    seed_neural_runtime(seed)\n\n    budget = neural_model_budget_kwargs(config, device=\"cpu\")\n    model = model_factory(dict(budget))",
             "    budget = neural_model_budget_kwargs(config, device=\"cpu\")\n    model = model_factory(dict(budget))\n\n    seed = fold_seed(config.seed, fold_index=fold_index)\n    seed_neural_runtime(seed)",
             [PYTHON, "-m", "pytest",
              "tests/unit/test_neural_runtime.py::test_train_and_forecast_deterministic_for_same_seed",
              "-q", "-p", "no:cacheprovider", "--no-header"], "SURVIVED"),
    Mutation("M20", "modeling.yaml: lstm libraries ['neuralforecast'] -> ['darts']", YAML,
             "        supports_prediction_intervals: true   # MC Dropout / deep ensembles\n        libraries: [\"neuralforecast\"]",
             "        supports_prediction_intervals: true   # MC Dropout / deep ensembles\n        libraries: [\"darts\"]",
             FAST_CONTRACT, "SURVIVED"),
    Mutation("M21", "train_and_forecast: val_size не передаётся в fit", RUNTIME,
             "    if config.early_stopping_enabled:\n        fit_kwargs[\"val_size\"] = int(config.val_size)",
             "    if False and config.early_stopping_enabled:\n        fit_kwargs[\"val_size\"] = int(config.val_size)",
             [PYTHON, "-m", "pytest", "tests/unit/test_neural_runtime.py", "-q",
              "-p", "no:cacheprovider", "--no-header"], "SURVIVED"),
    Mutation("M22", "PANEL_MIN_SERIES 2 -> 3 (граница панели не прижата)", CONTRACT,
             "PANEL_MIN_SERIES = 2",
             "PANEL_MIN_SERIES = 3",
             FAST_CONTRACT, "SURVIVED"),
]


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=REPO, capture_output=True, text=True,
                          check=True).stdout


def apply_mutation(m: Mutation) -> bool:
    path = REPO / m.file
    text = path.read_text(encoding="utf-8")
    if m.old not in text:
        return False
    if text.count(m.old) != 1:
        return False
    path.write_text(text.replace(m.old, m.new), encoding="utf-8")
    return True


def run_tests(cmd: list[str]) -> tuple[bool, str]:
    proc = subprocess.run(cmd, cwd=REPO, capture_output=True, text=True, timeout=1200)
    out = proc.stdout + proc.stderr
    passed = (" passed" in out and " failed" not in out and " error" not in out
              and proc.returncode == 0)
    tail = " ".join(out.strip().split()[-12:])
    return passed, tail


def main() -> None:
    print("=" * 78)
    print("CERT137 MUTATIONS -- apply -> targeted check -> revert -> git-diff verify")
    print("=" * 78)
    rows: list[tuple[str, str, str, str]] = []
    for m in MUTATIONS:
        ok_apply = apply_mutation(m)
        if not ok_apply:
            rows.append((m.mid, "APPLY-FAIL", m.expected, "якорь не найден/неуникален"))
            print(f"[APPLY-FAIL] {m.mid}: {m.description}")
            continue
        try:
            green, tail = run_tests(m.cmd)
        except subprocess.TimeoutExpired:
            green, tail = False, "timeout"
        finally:
            subprocess.run(["git", "checkout", "--", m.file], cwd=REPO, check=True,
                           capture_output=True)
        status = "KILLED" if not green else "SURVIVED"
        match = (status == m.expected)
        rows.append((m.mid, status, m.expected, tail))
        print(f"[{status}{'/' if match else '!'}{'ok' if match else 'UNEXPECTED'}] "
              f"{m.mid}: {m.description}")
    diff = git("diff", "--stat").strip()
    dirty = bool(diff)
    print("-" * 78)
    print("git diff после откатов:", "ЧИСТО" if not dirty else f"ГРЯЗНО:\n{diff}")
    n_killed = sum(1 for _, s, _, _ in rows if s == "KILLED")
    n_surv = sum(1 for _, s, _, _ in rows if s == "SURVIVED")
    print(f"TOTAL: {len(rows)} applied; KILLED={n_killed}, SURVIVED={n_surv}")
    for mid, status, expected, tail in rows:
        if status == "SURVIVED":
            print(f"  SURVIVED {mid}: {tail[:150]}")
    sys.exit(0 if not dirty else 2)


if __name__ == "__main__":
    main()
