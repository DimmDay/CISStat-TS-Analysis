# scripts/doclog8cert/test_d8cert_oracle_api.py
"""DOCLOG-8-CERT: API-оракулы /v1/documentation/runs/{run_id}/monitoring/*
на СВОИХ данных (a01–a20).

§17-семантика: 201 создание; uniform 404 (аноним/чужой -- существование
run не дисклоужается); 409 идемпотентность; 422 каталог с отдельным кодом
units mismatch (AC15); плоское тело ошибок {code, message, request_id};
аудит monitoring_* -- standard-класс (сбой не ломает научную операцию,
§8); GET не пишет audit и не меняет состояние.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from .conftest import (
    D8C_SENTINEL,
    RUN_A,
    RUN_B,
    SESSION_A,
    SESSION_B,
    build_comparison,
    cookie,
    register_batch,
    seed_forecast,
    seed_run,
    subject_of,
)

BASE = "/v1/documentation/runs"
MON = f"{BASE}/{{run_id}}/monitoring"


def _register_body(**overrides):
    body = {
        "target_name": "d8cert_gdp_growth",
        "units": "percent",
        "as_of": "2026-12-01T00:00:00+00:00",
        "values": [
            {"period": "2026-09-01", "value": 4.8},
            {"period": "2026-10-01", "value": 6.1},
        ],
    }
    body.update(overrides)
    return body


def _do_register(client: TestClient, run_id=RUN_A, *, session=SESSION_A,
                 **overrides):
    cookie(client, session)
    return client.post(
        f"{BASE}/{run_id}/monitoring/actuals",
        json=_register_body(**overrides),
    )


def _make_comparison(client: TestClient, run_id=RUN_A, *,
                     session=SESSION_A, **overrides):
    artifact = seed_forecast(run_id)
    resp = _do_register(client, run_id, session=session)
    batch_id = resp.json()["batch"]["batch_id"]
    body = {
        "forecast_artifact_id": artifact.artifact_id,
        "actual_batch_id": batch_id,
    }
    body.update(overrides)
    cookie(client, session)
    return client.post(
        f"{BASE}/{run_id}/monitoring/comparisons", json=body
    )


ALL_ROUTES = [
    ("POST", "actuals"),
    ("GET", "actuals"),
    ("POST", "comparisons"),
    ("GET", "comparisons"),
]


class TestAccessUniform404:
    def test_a01_anonymous_all_routes(self, client: TestClient):
        seed_run()
        routes = [
            ("POST", "/actuals", _register_body()),
            ("GET", "/actuals", None),
            ("POST", "/comparisons", {"forecast_artifact_id": "x",
                                      "actual_batch_id": "y"}),
            ("GET", "/comparisons", None),
            ("GET", "/comparisons/mon-d8cert-ghost", None),
            ("POST", "/comparisons/mon-d8cert-ghost/decisions",
             {"action": "accept", "rationale": "r"}),
            ("GET", "/comparisons/mon-d8cert-ghost/decisions", None),
        ]
        for method, tail, body in routes:
            url = f"{BASE}/{RUN_A}/monitoring{tail}"
            resp = (client.post(url, json=body) if method == "POST"
                    else client.get(url))
            assert resp.status_code == 404, (method, tail, resp.status_code)

    def test_a02_foreign_session_all_routes_404(self, client: TestClient):
        seed_run(RUN_A, SESSION_A)
        seed_run(RUN_B, SESSION_B)
        cookie(client, SESSION_B)
        for tail in ("/actuals", "/comparisons"):
            resp = client.get(f"{BASE}/{RUN_A}/monitoring{tail}")
            assert resp.status_code == 404, tail
        post = client.post(
            f"{BASE}/{RUN_A}/monitoring/actuals",
            json=_register_body(),
        )
        assert post.status_code == 404


class TestRegistrationContract:
    def test_a03_register_201_shape(self, client: TestClient):
        seed_run()
        resp = _do_register(
            client, as_of="2026-12-01T12:00:00Z",
            notes="d8cert note", source_ref="d8cert-ref-1",
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["created"] is True
        batch = body["batch"]
        assert batch["schema_version"] == "doclog.actual_vintage/1"
        assert batch["batch_id"].startswith("act-")
        assert batch["point_count"] == 2
        assert batch["as_of"] == "2026-12-01T12:00:00+00:00"  # Z-раундтрип
        assert batch["notes"] == "d8cert note"
        assert batch["source_ref"] == "d8cert-ref-1"
        assert batch["created_by"] == subject_of(SESSION_A).subject_id
        assert batch["target_name"] == "d8cert_gdp_growth"
        assert batch["units"] == "percent"
        listed = client.get(f"{BASE}/{RUN_A}/monitoring/actuals")
        assert listed.status_code == 200
        assert listed.json()["total"] == 1
        assert listed.json()["items"][0]["batch_id"] == batch["batch_id"]

    def test_a04_validation_422_flat_body(self, client: TestClient):
        seed_run()
        for overrides in (
            {"values": []},
            {"values": [{"period": "p", "value": 1.0},
                        {"period": "p", "value": 2.0}]},
            {"values": [{"period": "p", "value": "oops"}]},
            {"units": ""},
            {"as_of": "мусор"},
        ):
            resp = _do_register(client, **overrides)
            assert resp.status_code == 422, overrides
            payload = resp.json()
            assert payload["code"] == "monitoring_validation_error"
            assert "detail" not in payload          # плоское тело
            assert payload["request_id"]
            assert D8C_SENTINEL not in resp.text

    def test_a05_units_mismatch_distinct_code(self, client: TestClient):
        seed_run()
        artifact = seed_forecast()
        batch_id = _do_register(client).json()["batch"]["batch_id"]
        resp = client.post(
            f"{BASE}/{RUN_A}/monitoring/comparisons",
            json={
                "forecast_artifact_id": artifact.artifact_id,
                "actual_batch_id": batch_id,
                "forecast_units": "tonnes",
            },
        )
        assert resp.status_code == 422
        assert resp.json()["code"] == "monitoring_units_mismatch"
        assert resp.json()["request_id"]

    def test_a06_idempotency_repeat_and_conflict(self, client: TestClient):
        seed_run()
        kw = {"idempotency_key": "d8c-api-batch-1"}
        first = _do_register(client, **kw)
        assert first.status_code == 201
        second = _do_register(client, **kw)
        assert second.status_code == 201
        assert second.json()["created"] is False
        assert second.json()["batch"]["batch_id"] \
            == first.json()["batch"]["batch_id"]
        conflict = _do_register(client, **kw,
                                values=[{"period": "p", "value": 1.0}])
        assert conflict.status_code == 409
        assert conflict.json()["code"] == "monitoring_idempotency_conflict"


class TestComparisonContract:
    def test_a07_missing_forecast_code(self, client: TestClient):
        seed_run()
        batch_id = _do_register(client).json()["batch"]["batch_id"]
        resp = client.post(
            f"{BASE}/{RUN_A}/monitoring/comparisons",
            json={"forecast_artifact_id": "art-d8cert-ghost",
                  "actual_batch_id": batch_id},
        )
        assert resp.status_code == 404
        assert resp.json()["code"] == "monitoring_forecast_unavailable"

    def test_a08_foreign_forecast_uniform_404_code(self, client: TestClient):
        seed_run(RUN_A, SESSION_A)
        seed_run(RUN_B, SESSION_B)
        foreign_artifact = seed_forecast(RUN_B)
        batch_id = _do_register(client).json()["batch"]["batch_id"]
        resp = client.post(
            f"{BASE}/{RUN_A}/monitoring/comparisons",
            json={"forecast_artifact_id": foreign_artifact.artifact_id,
                  "actual_batch_id": batch_id},
        )
        # T7/T15: знание идентификатора чужого артефакта НЕ право;
        # AccessDenied -> uniform 404 run_not_found_or_forbidden.
        assert resp.status_code == 404
        assert resp.json()["code"] == "run_not_found_or_forbidden"

    def test_a09_comparison_201_shape_and_idempotency(self, client):
        seed_run()
        artifact = seed_forecast()
        batch_id = _do_register(client).json()["batch"]["batch_id"]
        body = {
            "forecast_artifact_id": artifact.artifact_id,
            "actual_batch_id": batch_id,
            "forecast_units": "percent",
            "threshold": {"metric": "mae", "operator": ">", "value": 0.1},
            "idempotency_key": "d8c-api-cmp-1",
        }
        url = f"{BASE}/{RUN_A}/monitoring/comparisons"
        first = client.post(url, json=body)
        assert first.status_code == 201, first.text
        comparison = first.json()["comparison"]
        assert comparison["schema_version"] == "doclog.monitoring_comparison/1"
        assert comparison["comparison_id"].startswith("mon-")
        assert comparison["status"] == "ready"
        assert comparison["matured_count"] == 2
        assert comparison["units_check"] == "as_is"
        assert comparison["forecast_sha256"] == artifact.payload_sha256
        assert comparison["payload_sha256"]
        assert comparison["result"]["threshold"]["status"] == "exceeded"
        assert comparison["result"]["decision_action"] is None
        second = client.post(url, json=body)
        assert second.status_code == 201
        assert second.json()["created"] is False
        assert second.json()["comparison"]["comparison_id"] \
            == comparison["comparison_id"]
        detail = client.get(f"{url}/{comparison['comparison_id']}")
        assert detail.status_code == 200
        assert detail.json()["payload_sha256"] == comparison["payload_sha256"]


class TestDecisionContract:
    def test_a10_decision_flow_and_append_only(self, client: TestClient):
        seed_run()
        made = _make_comparison(client)
        comparison_id = made.json()["comparison"]["comparison_id"]
        url = f"{BASE}/{RUN_A}/monitoring/comparisons/{comparison_id}/decisions"
        first = client.post(url, json={
            "action": "investigate", "rationale": "d8cert причина 1",
        })
        assert first.status_code == 201, first.text
        decision = first.json()["decision"]
        assert decision["decision_id"].startswith("dec-")
        assert decision["schema_version"] == "doclog.monitoring_decision/1"
        assert decision["action"] == "investigate"
        assert decision["decided_by"] == subject_of(SESSION_A).subject_id
        assert decision["comparison_id"] == comparison_id
        second = client.post(url, json={
            "action": "retrain_requested", "rationale": "d8cert запрос",
        })
        assert second.status_code == 201
        listed = client.get(url)
        assert listed.status_code == 200
        assert listed.json()["total"] == 2
        ids = [item["decision_id"] for item in listed.json()["items"]]
        assert ids == [decision["decision_id"],
                       second.json()["decision"]["decision_id"]]

    def test_a11_decision_422_catalog(self, client: TestClient):
        seed_run()
        comparison_id = _make_comparison(client) \
            .json()["comparison"]["comparison_id"]
        url = f"{BASE}/{RUN_A}/monitoring/comparisons/{comparison_id}/decisions"
        for body in (
            {"action": "retrain", "rationale": "x"},
            {"action": "", "rationale": "x"},
            {"action": "accept", "rationale": ""},
            {"action": "accept", "rationale": None},
            {"rationale": "без действия"},
        ):
            resp = client.post(url, json=body)
            assert resp.status_code == 422, body
            assert resp.json()["code"] == "monitoring_validation_error"

    def test_a12_decision_foreign_comparison_404_code(self, client):
        seed_run(RUN_A, SESSION_A)
        seed_run(RUN_B, SESSION_B)
        # Сверка владельца B (создана сессией B в своём run).
        comparison_id = _make_comparison(client, RUN_B, session=SESSION_B) \
            .json()["comparison"]["comparison_id"]
        # Сессия A пытается вынести решение по чужой сверке.
        cookie(client, SESSION_A)
        resp = client.post(
            f"{BASE}/{RUN_A}/monitoring/comparisons/"
            f"{comparison_id}/decisions",
            json={"action": "accept", "rationale": "d8c"},
        )
        assert resp.status_code == 404
        assert resp.json()["code"] == "monitoring_not_found"


class TestAuditSemantics:
    def test_a13_trio_standard_records(self, client: TestClient):
        from .conftest import audit_count

        seed_run()
        made = _make_comparison(client)
        comparison_id = made.json()["comparison"]["comparison_id"]
        client.post(
            f"{BASE}/{RUN_A}/monitoring/comparisons/{comparison_id}/decisions",
            json={"action": "accept", "rationale": "d8c audit probe"},
        )
        assert audit_count("monitoring_actual_registered") == 1
        assert audit_count("monitoring_comparison_created") == 1
        assert audit_count("monitoring_decision_recorded") == 1
        from apps.api.security_audit import audit_records

        records = [r for r in audit_records()
                   if r.get("action") == "monitoring_actual_registered"]
        record = records[0]
        assert record["decision"] == "allowed"
        assert record["actor_subject"] == subject_of(SESSION_A).subject_id
        assert record["resource_kind"] == "monitoring"
        assert record["run_id"] == RUN_A
        assert record["policy_basis"]

    def test_a14_standard_class_no_break(self, client, monkeypatch):
        """§8/AC11: monitoring_* -- standard-класс; ломучий sink НЕ ломает
        научную операцию (в отличие от mandatory контуров DOCLOG-6/7).
        Патчим apps.api.security_audit.record_standard: _audit импортирует
        его на каждом вызове (from-import в теле функции)."""
        import apps.api.security_audit as security_audit_mod

        seed_run()

        def _boom(*args, **kwargs):
            raise RuntimeError("d8cert audit outage")

        monkeypatch.setattr(security_audit_mod, "record_standard", _boom)
        resp = _do_register(client)
        assert resp.status_code == 201, resp.text
        assert resp.json()["created"] is True

    def test_a15_gets_write_no_monitoring_audit(self, client: TestClient):
        """§17: GET не меняет исследовательское состояние; security-аудит
        факта доступа (решающая таблица) -- допустим, но НОВЫХ записей
        monitoring_* GET не создаёт (не имитирует научные операции)."""
        from .conftest import audit_records

        seed_run()
        made = _make_comparison(client)
        comparison_id = made.json()["comparison"]["comparison_id"]
        baseline_monitoring = [
            r["audit_id"] for r in audit_records()
            if r.get("action", "").startswith("monitoring_")
        ]
        state_before = client.get(
            f"{BASE}/{RUN_A}/monitoring/comparisons"
        ).json()
        for tail in (
            "/actuals",
            "/comparisons",
            f"/comparisons/{comparison_id}",
            f"/comparisons/{comparison_id}/decisions",
        ):
            resp = client.get(f"{BASE}/{RUN_A}/monitoring{tail}")
            assert resp.status_code == 200, tail
        after_monitoring = [
            r["audit_id"] for r in audit_records()
            if r.get("action", "").startswith("monitoring_")
        ]
        assert after_monitoring == baseline_monitoring
        state_after = client.get(
            f"{BASE}/{RUN_A}/monitoring/comparisons"
        ).json()
        assert state_after == state_before  # read-only (AC05-дух)


class TestErrorHygiene:
    def test_a16_no_secrets_in_errors(self, client: TestClient):
        seed_run()
        cookie(client)
        resp = client.post(
            f"{BASE}/{RUN_A}/monitoring/comparisons",
            json={"forecast_artifact_id": "art-d8cert-ghost",
                  "actual_batch_id": "act-d8cert-ghost"},
        )
        text = resp.text
        assert D8C_SENTINEL not in text
        assert "Traceback" not in text
        assert "postgres://" not in text
        body = resp.json()
        assert set(body) == {"code", "message", "request_id"}

    def test_a21_gateway_vs_service_404_shape_pin(self, client):
        """ПИН наблюдения N-D8C1: uniform 404 имеет ДВЕ формы тела.
        Шлюз (_authorized_run_or_404, HTTPException) -- {"detail": {...}};
        сервисный MonitoringAccessDenied -- плоское {code, message,
        request_id}. Статус uniform (404), но форма тела асимметрична."""
        seed_run()
        # Аноним -> шлюз -> detail-обёртка.
        anonymous = client.get(f"{BASE}/{RUN_A}/monitoring/actuals")
        assert anonymous.status_code == 404
        assert set(anonymous.json()) == {"detail"}
        # Сервисный AccessDenied (чужой артефакт при валидной сессии)
        # -> плоское тело.
        seed_run(RUN_B, SESSION_B)
        foreign = seed_forecast(RUN_B)
        cookie(client)
        batch_id = _do_register(client).json()["batch"]["batch_id"]
        flat = client.post(
            f"{BASE}/{RUN_A}/monitoring/comparisons",
            json={"forecast_artifact_id": foreign.artifact_id,
                  "actual_batch_id": batch_id},
        )
        assert flat.status_code == 404
        assert set(flat.json()) == {"code", "message", "request_id"}

    def test_a17_422_404_409_code_catalog_disjoint(self, client):
        seed_run()
        codes = set()
        r422 = _do_register(client, values=[])
        codes.add(r422.json()["code"])
        r404 = client.post(
            f"{BASE}/{RUN_A}/monitoring/comparisons",
            json={"forecast_artifact_id": "art-d8cert-ghost",
                  "actual_batch_id": "act-d8cert-ghost"},
        )
        codes.add(r404.json()["code"])
        _do_register(client, idempotency_key="d8c-cat-1")
        r409 = _do_register(client, idempotency_key="d8c-cat-1",
                            values=[{"period": "p", "value": 3.0}])
        codes.add(r409.json()["code"])
        codes.add("monitoring_units_mismatch")  # пин a05
        assert codes == {
            "monitoring_validation_error",
            "monitoring_forecast_unavailable",
            "monitoring_idempotency_conflict",
            "monitoring_units_mismatch",
        }


class TestSnapshotIntegration:
    def _build_d12(self):
        from apps.api.snapshot_builder import SnapshotService

        artifact = seed_forecast()
        batch = register_batch()
        build_comparison(artifact=artifact, batch=batch, threshold={
            "metric": "mae", "operator": ">", "value": 0.1,
        })
        snapshot, _created = (
            SnapshotService.create_default().build_snapshot(
                RUN_A, subject_of(SESSION_A),
                session_id=SESSION_A, kinds=["D12"],
            )
        )
        section = next(
            s for s in snapshot.sections if s.get("code") == "D12"
        )
        return section, artifact

    def test_a18_d12_section_reads_frozen(self, client: TestClient):
        seed_run()
        section, artifact = self._build_d12()
        assert section["claims"], "D12 секция без claims"
        claim = section["claims"][0]
        assert f"artifact:{artifact.artifact_id}" in claim["result_refs"]
        text = claim["text"]
        assert "mon-" in text                    # id сверки из frozen
        assert "порог mae" in text and "exceeded" in text
        assert "решение человека: —" in text     # решения ещё нет

    def test_a19_d12_section_empty_honest(self, client: TestClient):
        from apps.api.snapshot_builder import SnapshotService

        seed_run()
        snapshot, _created = (
            SnapshotService.create_default().build_snapshot(
                RUN_A, subject_of(SESSION_A),
                session_id=SESSION_A, kinds=["D12"],
            )
        )
        section = next(
            s for s in snapshot.sections if s.get("code") == "D12"
        )
        assert section["claims"][0]["validity"] == "unknown"
        assert "не зарегистрированы" in section["claims"][0]["text"]

    def test_a22_d12_no_matured_aggregates_dash_honest(self, client):
        """§6.1-честность снапшота: сверка без зрелых горизонтов --
        агрегаты None отображаются «—», НЕ фабрикуются как «0»."""
        from apps.api.snapshot_builder import SnapshotService

        seed_run()
        artifact = seed_forecast()
        # Факты полностью вне горизонта прогноза: matured_count == 0.
        batch = register_batch(periods=[("2025-01-01", 1.0),
                                        ("2025-02-01", 2.0)])
        build_comparison(artifact=artifact, batch=batch)
        snapshot, _created = (
            SnapshotService.create_default().build_snapshot(
                RUN_A, subject_of(SESSION_A),
                session_id=SESSION_A, kinds=["D12"],
            )
        )
        section = next(
            s for s in snapshot.sections if s.get("code") == "D12"
        )
        text = section["claims"][0]["text"]
        assert "зрелых горизонтов 0" in text
        assert "MAE=—" in text, text          # честное «—»
        assert "MAE=0" not in text            # не фабрикованный ноль


class TestSurfaceContract:
    def test_a20_source_kind_artifact_reserved_accepted(self, client):
        seed_run()
        resp = _do_register(client, source_kind="artifact",
                            source_ref="upload:2026")
        assert resp.status_code == 201
        assert resp.json()["batch"]["source_kind"] == "artifact"
        bad = _do_register(client, source_kind="db")
        assert bad.status_code == 422
        assert bad.json()["code"] == "monitoring_validation_error"
