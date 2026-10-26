# tests/api/test_doclog_recheck_fix.py
"""
Repo-тесты DOCLOG-E2E-RECHECK-1-FIX (исправление находок повторного
аудита docs/doclogcert_2026_10_26/certification.md):

  C03 -- producer→artifact интеграция: паспорт/валидация/коррекции/
         версии данных продвигаются в durable-слой в момент фиксации;
         идемпотентность AC09; честный receipt сбоя; наука не ломается.
  C04 -- применимость исторических событий: единый reducer
         event_context_validity (stale/unknown, не current).
  C05 -- обязательные элементы полноты по видам (missing_mandatory):
         D02 без текущего паспорта/data_ref -- partial.
  C06 -- D03/D04 несут научный протокол (правила/пороги, стратегия/
         метод/масштаб) из продвинутых артефактов.
  C08 -- mandatory-аудит профилей ДО защищённой записи (fail-closed
         по состоянию, не только исключением).
  F-D5C1 -- CAS-гейт отмены: завершение воркера не перезаписывает
         отменённое задание.

Namespace дизъюнктен: RUN-RECHECK*, recheck-*.
"""
from __future__ import annotations

import dataclasses
import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from apps.api.session_store import SESSION_COOKIE_NAME


@pytest.fixture()
def client(monkeypatch, tmp_path):
    """Изолированный TestClient: memory-бекенды, свой каталог данных."""
    monkeypatch.setenv("CISSTAT_DATA_DIR", str(tmp_path / "recheck-data"))
    monkeypatch.setenv("CISSTAT_STORAGE_MODE", "advisory")
    monkeypatch.setenv("CISSTAT_RUNS_BACKEND", "memory")
    monkeypatch.setenv("CISSTAT_SESSION_BACKEND", "memory")
    monkeypatch.setenv("CISSTAT_ARTIFACTS_BACKEND", "memory")
    monkeypatch.setenv("CISSTAT_DOCUMENTS_BACKEND", "memory")
    monkeypatch.setenv("CISSTAT_SNAPSHOTS_BACKEND", "memory")
    monkeypatch.setenv("CISSTAT_IDENTITY_MODE", "session_scoped")
    monkeypatch.setenv("CISSTAT_DELIVERY_WORKER_ENABLED", "0")
    monkeypatch.setenv("CISSTAT_DOCUMENT_RENDER_WORKER_ENABLED", "0")
    monkeypatch.setenv("CISSTAT_API_KEYS", "recheck-fix-key")
    for name in ("DATABASE_URL", "REDIS_URL"):
        monkeypatch.delenv(name, raising=False)
    from apps.api import artifact_store, document_jobs, doc_profiles
    from apps.api import research_runs, report_snapshot, session_store
    from apps.api import security_audit
    from apps.api.admin_logs import reset_support_grant_registry_for_testing
    from apps.api.main import app
    from apps.api.monitoring import reset_monitoring_registry_for_testing

    # сброс фабрик-одиночек (паттерн repo-корпуса DOCLOG-*)
    session_store.reset_session_store_for_testing()
    research_runs.reset_research_run_store_for_testing()
    artifact_store.reset_artifact_registry_for_testing()
    artifact_store.reset_artifact_object_store_for_testing()
    report_snapshot.reset_snapshot_registry_for_testing()
    document_jobs.reset_document_registry_for_testing()
    doc_profiles.reset_org_profile_service_for_testing()
    reset_support_grant_registry_for_testing()
    reset_monitoring_registry_for_testing()
    # audit sink: честный memory-бекенд независимо от порядка тестов
    # (песочница DATABASE_URL других корпусов может оставить Postgres-
    # singleton с ProgrammingError -- для standard это глотается, для
    # mandatory -- ложный fail-closed)
    monkeypatch.setenv("CISSTAT_AUDIT_BACKEND", "memory")
    security_audit.reset_audit_for_testing()

    with TestClient(app) as test_client:
        yield test_client


def _scenario_csv() -> bytes:
    """Детерминированный ряд n=36 (date/value): 3 пропуска и 4 выброса --
    тот же класс входа, что у сценария аудита (forecast_monitor CSV из
    штатного TS-генератора); 33 валидные точки (гейт паспорта ≥30)."""
    from datetime import date, timedelta

    start_day = date(2024, 1, 1)
    rows = ["date,value"]
    # 3 пропуска (пустые ячейки), 4 выброса (резкие всплески)
    for index in range(36):
        day = (start_day + timedelta(days=index)).isoformat()
        if index in (4, 17, 30):
            rows.append(f"{day},")
            continue
        value = float(10 + index)
        if index in (2, 9, 22, 27):
            value = value + 40.0  # выброс
        rows.append(f"{day},{value}")
    return ("\n".join(rows) + "\n").encode("utf-8")


def _upload_scenario(client: TestClient, with_corrections: bool = True):
    """Штатный сценарий: CSV → цель/дата → паспорт start → validate →
    (коррекции пропусков/выбросов) → run_id."""
    upload = client.post(
        "/v1/internal/upload",
        files={"file": ("recheck-scenario.csv", _scenario_csv(), "text/csv")},
    )
    assert upload.status_code == 200, upload.text
    client.post("/v1/session/target-column", json={"column": "value"})
    client.post("/v1/session/date-column", json={"column": "date"})
    start = client.post("/v1/session/dataset/passport/start")
    assert start.status_code == 200, start.text
    validated = client.get("/v1/session/dataset/validate")
    assert validated.status_code == 200, validated.text
    if with_corrections:
        missing = client.post(
            "/v1/session/dataset/missing-corrections",
            json={"columns": ["value"], "strategy": "median_mode", "apply": True},
        )
        assert missing.status_code == 200, missing.text
        outliers = client.post(
            "/v1/session/dataset/outlier-corrections",
            json={
                "columns": ["value"],
                "strategy": "cap",
                "method": "iqr",
                "apply": True,
            },
        )
        assert outliers.status_code == 200, outliers.text
    trace = client.get("/v1/progress/trace")
    assert trace.status_code == 200, trace.text
    return trace.json()["run_id"]


def _registry_artifacts(run_id: str):
    from apps.api.artifact_store import get_artifact_registry

    return get_artifact_registry().list_artifacts(run_id)


def _read_json_payload(artifact) -> dict:
    from apps.api.artifact_store import get_artifact_object_store

    data = get_artifact_object_store().read_bytes(artifact.storage_key)
    return json.loads(data.decode("utf-8"))




def _create_document(client: TestClient, run_id: str, kind: str) -> dict:
    """Создание черновика через штатный HTTP-поток (субъект из cookie);
    возврат словаря снимка через GET ревизии."""
    created = client.post(
        f"/v1/documentation/runs/{run_id}/documents",
        json={"kind": kind, "refresh": True},
    )
    assert created.status_code in (200, 201), created.text
    revision_id = created.json()["revision"]["revision_id"]
    detail = client.get(f"/v1/documentation/revisions/{revision_id}")
    assert detail.status_code == 200, detail.text
    return detail.json()["snapshot"]


def _events(run_id: str):
    from apps.api.research_runs import get_research_run_store

    return [
        e.to_dict() if hasattr(e, "to_dict") else dict(e)
        for e in get_research_run_store().list_events(run_id)
    ]


# ══════════════════════════════════════════════════════════════════════
# C03: producer→artifact интеграция
# ══════════════════════════════════════════════════════════════════════


class TestC03PassportPromotion:
    def test_passport_capture_promotes_durable_passport(self, client):
        """RED-оракул акта: после штатного пайплайна durable-паспорт
        существует (kind='passport') с context/revision."""
        run_id = _upload_scenario(client, with_corrections=False)
        passports = [
            a for a in _registry_artifacts(run_id) if a.kind == "passport"
        ]
        assert passports, "паспорт start не продвинут в durable-слой"
        assert passports[0].context_id, "артефакт без context_id"
        assert passports[0].data_revision is not None
        payload = _read_json_payload(passports[0])
        assert payload["kind"] == "passport"
        assert payload["stage"] == "start"

    def test_passport_promotion_is_idempotent(self, client):
        """AC09: повторный промоушен ТОГО ЖЕ снимка не плодит дублей
        (producer_key=passport:{snapshot_id}); повторный capture создаёт
        НОВЫЙ snapshot_id -- легитимный новый артефакт."""
        from apps.api.session_store import (
            SESSION_COOKIE_NAME,
            get_session_store,
        )
        from apps.api import promotion_integration

        _upload_scenario(client, with_corrections=False)
        run_id = client.get("/v1/progress/trace").json()["run_id"]
        session = get_session_store().get(
            client.cookies.get(SESSION_COOKIE_NAME)
        )
        # повторный вызов промоушена того же снимка
        first = promotion_integration.notify_passport_captured(
            client, session, stage="start"
        )
        second = promotion_integration.notify_passport_captured(
            client, session, stage="start"
        )
        assert first is not None and second is not None
        assert first.artifact_id == second.artifact_id, (
            "повторный промоушен того же снимка создал дубль (AC09)"
        )
        passports = [
            a for a in _registry_artifacts(run_id) if a.kind == "passport"
        ]
        assert len(passports) == 1

    def test_validation_result_promoted_on_check(self, client):
        """§9.3 «check»: GET /dataset/validate продвигает полный результат
        (правила/пороги/знаменатели) в durable-слой."""
        run_id = _upload_scenario(client, with_corrections=False)
        results = [
            a
            for a in _registry_artifacts(run_id)
            if a.kind == "validation_result"
        ]
        assert results, "результат валидации не продвинут"
        payload = _read_json_payload(results[0])
        assert payload["kind"] == "validation_result"
        assert payload.get("checks"), "протокол без проверок"
        data_types = payload["checks"].get("data_types")
        assert data_types, "нет проверки data_types в протоколе"
        assert "rule_source" in data_types and "mode" in data_types

    def test_corrections_promote_data_version_and_recipe(self, client):
        """§9.3 «apply»: коррекция продвигает версию данных (CSV) и рецепт
        (стратегия/метод/масштаб) с исходным context/revision."""
        run_id = _upload_scenario(client, with_corrections=True)
        artifacts = _registry_artifacts(run_id)
        recipes = [a for a in artifacts if a.kind == "correction_recipe"]
        data_versions = [a for a in artifacts if a.kind == "data_frame"]
        assert len(recipes) >= 2, "рецепты missing/outliers не продвинуты"
        assert data_versions, "версии данных не продвинуты"
        by_node = {(a.refs or {}).get("node_id"): a for a in recipes}
        assert "missing" in by_node and "outliers" in by_node
        outliers = by_node["outliers"]
        assert (outliers.refs or {}).get("strategy") == "cap"
        payload = _read_json_payload(outliers)
        assert payload["strategy"] == "cap"
        assert payload["method"] == "iqr"
        assert payload["total_changed"] >= 1

    def test_correction_recipe_depends_on_data_version(self, client):
        """§16: metadata graph хранит причины -- рецепт зависит от версии
        данных, созданной той же операцией."""
        run_id = _upload_scenario(client, with_corrections=True)
        artifacts = _registry_artifacts(run_id)
        data_ids = {
            a.artifact_id for a in artifacts if a.kind == "data_frame"
        }
        recipes = [a for a in artifacts if a.kind == "correction_recipe"]
        assert recipes
        assert all(
            set(a.dependencies) & data_ids for a in recipes
        ), "рецепт не связан с версией данных"

    def test_science_state_untouched_by_promotion(self, client):
        """AC05-дух: промоушен не меняет научное состояние сессии
        (dataframe/revision) и не добавляет событий научного контура."""
        from apps.api.session_store import (
            SESSION_COOKIE_NAME,
            get_session_store,
        )

        run_id = _upload_scenario(client, with_corrections=True)
        store = get_session_store()
        session = store.get(client.cookies.get(SESSION_COOKIE_NAME))
        df_before = session.dataframe.to_json(date_format="iso")
        rev_before = session.data_revision
        before_ids = {e["event_id"] for e in _events(run_id)}
        client.get("/v1/session/dataset/validate")
        client.get("/v1/session/dataset/missing-profile")
        session_after = store.get(client.cookies.get(SESSION_COOKIE_NAME))
        assert session_after.dataframe.to_json(date_format="iso") == df_before
        assert session_after.data_revision == rev_before
        new_events = [
            e for e in _events(run_id) if e["event_id"] not in before_ids
        ]
        assert all(
            e["event_type"]
            not in {"validation_check_status", "correction_applied"}
            for e in new_events
        )


class TestC03PromotionFailureReceipt:
    def test_promotion_failure_records_durable_receipt(
        self, client, monkeypatch
    ):
        """§9.3: при сбое -- честный durable-receipt; научная операция и
        HTTP-ответ не ломаются."""
        from apps.api import artifact_promotion, security_audit

        class UnavailableStore:
            def stage_bytes(self, *args, **kwargs):
                raise RuntimeError("recheck-store-unavailable")

        real_service = artifact_promotion.PromotionService.create_default()

        def broken_default():
            return artifact_promotion.PromotionService(
                registry=real_service.registry,
                objects=UnavailableStore(),
            )

        monkeypatch.setattr(
            artifact_promotion.PromotionService,
            "create_default",
            staticmethod(broken_default),
            raising=True,
        )
        captured = []
        monkeypatch.setattr(
            security_audit,
            "record_standard",
            lambda action, decision, **kwargs: captured.append(
                (action, decision)
            ),
        )

        upload = client.post(
            "/v1/internal/upload",
            files={
                "file": (
                    "recheck-receipt.csv",
                    _scenario_csv(),
                    "text/csv",
                )
            },
        )
        assert upload.status_code == 200, "научная операция сломана"
        client.post("/v1/session/target-column", json={"column": "value"})
        client.post("/v1/session/date-column", json={"column": "date"})
        start = client.post("/v1/session/dataset/passport/start")
        assert start.status_code == 200, "сбой промоушена сломал capture"
        assert any(
            action == "artifact_promotion_failed" and decision == "aborted"
            for action, decision in captured
        ), "durable-receipt сбоя промоушена не записан"


# ══════════════════════════════════════════════════════════════════════
# C04: применимость исторических событий
# ══════════════════════════════════════════════════════════════════════


class TestC04EventClaimValidity:
    def test_historical_event_claims_are_stale_not_current(self, client):
        """RED-оракул акта: события другого контекста НЕ маркируются
        current (единый reducer event_context_validity)."""
        run_id = _upload_scenario(client, with_corrections=True)
        snapshot = _create_document(client, run_id, "D02")
        events = {e["event_id"]: e for e in _events(run_id)}
        mismarked = []
        for section in snapshot["sections"]:
            for claim in section["claims"]:
                for ref in claim["event_refs"]:
                    event = events.get(ref.split(":", 1)[1])
                    if (
                        event
                        and event.get("context_id") != snapshot["context_id"]
                        and claim["validity"] == "current"
                    ):
                        mismarked.append((event["event_id"], claim["validity"]))
        assert not mismarked, mismarked

    def test_current_context_event_stays_current(self, client):
        """Факт ТЕКУЩЕГО контекста остаётся current (stale -- вердикт
        применимости, не стирание истории, I4)."""
        run_id = _upload_scenario(client, with_corrections=True)
        snapshot = _create_document(client, run_id, "D04")
        events = {e["event_id"]: e for e in _events(run_id)}
        found_current = False
        for section in snapshot["sections"]:
            for claim in section["claims"]:
                for ref in claim["event_refs"]:
                    event = events.get(ref.split(":", 1)[1])
                    if (
                        event
                        and event.get("context_id") == snapshot["context_id"]
                        and claim["validity"] == "current"
                    ):
                        found_current = True
        assert found_current, "факт текущего контекста потерял current"


# ══════════════════════════════════════════════════════════════════════
# C05: обязательные элементы полноты по видам
# ══════════════════════════════════════════════════════════════════════


class TestC05MandatoryCompleteness:
    def test_d02_partial_without_current_passport(self, client):
        """RED-оракул акта: D02 без current-паспорта -- partial (паспорт
        иного контекста -- stale-история, не источник текущей версии)."""
        run_id = _upload_scenario(client, with_corrections=True)
        snapshot = _create_document(client, run_id, "D02")
        assert snapshot["completeness"]["status"] == "partial"
        assert "missing_source_passport_artifact" in snapshot["completeness"][
            "missing_mandatory"
        ]

    def test_d02_complete_when_passport_current(self, client):
        """Паспорт текущего контекста + версия данных -- complete."""
        run_id = _upload_scenario(client, with_corrections=False)
        snapshot = _create_document(client, run_id, "D02")
        assert snapshot["completeness"]["status"] == "complete", (
            snapshot["completeness"]
        )
        assert snapshot["completeness"]["missing_mandatory"] == []

    def test_completeness_axes_are_separate(self, client):
        """Полнота/целостность -- раздельные оси: missing_mandatory --
        отдельное поле контракта снимка."""
        run_id = _upload_scenario(client, with_corrections=True)
        snapshot = _create_document(client, run_id, "D02")
        completeness = snapshot["completeness"]
        assert set(completeness) >= {
            "status",
            "missing_refs",
            "missing_mandatory",
        }


# ══════════════════════════════════════════════════════════════════════
# C06: научный протокол в D03/D04
# ══════════════════════════════════════════════════════════════════════


class TestC06DocumentProtocol:
    def test_d04_preserves_actual_strategy(self, client):
        """RED-оракул акта: D04 несёт фактически выбранные стратегию и
        метод (median_mode, iqr) из продвинутых рецептов."""
        run_id = _upload_scenario(client, with_corrections=True)
        snapshot = _create_document(client, run_id, "D04")
        texts = "\n".join(
            claim["text"]
            for section in snapshot["sections"]
            for claim in section["claims"]
        )
        assert "median_mode" in texts, texts
        assert "iqr" in texts, texts
        assert "Рецепт" in texts

    def test_d03_carries_validation_protocol(self, client):
        """D03 несёт правила/пороги/знаменатели из validation_result (не
        только статусы клиентских наблюдений)."""
        run_id = _upload_scenario(client, with_corrections=False)
        snapshot = _create_document(client, run_id, "D03")
        texts = "\n".join(
            claim["text"]
            for section in snapshot["sections"]
            for claim in section["claims"]
        )
        assert "Протокол валидации зафиксирован" in texts, texts
        assert "правило" in texts, texts
        assert "data_types" in texts, texts


# ══════════════════════════════════════════════════════════════════════
# C08: mandatory-аудит профилей ДО защищённой записи
# ══════════════════════════════════════════════════════════════════════


class TestC08ProfileAuditOrder:
    @staticmethod
    def _admin(subject_id: str):
        return SimpleNamespace(
            is_anonymous=False,
            role="admin",
            subject_id=subject_id,
            tenant_id="recheck-tenant",
            via="api_key",
            scopes=frozenset(),
        )

    def test_mandatory_profile_audit_failure_does_not_commit_policy(self):
        """RED-оракул акта: MandatoryAuditFailure не оставляет защищённую
        запись в реестре (fail-closed по состоянию)."""
        from apps.api.doc_profiles import (
            MemoryOrgProfileRegistry,
            OrgProfileService,
        )
        from apps.api.security_audit import (
            MandatoryAuditFailure,
            set_audit_sink_for_testing,
        )

        class UnavailableAudit:
            def append(self, record):
                raise RuntimeError("owned-audit-unavailable")

        registry = MemoryOrgProfileRegistry()
        service = OrgProfileService(registry)
        subject = SimpleNamespace(
            is_anonymous=False,
            role="admin",
            subject_id="recheck-subject",
            tenant_id="recheck-tenant",
            via="api_key",
            scopes=frozenset(),
        )
        set_audit_sink_for_testing(UnavailableAudit())
        try:
            with pytest.raises(MandatoryAuditFailure):
                service.create_profile(
                    name="recheck-policy",
                    version_no=1,
                    format="docx",
                    subject=subject,
                )
        finally:
            set_audit_sink_for_testing(None)
        assert registry.find_duplicate("recheck-policy", 1) is None

    def test_retire_profile_audit_failure_keeps_active(self):
        """retire -- защищённая запись того же класса: при отказе
        mandatory-аудита статус не меняется."""
        from apps.api.doc_profiles import (
            MemoryOrgProfileRegistry,
            OrgProfileService,
            PROFILE_ACTIVE,
        )
        from apps.api.security_audit import (
            MandatoryAuditFailure,
            MemoryAuditSink,
            set_audit_sink_for_testing,
        )

        registry = MemoryOrgProfileRegistry()
        service = OrgProfileService(registry)
        admin = self._admin("recheck-subject-retire")
        # честный memory-sink на время создания (процесс может нести
        # Postgres-singleton другого корпуса -- C08 проверяет порядок,
        # а не бекенд)
        set_audit_sink_for_testing(MemoryAuditSink())
        profile = service.create_profile(
            name="recheck-retire-policy",
            version_no=1,
            format="pdfa",
            subject=admin,
        )

        class UnavailableAudit:
            def append(self, record):
                raise RuntimeError("owned-audit-unavailable")

        try:
            set_audit_sink_for_testing(UnavailableAudit())
            with pytest.raises(MandatoryAuditFailure):
                service.retire_profile(profile.profile_id, admin)
        finally:
            set_audit_sink_for_testing(None)
        still_active = registry.get_profile(profile.profile_id)
        assert still_active is not None
        assert still_active.status == PROFILE_ACTIVE


# ══════════════════════════════════════════════════════════════════════
# F-D5C1: CAS-гейт отмены
# ══════════════════════════════════════════════════════════════════════


class TestCancelRaceGate:
    def test_complete_render_does_not_overwrite_cancelled(self, tmp_path):
        """Завершение воркера не перезаписывает отменённое задание."""
        from apps.api.document_jobs import (
            DocumentDeliveryService,
            DocumentJobRecord,
            MemoryDocumentRegistry,
            JOB_CANCELLED,
            JOB_RENDERING,
            new_job_id,
        )
        from apps.api.artifact_store import ArtifactObjectStore

        registry = MemoryDocumentRegistry()
        service = DocumentDeliveryService(
            registry, ArtifactObjectStore(root=str(tmp_path))
        )
        job = DocumentJobRecord(
            job_id=new_job_id(),
            run_id="RUN-RECHECK-CAS",
            snapshot_id="snap-recheck-cas",
            format="pdf",
            state=JOB_RENDERING,
            attempt=1,
        )
        registry.register_job(job)
        registry.update_job(
            dataclasses.replace(job, state=JOB_CANCELLED)
        )
        from apps.api.report_snapshot import ReportSnapshot

        snapshot = ReportSnapshot(
            snapshot_id="snap-recheck-cas",
            research_run_id="RUN-RECHECK-CAS",
            payload_sha256="a" * 64,
        )
        updated, _rendition = service.complete_render(
            job,
            SimpleNamespace(media_type="application/pdf"),
            b"%PDF-1.4 recheck",
            snapshot,
        )
        assert updated.state == JOB_CANCELLED, (
            "отмена перезаписана готовностью (F-D5C1)"
        )

    def test_complete_render_finishes_running_job(self, tmp_path):
        """Позитивный контроль: незаказанное задание завершается ready
        (гейт не блокирует нормальное завершение)."""
        from apps.api.document_jobs import (
            DocumentDeliveryService,
            DocumentJobRecord,
            MemoryDocumentRegistry,
            JOB_READY,
            JOB_RENDERING,
            new_job_id,
        )
        from apps.api.artifact_store import ArtifactObjectStore

        registry = MemoryDocumentRegistry()
        service = DocumentDeliveryService(
            registry, ArtifactObjectStore(root=str(tmp_path))
        )
        job = DocumentJobRecord(
            job_id=new_job_id(),
            run_id="RUN-RECHECK-CAS-OK",
            snapshot_id="snap-recheck-cas-ok",
            format="pdf",
            state=JOB_RENDERING,
            attempt=1,
        )
        registry.register_job(job)
        from apps.api.report_snapshot import ReportSnapshot

        snapshot = ReportSnapshot(
            snapshot_id="snap-recheck-cas-ok",
            research_run_id="RUN-RECHECK-CAS-OK",
            payload_sha256="b" * 64,
        )
        updated, rendition = service.complete_render(
            job,
            SimpleNamespace(media_type="application/pdf"),
            b"%PDF-1.4 recheck-ok",
            snapshot,
        )
        assert updated.state == JOB_READY
        assert rendition is not None
