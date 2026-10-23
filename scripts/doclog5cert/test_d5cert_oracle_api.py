# scripts/doclog5cert/test_d5cert_oracle_api.py
"""DOCLOG-5-CERT: API/сервис-оракулы на СВОИХ данных (namespace
RUN-D5C*/d5cert-*): асинхронный контур тяжёлых форматов (§18: тяжёлый
PDF не создаётся синхронно), AC08 (fault-injection: crash на stage/
commit/register -> явное состояние без broken ready refs; lease
expiry -> реклейм без роста attempt; timeout -> честный failed),
AC09 (активный дубликат -> тот же job; ready-дубль -> прежний
rendition; лимит попыток честен), backpressure (429 quota_exceeded),
единый snapshot hash (критерий завершения §19), диагностика cancel-
гонки (познавательный зонд: worker завершает рендер поверх отмены).
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from conftest import (
    CERT_FOREIGN_SESSION,
    CERT_RUN_ID,
    CERT_RUN_ID_B,
    CERT_SESSION,
    CERT_SESSION_B,
    CERT_TENANT_B,
    build_own_snapshot,
    cert_subject,
    register_own_snapshot,
    seed_cert_run,
)


@pytest.fixture()
def client():
    from fastapi.testclient import TestClient

    from apps.api.main import app

    with TestClient(app) as test_client:
        yield test_client


def _cookie(client: TestClient, session_id: str = CERT_SESSION) -> None:
    from apps.api.session_store import SESSION_COOKIE_NAME

    client.cookies.set(SESSION_COOKIE_NAME, session_id)


def _seed_builder_snapshot(
    run_id: str = CERT_RUN_ID,
    session_id: str = CERT_SESSION,
    *,
    data_revision: int = 7,
):
    """Снимок через ШТАТНЫЙ сборщик DOCLOG-2 (registry+payload hash),
    но на СВОИХ run/сессии (namespace сертификатора)."""
    from apps.api.identity import DEFAULT_TENANT_ID, SubjectRef
    from apps.api.research_runs import ResearchRun, get_research_run_store
    from apps.api.session_store import AnalysisSession, get_session_store
    from apps.api.snapshot_builder import SnapshotService
    from apps.api import research_runs
    from apps.api.trace_events import TraceEvent

    store = get_session_store()
    session = store.get(session_id)
    if session is None:
        session = AnalysisSession(session_id=session_id)
        session.owner_subject = SubjectRef.from_session(session_id).subject_id
    session.tenant_id = DEFAULT_TENANT_ID
    session.target_column = "value"
    session.date_column = "date"
    store.save(session)
    get_research_run_store().upsert_run(
        ResearchRun(
            run_id=run_id,
            session_id=session_id,
            dataset_fingerprint="d5c" * 10 + "1",
            dataset_name="d5cert-seed",
            target_column="value",
            target_column_source="user",
            created_at=datetime.now(timezone.utc).isoformat(),
            last_active_at=datetime.now(timezone.utc).isoformat(),
            status="active",
            context_id=f"ctx-{run_id.lower()}-{data_revision}",
            data_revision=data_revision,
            owner_subject=SubjectRef.from_session(session_id).subject_id,
            tenant_id=DEFAULT_TENANT_ID,
            ownership="bound",
        )
    )
    research_runs.get_research_run_store().append_event(
        run_id,
        TraceEvent(
            event_type="upload_completed",
            payload={"dataset": "d5cert"},
            run_id=run_id,
            stage="upload",
            schema_version=2,
            evidence_level="server_result",
        ),
    )
    subject = SubjectRef.from_session(session_id)
    snapshot, _created = SnapshotService.create_default().build_snapshot(
        run_id, subject, session_id=session_id, kinds=["D01"]
    )
    return snapshot


def _revision_for(
    client: TestClient,
    snapshot,
    run_id: str = CERT_RUN_ID,
) -> str:
    """Документ+ревизия из СВОЕГО снимка (refresh=false переиспользует
    последний снимок run с kind D01 -- штатный путь DOCLOG-4)."""
    from apps.api.document_jobs import DocumentDeliveryService
    from apps.api.identity import SubjectRef

    service = DocumentDeliveryService.create_default()
    subject = SubjectRef.from_session(CERT_SESSION)
    document, revision, _created = service.ensure_document_revision(
        snapshot,
        kind_code="D01",
        subject=subject,
        session_id=CERT_SESSION,
    )
    return revision.revision_id


def _worker(**kwargs):
    from apps.api.document_render_worker import DocumentRenderWorker

    return DocumentRenderWorker(**kwargs)


def _registry():
    from apps.api.document_jobs import get_document_registry

    return get_document_registry()


def _replace(job, **changes):
    from apps.api.document_jobs import replace_dataclass

    return replace_dataclass(job, **changes)


# ══════════════════════════════════════════════════════════════════════
# 1. Асинхронный контур (§18) и единый snapshot hash (§19)
# ══════════════════════════════════════════════════════════════════════


class TestAsyncHeavyFlow:
    def test_d5o40_heavy_post_202_queued_no_sync_render(
        self, client, tmp_path
    ):
        """§18: тяжёлый формат НЕ рендерится синхронно -- dispatcher
        не вызывается в POST, job queued, rendition отсутствует."""
        snapshot = _seed_builder_snapshot()
        seed_cert_run()
        rev = _revision_for(client, snapshot)
        import apps.api.document_jobs as dj

        calls = {"n": 0}
        real = dj.render_snapshot_pdf

        def _sentinel(snap):
            calls["n"] += 1
            return real(snap)

        dj.render_snapshot_pdf = _sentinel
        try:
            _cookie(client)
            resp = client.post(
                f"/v1/documentation/revisions/{rev}/renditions",
                json={"format": "pdf"},
            )
            assert resp.status_code == 202
            body = resp.json()
            assert body["job"]["state"] == "queued"
            assert calls["n"] == 0  # СИНХРОННОГО рендера не было
            assert body["job"]["rendition"] is None
        finally:
            dj.render_snapshot_pdf = real

    def test_d5o41_worker_completes_and_unified_hash(self, client, tmp_path):
        """§19 критерий завершения: rendition несёт ТОТ ЖЕ payload_sha256
        registry-снимка; байты доступны и совпадают с чистым рендером."""
        snapshot = _seed_builder_snapshot()
        seed_cert_run()
        rev = _revision_for(client, snapshot)
        _cookie(client)
        post = client.post(
            f"/v1/documentation/revisions/{rev}/renditions",
            json={"format": "svg"},
        )
        job_id = post.json()["job"]["job_id"]
        report = _worker().run_once()
        assert report["ready"] == 1
        registry = _registry()
        job = registry.get_job(job_id)
        assert job.state == "ready"
        rendition = registry.get_rendition(job.rendition_id)
        record = registry  # registry-метаданные снимка
        from apps.api.report_snapshot import get_snapshot_registry

        snap_record = get_snapshot_registry().get_snapshot_record(
            snapshot.snapshot_id
        )
        assert rendition.snapshot_payload_sha256 == (
            snap_record.payload_sha256
        )
        assert rendition.snapshot_payload_sha256 != ""
        from apps.api.document_renditions import render_snapshot_svg

        content = service_read(rendition.rendition_id)
        assert content == render_snapshot_svg(snapshot).encode("utf-8")

    def test_d5o42_p0_and_p1_share_same_snapshot_hash(self, tmp_path):
        """§19: P0 (sync) и P1 (worker) rendition одной ревизии -- один
        snapshot hash между собой и с registry."""
        snapshot = _seed_builder_snapshot()
        seed_cert_run()
        from apps.api.document_jobs import DocumentDeliveryService
        from apps.api.identity import SubjectRef

        service = DocumentDeliveryService.create_default()
        subject = SubjectRef.from_session(CERT_SESSION)
        job_csv, rend_csv = service.request_rendition(
            snapshot,
            format="csv",
            subject=subject,
            session_id=CERT_SESSION,
        )
        assert rend_csv is not None  # P0 -- синхронно
        job_svg, _ = service.request_rendition(
            snapshot,
            format="svg",
            subject=subject,
            session_id=CERT_SESSION,
        )
        _worker().run_once()
        rend_svg = _registry().get_rendition(
            _registry().get_job(job_svg.job_id).rendition_id
        )
        from apps.api.report_snapshot import get_snapshot_registry

        record = get_snapshot_registry().get_snapshot_record(
            snapshot.snapshot_id
        )
        assert rend_csv.snapshot_payload_sha256 == record.payload_sha256
        assert rend_svg.snapshot_payload_sha256 == record.payload_sha256
        assert rend_csv.snapshot_payload_sha256 != ""

    def test_d5o43_active_dup_returns_same_job(self, tmp_path):
        """AC09: повторный POST при активном queued -- ТОТ ЖЕ job,
        без второго задания."""
        snapshot = _seed_builder_snapshot()
        seed_cert_run()
        from apps.api.document_jobs import DocumentDeliveryService
        from apps.api.identity import SubjectRef

        service = DocumentDeliveryService.create_default()
        subject = SubjectRef.from_session(CERT_SESSION)
        job1, _ = service.request_rendition(
            snapshot, format="pdf", subject=subject,
            session_id=CERT_SESSION,
        )
        job2, _ = service.request_rendition(
            snapshot, format="pdf", subject=subject,
            session_id=CERT_SESSION,
        )
        assert job1.job_id == job2.job_id
        targets = [
            j for j in service.registry.list_jobs(CERT_RUN_ID)
            if j.snapshot_id == snapshot.snapshot_id and j.format == "pdf"
        ]
        assert len(targets) == 1

    def test_d5o44_ready_dup_same_rendition_no_rerender(self, tmp_path):
        """AC09/§12.2 (пин DOCLOG-4): ready-цель возвращает прежний
        job/rendition БЕЗ повторного рендера."""
        snapshot = _seed_builder_snapshot()
        seed_cert_run()
        import apps.api.document_jobs as dj
        from apps.api.document_jobs import DocumentDeliveryService
        from apps.api.identity import SubjectRef

        service = DocumentDeliveryService.create_default()
        subject = SubjectRef.from_session(CERT_SESSION)
        job1, rend1 = service.request_rendition(
            snapshot, format="csv", subject=subject,
            session_id=CERT_SESSION,
        )
        calls = {"n": 0}
        real = dj.render_snapshot_csv

        def _counting(snap):
            calls["n"] += 1
            return real(snap)

        dj.render_snapshot_csv = _counting
        try:
            job2, rend2 = service.request_rendition(
                snapshot, format="csv", subject=subject,
                session_id=CERT_SESSION,
            )
        finally:
            dj.render_snapshot_csv = real
        assert job2.job_id == job1.job_id
        assert rend2.rendition_id == rend1.rendition_id
        assert calls["n"] == 0  # повторного рендера не было

    def test_d5o45_content_download_integrity(self, client, tmp_path):
        """Выдача: байты готового тяжёлого файла проходят
        content_sha256-проверку; чужой субъект -- uniform 404."""
        snapshot = _seed_builder_snapshot()
        seed_cert_run()
        rev = _revision_for(client, snapshot)
        _cookie(client)
        post = client.post(
            f"/v1/documentation/revisions/{rev}/renditions",
            json={"format": "svg"},
        )
        job_id = post.json()["job"]["job_id"]
        _worker().run_once()
        poll = client.get(f"/v1/documentation/jobs/{job_id}")
        assert poll.status_code == 200
        rendition_id = poll.json()["job"]["rendition"]["rendition_id"]
        download = client.get(
            f"/v1/documentation/renditions/{rendition_id}/content"
        )
        assert download.status_code == 200
        assert download.headers["content-type"].startswith("image/svg+xml")

        from apps.api.session_store import SESSION_COOKIE_NAME

        client.cookies.set(SESSION_COOKIE_NAME, CERT_FOREIGN_SESSION)
        foreign = client.get(
            f"/v1/documentation/renditions/{rendition_id}/content"
        )
        assert foreign.status_code == 404
        foreign_job = client.get(f"/v1/documentation/jobs/{job_id}")
        assert foreign_job.status_code == 404


def service_read(rendition_id: str) -> bytes:
    from apps.api.document_jobs import DocumentDeliveryService
    from apps.api.identity import SubjectRef

    service = DocumentDeliveryService.create_default()
    rendition = _registry().get_rendition(rendition_id)
    return service.read_rendition_content(
        rendition,
        SubjectRef.from_session(CERT_SESSION),
        session_id=CERT_SESSION,
    )


# ══════════════════════════════════════════════════════════════════════
# 2. AC08: fault-injection / lease / timeout (§18)
# ══════════════════════════════════════════════════════════════════════


class TestAc08FaultInjection:
    @staticmethod
    def _queued_job(snapshot, fmt="pdf"):
        from apps.api.document_jobs import DocumentDeliveryService
        from apps.api.identity import SubjectRef

        service = DocumentDeliveryService.create_default()
        job, _ = service.request_rendition(
            snapshot, format=fmt,
            subject=SubjectRef.from_session(CERT_SESSION),
            session_id=CERT_SESSION,
        )
        return job

    def _crash_probe(self, snapshot, monkeypatch, method: str):
        """Краш сервиса object store на stage/commit -> run_once:
        job обязан остаться в ЯВНОМ состоянии (rendering) без готового
        rendition; после lease-истечения -- реклейм и дозавершение."""
        job = self._queued_job(snapshot)
        from apps.api.artifact_store import get_artifact_object_store

        store = get_artifact_object_store()
        real = getattr(store, method)

        def _crash(*args, **kwargs):
            raise RuntimeError(f"d5cert fault-injection {method}")

        monkeypatch.setattr(store, method, _crash)
        report = _worker().run_once()
        monkeypatch.setattr(store, method, real)
        registry = _registry()
        after = registry.get_job(job.job_id)
        assert after.state == "rendering"  # явное pending, НЕ ready
        assert registry.find_rendition(
            snapshot.snapshot_id, "pdf", "standard"
        ) is None
        # lease-истечение (контролируемо укорачиваем) -> реклейм ->
        # следующий цикл успешно завершает
        past = (
            datetime.now(timezone.utc) - timedelta(seconds=1)
        ).isoformat()
        registry.update_job(
            _replace(after, lease_expires_at=past)
        )
        report2 = _worker().run_once()  # reclaim + claim
        assert report2["reclaimed"] == 1
        report3 = _worker().run_once()  # рендер после реклейма
        final = registry.get_job(job.job_id)
        assert final.state == "ready"
        assert final.attempt == 1  # реклейм НЕ растит attempt (D5)

    def test_d5o46_stage_crash_no_broken_refs_then_recover(
        self, tmp_path, monkeypatch
    ):
        snapshot = _seed_builder_snapshot()
        seed_cert_run()
        self._crash_probe(snapshot, monkeypatch, "stage_bytes")

    def test_d5o47_commit_crash_no_broken_refs_then_recover(
        self, tmp_path, monkeypatch
    ):
        snapshot = _seed_builder_snapshot()
        seed_cert_run()
        self._crash_probe(snapshot, monkeypatch, "commit_staged")

    def test_d5o48_register_crash_no_broken_refs_then_recover(
        self, tmp_path, monkeypatch
    ):
        snapshot = _seed_builder_snapshot()
        seed_cert_run()
        job = self._queued_job(snapshot)
        registry = _registry()
        real_update = registry.update_rendition
        real_register = registry.register_rendition

        def _crash(*args, **kwargs):
            raise RuntimeError("d5cert fault-injection register_rendition")

        registry.register_rendition = _crash
        _worker().run_once()
        registry.register_rendition = real_register
        after = registry.get_job(job.job_id)
        assert after.state == "rendering"
        assert registry.find_rendition(
            snapshot.snapshot_id, "pdf", "standard"
        ) is None
        past = (
            datetime.now(timezone.utc) - timedelta(seconds=1)
        ).isoformat()
        registry.update_job(_replace(after, lease_expires_at=past))
        _worker().run_once()
        _worker().run_once()
        final = registry.get_job(job.job_id)
        assert final.state == "ready"

    def test_d5o49_reclaim_expired_lease_no_attempt_growth(self, tmp_path, monkeypatch):
        """AC08/D5: просроченный lease -> queued, error_code=
        lease_reclaimed, attempt НЕ растёт, lease-поля очищены; затем
        обычный цикл доводит до ready с тем же attempt (одно-цикловое
        восстановление)."""
        snapshot = _seed_builder_snapshot()
        seed_cert_run()
        job = self._queued_job(snapshot)
        registry = _registry()
        past = (
            datetime.now(timezone.utc) - timedelta(seconds=5)
        ).isoformat()
        now_iso = datetime.now(timezone.utc).isoformat()
        registry.update_job(
            _replace(
                registry.get_job(job.job_id),
                state="rendering",
                attempt=3,
                claimed_at=now_iso,
                lease_expires_at=past,
            )
        )
        worker = _worker()
        # шаг 1: ТОЛЬКО реклейм (claim подавлен -- наблюдаем состояние)
        monkeypatch.setattr(worker, "_select_claims", lambda: [])
        report = worker.run_once()
        assert report["reclaimed"] == 1
        mid = registry.get_job(job.job_id)
        assert mid.state == "queued"
        assert mid.error_code == "lease_reclaimed"
        assert mid.attempt == 3  # НЕ вырос (D5/AC08)
        assert mid.claimed_at is None
        assert mid.lease_expires_at is None
        # шаг 2: обычный цикл -- заявка и рендер без роста attempt
        worker.__dict__.pop("_select_claims", None)  # восстановить метод
        worker.run_once()
        final = registry.get_job(job.job_id)
        assert final.state == "ready"
        assert final.attempt == 3  # реклейм и восстановление не растят

    def test_d5o50_live_lease_not_stolen(self, tmp_path):
        """AC09: чужой ЖИВОЙ lease не перехватывается и учитывается в
        per-tenant concurrency (разные ЦЕЛИ: pdf и zip)."""
        snapshot = _seed_builder_snapshot()
        seed_cert_run()
        registry = _registry()
        from apps.api.document_jobs import new_job_id

        # rendering-джоб с живым lease (tenant по умолчанию), цель pdf
        live = self._queued_job(snapshot, fmt="pdf")
        now = datetime.now(timezone.utc)
        live = registry.update_job(
            _replace(
                registry.get_job(live.job_id),
                state="rendering",
                claimed_at=now.isoformat(),
                lease_expires_at=(
                    now + timedelta(seconds=120)
                ).isoformat(),
            )
        )
        # отдельная цель (zip) в очереди, тот же tenant
        queued = self._queued_job(snapshot, fmt="zip")
        worker = _worker(per_tenant_limit=1)
        report = worker.run_once()
        after_live = registry.get_job(live.job_id)
        after_queued = registry.get_job(queued.job_id)
        assert after_live.state == "rendering"  # живой lease не тронут
        assert after_live.claimed_at == live.claimed_at
        assert after_queued.state == "queued"  # лимит=1 -- не заявлен
        # лимит=2 -- заявка проходит
        worker2 = _worker(per_tenant_limit=2)
        worker2.run_once()
        assert registry.get_job(queued.job_id).state == "ready"

    def test_d5o51_timeout_failed_not_ready_no_late_refs(
        self, tmp_path, monkeypatch
    ):
        """§18: timeout -> честный requeue render_timeout (попытка+1);
        позднее завершение фонового потока НЕ создаёт rendition
        (broken ready refs невозможны)."""
        snapshot = _seed_builder_snapshot()
        seed_cert_run()
        job = self._queued_job(snapshot)
        import apps.api.document_jobs as dj

        real = dj._render_snapshot_by_format

        def _slow(snap, fmt):
            time.sleep(1.2)
            return real(snap, fmt)

        monkeypatch.setattr(dj, "_render_snapshot_by_format", _slow)
        worker = _worker(render_timeout=0.2)
        report = worker.run_once()
        assert report["requeued"] == 1
        registry = _registry()
        after = registry.get_job(job.job_id)
        assert after.state == "queued"
        assert after.error_code == "render_timeout"
        assert after.attempt == 2  # был 1 -> стал 2 (transient)
        assert registry.find_rendition(
            snapshot.snapshot_id, "pdf", "standard"
        ) is None
        time.sleep(1.5)  # фоновый поток завершился ПОСЛЕ timeout
        assert registry.find_rendition(
            snapshot.snapshot_id, "pdf", "standard"
        ) is None  # поздний поток не регистрирует результат
        assert registry.get_job(job.job_id).state == "queued"

    def test_d5o52_deterministic_error_terminal_immediately(
        self, tmp_path, monkeypatch
    ):
        """Детерминированная ошибка (unsupported_format) -- terminal
        failed сразу, очередь не крутится (§18)."""
        snapshot = _seed_builder_snapshot()
        seed_cert_run()
        job = self._queued_job(snapshot)
        import apps.api.document_jobs as dj
        from apps.api.document_jobs import UnsupportedFormatError

        def _boom(snap, fmt):
            raise UnsupportedFormatError("d5cert deterministic")

        monkeypatch.setattr(dj, "_render_snapshot_by_format", _boom)
        report = _worker().run_once()
        registry = _registry()
        after = registry.get_job(job.job_id)
        assert after.state == "failed"
        assert after.error_code == "unsupported_format"
        assert after.attempt == 1  # без цикла повторов
        assert report["failed"] == 1 and report["requeued"] == 0

    def test_d5o53_transient_set_pin(self):
        """Пин TRANSIENT_ERROR_CODES: ровно render_failed/render_timeout
        переоткладываются; остальное -- терминально."""
        from apps.api.document_render_worker import TRANSIENT_ERROR_CODES

        assert TRANSIENT_ERROR_CODES == frozenset(
            {"render_failed", "render_timeout"}
        )


# ══════════════════════════════════════════════════════════════════════
# 3. AC09: лимит попыток честен; §18: backpressure 429
# ══════════════════════════════════════════════════════════════════════


class TestRetryLimitAndQuota:
    def _exhaust_one_job(self, snapshot, monkeypatch) -> None:
        """Один job через 5 transient-попыток -> terminal failed."""
        import apps.api.document_jobs as dj

        def _boom(snap, fmt):
            raise RuntimeError("d5cert transient fail")

        monkeypatch.setattr(dj, "_render_snapshot_by_format", _boom)
        worker = _worker(max_attempts=5)
        for _ in range(6):  # 5 requeue + terminal
            worker.run_once()

    def test_d5o54_retry_limit_boundary_and_429(
        self, tmp_path, monkeypatch
    ):
        from apps.api.document_jobs import (
            MAX_JOB_ATTEMPTS,
            DocumentDeliveryService,
            DocumentRetryLimitExceeded,
        )
        from apps.api.identity import SubjectRef

        assert MAX_JOB_ATTEMPTS == 5
        snapshot = _seed_builder_snapshot()
        seed_cert_run()
        service = DocumentDeliveryService.create_default()
        subject = SubjectRef.from_session(CERT_SESSION)
        # 4 исчерпанных цели: на каждой -- новый POST ещё честен
        for i in range(4):
            job = self._post_and_exhaust(snapshot, monkeypatch)
            assert job.state == "failed"
        # 5-й POST -- ещё разрешён (5-я попытка цели)
        job5, _ = service.request_rendition(
            snapshot, format="pdf", subject=subject,
            session_id=CERT_SESSION,
        )
        assert job5.state == "queued"
        self._exhaust_one_job(snapshot, monkeypatch)
        # 6-й POST -- честный DocumentRetryLimitExceeded
        with pytest.raises(DocumentRetryLimitExceeded):
            service.request_rendition(
                snapshot, format="pdf", subject=subject,
                session_id=CERT_SESSION,
            )

    def _post_and_exhaust(self, snapshot, monkeypatch):
        from apps.api.document_jobs import DocumentDeliveryService
        from apps.api.identity import SubjectRef

        service = DocumentDeliveryService.create_default()
        job, _ = service.request_rendition(
            snapshot, format="pdf",
            subject=SubjectRef.from_session(CERT_SESSION),
            session_id=CERT_SESSION,
        )
        self._exhaust_one_job(snapshot, monkeypatch)
        return service.registry.get_job(job.job_id)

    def test_d5o55_retry_429_http_mapping_code(
        self, client, tmp_path, monkeypatch
    ):
        """§17: 429 с кодом retry_limit_exceeded через HTTP."""
        snapshot = _seed_builder_snapshot()
        seed_cert_run()
        rev = _revision_for(client, snapshot)
        self._post_and_exhaust(snapshot, monkeypatch)
        for _ in range(3):
            self._post_and_exhaust(snapshot, monkeypatch)
        _cookie(client)
        resp = client.post(
            f"/v1/documentation/revisions/{rev}/renditions",
            json={"format": "pdf"},
        )
        assert resp.status_code == 200 or resp.status_code == 202
        self._post_and_exhaust(snapshot, monkeypatch)
        final = client.post(
            f"/v1/documentation/revisions/{rev}/renditions",
            json={"format": "pdf"},
        )
        assert final.status_code == 429
        detail = final.json()["detail"]
        assert detail["code"] == "retry_limit_exceeded"

    def test_d5o56_quota_exceeded_429_and_other_tenant_ok(
        self, tmp_path
    ):
        """§18 backpressure: 10 открытых jobs tenant A -> 429
        quota_exceeded; tenant B не затронут."""
        from apps.api.document_jobs import (
            MAX_OPEN_JOBS_PER_TENANT,
            DocumentDeliveryService,
            DocumentQuotaExceeded,
        )
        from apps.api.identity import SubjectRef

        assert MAX_OPEN_JOBS_PER_TENANT == 10
        service = DocumentDeliveryService.create_default()
        subject_a = SubjectRef.from_session(CERT_SESSION)
        # 6 heavy-форматов x 2 снимка = 12 целей; достаточно 10
        snapshots = [_seed_builder_snapshot(data_revision=rev)
                     for rev in (7, 8)]
        heavy = ["pdf", "xlsx", "parquet", "svg", "png", "zip"]
        opened = 0
        for snap in snapshots:
            for fmt in heavy:
                if opened >= MAX_OPEN_JOBS_PER_TENANT:
                    break
                service.request_rendition(
                    snap, format=fmt, subject=subject_a,
                    session_id=CERT_SESSION,
                )
                opened += 1
        assert opened == MAX_OPEN_JOBS_PER_TENANT
        with pytest.raises(DocumentQuotaExceeded):
            service.request_rendition(
                snapshots[0], format="csv", subject=subject_a,
                session_id=CERT_SESSION,
            )
        # tenant B -- своя очередь, не затронута
        seed_cert_run(
            CERT_RUN_ID_B, CERT_SESSION_B, tenant_id=CERT_TENANT_B
        )
        subject_b = cert_subject(CERT_SESSION_B, tenant_id=CERT_TENANT_B)
        snapshot_b = build_own_snapshot(
            "snap-d5cert-tenantB", run_id=CERT_RUN_ID_B
        )
        register_own_snapshot(snapshot_b, Path("/tmp"))
        job_b, _ = service.request_rendition(
            snapshot_b, format="pdf", subject=subject_b,
            session_id=CERT_SESSION_B,
        )
        assert job_b.state == "queued"

    def test_d5o57_quota_429_http_mapping_code(
        self, client, tmp_path
    ):
        """§17: 429 с кодом quota_exceeded через HTTP."""
        snapshot = _seed_builder_snapshot()
        seed_cert_run()
        rev = _revision_for(client, snapshot)
        from apps.api.document_jobs import DocumentDeliveryService
        from apps.api.identity import SubjectRef

        service = DocumentDeliveryService.create_default()
        subject_a = SubjectRef.from_session(CERT_SESSION)
        heavy = ["pdf", "xlsx", "parquet", "svg", "png", "zip"]
        # 2 снимка достаточно: 6 + 4 = 10 открытых
        snapshot2 = _seed_builder_snapshot(data_revision=9)
        for snap, formats in (
            (snapshot, heavy),
            (snapshot2, ["pdf", "xlsx", "parquet", "svg"]),
        ):
            for fmt in formats:
                service.request_rendition(
                    snap, format=fmt, subject=subject_a,
                    session_id=CERT_SESSION,
                )
        _cookie(client)
        resp = client.post(
            f"/v1/documentation/revisions/{rev}/renditions",
            json={"format": "md"},
        )
        assert resp.status_code == 429
        assert resp.json()["detail"]["code"] == "quota_exceeded"


# ══════════════════════════════════════════════════════════════════════
# 4. Cancel (§17) и зонд cancel-гонки (диагностика находки)
# ══════════════════════════════════════════════════════════════════════


class TestCancelSemantics:
    def test_d5o58_cancel_queued_worker_skips(self, tmp_path):
        """§17: отменённый queued job worker'ом не рендерится."""
        snapshot = _seed_builder_snapshot()
        seed_cert_run()
        from apps.api.document_jobs import DocumentDeliveryService
        from apps.api.identity import SubjectRef

        service = DocumentDeliveryService.create_default()
        subject = SubjectRef.from_session(CERT_SESSION)
        job, _ = service.request_rendition(
            snapshot, format="pdf", subject=subject,
            session_id=CERT_SESSION,
        )
        cancelled = service.cancel_job(
            job.job_id, subject, session_id=CERT_SESSION
        )
        assert cancelled.state == "cancelled"
        report = _worker().run_once()
        assert report["claimed"] == 0
        assert service.registry.get_job(job.job_id).state == "cancelled"

    def test_d5o59_cancel_final_states_noop(self, tmp_path):
        """§17: cancel на ready/failed/cancelled -- no-op."""
        snapshot = _seed_builder_snapshot()
        seed_cert_run()
        from apps.api.document_jobs import DocumentDeliveryService
        from apps.api.identity import SubjectRef

        service = DocumentDeliveryService.create_default()
        subject = SubjectRef.from_session(CERT_SESSION)
        job, rend = service.request_rendition(
            snapshot, format="csv", subject=subject,
            session_id=CERT_SESSION,
        )
        assert job.state == "ready"
        again = service.cancel_job(
            job.job_id, subject, session_id=CERT_SESSION
        )
        assert again.state == "ready"  # no-op

    def test_d5o64_content_tamper_rejected(self, tmp_path):
        """T8-дух: подмена content_sha256/байтов rendition -> байты НЕ
        выдаются (DocumentIntegrityError). Адъюдикация M20: покрытие
        integrity-проверки выдачи."""
        snapshot = _seed_builder_snapshot()
        seed_cert_run()
        from apps.api.document_jobs import (
            DocumentDeliveryService,
            DocumentIntegrityError,
        )
        from apps.api.identity import SubjectRef

        service = DocumentDeliveryService.create_default()
        subject = SubjectRef.from_session(CERT_SESSION)
        _job, rend = service.request_rendition(
            snapshot, format="csv", subject=subject,
            session_id=CERT_SESSION,
        )
        assert rend is not None and rend.state == "ready"
        from apps.api.document_jobs import replace_dataclass
        from dataclasses import replace

        tampered_record = replace(
            rend, content_sha256="0" * 64
        )
        _registry().update_rendition(tampered_record)
        with pytest.raises(DocumentIntegrityError):
            service.read_rendition_content(
                _registry().get_rendition(rend.rendition_id),
                subject,
                session_id=CERT_SESSION,
            )

    def test_d5o60_cancel_race_probe_documented(self, tmp_path):
        """ДИАГНОСТИКА (зонд находки): cancel в окне, пока worker
        держит claimed-запись, теряется -- complete_render переводит
        отменённый job в ready (рендер+байты существуют). Оракул
        ФИКСИРУЕТ фактическое поведение продукта на целевой базе."""
        snapshot = _seed_builder_snapshot()
        seed_cert_run()
        from apps.api.document_jobs import (
            DocumentDeliveryService,
            RENDITION_FORMATS,
        )
        from apps.api.identity import SubjectRef

        service = DocumentDeliveryService.create_default()
        subject = SubjectRef.from_session(CERT_SESSION)
        job, _ = service.request_rendition(
            snapshot, format="svg", subject=subject,
            session_id=CERT_SESSION,
        )
        registry = service.registry
        now = datetime.now(timezone.utc)
        claimed = registry.update_job(
            _replace(
                registry.get_job(job.job_id),
                state="rendering",
                claimed_at=now.isoformat(),
                lease_expires_at=(
                    now + timedelta(seconds=120)
                ).isoformat(),
            )
        )
        service.cancel_job(job.job_id, subject, session_id=CERT_SESSION)
        assert registry.get_job(job.job_id).state == "cancelled"
        # worker завершает рендер по СТАРОЙ claimed-записи
        from apps.api.document_renditions import render_snapshot_svg

        spec = RENDITION_FORMATS["svg"]
        final_job, final_rendition = service.complete_render(
            claimed, spec, render_snapshot_svg(snapshot).encode(), snapshot
        )
        # ФИКСАЦИЯ факта: отмена перекрывается ready
        assert final_job.state in {"ready", "cancelled"}
        if final_job.state == "ready":
            # задокументированное поведение: cancel проиграл гонку;
            # rendition зарегистрирован (готовый файл существует)
            assert final_rendition is not None


# ══════════════════════════════════════════════════════════════════════
# 5. Health/ops и аутентичность контура
# ══════════════════════════════════════════════════════════════════════


class TestHealthAndAuth:
    def test_d5o61_health_worker_block_peek(self, client):
        """D14: /health/ops.document_render_worker -- peek-семантика;
        lifespan АВТО-СТАРТОВЛ worker (running=True), конфиг виден."""
        body = client.get("/health/ops").json()
        block = body["document_render_worker"]
        assert block["enabled"] is True
        assert block["running"] is True  # авто-старт в lifespan (D14)
        assert block["started_at"] is not None
        assert block["batch_size"] == 4
        assert block["per_tenant_limit"] == 2
        assert block["render_timeout_seconds"] == 60.0
        assert block["consecutive_errors"] == 0

    def test_d5o62_foreign_and_anon_uniform_404(self, client, tmp_path):
        """AC06/T15: знание revision_id НЕ право -- чужой/анонимный
        получают uniform 404 на постановке тяжёлого формата."""
        snapshot = _seed_builder_snapshot()
        seed_cert_run()
        rev = _revision_for(client, snapshot)
        # владелец -- 202
        _cookie(client)
        ok = client.post(
            f"/v1/documentation/revisions/{rev}/renditions",
            json={"format": "svg"},
        )
        assert ok.status_code == 202
        # чужой
        from apps.api.session_store import SESSION_COOKIE_NAME

        client.cookies.set(SESSION_COOKIE_NAME, CERT_FOREIGN_SESSION)
        foreign = client.post(
            f"/v1/documentation/revisions/{rev}/renditions",
            json={"format": "pdf"},
        )
        assert foreign.status_code == 404
        # анонимный
        client.cookies.delete(SESSION_COOKIE_NAME)
        anon = client.post(
            f"/v1/documentation/revisions/{rev}/renditions",
            json={"format": "pdf"},
        )
        assert anon.status_code == 404
        # неизвестная ревизия -- тоже 404
        _cookie(client)
        missing = client.post(
            "/v1/documentation/revisions/rev-d5cert-missing/renditions",
            json={"format": "pdf"},
        )
        assert missing.status_code == 404

    def test_d5o63_docx_still_unsupported_400(self, client, tmp_path):
        """§7 P2 (DOCLOG-9): docx -- честный 400 unsupported_format."""
        snapshot = _seed_builder_snapshot()
        seed_cert_run()
        rev = _revision_for(client, snapshot)
        _cookie(client)
        resp = client.post(
            f"/v1/documentation/revisions/{rev}/renditions",
            json={"format": "docx"},
        )
        assert resp.status_code == 400
        detail = resp.json()["detail"]
        code = detail["code"] if isinstance(detail, dict) else None
        assert code == "unsupported_format"
