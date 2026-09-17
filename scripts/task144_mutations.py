#!/usr/bin/env python3
"""
Task 144 mutation testing runner -- мягкий порог истории (soft_min_observations).
Targets:
  apps/api/eda_model_matrix.py       (трёхуровневый гейт + soft_history_warning)
  src/catalog/modeling_spec_loader.py (F04-effective + D07 + валидатор + ctx)
  apps/api/routers/models.py         (warn-but-allow в /candidates)
  apps/api/routers/modeling_session.py (инъекция предупреждения в бэктест)
  rules/modeling.yaml                (данные soft-порогов)

Defense suite (per-mutant scope):
  fast:  tests/test_modeling_spec.py + tests/unit/test_eda_model_matrix.py +
         tests/unit/test_model_readiness_candidates.py
  slow:  tests/api/test_modeling_workflow.py::test_soft_history_backtest_...
KILLED = suite fails, SURVIVED = suite green. Originals restored, sha256 verified.
"""
import hashlib
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path("/home/z/my-project/CISStat-TS-Analysis")
MATRIX = REPO / "apps/api/eda_model_matrix.py"
LOADER = REPO / "src/catalog/modeling_spec_loader.py"
MODELS = REPO / "apps/api/routers/models.py"
SESSION = REPO / "apps/api/routers/modeling_session.py"
YAML = REPO / "rules/modeling.yaml"
BACKUP = Path("/home/z/my-project/scripts/.task144_backup")

FAST = [
    "tests/test_modeling_spec.py",
    "tests/unit/test_eda_model_matrix.py",
    "tests/unit/test_model_readiness_candidates.py",
]
SLOW = [
    "tests/api/test_modeling_workflow.py::test_soft_history_backtest_runs_and_returns_explicit_warning",
]
PY = "/home/z/.venv/bin/python3"

# (id, file, old, new, scope, rationale)
MUTANTS = [
    # ── apps/api/eda_model_matrix.py ─────────────────────────────
    ("M1", MATRIX,
     '        return "attention" if initial_train >= soft_min else "fail"',
     '        return "fail"',
     "fast",
     "мягкое окно удалено из матрицы (attention недостижим)"),
    ("M2", MATRIX,
     'return "attention" if initial_train >= soft_min else "fail"',
     'return "attention" if initial_train > soft_min else "fail"',
     "fast",
     "левая граница окна исключительна (n == soft_min снова fail)"),
    ("M3", MATRIX,
     "    soft_min = model.soft_min_observations",
     "    soft_min = model.min_observations",
     "fast",
     "soft-порог подменён жёстким -- окно вырождено"),
    ("M4", MATRIX,
     "    if soft_min is not None:\n        if initial_train >= model.min_observations:\n            return \"pass\"",
     "    if soft_min is not None:\n        if initial_train >= model.min_observations:\n            return \"attention\"",
     "fast",
     "правая граница окна размыта (pass превращён в attention на min)"),
    ("M5", MATRIX,
     'f"Обучено на {initial_train} наблюдениях при рекомендованном "',
     'f"Обучено на {initial_train} наблюдениях. "',
     "slow",
     "текст предупреждения бэктеста потерял формулу Task 144"),
    ("M6", MATRIX,
     'if history_gate_level(model, initial_train) != "attention":\n        return None',
     'if history_gate_level(model, initial_train) != "fail":\n        return None',
     "slow",
     "предупреждение выдаётся и на fail, но не на attention"),
    ("M7", MATRIX,
     '"но в пределах мягкого порога {model.soft_min_observations}: "',
     '"вне мягкого порога {model.soft_min_observations}: "',
     "fast",
     "conclusion attention-критерия лжёт о пределах окна"),
    ("M8", MATRIX,
     '        "На первом fold модели не хватит истории.",\n        blocking=True,',
     '        "На первом fold модели не хватит истории.",\n        blocking=False,',
     "fast",
     "нижняя граница снята: fail перестал блокировать"),
    ("M9", MATRIX,
     '"soft_min_observations": model.soft_min_observations,',
     '"soft_min_observations": None,',
     "fast",
     "матрица перестала раскрывать soft-порог (прозрачность)"),
    # ── src/catalog/modeling_spec_loader.py ──────────────────────
    ("M10", LOADER,
     '"F04": lambda: ctx["n_observations"] < ctx["model.effective_min_observations"],',
     '"F04": lambda: ctx["n_observations"] < ctx["model.min_observations"],',
     "fast",
     "F04 откат к жёсткому порогу (soft-модели снова блокируются целиком)"),
    ("M11", LOADER,
     '>= ctx["model.soft_min_observations"]\n            ),',
     '> ctx["model.soft_min_observations"]\n            ),',
     "fast",
     "левая граница D07 исключительна"),
    ("M12", LOADER,
     'and ctx["model.min_observations"] > ctx["n_observations"]\n                >= ctx["model.soft_min_observations"]',
     'and ctx["n_observations"] >= ctx["model.soft_min_observations"]',
     "fast",
     "D07 без верхней границы -- размыает D05/D01-D06"),
    ("M13", LOADER,
     'ctx.get("model.soft_min_observations") is not None\n                and ctx["model.min_observations"]',
     'ctx.get("model.soft_min_observations") is None\n                and ctx["model.min_observations"]',
     "fast",
     "D07 инвертирован: срабатывает только у моделей БЕЗ soft-порога"),
    ("M14", LOADER,
     '"model.effective_min_observations": (\n                model.soft_min_observations\n                if model.soft_min_observations is not None\n                else model.min_observations\n            ),',
     '"model.effective_min_observations": (\n                model.min_observations\n                if model.soft_min_observations is not None\n                else model.soft_min_observations\n            ),',
     "fast",
     "ветки effective-порога переставлены"),
    ("M15", LOADER,
     'if v >= info.data["min_observations"]:',
     'if v > info.data["min_observations"]:',
     "fast",
     "валидатор пропускает вырожденное окно soft == min"),
    # ── apps/api/routers/models.py ───────────────────────────────
    ("M16", MODELS,
     '            candidate.level == "NOT_RECOMMENDED"\n            and platform_ready\n            and not included',
     '            candidate.level == "NOT_APPLICABLE"\n            and platform_ready\n            and not included',
     "fast",
     "warn-but-allow применён к уровню 4 вместо уровня 3"),
    ("M17", MODELS,
     "        runnable = included or warn_only",
     "        runnable = included",
     "fast",
     "warn_only вычисляется, но не используется (баг NOT_RECOMMENDED возвращён)"),
    # ── apps/api/routers/modeling_session.py ─────────────────────
    ("M18", SESSION,
     "            if soft_warning:\n                preprocessing_warnings.append(soft_warning)",
     "            if False:\n                preprocessing_warnings.append(soft_warning)",
     "slow",
     "предупреждение не попадает в warnings бэктеста"),
    ("M19", SESSION,
     "                spec_model, len(plan.folds[0].train_indices),",
     "                spec_model, len(plan.folds[-1].train_indices),",
     "slow",
     "N берётся с последнего fold вместо первого (92 -> 94)"),
    # ── rules/modeling.yaml (данные) ─────────────────────────────
    ("M20", YAML,
     '        soft_min_observations: 50\n',
     '        soft_min_observations: 49\n',
     "fast",
     "порог tbats сдвинут (сообщение и границы едут)"),
    ("M21", YAML,
     '        # Task 144: мягкое окно [40, 100) -- как у всей tree_ml-четвёрки.\n        soft_min_observations: 40\n        supports_exogenous: true\n        requires_feature_engineering: true\n        supports_prediction_intervals: true    # через quantile\n        libraries: ["scikit-learn"]',
     '        # Task 144: мягкое окно [40, 100) -- как у всей tree_ml-четвёрки.\n        soft_min_observations: 99\n        supports_exogenous: true\n        requires_feature_engineering: true\n        supports_prediction_intervals: true    # через quantile\n        libraries: ["scikit-learn"]',
     "fast",
     "soft random_forest 40 -> 99: окно схлопнуто почти до нуля"),
]


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def run_suite(scope: str) -> bool:
    targets = FAST if scope == "fast" else SLOW
    r = subprocess.run(
        [PY, "-m", "pytest", *targets, "-q", "-p", "no:cacheprovider", "--no-header", "-x"],
        cwd=REPO, capture_output=True, text=True, timeout=900,
    )
    return r.returncode == 0


def main() -> int:
    BACKUP.mkdir(exist_ok=True)
    targets = {str(p): p for p in {MATRIX, LOADER, MODELS, SESSION, YAML}}
    baselines = {name: sha(p) for name, p in targets.items()}
    for p in targets.values():
        shutil.copy2(p, BACKUP / p.name)

    killed, survived, errors = [], [], []
    try:
        for mid, path, old, new, scope, why in MUTANTS:
            src = path.read_text(encoding="utf-8")
            if old not in src:
                errors.append(f"{mid}: pattern not found in {path.name}")
                continue
            path.write_text(src.replace(old, new, 1), encoding="utf-8")
            try:
                green = run_suite(scope)
                status = "SURVIVED" if green else "KILLED"
                (survived if green else killed).append((mid, why))
            except subprocess.TimeoutExpired:
                errors.append(f"{mid}: timeout")
                status = "ERROR(timeout)"
            finally:
                shutil.copy2(BACKUP / path.name, path)
            print(f"{mid}: {status} -- {why}", flush=True)
    finally:
        for p in targets.values():
            shutil.copy2(BACKUP / p.name, p)
        for name, h in baselines.items():
            assert sha(targets[name]) == h, f"RESTORE FAILED for {name}"
        print("restore verified: sha256 match for all targets", flush=True)
        shutil.rmtree(BACKUP, ignore_errors=True)

    print(f"\nSUMMARY: killed={len(killed)} survived={len(survived)} errors={len(errors)}")
    if survived:
        print("SURVIVED MUTANTS (test-defense gaps):")
        for mid, why in survived:
            print(f"  {mid}: {why}")
    for e in errors:
        print(f"  {e}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
