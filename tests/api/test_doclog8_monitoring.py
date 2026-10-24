# tests/api/test_doclog8_monitoring.py
"""Task DOCLOG-8 (spec_documentation_logging.md §6 D12, §19 строка
DOCLOG-8, §6.1 мониторинг, B07/F11, §20 AC12/AC15): D12 «Сверка прогноза
с фактом» -- monitoring контур: frozen forecast vintage, actual vintages,
выравнивание, честные оценки, revisions/threshold decisions.

Критерий завершения (§19): поздний факт и revise НЕ переписывают старый
выпуск/OOF -- фактический vintage иммутабелен, пересмотр факта создаёт
НОВЫЙ actual vintage и НОВУЮ сверку; прежний forecast vintage не
меняется; незрелые горизонты исключены ЯВНО (не нулевая ошибка).

AC15: actual_vintage пересмотрен/пришёл поздно/не совпали единицы --
новая оценка либо отказ с причиной (MonitoringUnitsMismatchError с
честной причиной; конверсия -- только явно переданным factor).
AC12: MAPE с нулями факта / MASE без scale / нет зрелых горизонтов --
null + reason, НЕ 0 и не «pass». Автопереобучение НЕ следует из
превышения порога (§6.1): threshold -- зафиксированный факт
(threshold_exceeded/within/not_evaluable), решение -- отдельная
append-only запись человека (record_decision), decision_action в
результате сверки всегда null.

Оракулы на СВОИХ данных (RUN-D8xxxxxx, корпус дизъюнктен repo);
изоляция каждого теста -- паттерн test_doclog2_snapshots.py (свой
tmp_path/CISSTAT_DATA_DIR, сброс singleton-фабрик ВКЛЮЧАЯ monitoring
registry/artifacts/session). Прогноз НЕ пересчитывается: сверка читает
frozen payload артефакта kind="forecast" с проверкой целостности байтов
(T8); битые/чужие байты -- честный отказ, не выдуманная цифра.
Знание forecast_artifact_id чужого run НЕ является правом (T7/T15).
Идемпотентность сверок -- UNIQUE(run_id, idempotency_key) (§10.3/AC09).
"""
from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from apps.api import research_runs
from apps.api.identity import DEFAULT_TENANT_ID, SubjectRef
from apps.api.research_runs import ResearchRun
from apps.api.session_store import AnalysisSession

# ── Изоляция КАЖДОГО теста (паттерн test_doclog2_snapshots.py) ────────


@pytest.fixture(autouse=True)
def _isolated_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("CISSTAT_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("CISSTAT_RUNS_BACKEND", raising=False)
    monkeypatch.delenv("CISSTAT_IDENTITY_MODE", raising=False)
    monkeypatch.delenv("CISSTAT_API_KEYS", raising=False)
    monkeypatch.delenv("CISSTAT_IDENTITY_SALT", raising=False)
    monkeypatch.delenv("CISSTAT_ARTIFACTS_BACKEND", raising=False)
    monkeypatch.delenv("CISSTAT_SNAPSHOTS_BACKEND", raising=False)
    monkeypatch.delenv("CISSTAT_MONITORING_BACKEND", raising=False)
    research_runs.reset_research_run_store_for_testing()
    research_runs.reset_dataset_file_store_for_testing()
    from apps.api import artifact_store, monitoring, report_snapshot
    from apps.api.session_store import reset_session_store_for_testing

    artifact_store.reset_artifact_registry_for_testing()
    artifact_store.reset_artifact_object_store_for_testing()
    report_snapshot.reset_snapshot_registry_for_testing()
    monitoring.reset_monitoring_registry_for_testing()
    reset_session_store_for_testing()
    yield
    research_runs.reset_research_run_store_for_testing()
    research_runs.reset_dataset_file_store_for_testing()
    artifact_store.reset_artifact_registry_for_testing()
    artifact_store.reset_artifact_object_store_for_testing()
    report_snapshot.reset_snapshot_registry_for_testing()
    monitoring.reset_monitoring_registry_for_testing()
    reset_session_store_for_testing()


@pytest.fixture()
def client():
    from apps.api.main import app

    with TestClient(app) as test_client:
        yield test_client


# ── Сид-хелперы: run/сессия/subject на СВОИХ данных ──────────────────

RUN_ID = "RUN-D8A00001"
SESSION_ID = "d8-seed-session"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _seed_session(session_id: str = SESSION_ID) -> AnalysisSession:
    from apps.api.session_store import get_session_store

    store = get_session_store()
    session = store.get(session_id)
    if session is not None:
        return session
    session = AnalysisSession(session_id=session_id)
    session.owner_subject = SubjectRef.from_session(session_id).subject_id
    session.tenant_id = DEFAULT_TENANT_ID
    session.target_column = "value"
    session.date_column = "date"
    store.save(session)
    return session


def _seed_bound_run(
    run_id: str = RUN_ID,
    session_id: str = SESSION_ID,
    *,
    context_id: str | None = "ctx-d8-1",
    data_revision: int | None = 3,
) -> ResearchRun:
    from apps.api.research_runs import get_research_run_store

    run = ResearchRun(
        run_id=run_id,
        session_id=session_id,
        dataset_fingerprint="d8" * 16,
        dataset_name="monitoring-seed",
        target_column="value",
        target_column_source="user",
        created_at=_now_iso(),
        last_active_at=_now_iso(),
        status="active",
        context_id=context_id,
        data_revision=data_revision,
        owner_subject=SubjectRef.from_session(session_id).subject_id,
        tenant_id=DEFAULT_TENANT_ID,
        ownership="bound",
    )
    get_research_run_store().upsert_run(run)
    return run


def _seed_run(run_id: str = RUN_ID, session_id: str = SESSION_ID) -> None:
    _seed_session(session_id)
    _seed_bound_run(run_id, session_id)


def _owner_subject(session_id: str = SESSION_ID) -> SubjectRef:
    return SubjectRef.from_session(session_id)


def _foreign_subject() -> SubjectRef:
    return SubjectRef.from_session("d8-foreign-session")


def _service():
    from apps.api.monitoring import MonitoringService

    return MonitoringService.create_default()


def _make_artifact(
    kind: str,
    producer_key: str,
    payload,
    *,
    run_id: str = RUN_ID,
    context_id: str | None = None,
    data_revision: int | None = None,
    refs: dict | None = None,
):
    from apps.api.artifact_store import (
        ResultArtifact,
        artifact_content_sha256,
        canonical_json_bytes,
        get_artifact_object_store,
        get_artifact_registry,
        new_artifact_id,
    )

    content = canonical_json_bytes(payload)
    objects = get_artifact_object_store()
    staged = objects.stage_bytes(content, "application/json")
    storage_key = objects.commit_staged(staged)
    artifact = ResultArtifact(
        artifact_id=new_artifact_id(),
        run_id=run_id,
        kind=kind,
        producer_key=producer_key,
        media_type="application/json",
        size_bytes=len(content),
        payload_sha256=artifact_content_sha256(content),
        data_digest=None,
        storage_key=storage_key,
        context_id=context_id,
        data_revision=data_revision,
        input_kind=None,
        panel=None,
        dependencies=[],
        refs=dict(refs or {}),
    )
    stored, _created = get_artifact_registry().register_artifact(artifact)
    return stored


FORECAST_POINTS = [
    {"step": 1, "date": "2026-09-01", "value": 5.0, "ci_lower": 4.0, "ci_upper": 6.0},
    {"step": 2, "date": "2026-10-01", "value": 6.0, "ci_lower": 4.8, "ci_upper": 7.2},
    {"step": 3, "date": "2026-11-01", "value": 7.0, "ci_lower": 5.6, "ci_upper": 8.4},
    {"step": 4, "date": "2026-12-01", "value": 8.0, "ci_lower": 6.4, "ci_upper": 9.6},
    {"step": 5, "date": "2027-01-01", "value": 9.0, "ci_lower": 7.2, "ci_upper": 10.8},
]


def _seed_forecast(
    run_id: str = RUN_ID,
    *,
    points: list | None = None,
    forecast_id: str = "fc-d8-1",
) -> object:
    return _make_artifact(
        "forecast",
        f"forecast:{forecast_id}",
        {
            "forecast_id": forecast_id,
            "model_card_id": "card-d8-1",
            "generated_at": _now_iso(),
            "horizon": len(points or FORECAST_POINTS),
            "alpha": 0.05,
            "points": points or FORECAST_POINTS,
        },
        run_id=run_id,
        context_id="ctx-d8-1",
        data_revision=3,
        refs={"forecast_id": forecast_id},
    )


def _seed_batch(
    run_id: str = RUN_ID,
    *,
    subject: object | None = None,
    periods: list[tuple[str, float]] | None = None,
    target_name: str = "gdp_growth",
    entity_id: str | None = None,
    units: str = "percent",
    as_of: str = "2026-12-01T00:00:00+00:00",
    idempotency_key: str = "",
) -> object:
    values = [
        {"period": period, "value": value}
        for period, value in (periods or [("2026-09-01", 4.8), ("2026-10-01", 6.1)])
    ]
    batch, _created = _service().register_actual_batch(
        run_id,
        subject if subject is not None else _owner_subject(),
        target_name=target_name,
        entity_id=entity_id,
        units=units,
        as_of=as_of,
        values=values,
        idempotency_key=idempotency_key,
    )
    return batch


# ══════════════════════════════════════════════════════════════════════
# 1. Поверхность модуля (§19.1: новые модули -- проектные названия)
# ══════════════════════════════════════════════════════════════════════


class TestModuleSurface:
    def test_import_and_schema_versions(self):
        from apps.api import monitoring

        assert monitoring.MONITORING_SCHEMA_VERSION == "doclog.monitoring/1"
        assert monitoring.ACTUAL_VINTAGE_SCHEMA_VERSION == "doclog.actual_vintage/1"
        assert monitoring.COMPARISON_SCHEMA_VERSION == "doclog.monitoring_comparison/1"
        assert monitoring.DECISION_SCHEMA_VERSION == "doclog.monitoring_decision/1"

    def test_decision_actions_catalog(self):
        from apps.api import monitoring

        # §6.1: решение -- отдельное действие человека; «retrain» --
        # ЗАПРОС на переобучение (запись), не автоматическое действие.
        assert monitoring.DECISION_ACTIONS == frozenset(
            {"none", "accept", "investigate", "retrain_requested"}
        )

    def test_error_taxonomy(self):
        from apps.api import monitoring

        for exc in (
            monitoring.MonitoringError,
            monitoring.MonitoringValidationError,
            monitoring.MonitoringUnitsMismatchError,
            monitoring.MonitoringForecastUnavailable,
            monitoring.MonitoringAccessDenied,
            monitoring.MonitoringIdempotencyConflictError,
            monitoring.MonitoringNotFoundError,
        ):
            assert issubclass(exc, Exception)


# ══════════════════════════════════════════════════════════════════════
# 2. Регистрация actual vintage: валидация и честные отказы (AC15)
# ══════════════════════════════════════════════════════════════════════


class TestActualBatchValidation:
    def test_valid_manual_batch(self):
        _seed_run()
        batch = _seed_batch()
        assert batch.batch_id
        assert batch.run_id == RUN_ID
        assert batch.target_name == "gdp_growth"
        assert batch.units == "percent"
        assert batch.point_count == 2
        assert batch.values[0] == {"period": "2026-09-01", "value": 4.8}
        assert batch.schema_version == "doclog.actual_vintage/1"

    def test_empty_values_rejected(self):
        _seed_run()
        with pytest.raises(Exception, match="пуст"):
            _service().register_actual_batch(
                RUN_ID, _owner_subject(), target_name="gdp_growth",
                units="percent", as_of=_now_iso(), values=[],
            )

    def test_non_finite_value_rejected(self):
        _seed_run()
        with pytest.raises(Exception, match="числ"):
            _service().register_actual_batch(
                RUN_ID, _owner_subject(), target_name="gdp_growth",
                units="percent", as_of=_now_iso(),
                values=[{"period": "2026-09-01", "value": float("nan")}],
            )

    def test_empty_period_or_target_rejected(self):
        _seed_run()
        with pytest.raises(Exception, match="target"):
            _service().register_actual_batch(
                RUN_ID, _owner_subject(), target_name="  ",
                units="percent", as_of=_now_iso(),
                values=[{"period": "2026-09-01", "value": 1.0}],
            )
        with pytest.raises(Exception, match="period"):
            _service().register_actual_batch(
                RUN_ID, _owner_subject(), target_name="gdp_growth",
                units="percent", as_of=_now_iso(),
                values=[{"period": "  ", "value": 1.0}],
            )

    def test_duplicate_periods_within_batch_rejected(self):
        _seed_run()
        with pytest.raises(Exception, match="дубл"):
            _service().register_actual_batch(
                RUN_ID, _owner_subject(), target_name="gdp_growth",
                units="percent", as_of=_now_iso(),
                values=[
                    {"period": "2026-09-01", "value": 1.0},
                    {"period": "2026-09-01", "value": 2.0},
                ],
            )

    def test_bad_as_of_rejected(self):
        _seed_run()
        with pytest.raises(Exception, match="as_of"):
            _service().register_actual_batch(
                RUN_ID, _owner_subject(), target_name="gdp_growth",
                units="percent", as_of="not-a-date",
                values=[{"period": "2026-09-01", "value": 1.0}],
            )

    def test_foreign_run_registration_denied(self):
        _seed_run()
        foreign_run = "RUN-D8FOREIGN1"
        _seed_run(foreign_run, "d8-foreign-session")
        # Владелец RUN_ID не может писать в чужой run (T7/T15).
        with pytest.raises(Exception):
            _service().register_actual_batch(
                foreign_run, _owner_subject(), target_name="x",
                units="u", as_of=_now_iso(),
                values=[{"period": "2026-09-01", "value": 1.0}],
            )


# ══════════════════════════════════════════════════════════════════════
# 3. Vintage-семантика: иммутабельность, revisions, идемпотентность
# ══════════════════════════════════════════════════════════════════════


class TestActualVintageSemantics:
    def test_revision_creates_new_batch_old_untouched(self):
        """§6.1/AC15: пересмотр факта -- НОВЫЙ vintage; прежний не
        переписывается (append-only)."""
        _seed_run()
        first = _seed_batch(periods=[("2026-09-01", 4.8)])
        second = _seed_batch(periods=[("2026-09-01", 5.3)])
        assert first.batch_id != second.batch_id
        listed = _service().list_actual_batches(RUN_ID, _owner_subject())
        assert len(listed) == 2
        assert listed[0].values[0]["value"] == 4.8
        assert listed[1].values[0]["value"] == 5.3

    def test_idempotent_registration_same_body(self):
        _seed_run()
        values = [{"period": "2026-09-01", "value": 4.8}]
        first, created1 = _service().register_actual_batch(
            RUN_ID, _owner_subject(), target_name="gdp_growth",
            units="percent", as_of="2026-12-01T00:00:00+00:00",
            values=values, idempotency_key="idem-d8-1",
        )
        second, created2 = _service().register_actual_batch(
            RUN_ID, _owner_subject(), target_name="gdp_growth",
            units="percent", as_of="2026-12-01T00:00:00+00:00",
            values=values, idempotency_key="idem-d8-1",
        )
        assert created1 is True
        assert created2 is False
        assert first.batch_id == second.batch_id

    def test_idempotency_conflict_different_body(self):
        _seed_run()
        _service().register_actual_batch(
            RUN_ID, _owner_subject(), target_name="gdp_growth",
            units="percent", as_of="2026-12-01T00:00:00+00:00",
            values=[{"period": "2026-09-01", "value": 4.8}],
            idempotency_key="idem-d8-2",
        )
        from apps.api.monitoring import MonitoringIdempotencyConflictError

        with pytest.raises(MonitoringIdempotencyConflictError):
            _service().register_actual_batch(
                RUN_ID, _owner_subject(), target_name="gdp_growth",
                units="percent", as_of="2026-12-01T00:00:00+00:00",
                values=[{"period": "2026-09-01", "value": 9.9}],
                idempotency_key="idem-d8-2",
            )


# ══════════════════════════════════════════════════════════════════════
# 4. Единицы: as_is / конверсия / отказ с причиной (AC15)
# ══════════════════════════════════════════════════════════════════════


class TestUnitsAlignment:
    def _comparison(self, *, forecast_units, units="percent", conversion=None):
        _seed_run()
        artifact = _seed_forecast()
        batch = _seed_batch(units=units)
        record, _created = _service().build_comparison(
            RUN_ID, _owner_subject(),
            forecast_artifact_id=artifact.artifact_id,
            actual_batch_id=batch.batch_id,
            forecast_units=forecast_units,
            units_conversion=conversion,
        )
        return record

    def test_units_match_as_is(self):
        record = self._comparison(forecast_units="percent")
        assert record.units_check == "as_is"

    def test_units_unknown_honest(self):
        """forecast_units не объявлены -- честное unknown, не фабкация."""
        record = self._comparison(forecast_units=None)
        assert record.units_check == "unknown"

    def test_units_mismatch_refused_with_reason(self):
        from apps.api.monitoring import MonitoringUnitsMismatchError

        _seed_run()
        artifact = _seed_forecast()
        batch = _seed_batch(units="percent")
        with pytest.raises(MonitoringUnitsMismatchError, match="единиц"):
            _service().build_comparison(
                RUN_ID, _owner_subject(),
                forecast_artifact_id=artifact.artifact_id,
                actual_batch_id=batch.batch_id,
                forecast_units="tonnes",
            )
        # Отказ БЕЗ записи: сравнение не создано (честный отказ 422).
        assert _service().list_comparisons(RUN_ID, _owner_subject()) == []

    def test_units_conversion_explicit_factor(self):
        record = self._comparison(
            forecast_units="basis_points",
            units="percent",
            conversion={"factor": 100.0, "note": "percent -> basis points"},
        )
        assert record.units_check == "converted"
        # Факт 4.8 percent -> 480 bp; прогноз 5.0 bp -> |err| = 475.
        pair = record.result["pairs"][0]
        assert pair["actual_value"] == pytest.approx(480.0)
        assert pair["signed_error"] == pytest.approx(475.0)
        assert pair["absolute_error"] == pytest.approx(475.0)

    def test_zero_conversion_factor_rejected(self):
        _seed_run()
        artifact = _seed_forecast()
        batch = _seed_batch()
        from apps.api.monitoring import MonitoringValidationError

        with pytest.raises(MonitoringValidationError):
            _service().build_comparison(
                RUN_ID, _owner_subject(),
                forecast_artifact_id=artifact.artifact_id,
                actual_batch_id=batch.batch_id,
                forecast_units="bp",
                units_conversion={"factor": 0.0, "note": "bad"},
            )


# ══════════════════════════════════════════════════════════════════════
# 5. Зрелость горизонтов: незрелые исключены ЯВНО (AC15, §6.1)
# ══════════════════════════════════════════════════════════════════════


class TestMaturity:
    def test_matured_and_excluded_counts(self):
        _seed_run()
        artifact = _seed_forecast()  # горизонт 5
        # Факт доступен только за 3 из 5 периодов прогноза.
        batch = _seed_batch(periods=[
            ("2026-09-01", 4.8), ("2026-10-01", 6.1), ("2026-11-01", 7.4),
        ])
        record, _created = _service().build_comparison(
            RUN_ID, _owner_subject(),
            forecast_artifact_id=artifact.artifact_id,
            actual_batch_id=batch.batch_id,
        )
        assert record.matured_count == 3
        assert record.excluded_count == 2
        assert set(record.result["alignment"]["excluded_labels"]) == {
            "2026-12-01", "2027-01-01"
        }

    def test_excluded_horizons_have_no_error(self):
        """§6.1: ещё не наступившие горизонты НЕ получают нулевую
        ошибку -- в pairs их нет вовсе."""
        _seed_run()
        artifact = _seed_forecast()
        batch = _seed_batch(periods=[("2026-09-01", 4.8)])
        record, _created = _service().build_comparison(
            RUN_ID, _owner_subject(),
            forecast_artifact_id=artifact.artifact_id,
            actual_batch_id=batch.batch_id,
        )
        assert len(record.result["pairs"]) == 1
        assert all(
            pair["date"] == "2026-09-01" for pair in record.result["pairs"]
        )

    def test_out_of_horizon_actuals_counted(self):
        _seed_run()
        artifact = _seed_forecast()
        batch = _seed_batch(periods=[
            ("2026-09-01", 4.8), ("2025-06-01", 3.3),
        ])
        record, _created = _service().build_comparison(
            RUN_ID, _owner_subject(),
            forecast_artifact_id=artifact.artifact_id,
            actual_batch_id=batch.batch_id,
        )
        assert record.out_of_horizon_count == 1
        assert record.result["alignment"]["out_of_horizon_labels"] == [
            "2025-06-01"
        ]

    def test_no_matured_horizons_null_not_zero(self):
        """AC12: нет зрелых горизонтов -- агрегаты null + reason, не 0."""
        _seed_run()
        artifact = _seed_forecast()
        batch = _seed_batch(periods=[("2025-06-01", 3.3)])
        record, _created = _service().build_comparison(
            RUN_ID, _owner_subject(),
            forecast_artifact_id=artifact.artifact_id,
            actual_batch_id=batch.batch_id,
        )
        assert record.matured_count == 0
        aggregates = record.result["aggregates"]
        assert aggregates["mae"] is None
        assert aggregates["mae_reason"] == "no_matured_horizons"
        assert aggregates["mean_signed_error"] is None


# ══════════════════════════════════════════════════════════════════════
# 6. Честные метрики (AC12): null + reason, не 0
# ══════════════════════════════════════════════════════════════════════


class TestMetricsHonesty:
    def _comparison(self, periods, **kwargs):
        _seed_run()
        artifact = _seed_forecast()
        batch = _seed_batch(periods=periods)
        record, _created = _service().build_comparison(
            RUN_ID, _owner_subject(),
            forecast_artifact_id=artifact.artifact_id,
            actual_batch_id=batch.batch_id, **kwargs,
        )
        return record

    def test_pair_metrics_known_numbers(self):
        record = self._comparison([
            ("2026-09-01", 4.8), ("2026-10-01", 6.1), ("2026-11-01", 7.4),
        ])
        pairs = record.result["pairs"]
        assert pairs[0]["signed_error"] == pytest.approx(-0.2)
        assert pairs[0]["absolute_error"] == pytest.approx(0.2)
        assert pairs[0]["ape"] == pytest.approx(0.2 / 4.8)
        aggregates = record.result["aggregates"]
        assert aggregates["mae"] == pytest.approx((0.2 + 0.1 + 0.4) / 3)
        assert aggregates["mean_signed_error"] == pytest.approx(
            (-0.2 + 0.1 + 0.4) / 3
        )

    def test_mape_zero_actual_null_with_reason(self):
        """AC12: фактический ноль -- ape неопределена; MAPE по корпусу с
        нулями -- null + reason + список нулевых периодов, НЕ 0."""
        record = self._comparison([
            ("2026-09-01", 0.0), ("2026-10-01", 6.1),
        ])
        pairs = record.result["pairs"]
        assert pairs[0]["ape"] is None
        assert pairs[0]["ape_undefined_reason"] == "actual_zero"
        aggregates = record.result["aggregates"]
        assert aggregates["mape"] is None
        assert aggregates["mape_reason"] == "mape_undefined_actual_zero"
        assert aggregates["mape_zero_periods"] == ["2026-09-01"]
        # MAE при этом ЧЕСТНО считaeтся (не зависит от ape).
        assert aggregates["mae"] == pytest.approx((5.0 + 0.1) / 2)

    def test_mape_all_defined_computed(self):
        record = self._comparison([
            ("2026-09-01", 4.8), ("2026-10-01", 6.1),
        ])
        aggregates = record.result["aggregates"]
        expected = ((0.2 / 4.8) + (0.1 / 6.1)) / 2
        assert aggregates["mape"] == pytest.approx(expected)
        assert aggregates["mape_reason"] is None

    def test_mase_requires_scale(self):
        record = self._comparison([("2026-09-01", 4.8)])
        aggregates = record.result["aggregates"]
        assert aggregates["mase"] is None
        assert aggregates["mase_reason"] == "mase_scale_required"

    def test_mase_with_scale_computed(self):
        record = self._comparison(
            [("2026-09-01", 4.8), ("2026-10-01", 6.1)],
            mase_scale=0.5,
        )
        aggregates = record.result["aggregates"]
        assert aggregates["mase"] == pytest.approx(((0.2 + 0.1) / 2) / 0.5)

    def test_mase_zero_scale_invalid_input(self):
        """MASE с нулевым scale -- не число: service отвергает вход
        (422-семантика); чистая функция даёт null + reason."""
        from apps.api import monitoring

        result = monitoring.compute_comparison_result(
            {"horizon": 1, "alpha": 0.05, "points": FORECAST_POINTS[:1]},
            [{"period": "2026-09-01", "value": 4.8}],
            mase_scale=0.0,
        )
        assert result["aggregates"]["mase"] is None
        assert result["aggregates"]["mase_reason"] == "mase_scale_invalid"

    def test_interval_coverage_with_bounds(self):
        record = self._comparison([
            ("2026-09-01", 4.8),   # в [4.0, 6.0] -> hit
            ("2026-10-01", 7.5),   # вне [4.8, 7.2] -> miss
            ("2026-11-01", 7.0),   # в [5.6, 8.4] -> hit
        ])
        aggregates = record.result["aggregates"]
        assert aggregates["interval_hits"] == 2
        assert aggregates["interval_coverage"] == pytest.approx(2 / 3)

    def test_interval_bounds_missing_honest(self):
        _seed_run()
        points = [
            {"step": 1, "date": "2026-09-01", "value": 5.0},
            {"step": 2, "date": "2026-10-01", "value": 6.0},
        ]
        artifact = _seed_forecast(points=points)
        batch = _seed_batch(periods=[
            ("2026-09-01", 4.8), ("2026-10-01", 6.1),
        ])
        record, _created = _service().build_comparison(
            RUN_ID, _owner_subject(),
            forecast_artifact_id=artifact.artifact_id,
            actual_batch_id=batch.batch_id,
        )
        aggregates = record.result["aggregates"]
        assert aggregates["interval_coverage"] is None
        assert aggregates["interval_coverage_reason"] == "interval_bounds_missing"
        assert all(pair["interval_hit"] is None for pair in record.result["pairs"])


# ══════════════════════════════════════════════════════════════════════
# 7. Целостность прогноза: frozen payload, T8, T7 (без пересчёта)
# ══════════════════════════════════════════════════════════════════════


class TestForecastIntegrity:
    def test_missing_forecast_artifact_honest(self):
        _seed_run()
        batch = _seed_batch()
        from apps.api.monitoring import MonitoringForecastUnavailable

        with pytest.raises(MonitoringForecastUnavailable, match="не найден"):
            _service().build_comparison(
                RUN_ID, _owner_subject(),
                forecast_artifact_id="art-d8-nonexistent",
                actual_batch_id=batch.batch_id,
            )

    def test_corrupted_forecast_bytes_refused(self, monkeypatch):
        """T8: расхождение payload_sha256 -- битые байты не выдаются за
        валидные; сверка не строится на подменённых числах."""
        _seed_run()
        artifact = _seed_forecast()
        from apps.api.artifact_store import get_artifact_object_store

        tampered = json.dumps({
            "forecast_id": "fc-d8-1", "horizon": 1, "alpha": 0.05,
            "points": [{"step": 1, "date": "2026-09-01", "value": 0.0001}],
        }).encode("utf-8")
        monkeypatch.setattr(
            get_artifact_object_store(),
            "read_bytes",
            lambda key: tampered,
        )
        batch = _seed_batch()
        from apps.api.monitoring import MonitoringForecastUnavailable

        with pytest.raises(MonitoringForecastUnavailable, match="Целостность"):
            _service().build_comparison(
                RUN_ID, _owner_subject(),
                forecast_artifact_id=artifact.artifact_id,
                actual_batch_id=batch.batch_id,
            )

    def test_wrong_kind_refused(self):
        _seed_run()
        not_forecast = _make_artifact(
            "data_frame", "dataframe:d8-x", {"rows": 1},
            context_id="ctx-d8-1", data_revision=3,
        )
        batch = _seed_batch()
        from apps.api.monitoring import MonitoringForecastUnavailable

        with pytest.raises(MonitoringForecastUnavailable, match="kind"):
            _service().build_comparison(
                RUN_ID, _owner_subject(),
                forecast_artifact_id=not_forecast.artifact_id,
                actual_batch_id=batch.batch_id,
            )

    def test_foreign_run_forecast_denied(self):
        _seed_run()
        foreign_run = "RUN-D8FOREIGN2"
        _seed_run(foreign_run, "d8-foreign-session")
        foreign_artifact = _seed_forecast(run_id=foreign_run)
        batch = _seed_batch()
        from apps.api.monitoring import MonitoringAccessDenied

        with pytest.raises(MonitoringAccessDenied):
            _service().build_comparison(
                RUN_ID, _owner_subject(),
                forecast_artifact_id=foreign_artifact.artifact_id,
                actual_batch_id=batch.batch_id,
            )


# ══════════════════════════════════════════════════════════════════════
# 8. Идемпотентность сверок (§10.3/AC09)
# ══════════════════════════════════════════════════════════════════════


class TestComparisonIdempotency:
    def _params(self, artifact, batch):
        return dict(
            forecast_artifact_id=artifact.artifact_id,
            actual_batch_id=batch.batch_id,
        )

    def test_same_key_same_body_same_comparison(self):
        _seed_run()
        artifact = _seed_forecast()
        batch = _seed_batch()
        params = self._params(artifact, batch)
        first, created1 = _service().build_comparison(
            RUN_ID, _owner_subject(), idempotency_key="cmp-d8-1", **params,
        )
        second, created2 = _service().build_comparison(
            RUN_ID, _owner_subject(), idempotency_key="cmp-d8-1", **params,
        )
        assert created1 is True
        assert created2 is False
        assert first.comparison_id == second.comparison_id

    def test_same_key_different_body_conflict(self):
        _seed_run()
        artifact = _seed_forecast()
        batch = _seed_batch()
        _service().build_comparison(
            RUN_ID, _owner_subject(),
            idempotency_key="cmp-d8-2",
            forecast_artifact_id=artifact.artifact_id,
            actual_batch_id=batch.batch_id,
        )
        other_batch = _seed_batch(periods=[("2026-09-01", 1.0)])
        from apps.api.monitoring import MonitoringIdempotencyConflictError

        with pytest.raises(MonitoringIdempotencyConflictError):
            _service().build_comparison(
                RUN_ID, _owner_subject(),
                idempotency_key="cmp-d8-2",
                forecast_artifact_id=artifact.artifact_id,
                actual_batch_id=other_batch.batch_id,
            )


# ══════════════════════════════════════════════════════════════════════
# 9. Frozen-семантика: revise НЕ переписывает старую сверку (§19)
# ══════════════════════════════════════════════════════════════════════


class TestFrozenSemantics:
    def test_revision_creates_new_comparison_old_frozen(self):
        _seed_run()
        artifact = _seed_forecast()
        v1 = _seed_batch(periods=[("2026-09-01", 4.8), ("2026-10-01", 6.1)])
        first, _ = _service().build_comparison(
            RUN_ID, _owner_subject(),
            forecast_artifact_id=artifact.artifact_id,
            actual_batch_id=v1.batch_id,
        )
        old_payload = first.payload_sha256
        old_pairs = json.dumps(first.result["pairs"], sort_keys=True)
        # Пересмотр факта: новый vintage с исправленными значениями.
        v2 = _seed_batch(periods=[("2026-09-01", 5.2), ("2026-10-01", 6.0)])
        second, _ = _service().build_comparison(
            RUN_ID, _owner_subject(),
            forecast_artifact_id=artifact.artifact_id,
            actual_batch_id=v2.batch_id,
        )
        assert first.comparison_id != second.comparison_id
        assert first.payload_sha256 == old_payload
        assert json.dumps(first.result["pairs"], sort_keys=True) == old_pairs
        assert second.result["pairs"][0]["actual_value"] == pytest.approx(5.2)
        assert len(_service().list_comparisons(RUN_ID, _owner_subject())) == 2

    def test_forecast_artifact_untouched_by_comparison(self):
        """Прежний forecast vintage не меняется: байты артефакта после
        сверки совпадают с исходными (§6 D08: никогда не заменять)."""
        _seed_run()
        artifact = _seed_forecast()
        before_sha = artifact.payload_sha256
        before_size = artifact.size_bytes
        batch = _seed_batch()
        _service().build_comparison(
            RUN_ID, _owner_subject(),
            forecast_artifact_id=artifact.artifact_id,
            actual_batch_id=batch.batch_id,
        )
        from apps.api.artifact_store import get_artifact_registry

        after = get_artifact_registry().get_artifact(artifact.artifact_id)
        assert after.payload_sha256 == before_sha
        assert after.size_bytes == before_size

    def test_no_scientific_state_mutation(self):
        """Сверка -- read-only над научным слоем: реестр артефактов и
        ledger run не растут от построения сверок (AC05-дух, §17)."""
        _seed_run()
        artifact = _seed_forecast()
        batch = _seed_batch()
        from apps.api.artifact_store import get_artifact_registry
        from apps.api import research_runs as rr

        artifacts_before = len(
            get_artifact_registry().list_artifacts(run_id=RUN_ID)
        )
        events_before = len(rr.get_research_run_store().list_events(RUN_ID))
        _service().build_comparison(
            RUN_ID, _owner_subject(),
            forecast_artifact_id=artifact.artifact_id,
            actual_batch_id=batch.batch_id,
        )
        _service().record_decision(
            RUN_ID, _owner_subject(),
            _service().list_comparisons(RUN_ID, _owner_subject())[0].comparison_id,
            action="accept", rationale="в пределах порога",
        )
        assert len(
            get_artifact_registry().list_artifacts(run_id=RUN_ID)
        ) == artifacts_before
        assert len(rr.get_research_run_store().list_events(RUN_ID)) == events_before


# ══════════════════════════════════════════════════════════════════════
# 10. Threshold facts и решение человека (§6.1: без автопереобучения)
# ══════════════════════════════════════════════════════════════════════


class TestThresholdDecision:
    def _comparison(self, *, threshold=None, periods=None, forecast_id="fc-d8-1"):
        _seed_run()
        artifact = _seed_forecast(forecast_id=forecast_id)
        batch = _seed_batch(periods=periods or [
            ("2026-09-01", 4.8), ("2026-10-01", 6.1),
        ])
        record, _created = _service().build_comparison(
            RUN_ID, _owner_subject(),
            forecast_artifact_id=artifact.artifact_id,
            actual_batch_id=batch.batch_id,
            threshold=threshold,
        )
        return record

    def test_threshold_exceeded_recorded_no_autoretrain(self):
        record = self._comparison(
            threshold={"metric": "mae", "operator": ">", "value": 0.05},
        )
        threshold = record.result["threshold"]
        assert threshold["status"] == "exceeded"
        # §6.1: автопереобучение НЕ следует из превышения порога.
        assert record.result["decision_action"] is None

    def test_threshold_within(self):
        record = self._comparison(
            threshold={"metric": "mae", "operator": ">", "value": 100.0},
        )
        assert record.result["threshold"]["status"] == "within"

    def test_threshold_not_evaluable_honest(self):
        """MAPE не определён (факт-ноль) -- порог по mape честно
        not_evaluable, а не «в норме»."""
        record = self._comparison(
            threshold={"metric": "mape", "operator": ">", "value": 0.1},
            periods=[("2026-09-01", 0.0), ("2026-10-01", 6.1)],
        )
        threshold = record.result["threshold"]
        assert threshold["status"] == "not_evaluable"
        assert threshold["reason"] == "mape_undefined_actual_zero"

    def test_invalid_threshold_rejected(self):
        from apps.api.monitoring import MonitoringValidationError

        with pytest.raises(MonitoringValidationError):
            self._comparison(
                forecast_id="fc-d8-th1",
                threshold={"metric": "rmse", "operator": ">", "value": 1.0},
            )
        with pytest.raises(MonitoringValidationError):
            self._comparison(
                forecast_id="fc-d8-th2",
                threshold={"metric": "mae", "operator": "==", "value": 1.0},
            )

    def test_decision_append_only(self):
        record = self._comparison()
        service = _service()
        decision = service.record_decision(
            RUN_ID, _owner_subject(), record.comparison_id,
            action="retrain_requested", rationale="MAE выше регламентного",
        )
        assert decision.action == "retrain_requested"
        assert decision.rationale == "MAE выше регламентного"
        listed = service.list_decisions(RUN_ID, _owner_subject(), record.comparison_id)
        assert [d.decision_id for d in listed] == [decision.decision_id]
        # Повторное решение -- append-only, старое не переписывается.
        second = service.record_decision(
            RUN_ID, _owner_subject(), record.comparison_id,
            action="investigate", rationale="уточнить единицы факта",
        )
        listed = service.list_decisions(RUN_ID, _owner_subject(), record.comparison_id)
        assert len(listed) == 2
        assert listed[-1].decision_id == second.decision_id

    def test_decision_requires_rationale_and_known_action(self):
        record = self._comparison()
        service = _service()
        from apps.api.monitoring import MonitoringValidationError

        with pytest.raises(MonitoringValidationError, match="rationale"):
            service.record_decision(
                RUN_ID, _owner_subject(), record.comparison_id,
                action="accept", rationale="  ",
            )
        with pytest.raises(MonitoringValidationError, match="action"):
            service.record_decision(
                RUN_ID, _owner_subject(), record.comparison_id,
                action="auto_retrain_now", rationale="x",
            )

    def test_decision_on_foreign_comparison_denied(self):
        _seed_run()
        foreign_run = "RUN-D8FOREIGN3"
        _seed_run(foreign_run, "d8-foreign-session")
        foreign_artifact = _seed_forecast(run_id=foreign_run)
        foreign_batch = _seed_batch(
            run_id=foreign_run, subject=_foreign_subject()
        )
        foreign_comparison, _ = _service().build_comparison(
            foreign_run, _foreign_subject(),
            forecast_artifact_id=foreign_artifact.artifact_id,
            actual_batch_id=foreign_batch.batch_id,
        )
        from apps.api.monitoring import MonitoringNotFoundError

        with pytest.raises(MonitoringNotFoundError):
            _service().record_decision(
                RUN_ID, _owner_subject(), foreign_comparison.comparison_id,
                action="accept", rationale="чужое",
            )


# ══════════════════════════════════════════════════════════════════════
# 11. D12: каталог видов и адаптер секции снимка (§6 D12, §10)
# ══════════════════════════════════════════════════════════════════════


class TestD12KindAndAdapter:
    def test_d12_in_catalog(self):
        from apps.api.report_snapshot import DOCUMENT_KINDS, resolve_kinds

        assert DOCUMENT_KINDS["D12"] == (
            "forecast_vs_actual", "Сверка прогноза с фактом", None
        )
        assert resolve_kinds(["D12"]) == ["D12"]
        assert resolve_kinds(["forecast_vs_actual"]) == ["D12"]
        assert len(DOCUMENT_KINDS) == 12

    def test_unknown_kind_still_rejected(self):
        from apps.api.report_snapshot import resolve_kinds

        with pytest.raises(ValueError, match="Неизвестный вид"):
            resolve_kinds(["D99"])

    def _snapshot_d12(self):
        _seed_run()
        from apps.api.snapshot_builder import SnapshotService

        artifact = _seed_forecast()
        batch = _seed_batch(periods=[("2026-09-01", 4.8), ("2026-10-01", 6.1)])
        _service().build_comparison(
            RUN_ID, _owner_subject(),
            forecast_artifact_id=artifact.artifact_id,
            actual_batch_id=batch.batch_id,
        )
        snapshot, _created = SnapshotService.create_default().build_snapshot(
            RUN_ID, _owner_subject(), session_id=SESSION_ID, kinds=["D12"],
        )
        return snapshot, artifact

    def test_d12_section_reads_comparison_without_recompute(self):
        """Адаптер D12 ЧИТАЕТ frozen сравнения (без пересчёта §19.1):
        claim со ссылками на артефакт прогноза и id сверки."""
        snapshot, artifact = self._snapshot_d12()
        section = next(
            s for s in snapshot.sections if s.get("code") == "D12"
        )
        assert section["claims"], "D12 секция без claims"
        claim = section["claims"][0]
        assert f"artifact:{artifact.artifact_id}" in claim["result_refs"]
        assert "зрел" in claim["text"]  # matured/excluded отражены

    def test_d12_section_empty_honest(self):
        _seed_run()
        from apps.api.snapshot_builder import SnapshotService

        snapshot, _created = SnapshotService.create_default().build_snapshot(
            RUN_ID, _owner_subject(), session_id=SESSION_ID, kinds=["D12"],
        )
        section = next(
            s for s in snapshot.sections if s.get("code") == "D12"
        )
        assert section["claims"]
        assert "не зарегистрирован" in section["claims"][0]["text"]
        assert section["claims"][0]["validity"] == "unknown"


# ══════════════════════════════════════════════════════════════════════
# 12. API /v1/documentation/runs/{run_id}/monitoring/* (§17-семантика)
# ══════════════════════════════════════════════════════════════════════


def _cookie(client: TestClient, session_id: str = SESSION_ID) -> None:
    from apps.api.session_store import SESSION_COOKIE_NAME

    client.cookies.set(SESSION_COOKIE_NAME, session_id)


class TestMonitoringApi:
    def _register(self, client, run_id=RUN_ID, **overrides):
        _cookie(client)
        body = {
            "target_name": "gdp_growth",
            "entity_id": None,
            "units": "percent",
            "as_of": "2026-12-01T00:00:00+00:00",
            "values": [
                {"period": "2026-09-01", "value": 4.8},
                {"period": "2026-10-01", "value": 6.1},
            ],
        }
        body.update(overrides)
        return client.post(
            f"/v1/documentation/runs/{run_id}/monitoring/actuals", json=body
        )

    def test_register_and_list_actuals(self, client):
        _seed_run()
        resp = self._register(client)
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["created"] is True
        assert body["batch"]["point_count"] == 2
        assert body["batch"]["schema_version"] == "doclog.actual_vintage/1"
        listed = client.get(
            f"/v1/documentation/runs/{RUN_ID}/monitoring/actuals"
        )
        assert listed.status_code == 200
        assert listed.json()["total"] == 1

    def test_register_validation_422(self, client):
        _seed_run()
        resp = self._register(client, values=[])
        assert resp.status_code == 422
        assert resp.json()["code"] == "monitoring_validation_error"

    def test_register_foreign_run_uniform_404(self, client):
        _seed_run()
        foreign = "RUN-D8FOREIGN4"
        _seed_run(foreign, "d8-foreign-session")
        resp = self._register(client, run_id=foreign)
        assert resp.status_code == 404

    def test_comparison_roundtrip_and_units_mismatch_422(self, client):
        _seed_run()
        artifact = _seed_forecast()
        resp = self._register(client)
        batch_id = resp.json()["batch"]["batch_id"]
        ok = client.post(
            f"/v1/documentation/runs/{RUN_ID}/monitoring/comparisons",
            json={
                "forecast_artifact_id": artifact.artifact_id,
                "actual_batch_id": batch_id,
                "forecast_units": "percent",
            },
        )
        assert ok.status_code == 201, ok.text
        comparison = ok.json()["comparison"]
        assert comparison["status"] == "ready"
        assert comparison["matured_count"] == 2
        detail = client.get(
            f"/v1/documentation/runs/{RUN_ID}/monitoring/comparisons/"
            f"{comparison['comparison_id']}"
        )
        assert detail.status_code == 200
        assert detail.json()["payload_sha256"] == comparison["payload_sha256"]
        # Несовпадение единиц -- 422 с честной причиной (AC15).
        mismatch = client.post(
            f"/v1/documentation/runs/{RUN_ID}/monitoring/comparisons",
            json={
                "forecast_artifact_id": artifact.artifact_id,
                "actual_batch_id": batch_id,
                "forecast_units": "tonnes",
            },
        )
        assert mismatch.status_code == 422
        assert mismatch.json()["code"] == "monitoring_units_mismatch"

    def test_comparison_missing_forecast_404_code(self, client):
        _seed_run()
        resp = self._register(client)
        batch_id = resp.json()["batch"]["batch_id"]
        missing = client.post(
            f"/v1/documentation/runs/{RUN_ID}/monitoring/comparisons",
            json={
                "forecast_artifact_id": "art-d8-nonexistent",
                "actual_batch_id": batch_id,
            },
        )
        assert missing.status_code == 404
        assert missing.json()["code"] == "monitoring_forecast_unavailable"

    def test_comparison_idempotency_conflict_409(self, client):
        _seed_run()
        artifact = _seed_forecast()
        resp = self._register(client)
        batch_id = resp.json()["batch"]["batch_id"]
        route = f"/v1/documentation/runs/{RUN_ID}/monitoring/comparisons"
        first = client.post(route, json={
            "forecast_artifact_id": artifact.artifact_id,
            "actual_batch_id": batch_id,
            "idempotency_key": "cmp-api-1",
        })
        assert first.status_code == 201
        second = client.post(route, json={
            "forecast_artifact_id": artifact.artifact_id,
            "actual_batch_id": batch_id,
            "idempotency_key": "cmp-api-1",
        })
        assert second.status_code == 201
        assert second.json()["created"] is False
        conflict = client.post(route, json={
            "forecast_artifact_id": artifact.artifact_id,
            "actual_batch_id": batch_id,
            "idempotency_key": "cmp-api-1",
            "forecast_units": "percent",
        })
        assert conflict.status_code == 409

    def test_decision_api_roundtrip(self, client):
        _seed_run()
        artifact = _seed_forecast()
        resp = self._register(client)
        batch_id = resp.json()["batch"]["batch_id"]
        comparison = client.post(
            f"/v1/documentation/runs/{RUN_ID}/monitoring/comparisons",
            json={
                "forecast_artifact_id": artifact.artifact_id,
                "actual_batch_id": batch_id,
            },
        ).json()["comparison"]
        route = (
            f"/v1/documentation/runs/{RUN_ID}/monitoring/comparisons/"
            f"{comparison['comparison_id']}/decisions"
        )
        decision = client.post(route, json={
            "action": "investigate", "rationale": "проверить единицы",
        })
        assert decision.status_code == 201, decision.text
        assert decision.json()["decision"]["action"] == "investigate"
        listed = client.get(route)
        assert listed.status_code == 200
        assert listed.json()["total"] == 1
        bad = client.post(route, json={"action": "accept", "rationale": ""})
        assert bad.status_code == 422

    def test_unauthenticated_uniform_404(self, client):
        """Решающая таблица DOCLOG-0: anonymous -- deny -> uniform 404
        (существование run не дисклоужается, паритет documentation)."""
        _seed_run()
        resp = client.get(
            f"/v1/documentation/runs/{RUN_ID}/monitoring/actuals"
        )
        assert resp.status_code == 404


# ══════════════════════════════════════════════════════════════════════
# 13. Статические каталоги: миграции, аудит, маршруты
# ══════════════════════════════════════════════════════════════════════


class TestStaticCatalogs:
    def test_migration_catalog_counts(self):
        from apps.api.research_runs import MIGRATION_FILES, MIGRATION_STATEMENTS

        assert len(MIGRATION_FILES) == 15
        # DOCLOG-9 (честное обновление пина): последний файл каталога --
        # 0015; миграция DOCLOG-8 пинуется по имени (предпоследняя).
        assert "0014_doclog8_monitoring.sql" in [n for n, _ in MIGRATION_FILES]
        # 85 (0014) + 8 statement 0015 (2 ALTER + 3 таблицы + 3 индекса).
        assert len(MIGRATION_STATEMENTS) == 93

    def test_migration_file_parity(self):
        from apps.api.research_runs import MIGRATION_FILES

        name, statements = MIGRATION_FILES[-1]
        sql = (Path("apps/api/migrations") / name).read_text("utf-8")
        for statement in statements:
            compact = " ".join(statement.split())
            assert compact in " ".join(sql.split()), statement[:80]

    def test_monitoring_tables_in_ddl(self):
        sql = (
            Path("apps/api/migrations/0014_doclog8_monitoring.sql")
            .read_text("utf-8")
        )
        for fragment in (
            "CREATE TABLE IF NOT EXISTS monitoring_actual_batches",
            "CREATE TABLE IF NOT EXISTS monitoring_comparisons",
            "CREATE TABLE IF NOT EXISTS monitoring_decisions",
            "actual_values JSONB",
        ):
            assert fragment in sql, fragment

    def test_audit_actions_catalog(self):
        from apps.api import security_audit

        for action in (
            "monitoring_actual_registered",
            "monitoring_comparison_created",
            "monitoring_decision_recorded",
        ):
            assert action in security_audit.AUDIT_ACTIONS, action
        # DOCLOG-9 (честное обновление пина): +4 действия профилей
        # организации (created/retired mandatory, validated/anchored
        # standard); 24 + 4 = 28.
        assert len(security_audit.AUDIT_ACTIONS) == 28

    def test_routes_registered(self):
        from apps.api.main import app

        routes = [
            r
            for r in app.routes
            if hasattr(r, "path") and "/monitoring/" in r.path
        ]
        paths = {r.path for r in routes}
        assert (
            "/v1/documentation/runs/{run_id}/monitoring/actuals" in paths
        )
        assert (
            "/v1/documentation/runs/{run_id}/monitoring/comparisons" in paths
        )
        assert (
            "/v1/documentation/runs/{run_id}/monitoring/comparisons/"
            "{comparison_id}" in paths
        )
        assert (
            "/v1/documentation/runs/{run_id}/monitoring/comparisons/"
            "{comparison_id}/decisions" in paths
        )
        # 7 маршрутов (POST+GET на трёх путях + GET детализации сверки).
        assert len(routes) == 7
