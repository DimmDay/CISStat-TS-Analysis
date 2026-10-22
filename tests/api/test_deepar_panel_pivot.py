# tests/api/test_deepar_panel_pivot.py
"""PANEL-MODELS-3c: entity-pivot глобальных нейромоделей -- настоящий
DeepAR-панель (этап 3 из 3c-цепочки спеки spec_panel_models_2026-10-20.md).

TDD RED -- тесты написаны ДО реализации (спека §3c, TDD-план §5c):

- 5c-1 pivot: long-format unique_id = ЗНАЧЕНИЯ сущностей (НЕ series_i
  колонок Task 142), через сертифицированный to_long_format (fail-closed
  на дубликаты (unique_id, ds) = per-entity регулярность);
- 5c-2 гейт n_entities < DEEPAR_MIN_SERIES -- честный отказ адаптера
  (ValueError) и движка (BacktestExecutionError) ДО затрат на фит;
- 5c-3 прогноз содержит КАЖДУЮ сущность панели (по-сущностной прогноз);
- 5c-4 cohort-изоляция: deepar_panel -- input_kind="panel_entity"
  (сущностный контур, cohort_contract panel_entity), Task 142 deepar --
  input_kind="panel" (колонко-параллельный) -- обе ветки живут;
- 5c-5 детерминизм seed: random_state -> NeuralTrainingConfig.seed ->
  fold_seed -> random_seed КОНСТРУКТОРА модели (ресертификация Task 137);
- 5c-6 regression-инвариант: колонко-параллельный DeepAR Task 142 не
  изменён (полная регрессия -- существующие сюиты; здесь -- адресные
  гварды сигнатур/контрактов).

Нейро-runtime (torch/neuralforecast) -- ОПЦИОНАЛЬНАЯ dependency-группа
(прецедент тестов Task 137-142: pytest.importorskip). Гейты/пивот/
паспорт/движок тестируются БЕЗ runtime (ленивые импорты адаптера);
живые нейро-оракулы и wiring-оракулы (spy на train_and_forecast --
урок «прижата spy-тестом» Task 138) -- отдельными классами.
"""
from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from app.preprocessing.panel import build_panel_frame
from apps.api.backtesting import BacktestExecutionError, run_panel_entity_backtest_plan
from apps.api.model_execution import MODEL_EXECUTION_REGISTRY, _panel_entity_executor
from apps.api.model_execution import ModelExecutionRequest


DEEPAR_MIN_SERIES = 5   # честный перенос правила Task 142 на настоящую панель
DEEPAR_MIN_TRAIN = 30   # семейный пол нейро-пятёрки (DEEPAR_MIN_TRAIN адаптера)


# ── DGP ──────────────────────────────────────────────────────────────────────

def _make_panel_df(
    *,
    n_entities: int = 6,
    t_per_entity: int = 48,
    seed: int = 42,
    freq: str = "MS",
    start: str = "2021-01-01",
    inject_nan: bool = False,
    prefix: str = "region_",
):
    """Сбалансированная панель: per-entity уровень + тренд + сезон + шум.

    freq -- частота сетки (гейт общей частоты тестируется сменой частоты
    части сущностей; prefix -- уникальные имена сущностей группы)."""
    rng = np.random.default_rng(seed)
    dates = pd.date_range(start, periods=t_per_entity, freq=freq)
    rows: list[dict] = []
    for i in range(n_entities):
        entity = f"{prefix}{i}"
        level = 10.0 + 3.0 * i
        for t in range(t_per_entity):
            value = (
                level
                + 0.2 * t
                + 2.0 * np.sin(2.0 * np.pi * (t % 12) / 12.0)
                + rng.normal(0.0, 0.3)
            )
            rows.append({"entity": entity, "date": dates[t], "y": float(value)})
    frame = pd.DataFrame(rows)
    if inject_nan:
        frame.loc[frame.index[3], "y"] = np.nan
    return frame


def _build_frame(df: pd.DataFrame):
    return build_panel_frame(
        df, date_column="date", entity_column="entity",
        value_columns=["y"], target_column="y",
    )


@pytest.fixture()
def panel_frame():
    return _build_frame(_make_panel_df())


def _stub_predictions(frame, horizon: int, *, drift: float = 0.1) -> dict:
    """Детерминированный stub-прогноз адаптера: для КАЖДОЙ сущности --
    последнее train-значение + дрейф шага; lower/upper = point ± 1."""
    data = frame.frame
    entities = sorted(data[frame.entity_column].astype(str).unique().tolist())
    forecasts = {}
    for entity in entities:
        rows = data[data[frame.entity_column].astype(str) == entity]
        last = float(rows[frame.target_column].iloc[-1])
        point = [last + drift * (step + 1) for step in range(horizon)]
        forecasts[entity] = {
            "point": point,
            "lower": [value - 1.0 for value in point],
            "upper": [value + 1.0 for value in point],
        }
    return forecasts


# ── 5c-1: pivot -- long-format unique_id = значения сущностей ───────────────

class TestPivot:
    def test_long_format_unique_id_is_entity_value(self, panel_frame):
        from apps.api.model_impls.deepar import _panel_entity_long_frame

        long = _panel_entity_long_frame(panel_frame)
        assert list(long.columns) == ["unique_id", "ds", "y"]
        entities = set(long["unique_id"].astype(str).unique())
        expected = set(panel_frame.frame[panel_frame.entity_column].astype(str).unique())
        assert entities == expected
        # unique_id -- ЗНАЧЕНИЯ сущности, НЕ позиционные series_i Task 142
        assert not any(name.startswith("series_") for name in entities)
        # y -- float без NaN; ds -- datetime
        assert long["y"].dtype == float
        assert not long["y"].isna().any()
        assert pd.api.types.is_datetime64_any_dtype(long["ds"])

    def test_long_format_per_entity_grid_preserved(self, panel_frame):
        from apps.api.model_impls.deepar import _panel_entity_long_frame

        long = _panel_entity_long_frame(panel_frame)
        first = panel_frame.frame[panel_frame.entity_column].astype(str).unique()[0]
        entity_rows = long[long["unique_id"].astype(str) == first]
        source_rows = panel_frame.frame[
            panel_frame.frame[panel_frame.entity_column].astype(str) == first
        ]
        assert len(entity_rows) == len(source_rows)
        assert (
            entity_rows["y"].to_numpy() == source_rows[source_rows.columns[-1]].to_numpy()
        ).all()

    def test_long_format_fail_closed_on_duplicate_entity_date(self):
        # Дубликат (entity, date) ломает per-entity регулярность; панельный
        # контракт build_panel_frame его уже отвергает -- pivot-оракул
        # проверяет СВОЙ fail-closed (сертифицированный to_long_format)
        # на duck-typed frame-подобном объекте.
        from apps.api.model_impls.deepar import _panel_entity_long_frame
        from apps.api.neural_contract import NeuralContractError

        duplicated = pd.concat(
            [_make_panel_df(n_entities=2, t_per_entity=6),
             _make_panel_df(n_entities=1, t_per_entity=6)],
            ignore_index=True,
        )
        fake = SimpleNamespace(
            frame=duplicated, date_column="date", entity_column="entity",
            target_column="y", value_columns=["y"],
        )
        with pytest.raises((NeuralContractError, ValueError)) as exc:
            _panel_entity_long_frame(fake)
        assert "повторяются точки" in str(exc.value)

    def test_long_format_fail_closed_on_nan_target(self):
        from apps.api.model_impls.deepar import _panel_entity_long_frame
        from apps.api.neural_contract import NeuralContractError

        fake = SimpleNamespace(
            frame=_make_panel_df(n_entities=2, t_per_entity=8, inject_nan=True),
            date_column="date", entity_column="entity",
            target_column="y", value_columns=["y"],
        )
        with pytest.raises((NeuralContractError, ValueError)):
            _panel_entity_long_frame(fake)


# ── 5c-2: гейты адаптера (fail-closed ДО фита, без нейро-runtime) ────────────

class TestAdapterGates:
    def test_gate_n_entities_below_min_series(self):
        from apps.api.model_impls.deepar import _deepar_panel_fit_predict

        frame = _build_frame(_make_panel_df(n_entities=4, t_per_entity=48))
        with pytest.raises(ValueError) as exc:
            _deepar_panel_fit_predict(frame, horizon=4)
        message = str(exc.value)
        assert str(DEEPAR_MIN_SERIES) in message
        assert "сущност" in message.lower()
        # честный перенос правила Task 142: колонко-параллельная
        # семантика в тексте отказа не участвует
        assert "related" not in message.lower()

    def test_gate_per_entity_length_below_neural_floor(self):
        from apps.api.model_impls.deepar import _deepar_panel_fit_predict

        frame = _build_frame(_make_panel_df(n_entities=6, t_per_entity=20))
        with pytest.raises(ValueError) as exc:
            _deepar_panel_fit_predict(frame, horizon=4)
        message = str(exc.value)
        # отказ называет сущность и минимум (fail-closed, без молчаливого
        # выбрасывания коротких сущностей)
        assert str(DEEPAR_MIN_TRAIN) in message
        assert "region_0" in message or "сущност" in message.lower()

    def test_gate_window_infeasible_per_entity(self):
        from apps.api.model_impls.deepar import _deepar_panel_fit_predict

        frame = _build_frame(_make_panel_df(n_entities=6, t_per_entity=44))
        with pytest.raises(ValueError) as exc:
            _deepar_panel_fit_predict(
                frame, horizon=10, params={"input_size": 40},
            )
        message = str(exc.value)
        assert "input_size" in message and "horizon" in message

    def test_gate_horizon_must_be_positive(self, panel_frame):
        from apps.api.model_impls.deepar import _deepar_panel_fit_predict

        with pytest.raises(ValueError):
            _deepar_panel_fit_predict(panel_frame, horizon=0)

    def test_gate_nan_target_refused(self):
        from apps.api.model_impls.deepar import _deepar_panel_fit_predict

        frame = _build_frame(_make_panel_df(n_entities=6, t_per_entity=48, inject_nan=True))
        with pytest.raises(ValueError):
            _deepar_panel_fit_predict(frame, horizon=4)

    def test_gate_common_frequency_required(self):
        from apps.api.model_impls.deepar import _deepar_panel_fit_predict

        # per-entity регулярность соблюдена, но сетки сущностей имеют
        # РАЗНЫЕ частоты -- сущностная панель не собирается в один
        # NeuralForecast-runtime (fail-closed, честный текст). Имена
        # сущностей групп уникальны (prefix), длины >= пола нейро-пятёрки.
        mixed = pd.concat(
            [
                _make_panel_df(n_entities=3, t_per_entity=36, freq="MS", prefix="ms_"),
                _make_panel_df(n_entities=3, t_per_entity=36, freq="QE", start="2021-01-01", prefix="q_"),
            ],
            ignore_index=True,
        )
        frame = _build_frame(mixed)
        with pytest.raises(ValueError) as exc:
            _deepar_panel_fit_predict(frame, horizon=4)
        assert "частот" in str(exc.value).lower()


# ── Реестр/каталог: deepar_panel как panel_entity-модель ─────────────────────

class TestRegistryAndCatalog:
    def test_deepar_panel_registered_as_panel_entity(self):
        definition = MODEL_EXECUTION_REGISTRY.require("deepar_panel")
        assert definition.family_id == "panel"
        assert definition.input_kind == "panel_entity"
        assert definition.deterministic is True
        assert definition.supports_prediction_intervals is True
        assert "backtest" in definition.actions
        assert definition.engine == "neuralforecast"
        assert "neuralforecast" in definition.required_packages

    def test_descriptor_honest_runtime(self):
        descriptor = MODEL_EXECUTION_REGISTRY.describe("deepar_panel")
        assert descriptor["input_kind"] == "panel_entity"
        try:
            import neuralforecast  # noqa: F401
            available = True
        except ModuleNotFoundError:
            available = False
        assert descriptor["runtime_available"] is available

    def test_flat_executor_refusal_mentions_deepar_panel(self):
        request = ModelExecutionRequest(target=[1.0, 2.0, 3.0], horizon=1)
        with pytest.raises(Exception) as exc:
            _panel_entity_executor(request)
        assert "deepar_panel" in str(exc.value)
        assert "run_panel_entity_backtest_plan" in str(exc.value)

    def test_cohort_isolation_from_task_142(self):
        # 5c-4: две «панели» явно различимы -- deepar (Task 142,
        # колонко-параллельный) vs deepar_panel (сущностный).
        deepar_142 = MODEL_EXECUTION_REGISTRY.require("deepar")
        deepar_entity = MODEL_EXECUTION_REGISTRY.require("deepar_panel")
        assert deepar_142.input_kind == "panel"
        assert deepar_entity.input_kind == "panel_entity"
        assert deepar_142.requires_related_series is True
        assert deepar_entity.requires_related_series is False

    def test_catalog_family_panel_contains_deepar_panel(self):
        import yaml

        with open("rules/modeling.yaml", "r", encoding="utf-8") as handle:
            catalog = yaml.safe_load(handle)
        assert catalog["metadata"]["version"] == "1.4.1"
        families = {family["id"]: family for family in catalog["families"]}
        panel_family = families["panel"]
        model_ids = {model["id"] for model in panel_family["models"]}
        assert "deepar_panel" in model_ids
        deepar_panel = next(
            model for model in panel_family["models"] if model["id"] == "deepar_panel"
        )
        assert deepar_panel["min_series"] == DEEPAR_MIN_SERIES
        assert deepar_panel["supports_prediction_intervals"] is True
        assert deepar_panel["supports_exogenous"] is False

    def test_task_142_adapter_surface_untouched(self):
        # 5c-6: regression-инвариант -- Task 142 поверхность не изменена
        # (адресный гвард; полная регрессия -- существующие сюиты).
        from apps.api.model_impls import deepar as deepar_module

        assert deepar_module.DEEPAR_MIN_SERIES == DEEPAR_MIN_SERIES
        assert callable(deepar_module._deepar_fit_predict)
        assert callable(deepar_module._panel_frame)
        assert deepar_module._TARGET_UNIQUE_ID == "series_0"


# ── 5c-3: движок -- прогноз содержит КАЖДУЮ сущность; fold-локальность ──────

class TestEngineDeeparPanel:
    @pytest.fixture()
    def stub_calls(self, monkeypatch):
        """Stub адаптера в движке: записывает вызовы, отдаёт детерминированный
        по-сущностной прогноз (last train + дрейф, ±1 интервал)."""
        from apps.api.model_impls import deepar as deepar_module

        calls: list[dict] = []

        def stub(frame, *, horizon, params=None, random_state=42):
            calls.append({
                "horizon": int(horizon),
                "params": dict(params or {}),
                "random_state": int(random_state),
                "frame": frame,
                "n_entities": frame.n_entities,
            })
            return {
                "adapter_id": "neuralforecast-deepar-panel",
                "entities": sorted(
                    frame.frame[frame.entity_column].astype(str).unique().tolist()
                ),
                "forecasts": _stub_predictions(frame, int(horizon)),
                "n_entities": frame.n_entities,
                "nobs_total": int(len(frame.frame)),
                "horizon": int(horizon),
                "params": {},
                "freq": {"kind": "datetime", "value": "MS"},
                "intervals": {
                    "method": "neural_quantile_outputs",
                    "loss": "distribution",
                    "distribution": "StudentT",
                    "alpha": 0.05,
                },
                "seed": int(random_state),
                "max_steps": 300,
                "deterministic": True,
            }

        monkeypatch.setattr(deepar_module, "_deepar_panel_fit_predict", stub)
        return calls

    def test_forecast_contains_every_entity(self, panel_frame, stub_calls):
        result = run_panel_entity_backtest_plan(
            model_id="deepar_panel", model_name="DeepAR (panel)",
            family_id="panel", frame=panel_frame,
            validation={"strategy": "expanding", "horizon": 4, "n_folds": 2},
            seasonal_period=12,
        )
        assert result["status"] == "success"
        entities = set(panel_frame.frame[panel_frame.entity_column].astype(str))
        # 5c-3: КАЖДАЯ сущность панели в по-сущностных метриках и OOF
        assert set(result["panel"]["entity_metrics"].keys()) == entities
        oof_entities = {point["entity"] for point in result["oof_predictions"]}
        assert oof_entities == entities
        # НЕ series_i колонок Task 142
        assert not any(name.startswith("series_") for name in oof_entities)

    def test_oof_points_carry_probabilistic_surface(self, panel_frame, stub_calls):
        result = run_panel_entity_backtest_plan(
            model_id="deepar_panel", model_name="DeepAR (panel)",
            family_id="panel", frame=panel_frame,
            validation={"strategy": "expanding", "horizon": 4, "n_folds": 2},
            seasonal_period=12,
        )
        for point in result["oof_predictions"]:
            assert "lower" in point and "upper" in point
            assert point["lower"] <= point["predicted"] <= point["upper"]

    def test_fold_local_fit_train_only_prefix(self, panel_frame, stub_calls):
        # leakage-гвард: адаптер получает train-префикс (max дата train
        # строго раньше min даты test fold'а)
        run_panel_entity_backtest_plan(
            model_id="deepar_panel", model_name="DeepAR (panel)",
            family_id="panel", frame=panel_frame,
            validation={"strategy": "expanding", "horizon": 4, "n_folds": 2},
            seasonal_period=12,
        )
        assert len(stub_calls) == 2
        data = panel_frame.frame
        date_column = panel_frame.date_column
        for call, fold_dates in zip(stub_calls, _folds_dates(panel_frame, 4, 2)):
            call_dates = call["frame"].frame[date_column]
            assert call_dates.max() < min(fold_dates["test"])
            assert set(fold_dates["train"]) == set(
                data[data[date_column].isin(fold_dates["train"])][date_column].unique()
            )

    def test_per_entity_and_pooled_metrics_consistent(self, panel_frame, stub_calls):
        result = run_panel_entity_backtest_plan(
            model_id="deepar_panel", model_name="DeepAR (panel)",
            family_id="panel", frame=panel_frame,
            validation={"strategy": "expanding", "horizon": 4, "n_folds": 2},
            seasonal_period=12,
        )
        panel_block = result["panel"]
        assert panel_block["pooled_metrics"]["mae"] >= 0.0
        assert panel_block["pooled_mase_scale_method"]
        # pooled OOF -- конкатенация по-сущностных OOF (микро-усреднение)
        assert result["n_test"] == len(result["oof_predictions"]) == 6 * 4 * 2

    def test_cohort_contract_panel_entity(self, panel_frame, stub_calls):
        result = run_panel_entity_backtest_plan(
            model_id="deepar_panel", model_name="DeepAR (panel)",
            family_id="panel", frame=panel_frame,
            validation={"strategy": "expanding", "horizon": 4, "n_folds": 2},
            seasonal_period=12,
        )
        contract = result["cohort_contract"]
        assert contract["panel_entity"] is True
        assert contract["input_kind"] == "panel_entity"
        assert contract["n_entities"] == panel_frame.n_entities
        assert contract["min_entities"] == DEEPAR_MIN_SERIES
        assert contract["balance"] == panel_frame.balance

    def test_engine_gate_n_entities_fail_fast(self, monkeypatch):
        # 5c-2: гейт движка -- BacktestExecutionError с честным текстом
        # ДО fold'ов (стаб НЕ вызывается -- fail-fast)
        from apps.api.model_impls import deepar as deepar_module

        def boom(*args, **kwargs):
            raise AssertionError("адаптер не должен вызываться при отказе гейта")

        monkeypatch.setattr(deepar_module, "_deepar_panel_fit_predict", boom)
        frame = _build_frame(_make_panel_df(n_entities=4, t_per_entity=48))
        with pytest.raises(BacktestExecutionError) as exc:
            run_panel_entity_backtest_plan(
                model_id="deepar_panel", model_name="DeepAR (panel)",
                family_id="panel", frame=frame,
                validation={"strategy": "expanding", "horizon": 4, "n_folds": 2},
                seasonal_period=12,
            )
        message = str(exc.value)
        assert str(DEEPAR_MIN_SERIES) in message
        assert "сущност" in message.lower()

    def test_neural_capacity_error_passes_through(self, panel_frame, monkeypatch):
        # Прецедент Task 138c: ресурсный отказ нейро-runtime идёт НАСКВОЗЬ
        # (не оборачивается в BacktestExecutionError -- HTTP-слой обязан
        # увидеть честный статус).
        from apps.api.model_impls import deepar as deepar_module
        from apps.api.neural_contract import NeuralRuntimeCapacityError

        def boom(frame, **kwargs):
            raise NeuralRuntimeCapacityError("torch OOM (stub)")

        monkeypatch.setattr(deepar_module, "_deepar_panel_fit_predict", boom)
        with pytest.raises(NeuralRuntimeCapacityError):
            run_panel_entity_backtest_plan(
                model_id="deepar_panel", model_name="DeepAR (panel)",
                family_id="panel", frame=panel_frame,
                validation={"strategy": "expanding", "horizon": 4, "n_folds": 1},
                seasonal_period=12,
            )

    def test_adapter_error_wrapped_honest(self, panel_frame, monkeypatch):
        from apps.api.model_impls import deepar as deepar_module

        def boom(frame, **kwargs):
            raise ValueError("DeepAR: пер-сущностная история недостаточна")

        monkeypatch.setattr(deepar_module, "_deepar_panel_fit_predict", boom)
        with pytest.raises(BacktestExecutionError) as exc:
            run_panel_entity_backtest_plan(
                model_id="deepar_panel", model_name="DeepAR (panel)",
                family_id="panel", frame=panel_frame,
                validation={"strategy": "expanding", "horizon": 4, "n_folds": 1},
                seasonal_period=12,
            )
        assert "пер-сущностная история" in str(exc.value)

    def test_task_142_model_refused_by_entity_engine(self, panel_frame):
        # 5c-4/5c-6: колонко-параллельный DeepAR Task 142 (input_kind=
        # "panel") НЕ исполняется сущностным движком -- cohort-изоляция.
        with pytest.raises(BacktestExecutionError) as exc:
            run_panel_entity_backtest_plan(
                model_id="deepar", model_name="DeepAR (Task 142)",
                family_id="neural", frame=panel_frame,
                validation={"strategy": "expanding", "horizon": 4, "n_folds": 1},
                seasonal_period=12,
            )
        assert "panel_entity" in str(exc.value)


def _folds_dates(frame, horizon: int, n_folds: int):
    """Раскладка дат движка (зеркало build_panel_entity_folds) для гварда
    fold-локальности: expanding по датам внутри сущностей."""
    from app.modeling.panel_models import build_panel_entity_folds

    plan = build_panel_entity_folds(
        frame, horizon=horizon, n_folds=n_folds, strategy="expanding",
        mode="dates", gap=0,
    )
    return [
        {"train": list(fold.train_dates), "test": list(fold.test_dates)}
        for fold in plan
    ]


# ── 5c-5: wiring-оракулы (spy) и живые нейро-оракулы ────────────────────────

class TestAdapterWiring:
    """Детерминизм/поверхность БЕЗ живого фита: fake-модуль neuralforecast
    на месте _require_neuralforecast -- РЕАЛЬНЫЙ train_and_forecast
    исполняет свой контракт целиком (seed -> fold_seed -> random_seed
    КОНСТРУКТОРА; ресертификация Task 137), FakeDeepAR записывает kwargs
    конструктора (урок «прижата spy-тестом» сертификации Task 138).
    Same-seed бит-паритет живого рантайма -- отдельным классом ниже."""

    @pytest.fixture()
    def fake_nf(self, monkeypatch, panel_frame):
        from apps.api.model_impls import neural_runtime

        dates = sorted(panel_frame.frame[panel_frame.date_column].unique())
        entities = sorted(
            panel_frame.frame[panel_frame.entity_column].astype(str).unique()
        )
        horizon = 4

        def _make_preds(scale: float = 1.0) -> pd.DataFrame:
            rows = []
            for index, entity in enumerate(entities):
                for step in range(horizon):
                    point = (100.0 + index + 0.5 * step) * scale
                    rows.append({
                        "unique_id": entity,
                        "ds": (
                            pd.Timestamp(dates[-1])
                            + pd.tseries.frequencies.to_offset("MS") * (step + 1)
                        ),
                        "DeepAR-median": point,
                        "DeepAR-lo-95.0": point - 2.0,
                        "DeepAR-hi-95.0": point + 2.0,
                    })
            return pd.DataFrame(rows)

        constructor_kwargs: list[dict] = []

        class FakeDeepAR:
            def __init__(self, **kwargs):
                constructor_kwargs.append(dict(kwargs))

        class FakeLoss:
            def __init__(self, **kwargs):
                self.kwargs = dict(kwargs)

        class FakeMAE:
            pass

        class FakeNF:
            def __init__(self, *, models, freq):
                self.models_list = models
                self.freq = freq

            def fit(self, **kwargs):
                self.fit_kwargs = dict(kwargs)

            def predict(self, **kwargs):
                return _make_preds()

        fake_module = SimpleNamespace(
            NeuralForecast=FakeNF,
            models=SimpleNamespace(DeepAR=FakeDeepAR),
            losses=SimpleNamespace(
                pytorch=SimpleNamespace(DistributionLoss=FakeLoss, MAE=FakeMAE),
            ),
        )
        monkeypatch.setattr(
            neural_runtime, "require_neuralforecast", lambda: fake_module,
        )
        return SimpleNamespace(
            constructor_kwargs=constructor_kwargs,
            make_preds=_make_preds,
            horizon=horizon,
            entities=entities,
        )

    def test_seed_reaches_model_constructor(self, panel_frame, fake_nf):
        from apps.api.model_impls.deepar import _deepar_panel_fit_predict
        from apps.api.neural_contract import fold_seed

        payload = _deepar_panel_fit_predict(
            panel_frame, horizon=4, random_state=123,
        )
        assert len(fake_nf.constructor_kwargs) == 1
        kwargs = fake_nf.constructor_kwargs[0]
        # Сид доходит до КОНСТРУКТОРА (ресертификация Task 137)
        assert kwargs["random_seed"] == fold_seed(123, fold_index=0)
        # Поверхность Task 142a: DistributionLoss(StudentT) + robust
        assert kwargs["alias"] == "DeepAR"
        assert kwargs["h"] == 4
        assert kwargs["input_size"] == 24
        assert kwargs["scaler_type"] == "robust"
        assert kwargs["loss"].kwargs["distribution"] == "StudentT"
        assert kwargs["trajectory_samples"] == 1000
        # payload: КАЖДАЯ сущность с point/lower/upper (5c-3)
        assert set(payload["forecasts"].keys()) == set(fake_nf.entities)
        for block in payload["forecasts"].values():
            assert len(block["point"]) == 4
            assert all(
                low <= mid <= up
                for low, mid, up in zip(block["lower"], block["point"], block["upper"])
            )
        assert payload["deterministic"] is True
        assert payload["intervals"]["loss"] == "distribution"
        assert payload["intervals"]["method"] == "neural_quantile_outputs"
        assert payload["n_entities"] == len(fake_nf.entities)
        assert payload["adapter_id"] == "neuralforecast-deepar-panel"

    def test_missing_entity_in_response_fail_closed(self, panel_frame, fake_nf, monkeypatch):
        from apps.api.model_impls import neural_runtime
        from apps.api.model_impls.deepar import _deepar_panel_fit_predict

        preds = fake_nf.make_preds()
        broken = preds[preds["unique_id"] != preds["unique_id"].iloc[0]]

        def broken_predict(self, **kwargs):
            return broken

        fake_module = neural_runtime.require_neuralforecast()
        monkeypatch.setattr(
            fake_module.NeuralForecast,  # класс FakeNF фикстуры
            "predict",
            broken_predict,
            raising=True,
        )
        with pytest.raises(ValueError) as exc:
            _deepar_panel_fit_predict(panel_frame, horizon=4)
        assert "сущност" in str(exc.value).lower()
        assert "fail-closed" in str(exc.value)

    def test_clamp_invariant_fail_closed(self, panel_frame, fake_nf, monkeypatch):
        from apps.api.model_impls import neural_runtime
        from apps.api.model_impls.deepar import _deepar_panel_fit_predict

        preds = fake_nf.make_preds().copy()
        preds.loc[preds.index[0], "DeepAR-lo-95.0"] = (
            float(preds["DeepAR-median"].iloc[0]) + 5.0
        )

        def broken_predict(self, **kwargs):
            return preds

        fake_module = neural_runtime.require_neuralforecast()
        monkeypatch.setattr(
            fake_module.NeuralForecast, "predict", broken_predict, raising=True,
        )
        with pytest.raises(Exception) as exc:
            _deepar_panel_fit_predict(panel_frame, horizon=4)
        assert "lower" in str(exc.value) or "инвариант" in str(exc.value).lower()


def _deepar_panel_fit_predict_safe(frame, *, horizon, random_state: int = 42):
    from apps.api.model_impls.deepar import _deepar_panel_fit_predict

    return _deepar_panel_fit_predict(frame, horizon, random_state=random_state)


class TestLiveDeeparPanel:
    """Живые нейро-оракулы: только при установленной neural-группе
    (прецедент тестов Task 137-142: importorskip)."""

    @pytest.fixture(autouse=True)
    def _require_runtime(self):
        pytest.importorskip("neuralforecast", reason="neural runtime -- опциональная группа")

    def test_live_fit_per_entity_surface_and_determinism(self, panel_frame, monkeypatch):
        from apps.api.model_impls.deepar import _deepar_panel_fit_predict

        monkeypatch.setenv("CISSTAT_NEURAL_MAX_STEPS", "40")
        params = {"input_size": 12, "lstm_hidden_size": 8, "alpha": 0.05}
        first = _deepar_panel_fit_predict(
            panel_frame, horizon=4, params=params, random_state=7,
        )
        second = _deepar_panel_fit_predict(
            panel_frame, horizon=4, params=params, random_state=7,
        )
        # same-seed бит-паритет
        for entity in first["forecasts"]:
            assert first["forecasts"][entity]["point"] == second["forecasts"][entity]["point"]
            assert first["forecasts"][entity]["lower"] == second["forecasts"][entity]["lower"]
        # другой seed -- другой прогноз
        third = _deepar_panel_fit_predict(
            panel_frame, horizon=4, params=params, random_state=8,
        )
        any_point = sorted(first["forecasts"])[0]
        assert first["forecasts"][any_point]["point"] != third["forecasts"][any_point]["point"]
        # probabilistic-поверхность per entity
        for block in first["forecasts"].values():
            assert all(
                low <= mid <= up and np.isfinite(mid)
                for low, mid, up in zip(block["lower"], block["point"], block["upper"])
            )


# ── Паспорт панели: гейт deepar_panel ────────────────────────────────────────

class TestPassportGate:
    def test_passport_deepar_panel_applicable(self):
        from app.preprocessing.panel import build_panel_passport

        passport = build_panel_passport(
            _make_panel_df(n_entities=6, t_per_entity=48),
            date_column="date", entity_column="entity",
            value_columns=["y"], target_column="y",
        )
        gate = passport.to_dict()["models"]["deepar_panel"]
        assert gate["applicable"] is True
        assert gate["gates"]["n_entities"] == 6
        assert gate["gates"]["min_entities"] == DEEPAR_MIN_SERIES

    def test_passport_deepar_panel_refused_below_min_entities(self):
        from app.preprocessing.panel import build_panel_passport

        passport = build_panel_passport(
            _make_panel_df(n_entities=4, t_per_entity=48),
            date_column="date", entity_column="entity",
            value_columns=["y"], target_column="y",
        )
        gate = passport.to_dict()["models"]["deepar_panel"]
        assert gate["applicable"] is False
        assert any(str(DEEPAR_MIN_SERIES) in reason for reason in gate["reasons"])

    def test_passport_deepar_panel_refused_short_entities(self):
        from app.preprocessing.panel import build_panel_passport

        passport = build_panel_passport(
            _make_panel_df(n_entities=6, t_per_entity=20),
            date_column="date", entity_column="entity",
            value_columns=["y"], target_column="y",
        )
        gate = passport.to_dict()["models"]["deepar_panel"]
        assert gate["applicable"] is False
        assert any(str(DEEPAR_MIN_TRAIN) in reason for reason in gate["reasons"])


# ── Сессионный панельный контур (UI-контракты, изоляция R4) ──────────────────

class TestSessionPanelContour:
    """Панельные эндпоинты /v1/session/modeling/panel/*: passport ->
    confirm -> candidates -> backtest/forecast; изоляция от однорядного
    контура (R4 -- tripwire на prepare_passport_series/build_modeling_context)."""

    @pytest.fixture(scope="class")
    def client(self):
        from fastapi.testclient import TestClient

        from apps.api.main import app

        with TestClient(app) as test_client:
            # Warm-up: устанавливает cookie cisstat_session_id (пустая сессия)
            test_client.get("/v1/session/modeling/state")
            assert test_client.cookies.get("cisstat_session_id")
            yield test_client

    @pytest.fixture()
    def seeded_client(self, client):
        from apps.api.session_store import get_session_store

        session_id = client.cookies.get("cisstat_session_id")
        store = get_session_store()
        session = store.get_or_create(session_id)
        df = _make_panel_df(n_entities=6, t_per_entity=48)
        df["x"] = df["y"] * 0.5 + 1.0
        session.set_dataframe(df, reason="panel-3c-tests")
        session.target_column = "y"
        session.date_column = "date"
        store.save(session)
        yield client
        store.delete(session_id) if hasattr(store, "delete") else None

    PANEL_COLUMNS = {
        "date_column": "date",
        "entity_column": "entity",
        "value_columns": ["y", "x"],
        "target_column": "y",
    }

    def test_r4_tripwire_univariate_contour_untouched(
        self, seeded_client, monkeypatch,
    ):
        from app.core.passport import prepare_passport_series
        from apps.api.modeling_workflow import build_modeling_context

        def boom(*args, **kwargs):
            raise AssertionError("однорядный контур вызван из панельного")

        monkeypatch.setattr(
            "app.core.passport.prepare_passport_series", boom,
        )
        monkeypatch.setattr(
            "apps.api.routers.modeling_session.build_modeling_context", boom,
        )
        # Панельный флоу целиком -- без единого касания однорядного контура
        build = seeded_client.post(
            "/v1/session/modeling/panel/passport", json=self.PANEL_COLUMNS,
        )
        assert build.status_code == 200, build.text
        confirm = seeded_client.post("/v1/session/modeling/panel/passport/confirm")
        assert confirm.status_code == 200, confirm.text
        candidates = seeded_client.get("/v1/session/modeling/panel/candidates")
        assert candidates.status_code == 200, candidates.text

    def test_passport_build_confirm_conflict_cycle(self, seeded_client):
        build = seeded_client.post(
            "/v1/session/modeling/panel/passport", json=self.PANEL_COLUMNS,
        )
        assert build.status_code == 200, build.text
        passport = build.json()["passport"]
        assert passport["models"]["deepar_panel"]["applicable"] is True
        assert build.json()["fingerprint"]
        confirm = seeded_client.post("/v1/session/modeling/panel/passport/confirm")
        assert confirm.status_code == 200, confirm.text
        assert confirm.json()["checkpoint_id"]
        # Повторное подтверждение того же состояния -- честный 409
        again = seeded_client.post("/v1/session/modeling/panel/passport/confirm")
        assert again.status_code == 409
        # Повторное построение того же паспорта -- честный 409
        rebuild = seeded_client.post(
            "/v1/session/modeling/panel/passport", json=self.PANEL_COLUMNS,
        )
        assert rebuild.status_code == 409

    def test_candidates_gated_by_panel_entry(self, client):
        fresh = client.post(
            "/v1/session/modeling/panel/passport", json=self.PANEL_COLUMNS,
        )
        if fresh.status_code == 409:
            pass  # сессия класса уже подтверждена -- гейт сработал ранее
        candidates = client.get("/v1/session/modeling/panel/candidates")
        assert candidates.status_code in {200, 409, 422}
        if candidates.status_code == 422:
            assert "панел" in candidates.text.lower()
        if candidates.status_code == 200:
            cards = {card["model_id"]: card for card in candidates.json()["models"]}
            # PANEL-GMM-4: пятая карточка сущностного контура.
            assert set(cards) == {"panel_fe", "panel_re", "panel_var", "deepar_panel", "panel_gmm"}
            deepar_card = cards["deepar_panel"]
            assert deepar_card["gates"]["min_entities"] == DEEPAR_MIN_SERIES

    def test_candidates_after_confirm(self, seeded_client):
        seeded_client.post(
            "/v1/session/modeling/panel/passport", json=self.PANEL_COLUMNS,
        )
        seeded_client.post("/v1/session/modeling/panel/passport/confirm")
        candidates = seeded_client.get("/v1/session/modeling/panel/candidates")
        assert candidates.status_code == 200, candidates.text
        body = candidates.json()
        cards = {card["model_id"]: card for card in body["models"]}
        # PANEL-GMM-4: пятая карточка сущностного контура.
        assert set(cards) == {"panel_fe", "panel_re", "panel_var", "deepar_panel", "panel_gmm"}
        # Гейты паспорта честны: 6x48 панель применима для FE/RE/deepar_panel
        assert cards["panel_fe"]["applicable"] is True
        assert cards["deepar_panel"]["gates"]["n_entities"] == 6
        assert cards["deepar_panel"]["gates"]["min_entity_observations"] == DEEPAR_MIN_TRAIN
        # PANEL-GMM-4: карточка panel_gmm появилась (реальные гейты
        # паспорта _gmm_computability); отдельного ключа "gmm" нет --
        # ключ карточки panel_gmm (канон имён каталога).
        assert "gmm" not in cards
        assert "panel_gmm" in cards

    def test_backtest_fe_session(self, seeded_client):
        seeded_client.post(
            "/v1/session/modeling/panel/passport", json=self.PANEL_COLUMNS,
        )
        seeded_client.post("/v1/session/modeling/panel/passport/confirm")
        run = seeded_client.post(
            "/v1/session/modeling/panel/backtest",
            json={
                "model_id": "panel_fe",
                "validation": {"strategy": "expanding", "horizon": 4, "n_folds": 2},
                "seasonal_period": 12,
            },
        )
        assert run.status_code == 200, run.text
        body = run.json()
        assert body["status"] == "success"
        assert body["cohort_contract"]["panel_entity"] is True
        assert set(body["panel"]["entity_metrics"]) == {
            f"region_{i}" for i in range(6)
        }
        assert body["n_test"] == 6 * 4 * 2

    def test_backtest_task_142_model_isolated_at_http(self, seeded_client):
        # R4/5c-4: колонко-параллельный DeepAR Task 142 не проходит
        # сущностный контур на HTTP-границе
        seeded_client.post(
            "/v1/session/modeling/panel/passport", json=self.PANEL_COLUMNS,
        )
        seeded_client.post("/v1/session/modeling/panel/passport/confirm")
        run = seeded_client.post(
            "/v1/session/modeling/panel/backtest",
            json={"model_id": "deepar", "validation": {"horizon": 4, "n_folds": 1}},
        )
        assert run.status_code == 422
        assert "panel_entity" in run.text

    def test_backtest_without_panel_entry_409(self, client):
        # Без подтверждённого checkpoint panel_entry панельный бэктест
        # честно отвергается (409 -- гейт панельного контура)
        run = client.post(
            "/v1/session/modeling/panel/backtest",
            json={"model_id": "panel_fe", "validation": {"horizon": 4, "n_folds": 1}},
        )
        assert run.status_code in {409, 422}

    def test_forecast_fe_scenario_cycle(self, seeded_client):
        seeded_client.post(
            "/v1/session/modeling/panel/passport", json=self.PANEL_COLUMNS,
        )
        seeded_client.post("/v1/session/modeling/panel/passport/confirm")
        without_paths = seeded_client.post(
            "/v1/session/modeling/panel/forecast",
            json={"model_id": "panel_fe", "horizon": 3},
        )
        assert without_paths.status_code == 422
        assert "сценар" in without_paths.text.lower()
        paths = {
            f"region_{i}": {"x": [1.0, 1.1, 1.2]} for i in range(6)
        }
        run = seeded_client.post(
            "/v1/session/modeling/panel/forecast",
            json={
                "model_id": "panel_fe",
                "horizon": 3,
                "exog_paths": paths,
                "confidence": 0.95,
            },
        )
        assert run.status_code == 200, run.text
        body = run.json()
        assert body["method"]
        assert len(body["entities"]) == 6
        for record in body["entities"]:
            assert len(record["point"]) == 3
            assert len(record["dates"]) == 3
            assert all(
                low <= mid <= up
                for low, mid, up in zip(
                    record["lower"], record["point"], record["upper"],
                )
            )

    def test_forecast_deepar_panel_runtime_gate(self, seeded_client):
        # Без neural-группы -- честный 422 (runtime-гейт); с группой --
        # живой путь покрыт адаптерными классами выше.
        seeded_client.post(
            "/v1/session/modeling/panel/passport", json=self.PANEL_COLUMNS,
        )
        seeded_client.post("/v1/session/modeling/panel/passport/confirm")
        try:
            import neuralforecast  # noqa: F401
            pytest.skip("neural-группа установлена -- живой путь, не гейт")
        except ModuleNotFoundError:
            pass
        run = seeded_client.post(
            "/v1/session/modeling/panel/forecast",
            json={"model_id": "deepar_panel", "horizon": 3},
        )
        assert run.status_code == 422
        assert "недоступ" in run.text.lower()
