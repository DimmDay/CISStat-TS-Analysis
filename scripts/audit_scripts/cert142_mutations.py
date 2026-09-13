# scripts/audit_scripts/cert142_mutations.py
"""Мутационное тестирование ПЕРЕСЕРТИФИКАЦИИ Task 142 (DeepAR,
Task 142a: исправление блокирующей находки F3 -- DistributionLoss +
scaler robust).

Протокол сертификаций Task 136-141 (cert136..cert141_mutations.py):
- каждая мутация -- минимальная точечная правка КОДА (одна строка /
  выражение), применяемая с проверкой "ровно одно вхождение";
- прогон kill-подмножества в СВЕЖЕМ subprocess (in-process недействителен);
- после каждой мутации файл восстанавливается, хэш сверяется --
  рабочее дерево обязано остаться байт-чистым;
- вердикт KILLED (упало >= 1 тестов kill-подмножества) / SURVIVED.

ОТКЛОНЕНИЕ ОТ ПРОТОКОЛА (документировано в worklog5.md): рабочее дерево
несёт некоммиченные изменения пересертификации (Task 142a: deepar.py,
neural_contract.py, modeling_session.py, model_execution.py -- запрет
коммитов AGENTS.md).  Поэтому БАЗОЙ восстановления служит снапшот
РАБОЧЕГО ДЕРЕВА на старте кампании (копия + SHA-256), а не git HEAD:
git checkout затёр бы фикс.  Гарантия байт-чистоты сохранена (SHA
сверяется против снапшота старта).

Kill-подмножество едино для всех мутаций -- cert142_oracles.py
(-m "not real_fit": 78 быстрых независимых оракула аудитора на
СОБСТВЕННЫХ данных (панель seed=142) + fake-harness; реальные фиты
секции E прогнаны на чистом дереве отдельно (6/6 GREEN) и из
kill-прогона исключены маркером real_fit).  Для каждой мутации в
комментарии указан убивающий оракул(ы).

Ключевые мутации исправления F3: M34a distribution="StudentT" ->
"Normal" (d01), M59 scaler robust -> identity (d01; живая семантика
масштаба -- e05), M60 trajectory_samples -> 100 (d01), M61 выведение
"distribution" из whitelist'а контракта (d03/f13 -- гейт).  Эквивалент:
valid_loss=None теперь эквивалентен MAE (дефолт библиотеки;
early-stopping отключён -- наблюдаемо неотличим), прежняя M34 исключена
из кампании как эквивалентный мутант.

Классы мутаций: панельный гейт min_series (M07/M08/M37), гейты данных:
окно (M01/M02), MIN_TRAIN (M03), NaN (M04), пустой (M05), horizon (M06),
длина related (M09), bounded (M10), alpha whitelist (M11), bool-коэрция
(M12); выбор целевого ряда ПО unique_id (M20/M21), сортировка по ds
(M22), missing-строки (M19), unique_id-колонка (M20); выбор колонок:
медиана (M13), сторона (M14), суффикс (M15), clamp (M16/M17), isfinite
(M18), fail-closed медиана/квантиль (M26/M27); панельная проводка до
runtime (M39); квантильный план (M57, общий источник tft), контрактный
гейт Task 137 (M23) и whitelist (M61), capacity passthrough (M24),
contract-wrap (M25), env-рычаг (M28/M29), metadata-ложь бюджета/сида/
метода (M30/M31/M32), голова распределения (M34a), скейлер (M59),
траекторный бюджет (M60), идентичность: alias (M33), adapter_id
(M35), константы бюджета/панели (M36/M37); реестр: model_id (M40),
input_kind panel (M41), requires_related_series (M42), deterministic
(M43), executor-мэппинг n_series/intervals (M44/M45), dispatch (M46);
panel-движок: objective (M47), input_kind (M48), одиночная система
(M49), leakage related-префиксов (M50), панельный блок результата
(M51), целостность fold'а (M52); yaml-ось (M53); EDA shape-критерий
(M54/M55/M56).

Запуск: OMP_NUM_THREADS=1 python3 scripts/audit_scripts/cert142_mutations.py
Батч-режим: ... cert142_mutations.py M01 M02 ... (урок Task 139 --
фоновые кампании ОС убивает, гонять foreground батчами).
"""
from __future__ import annotations

import hashlib
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

ORACLE_SUBSET = ["-m", "not real_fit", "scripts/audit_scripts/cert142_oracles.py"]

# (id, файл, old, new, kill-подмножество)
MUTATIONS = [
    # -- deepar.py: гейты данных и fail-closed --
    ("M01", "apps/api/model_impls/deepar.py",
     '    if nobs < normalized["input_size"] + int(horizon):',
     '    if nobs < normalized["input_size"]:',
     "c04 полоса [input+h-1] на 5 конфигах"),
    ("M02", "apps/api/model_impls/deepar.py",
     '    if nobs < normalized["input_size"] + int(horizon):',
     '    if nobs < normalized["input_size"] + int(horizon) + 2:',
     "c05 граница nobs=input+h адмиссибельна (БЕЗ +2 тройки)"),
    ("M03", "apps/api/model_impls/deepar.py",
     "    if nobs < DEEPAR_MIN_TRAIN:",
     "    if nobs < 5:",
     "c03 MIN_TRAIN=30"),
    ("M04", "apps/api/model_impls/deepar.py",
     "    if not np.isfinite(vector).all():",
     "    if False and not np.isfinite(vector).all():",
     "b05/b06 NaN/Inf вход (пин адаптерного слоя)"),
    ("M05", "apps/api/model_impls/deepar.py",
     "    if vector.size == 0:",
     "    if False and vector.size == 0:",
     "b07 пустой target"),
    ("M06", "apps/api/model_impls/deepar.py",
     "    if int(horizon) < 1:",
     "    if False and int(horizon) < 1:",
     "b08 horizon 0/-1/-7"),
    ("M07", "apps/api/model_impls/deepar.py",
     "    if n_series < DEEPAR_MIN_SERIES:",
     "    if n_series < DEEPAR_MIN_SERIES - 1:",
     "c01 полоса n_series=1..4 (ослабление на 1)"),
    ("M08", "apps/api/model_impls/deepar.py",
     "    if n_series < DEEPAR_MIN_SERIES:",
     "    if False and n_series < DEEPAR_MIN_SERIES:",
     "c01 панельный гейт удалён"),
    ("M09", "apps/api/model_impls/deepar.py",
     "        if vector.size != nobs:",
     "        if False and vector.size != nobs:",
     "b09 длина related != target"),
    ("M10", "apps/api/model_impls/deepar.py",
     "        if not low <= number <= high:",
     "        if not low <= number:",
     "b02 верхняя граница hidden/input"),
    ("M11", "apps/api/model_impls/deepar.py",
     "    if alpha_value not in ALPHA_OPTIONS:",
     "    if False and alpha_value not in ALPHA_OPTIONS:",
     "b02 alpha whitelist"),
    ("M12", "apps/api/model_impls/deepar.py",
     "        if isinstance(value, bool) or not isinstance(value, (int, np.integer)):",
     "        if not isinstance(value, (int, np.integer)):",
     "b01 bool-коэрция всех int-ручек"),
    # -- deepar.py: выбор целевого ряда и колонок (панельная честность) --
    ("M13", "apps/api/model_impls/deepar.py",
     '    return rows["DeepAR-median"].to_numpy(dtype=float)',
     "    return rows.iloc[:, 0].to_numpy(dtype=float)",
     "d01 точка == медиана (позиционный экстрактор)"),
    ("M14", "apps/api/model_impls/deepar.py",
     '    lower = _quantile_column(rows, "lo", width)',
     '    lower = _quantile_column(rows, "hi", width)',
     "d01 lower == 1.0 (стороны lo/hi)"),
    ("M15", "apps/api/model_impls/deepar.py",
     '    suffix = f"-{side}-{width}"',
     '    suffix = f"-{side}-{width + 1}"',
     "d01/f02 fail-closed выборка квантильной колонки"),
    ("M16", "apps/api/model_impls/deepar.py",
     "    if not ((lower_arr <= point_arr).all() and (point_arr <= upper_arr).all()):",
     "    if False and ((lower_arr <= point_arr).all() and (point_arr <= upper_arr).all()):",
     "f08 квантильное пересечение"),
    ("M17", "apps/api/model_impls/deepar.py",
     "    if not ((lower_arr <= point_arr).all() and (point_arr <= upper_arr).all()):",
     "    if not ((lower_arr < point_arr).all() and (point_arr < upper_arr).all()):",
     "f09 равенство на границе допустимо"),
    ("M18", "apps/api/model_impls/deepar.py",
     "    if not (np.isfinite(point).all() and np.isfinite(lower).all()\n"
     "            and np.isfinite(upper).all()):",
     "    if False and (np.isfinite(point).all() and np.isfinite(lower).all()\n"
     "            and np.isfinite(upper).all()):",
     "f03 NaN в отклике"),
    ("M19", "apps/api/model_impls/deepar.py",
     "    if len(rows) != horizon:",
     "    if False and len(rows) != horizon:",
     "f04 missing-строки целевого ряда"),
    ("M20", "apps/api/model_impls/deepar.py",
     '    if "unique_id" not in preds.columns:',
     '    if False and "unique_id" not in preds.columns:',
     "f05 unique_id-колонка отсутствует"),
    ("M21", "apps/api/model_impls/deepar.py",
     '    rows = preds[preds["unique_id"].astype(str) == _TARGET_UNIQUE_ID]',
     "    rows = preds.head(int(horizon))",
     "f06 выбор целевого ряда ПО unique_id (не по позиции)"),
    ("M22", "apps/api/model_impls/deepar.py",
     '    return rows.sort_values("ds", kind="stable").reset_index(drop=True)',
     "    return rows.reset_index(drop=True)",
     "f07 сортировка по ds (детерминированный порядок горизонта)"),
    ("M26", "apps/api/model_impls/deepar.py",
     '    if "DeepAR-median" not in rows.columns:',
     '    if False and "DeepAR-median" not in rows.columns:',
     "f01 медиана отсутствует"),
    ("M27", "apps/api/model_impls/deepar.py",
     "    if not matches:",
     "    if False and not matches:",
     "f02 квантильная колонка отсутствует"),
    # -- deepar.py: панельная проводка и контракт --
    ("M23", "apps/api/model_impls/deepar.py",
     '    resolve_probabilistic_loss(DEEPAR_LOSS_KEY, levels=plan["levels"])',
     '    pass  # ORACLE MUTATION: контрактный гейт Task 137 удалён',
     "f13 spy resolve_probabilistic_loss"),
    ("M24", "apps/api/model_impls/deepar.py",
     "а не потерять его.\n        raise\n    except NeuralContractError as exc:",
     "а не потерять его.\n        pass\n    except NeuralContractError as exc:",
     "f10 capacity passthrough"),
    ("M25", "apps/api/model_impls/deepar.py",
     '        raise ValueError(f"DeepAR: {exc}") from exc\n\n'
     "    rows = _target_rows(preds, int(horizon))",
     '        raise\n\n'
     "    rows = _target_rows(preds, int(horizon))",
     "f11 wrap ValueError"),
    ("M39", "apps/api/model_impls/deepar.py",
     '            "series": _TARGET_UNIQUE_ID,',
     '            "series": "series_9",',
     "d04 панель до runtime: уникальные id серий"),
    # -- deepar.py: бюджет/env и metadata-честность --
    ("M28", "apps/api/model_impls/deepar.py",
     "    if value < 1:",
     "    if value < 0:",
     "d02 env=0 fail-closed"),
    ("M29", "apps/api/model_impls/deepar.py",
     "        return DEEPAR_MAX_STEPS",
     "        return DEEPAR_MAX_STEPS + 7",
     "d02/a05 дефолт 300"),
    ("M30", "apps/api/model_impls/deepar.py",
     '        "max_steps": int(config.max_steps),',
     '        "max_steps": DEEPAR_MAX_STEPS,',
     "d02 env=77 -> payload.max_steps"),
    ("M31", "apps/api/model_impls/deepar.py",
     '        "seed": int(config.seed),',
     '        "seed": 42,',
     "d01/h02 seed echo"),
    ("M32", "apps/api/model_impls/deepar.py",
     '            "method": "neural_quantile_outputs",',
     '            "method": "conformal",',
     "g02/h02 intervals.method"),
    ("M33", "apps/api/model_impls/deepar.py",
     '            alias="DeepAR",',
     '            alias="deepar",',
     "d01 alias конструктора"),
    ("M34a", "apps/api/model_impls/deepar.py",
     '            loss=distribution_loss_cls(\n'
     '                distribution="StudentT", quantiles=quantiles,\n'
     '            ),',
     '            loss=distribution_loss_cls(\n'
     '                distribution="Normal", quantiles=quantiles,\n'
     '            ),',
     "d01 голова StudentT (замена семейства распределения)"),
    ("M59", "apps/api/model_impls/deepar.py",
     '            scaler_type="robust",',
     '            scaler_type="identity",',
     "d01 скейлер robust (Task 142a: против коллапса масштаба M2; "
     "живая семантика -- e05)"),
    ("M60", "apps/api/model_impls/deepar.py",
     "            trajectory_samples=DEEPAR_TRAJECTORY_SAMPLES,",
     "            trajectory_samples=100,",
     "d01 траекторный бюджет MC-квантилей"),
    ("M61", "apps/api/neural_contract.py",
     '    "distribution",\n)\nNEURAL_PROBABILISTIC_LOSSES',
     '    "distributionX",\n)\nNEURAL_PROBABILISTIC_LOSSES',
     "d03/f13 whitelist контракта теряет distribution -- гейт отказывает"),
    ("M35", "apps/api/model_impls/deepar.py",
     'DEEPAR_ADAPTER_ID = "neuralforecast-deepar"',
     'DEEPAR_ADAPTER_ID = "neuralforecast-deeparx"',
     "a05/g02/d05/h02 adapter_id"),
    ("M36", "apps/api/model_impls/deepar.py",
     "DEEPAR_MAX_STEPS = 300",
     "DEEPAR_MAX_STEPS = 307",
     "a05 константа бюджета 300"),
    ("M37", "apps/api/model_impls/deepar.py",
     "DEEPAR_MIN_SERIES = 5",
     "DEEPAR_MIN_SERIES = 4",
     "a05/c01 константа панели min_series=5"),
    # -- проводка: реестр / dispatch / yaml / executor --
    ("M40", "apps/api/model_execution.py",
     '        model_id="deepar", family_id="neural",',
     '        model_id="deeparx", family_id="neural",',
     "a01 реестр require(deepar)"),
    ("M41", "apps/api/model_execution.py",
     '        input_kind="panel",\n        requires_related_series=True,',
     '        input_kind="univariate",\n        requires_related_series=True,',
     "a01/h01 панельная ось input_kind=panel"),
    ("M42", "apps/api/model_execution.py",
     '        input_kind="panel",\n        requires_related_series=True,',
     '        input_kind="panel",\n        requires_related_series=False,',
     "a01 requires_related_series"),
    ("M43", "apps/api/model_execution.py",
     "        deterministic=True,\n"
     '        dependency_group="neural",\n'
     "        resource_capabilities=ModelResourceCapabilities(\n"
     '            memory_class="standard", gpu="optional",\n'
     "        ),\n"
     "    ),\n"
     "])",
     "        deterministic=False,\n"
     '        dependency_group="neural",\n'
     "        resource_capabilities=ModelResourceCapabilities(\n"
     '            memory_class="standard", gpu="optional",\n'
     "        ),\n"
     "    ),\n"
     "])",
     "a01 deterministic=True (deepar-запись, хвост реестра)"),
    ("M44", "apps/api/model_execution.py",
     '            "n_series": payload["n_series"],',
     '            "n_series": 1,',
     "h02 executor metadata n_series=5"),
    ("M45", "apps/api/model_execution.py",
     '            "intervals": payload["intervals"],\n'
     '            "deterministic": payload["deterministic"],\n'
     "        },\n"
     "    )\n\n\n"
     "def _xgboost_executor",
     '            "intervals": {},\n'
     '            "deterministic": payload["deterministic"],\n'
     "        },\n"
     "    )\n\n\n"
     "def _xgboost_executor",
     "h02 executor intervals mapping"),
    ("M46", "apps/api/routers/models.py",
     '        implementations["deepar"] = run_deepar_backtest',
     '        implementations["deeparx"] = run_deepar_backtest',
     "a03 dispatch + import-gate"),
    # -- panel-движок (backtesting.py) --
    ("M47", "apps/api/backtesting.py",
     '    if plan.objective != "level_forecast":\n'
     "        raise BacktestExecutionError(\n"
     '            "Панельный движок исполняет только level_forecast-планы "',
     '    if plan.objective != "multivariate":\n'
     "        raise BacktestExecutionError(\n"
     '            "Панельный движок исполняет только level_forecast-планы "',
     "h08 objective-гейт панельного движка"),
    ("M48", "apps/api/backtesting.py",
     '    if execution_contract.get("input_kind") != "panel":',
     '    if execution_contract.get("input_kind") != "panelx":',
     "h08 input_kind-гейт движка"),
    ("M49", "apps/api/backtesting.py",
     "    if len(names) < 2:",
     "    if len(names) < 1:",
     "h09 одиночная система -- не панель"),
    ("M50", "apps/api/backtesting.py",
     "            related_train = {\n"
     "                name: [float(value) for value in system.series[name][:n_train]]\n"
     "                for name in related_names\n"
     "            }\n"
     "            if fold_preprocessor is None:",
     "            related_train = {\n"
     "                name: [float(value) for value in system.series[name][:]]\n"
     "                for name in related_names\n"
     "            }\n"
     "            if fold_preprocessor is None:",
     "h11 related-ряды только train-префиксами (leakage; panel-блок)"),
    ("M51", "apps/api/backtesting.py",
     '            "target_series": target_name,',
     '            "target_series": "x",',
     "h08 панельный блок результата"),
    ("M52", "apps/api/backtesting.py",
     "        if fold.train_indices != list(range(n_train)):\n"
     "            raise BacktestExecutionError(\n"
     '                f"Fold {fold.fold}: train-срез панельной модели должен быть "',
     "        if False and fold.train_indices != list(range(n_train)):\n"
     "            raise BacktestExecutionError(\n"
     '                f"Fold {fold.fold}: train-срез панельной модели должен быть "',
     "h10 непрерывный префикс train"),
    # -- yaml и EDA shape-критерий --
    ("M53", "rules/modeling.yaml",
     "          lstm_hidden_size: [32, 64]\n          input_size: [24, 48]",
     "          lstm_hidden_size: [32]\n          input_size: [24, 48]",
     "a04 yaml 4 trials"),
    ("M54", "apps/api/eda_model_matrix.py",
     "        required = model.min_series or 5",
     "        required = model.min_series or 4",
     "h05 EDA fallback min_series=5"),
    ("M55", "apps/api/eda_model_matrix.py",
     "        enough = numeric_series >= required",
     "        enough = numeric_series > required",
     "h05 граница n_series=5 адмиссибельна"),
    ("M56", "apps/api/eda_model_matrix.py",
     "            blocking=not enough,",
     "            blocking=False,",
     "h05 fail-случай блокирующий"),
    # -- общий источник истины квантильного плана (tft.py) --
    ("M58", "apps/api/model_impls/deepar.py",
     "    raise ValueError(\n"
     "        \"DeepAR: квантильные колонки 'DeepAR-lo-<w>' отсутствуют в \"\n"
     "        \"отклике NeuralForecast (fail-closed)\"\n"
     "    )",
     "    return 0.0  # ORACLE MUTATION: width-суффикс fail-closed снят",
     "f02a width-суффикс fail-closed (точное сообщение)"),
    ("M57", "apps/api/model_impls/tft.py",
     '    return {\n        "method": "neural_quantile_outputs",',
     '    return {\n        "method": "conformal",',
     "g01 план method (единый источник tft)"),
]


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


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
    backup = _SNAPSHOT_DIR / Path(rel).name
    if not backup.exists():
        raise RuntimeError(f"{rel}: снапшот отсутствует")
    path.write_bytes(backup.read_bytes())
    if _sha(path) != expected_sha:
        raise RuntimeError(f"{rel}: восстановление не байт-чистое")


_SNAPSHOT_DIR = Path("/tmp/cert142_mut_snapshot")


def _snapshot(rel: str) -> None:
    """Снапшот рабочего дерева на старте кампании (Task 142a --
    некоммиченные изменения; git checkout затёр бы фикс)."""
    _SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    path = REPO / rel
    (_SNAPSHOT_DIR / Path(rel).name).write_bytes(path.read_bytes())


def _drop_snapshot() -> None:
    if _SNAPSHOT_DIR.exists():
        for item in _SNAPSHOT_DIR.iterdir():
            item.unlink()
        _SNAPSHOT_DIR.rmdir()


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
    files = sorted({m[1] for m in batch})
    try:
        # снапшот некоммиченного рабочего дерева (Task 142a) на старте
        for rel in files:
            _snapshot(rel)
        print(f"Мутационная кампания Task 142/142a: {len(batch)}/"
              f"{len(MUTATIONS)} мутаций"
              f"{'' if not only else ' (батч: ' + ' '.join(sorted(only)) + ')'}",
              flush=True)
        results: list[tuple[str, str, str]] = []
        for mid, rel, old, new, expected in batch:
            path = REPO / rel
            baseline_sha = _sha(path)
            try:
                _apply(rel, old, new)
                ok, tail = _run_kill_subset(ORACLE_SUBSET)
                verdict = "SURVIVED" if ok else "KILLED"
            finally:
                _restore(rel, baseline_sha)
            results.append((mid, verdict, tail))
            print(f"{mid} {verdict:>8}  | {expected}", flush=True)
    finally:
        _drop_snapshot()

    killed = sum(1 for _, verdict, _ in results if verdict == "KILLED")
    print(f"\nИтог: {killed}/{len(results)} KILLED")
    survivors = [mid for mid, verdict, _ in results if verdict == "SURVIVED"]
    print("Survivors:", survivors or "нет")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
