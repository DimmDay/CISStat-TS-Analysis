# scripts/doclog8cert/test_d8cert_oracle_unit.py
"""DOCLOG-8-CERT: unit-оракулы на СВОИХ данных (u01–u28).

Чистая функция compute_comparison_result -- точная математика на
ручных числах; сервис -- единицы/T8/T7/идемпотентность/vintage-заморозка/
решения. Канон: null+reason, НЕ 0 (AC12); незрелый горизонт НЕ нулевая
ошибка (§6.1); decision_action всегда null (без автопереобучения).
"""
from __future__ import annotations

import dataclasses

import pytest

from apps.api.monitoring import MonitoringAccessDenied  # noqa: F401

from .conftest import (
    FORECAST_ID_1,
    FORECAST_POINTS,
    RUN_A,
    RUN_B,
    SESSION_A,
    SESSION_B,
    build_comparison,
    make_artifact,
    register_batch,
    seed_forecast,
    seed_run,
    service,
    subject_of,
)

FC = {"horizon": 4, "alpha": 0.05, "points": FORECAST_POINTS}


# ── Чистая функция: выравнивание и зрелость (§6.1) ───────────────────


class TestComputeAlignment:
    def test_u01_alignment_exact_strip(self):
        from apps.api.monitoring import compute_comparison_result

        payload = {"points": [{"date": " 2026-09-01 ", "value": 5.0}]}
        result = compute_comparison_result(
            payload, [{"period": "2026-09-01", "value": 6.1}]
        )
        assert result["alignment"]["key"] == "period_label_exact"
        assert result["alignment"]["matured_count"] == 1
        assert result["pairs"][0]["date"] == "2026-09-01"

    def test_u02_immature_horizons_explicit_not_zero(self):
        from apps.api.monitoring import compute_comparison_result

        result = compute_comparison_result(
            FC, [{"period": "2026-09-01", "value": 4.8}]
        )
        align = result["alignment"]
        assert align["matured_count"] == 1
        assert align["excluded_count"] == 3
        assert align["excluded_labels"] == [
            "2026-10-01", "2026-11-01", "2026-12-01",
        ]
        # §6.1: незрелые НЕ пары -- в pairs только зрелые.
        assert len(result["pairs"]) == 1
        assert "2026-10-01" not in {p["date"] for p in result["pairs"]}

    def test_u03_out_of_horizon_sorted(self):
        from apps.api.monitoring import compute_comparison_result

        result = compute_comparison_result(
            FC,
            [
                {"period": "2026-09-01", "value": 4.8},
                {"period": "2025-01-01", "value": 1.0},
                {"period": "2027-06-01", "value": 2.0},
            ],
        )
        align = result["alignment"]
        assert align["out_of_horizon_count"] == 2
        assert align["out_of_horizon_labels"] == [
            "2025-01-01", "2027-06-01",
        ]
        assert align["matured_count"] == 1


class TestComputeMetrics:
    def test_u04_known_numbers(self):
        from apps.api.monitoring import compute_comparison_result

        result = compute_comparison_result(
            {"points": [{"date": "2026-09-01", "value": 5.0}]},
            [{"period": "2026-09-01", "value": 6.1}],
        )
        pair = result["pairs"][0]
        assert pair["forecast_value"] == 5.0
        assert pair["actual_value"] == 6.1
        assert pair["signed_error"] == pytest.approx(1.1)
        assert pair["absolute_error"] == pytest.approx(1.1)
        assert pair["ape"] == pytest.approx(1.1 / 6.1)
        agg = result["aggregates"]
        assert agg["mae"] == pytest.approx(1.1)
        assert agg["mean_signed_error"] == pytest.approx(1.1)
        assert agg["mape"] == pytest.approx(1.1 / 6.1)

    def test_u05_actual_zero_honest(self):
        from apps.api.monitoring import compute_comparison_result

        result = compute_comparison_result(
            {"points": [{"date": "2026-09-01", "value": 5.0}]},
            [{"period": "2026-09-01", "value": 0.0}],
        )
        pair = result["pairs"][0]
        assert pair["ape"] is None
        assert pair["ape_undefined_reason"] == "actual_zero"
        agg = result["aggregates"]
        assert agg["mape"] is None
        assert agg["mape_reason"] == "mape_undefined_actual_zero"
        assert agg["mape_zero_periods"] == ["2026-09-01"]
        # MAE от нуля факта НЕ страдает: считается честно.
        assert agg["mae"] == pytest.approx(5.0)

    def test_u06_mase_scale_semantics(self):
        from apps.api.monitoring import compute_comparison_result

        no_scale = compute_comparison_result(FC, [{"period": "2026-09-01", "value": 4.8}])
        assert no_scale["aggregates"]["mase"] is None
        assert no_scale["aggregates"]["mase_reason"] == "mase_scale_required"

        with_scale = compute_comparison_result(
            FC, [{"period": "2026-09-01", "value": 4.8}], mase_scale=2.0
        )
        agg = with_scale["aggregates"]
        expected_mae = abs(4.8 - 5.0)
        assert agg["mase"] == pytest.approx(expected_mae / 2.0)
        assert agg["mase_reason"] is None

        for bad in (0.0, -1.0):
            invalid = compute_comparison_result(
                FC, [{"period": "2026-09-01", "value": 4.8}], mase_scale=bad
            )
            assert invalid["aggregates"]["mase"] is None
            assert invalid["aggregates"]["mase_reason"] == "mase_scale_invalid"

    def test_u07_interval_coverage_full_and_boundary(self):
        from apps.api.monitoring import compute_comparison_result

        result = compute_comparison_result(
            {"points": [
                {"date": "2026-09-01", "value": 5.0, "ci_lower": 4.0, "ci_upper": 6.1},
            ]},
            [{"period": "2026-09-01", "value": 6.1}],
        )
        # Включительная граница: actual == ci_upper -> hit.
        assert result["pairs"][0]["interval_hit"] is True
        assert result["aggregates"]["interval_hits"] == 1
        assert result["aggregates"]["interval_coverage"] == 1.0

    def test_u08_interval_bounds_missing_honest(self):
        from apps.api.monitoring import compute_comparison_result

        result = compute_comparison_result(
            {"points": [
                {"date": "2026-09-01", "value": 5.0, "ci_lower": 4.0, "ci_upper": 6.0},
                {"date": "2026-10-01", "value": 6.0},
            ]},
            [
                {"period": "2026-09-01", "value": 5.5},
                {"period": "2026-10-01", "value": 6.5},
            ],
        )
        agg = result["aggregates"]
        assert agg["interval_hits"] == 1
        assert agg["interval_coverage"] is None
        assert agg["interval_coverage_reason"] == "interval_bounds_missing"

    def test_u09_no_matured_null_not_zero(self):
        from apps.api.monitoring import compute_comparison_result

        result = compute_comparison_result(
            FC, [{"period": "2025-01-01", "value": 1.0}]
        )
        agg = result["aggregates"]
        for key in ("mae", "mean_signed_error", "mape", "mase",
                    "interval_coverage"):
            assert agg[key] is None, key
            assert agg[key + "_reason"] == "no_matured_horizons", key
        assert agg["mae_reason"] == "no_matured_horizons"
        assert agg["mape_zero_periods"] == []
        assert agg["interval_hits"] == 0


class TestComputeThreshold:
    def test_u10_boundary_operators(self):
        from apps.api.monitoring import compute_comparison_result

        # Чистые числа: forecast 5.0, actual 4.0 -> mae ровно 1.0.
        data = [{"period": "2026-09-01", "value": 4.0}]
        fc = {"points": [{"date": "2026-09-01", "value": 5.0}]}
        th = {"metric": "mae", "value": 1.0}
        gt = compute_comparison_result(
            fc, data, threshold={**th, "operator": ">"}
        )
        assert gt["threshold"]["status"] == "within"  # 1.0 > 1.0 -- нет
        gte = compute_comparison_result(
            fc, data, threshold={**th, "operator": ">="}
        )
        assert gte["threshold"]["status"] == "exceeded"  # 1.0 >= 1.0

    def test_u11_not_evaluable_with_reason(self):
        from apps.api.monitoring import compute_comparison_result

        result = compute_comparison_result(
            FC, [{"period": "2026-09-01", "value": 4.8}],
            threshold={"metric": "mase", "operator": ">", "value": 1.0},
        )
        th = result["threshold"]
        assert th["status"] == "not_evaluable"
        assert th["reason"] == "mase_scale_required"

    def test_u12_bias_abs_negative(self):
        from apps.api.monitoring import compute_comparison_result

        result = compute_comparison_result(
            {"points": [{"date": "2026-09-01", "value": 6.0}]},
            [{"period": "2026-09-01", "value": 4.0}],
            threshold={"metric": "bias_abs", "operator": ">", "value": 1.0},
        )
        assert result["aggregates"]["mean_signed_error"] == pytest.approx(-2.0)
        assert result["threshold"]["status"] == "exceeded"

    def test_u13_decision_action_always_null(self):
        from apps.api.monitoring import compute_comparison_result

        result = compute_comparison_result(
            FC, [{"period": "2026-09-01", "value": 4.8}],
            threshold={"metric": "mae", "operator": ">", "value": 0.0},
        )
        assert result["threshold"]["status"] == "exceeded"
        # §6.1: автопереобучение не следует из порога.
        assert result["decision_action"] is None

    def test_u14_schema_origin_label(self):
        from apps.api.monitoring import compute_comparison_result

        result = compute_comparison_result(
            FC, [{"period": "2026-09-01", "value": 4.8}],
            threshold={"metric": "mae", "operator": ">", "value": 0.1,
                       "label": "d8cert-budget"},
        )
        assert result["schema_version"] == "doclog.monitoring_result/1"
        assert result["forecast_origin"]["horizon"] == 4
        assert result["forecast_origin"]["alpha"] == 0.05
        assert result["forecast_origin"]["point_count"] == 4
        assert result["threshold"]["label"] == "d8cert-budget"


# ── Сервис: единицы (AC15) ────────────────────────────────────────────


class TestServiceUnits:
    def setup_method(self):
        seed_run()
        self.artifact = seed_forecast()

    def test_u15_unknown_honest(self):
        record = build_comparison(artifact=self.artifact,
                                  batch=register_batch())
        assert record.units_check == "unknown"
        assert "unknown" in record.units_note

    def test_u16_as_is_equal(self):
        record = build_comparison(
            artifact=self.artifact, batch=register_batch(),
            forecast_units="percent",
        )
        assert record.units_check == "as_is"

    def test_u17_mismatch_refused_no_comparison_saved(self):
        from apps.api.monitoring import MonitoringUnitsMismatchError
        from apps.api.monitoring import get_monitoring_registry

        with pytest.raises(MonitoringUnitsMismatchError):
            build_comparison(
                artifact=self.artifact, batch=register_batch(),
                forecast_units="tonnes",
            )
        assert get_monitoring_registry()._comparisons == {}

    def test_u18_conversion_scales(self):
        record = build_comparison(
            artifact=self.artifact, batch=register_batch(),
            forecast_units="tonnes",
            units_conversion={"factor": 1000.0, "note": "кг->тонны d8c"},
        )
        assert record.units_check == "converted"
        assert record.units_note == "кг->тонны d8c"
        pair = record.result["pairs"][0]
        assert pair["actual_value"] == pytest.approx(4.8 * 1000.0)

    def test_u19_conversion_invalid_factor(self):
        from apps.api.monitoring import MonitoringValidationError

        for bad in (0.0, float("nan"), "abc", None, True):
            with pytest.raises(MonitoringValidationError):
                build_comparison(
                    artifact=self.artifact, batch=register_batch(),
                    forecast_units="tonnes",
                    units_conversion={"factor": bad},
                )
        # Отрицательный фактор контрактом разрешён (ненулевой factor) --
        # пин честной границы, а не требования.

    def test_u20_conversion_note_optional_pin(self):
        """ПИН находки-кандидата: контракт-док требует {factor, note},
        код принимает конверсию без note (units_note останется '')."""
        record = build_comparison(
            artifact=self.artifact, batch=register_batch(),
            forecast_units="tonnes",
            units_conversion={"factor": 10.0},
        )
        assert record.units_check == "converted"
        assert record.units_note == ""



# ── Сервис: целостность прогноза (T8) и границы (T7/T15) ─────────────


class TestForecastIntegrity:
    def setup_method(self):
        seed_run()

    def test_u21_corrupted_bytes_refused(self, monkeypatch):
        from apps.api.artifact_store import get_artifact_object_store
        from apps.api.monitoring import MonitoringForecastUnavailable
        from apps.api.monitoring import get_monitoring_registry

        artifact = seed_forecast()
        batch = register_batch()
        # ПОРЧА СОХРАНЯЕТ ВАЛИДНОСТЬ JSON и патчится ИНСТАНС (repo-паттерн):
        # parse проходит, отказ -- РОВНО по ветке T8 «Целостность»
        # (иначе мутант отключения sha-проверки не киллится).
        import json as _json

        real_read = get_artifact_object_store().read_bytes

        def _corrupted(key):
            payload = _json.loads(real_read(key).decode("utf-8"))
            payload["points"][0]["value"] = 999.0
            return _json.dumps(
                payload, sort_keys=True, separators=(",", ":"),
                ensure_ascii=False,
            ).encode("utf-8")

        monkeypatch.setattr(
            get_artifact_object_store(), "read_bytes", _corrupted
        )
        with pytest.raises(MonitoringForecastUnavailable,
                           match="Целостность"):
            build_comparison(artifact=artifact, batch=batch)
        assert get_monitoring_registry()._comparisons == {}

    def test_u22_wrong_kind_refused(self):
        from apps.api.monitoring import MonitoringForecastUnavailable

        # kind="model_card" валиден для артефактного реестра, но не
        # прогноз: сверка обязана отказать (не интерпретировать как угодно).
        stray = make_artifact(
            "model_card", "card:fc-d8cert-x",
            {"points": [{"date": "2026-09-01", "value": 5.0}]},
        )
        with pytest.raises(MonitoringForecastUnavailable):
            build_comparison(artifact=stray, batch=register_batch())

    def test_u23_foreign_run_forecast_refused(self):
        from apps.api.monitoring import MonitoringAccessDenied
        from apps.api.monitoring import get_monitoring_registry

        seed_run(RUN_B, SESSION_B)
        foreign_artifact = seed_forecast(run_id=RUN_B,
                                         forecast_id=FORECAST_ID_1)
        with pytest.raises(MonitoringAccessDenied):
            build_comparison(
                artifact=foreign_artifact,
                batch=register_batch(),
            )
        assert get_monitoring_registry()._comparisons == {}

    def test_u42_foreign_batch_refused(self):
        from apps.api.monitoring import MonitoringNotFoundError

        seed_run(RUN_B, SESSION_B)
        foreign_batch = register_batch(
            RUN_B, subject=subject_of(SESSION_B)
        )
        artifact = seed_forecast()  # свой прогноз RUN_A
        with pytest.raises(MonitoringNotFoundError):
            build_comparison(artifact=artifact, batch=foreign_batch)

    def test_u24_missing_and_empty_points(self):
        from apps.api.monitoring import MonitoringForecastUnavailable

        empty = seed_forecast(points=[])
        with pytest.raises(MonitoringForecastUnavailable):
            build_comparison(artifact=empty, batch=register_batch())
        ghost = type("A", (), {"artifact_id": "art-d8cert-ghost"})()
        with pytest.raises(MonitoringForecastUnavailable):
            build_comparison(artifact=ghost, batch=register_batch())


# ── Сервис: идемпотентность и fingerprint (§10.3/AC09) ────────────────


class TestIdempotency:
    def setup_method(self):
        seed_run()

    def test_u25_batch_same_body_created_false(self):
        kw = dict(idempotency_key="d8c-batch-1")
        first = register_batch(**kw)
        second = register_batch(**kw)
        assert second.batch_id == first.batch_id
        assert second.point_count == 2

    def test_u26_batch_conflict_different_body(self):
        from apps.api.monitoring import MonitoringIdempotencyConflictError

        register_batch(idempotency_key="d8c-batch-2")
        with pytest.raises(MonitoringIdempotencyConflictError):
            register_batch(idempotency_key="d8c-batch-2",
                           periods=[("2026-09-01", 9.9)])

    def test_u27_empty_key_no_dedup(self):
        b1 = register_batch()
        b2 = register_batch()
        assert b1.batch_id != b2.batch_id

    def test_u28_fingerprint_key_order_stable(self):
        from apps.api.monitoring import request_fingerprint

        a = {"x": 1, "y": [1, 2], "z": {"p": 1, "q": 2}}
        b = {"z": {"q": 2, "p": 1}, "y": [1, 2], "x": 1}
        assert request_fingerprint(a) == request_fingerprint(b)

    def test_u29_comparison_idempotent_and_conflict(self):
        from apps.api.monitoring import (
            MonitoringIdempotencyConflictError,
            get_monitoring_registry,
        )

        artifact = seed_forecast()
        batch = register_batch()
        kw = dict(forecast_units="percent", idempotency_key="d8c-cmp-1")
        first = build_comparison(artifact=artifact, batch=batch, **kw)
        second = build_comparison(artifact=artifact, batch=batch, **kw)
        assert second.comparison_id == first.comparison_id
        registry = get_monitoring_registry()
        assert len(registry._comparisons) == 1
        with pytest.raises(MonitoringIdempotencyConflictError):
            build_comparison(
                artifact=artifact, batch=batch,
                forecast_units="percent",
                idempotency_key="d8c-cmp-1", mase_scale=2.0,
            )


# ── Сервис: валидация и as_of ─────────────────────────────────────────


class TestValidation:
    def setup_method(self):
        seed_run()

    def test_u30_batch_validation_catalog(self):
        from apps.api.monitoring import MonitoringValidationError

        s = service()
        subj = subject_of(SESSION_A)
        base = dict(target_name="t", units="u", as_of="2026-12-01T00:00:00+00:00",
                    values=[{"period": "p", "value": 1.0}])
        bad_bodies = [
            dict(base, target_name="  "),
            dict(base, units=""),
            dict(base, values=[]),
            dict(base, values="not-a-list"),
            dict(base, values=[{"period": "  ", "value": 1.0}]),
            dict(base, values=[{"period": "p", "value": float("nan")}]),
            dict(base, values=[{"period": "p", "value": float("inf")}]),
            dict(base, values=[{"period": "p", "value": True}]),
            dict(base, values=[{"period": "p", "value": "1.0"}]),
            dict(base, values=[{"period": "p", "value": 1.0},
                               {"period": "p", "value": 2.0}]),
            dict(base, entity_id="   "),
            dict(base, as_of="не-дата"),
            dict(base, as_of="   "),
            dict(base, source_kind="db"),
        ]
        for body in bad_bodies:
            with pytest.raises(MonitoringValidationError):
                s.register_actual_batch(RUN_A, subj, **body)

    def test_u31_as_of_roundtrip_z_and_naive(self):
        b1 = register_batch(as_of="2026-12-01T00:00:00Z")
        assert b1.as_of == "2026-12-01T00:00:00+00:00"
        b2 = register_batch(as_of="2026-12-02T10:30:00")
        assert b2.as_of == "2026-12-02T10:30:00"  # naive без фабрикации TZ

    def test_u32_threshold_service_catalog(self):
        from apps.api.monitoring import MonitoringValidationError

        artifact = seed_forecast()
        batch = register_batch()
        bad = [
            {"metric": "rmse", "operator": ">", "value": 1.0},
            {"metric": "mae", "operator": "<", "value": 1.0},
            {"metric": "mae", "operator": ">", "value": float("nan")},
            {"metric": "mae", "operator": ">", "value": "1.0"},
            "not-a-dict",
        ]
        for threshold in bad:
            with pytest.raises(MonitoringValidationError):
                build_comparison(artifact=artifact, batch=batch,
                                 threshold=threshold)


# ── Сервис: vintage-заморозка и read-only (критерий §19) ──────────────


class TestVintageFrozen:
    def test_u33_revision_new_batch_old_untouched(self):
        seed_run()
        b1 = register_batch(periods=[("2026-09-01", 4.8)])
        snapshot1 = b1.to_dict()
        b2 = register_batch(periods=[("2026-09-01", 5.5)],
                            idempotency_key="d8c-rev-1")
        assert b2.batch_id != b1.batch_id
        assert b1.to_dict() == snapshot1  # старый vintage не переписан
        assert b2.values[0]["value"] == 5.5

    def test_u34_new_comparison_old_frozen(self):
        seed_run()
        artifact = seed_forecast()
        b1 = register_batch(periods=[("2026-09-01", 4.8)])
        c1 = build_comparison(artifact=artifact, batch=b1)
        frozen_payload = c1.payload_sha256
        frozen_pairs = c1.result["pairs"]
        b2 = register_batch(periods=[("2026-09-01", 9.9)])
        c2 = build_comparison(artifact=artifact, batch=b2)
        assert c2.comparison_id != c1.comparison_id
        assert c1.payload_sha256 == frozen_payload
        assert c1.result["pairs"] == frozen_pairs
        assert c2.result["pairs"][0]["actual_value"] == 9.9

    def test_u35_readonly_scientific_layer(self):
        from apps.api.artifact_store import (
            get_artifact_object_store,
            get_artifact_registry,
        )
        from apps.api.research_runs import get_research_run_store

        seed_run()
        artifact = seed_forecast()
        batch = register_batch()
        decision_target = build_comparison(artifact=artifact, batch=batch)

        forecast_bytes_before = get_artifact_object_store().read_bytes(
            artifact.storage_key
        )
        artifacts_before = len(
            get_artifact_registry().list_artifacts(RUN_A)
        )
        run_before = dataclasses.asdict(
            get_research_run_store().get_run(RUN_A)
        )

        service().record_decision(
            RUN_A, subject_of(SESSION_A), decision_target.comparison_id,
            action="investigate", rationale="d8cert read-only probe",
        )

        assert get_artifact_object_store().read_bytes(
            artifact.storage_key
        ) == forecast_bytes_before
        assert len(get_artifact_registry().list_artifacts(RUN_A)) \
            == artifacts_before
        assert dataclasses.asdict(
            get_research_run_store().get_run(RUN_A)
        ) == run_before


# ── Сервис: решения (§6.1 append-only) ────────────────────────────────


class TestDecisions:
    def setup_method(self):
        seed_run()

    def _comparison(self):
        artifact = seed_forecast()
        return build_comparison(artifact=artifact, batch=register_batch())

    def test_u36_catalog_fail_closed_and_retrain_record(self):
        from apps.api.monitoring import MonitoringValidationError

        comparison = self._comparison()
        s = service()
        with pytest.raises(MonitoringValidationError):
            s.record_decision(RUN_A, subject_of(SESSION_A),
                              comparison.comparison_id,
                              action="retrain", rationale="x")
        decision = s.record_decision(
            RUN_A, subject_of(SESSION_A), comparison.comparison_id,
            action="retrain_requested", rationale="превышен MAE d8c",
        )
        assert decision.action == "retrain_requested"  # запрос, не действие

    def test_u37_rationale_required(self):
        from apps.api.monitoring import MonitoringValidationError

        comparison = self._comparison()
        for rationale in ("", "   ", None):
            with pytest.raises(MonitoringValidationError):
                service().record_decision(
                    RUN_A, subject_of(SESSION_A),
                    comparison.comparison_id,
                    action="accept", rationale=rationale,
                )

    def test_u38_foreign_comparison_refused(self):
        from apps.api.monitoring import MonitoringNotFoundError

        seed_run(RUN_B, SESSION_B)
        foreign_artifact = seed_forecast(run_id=RUN_B)
        foreign_batch = register_batch(
            RUN_B, subject=subject_of(SESSION_B)
        )
        foreign_comparison = build_comparison(
            RUN_B, artifact=foreign_artifact, batch=foreign_batch,
            subject=subject_of(SESSION_B),
        )
        with pytest.raises(MonitoringNotFoundError):
            service().record_decision(
                RUN_A, subject_of(SESSION_A),
                foreign_comparison.comparison_id,
                action="accept", rationale="d8c",
            )

    def test_u39_append_only_order_and_attribution(self):
        comparison = self._comparison()
        s = service()
        d1 = s.record_decision(RUN_A, subject_of(SESSION_A),
                               comparison.comparison_id,
                               action="accept", rationale="первое d8c")
        d2 = s.record_decision(RUN_A, subject_of(SESSION_A),
                               comparison.comparison_id,
                               action="investigate", rationale="второе d8c")
        listed = s.list_decisions(RUN_A, subject_of(SESSION_A),
                                  comparison.comparison_id)
        assert [d.decision_id for d in listed] == [
            d1.decision_id, d2.decision_id,
        ]
        assert d1.decided_by == subject_of(SESSION_A).subject_id
        assert d1.comparison_id == comparison.comparison_id


# ── Реестр Memory: паритет базовых операций ───────────────────────────


class TestMemoryRegistry:
    def test_u40_unknown_and_empty_key(self):
        from apps.api.monitoring import get_monitoring_registry

        registry = get_monitoring_registry()
        assert registry.get_actual_batch("act-d8cert-ghost") is None
        assert registry.get_comparison("mon-d8cert-ghost") is None
        seed_run()
        register_batch()
        assert registry.find_actual_batch_idempotent(RUN_A, "") is None

    def test_u41_list_limit_and_order(self):
        seed_run()
        for i in range(3):
            register_batch(idempotency_key=f"d8c-list-{i}")
        listed = service().list_actual_batches(RUN_A, subject_of(SESSION_A))
        assert len(listed) == 3
        assert listed == sorted(listed, key=lambda b: b.created_at)
        limited = service().list_actual_batches(
            RUN_A, subject_of(SESSION_A), limit=2
        )
        assert len(limited) == 2
