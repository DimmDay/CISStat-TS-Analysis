# scripts/doclogcert/test_e2cert_oracle_unit.py
"""DOCLOG-CERT: unit-оракулы сквозной приёмки (свои данные, свой
namespace). Покрывают §20: AC01 (честные refs/gaps), AC02/AC09
(заморозка и идемпотентность снимка), AC03 (паритет фактов форматов),
AC07 (bound-hash согласование), AC08/AC09 (worker: lease/retry/fail),
AC11 (telemetry resilience, mandatory audit fail-closed), AC12/AC15
(честные метрики и vintages мониторинга), §15.1 (гранты/доступ),
DOCLOG-9 (профиль/валидатор/подпись), §16 (retention/hold), AC04
(публикация переживает утрату TTL-сессии)."""
from __future__ import annotations

import hashlib
import io
import json
import zipfile
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone

import pytest

from .conftest import (
    CTX_A,
    FORECAST_POINTS,
    RUN_A,
    RUN_B,
    SESSION_A,
    SESSION_B,
    SUBJECT_ADMIN,
    SUBJECT_LOGS,
    SUBJECT_NOSCOPE,
    TENANT_2,
    build_comparison,
    build_snapshot,
    ensure_revision,
    monitoring_service,
    now_iso,
    register_batch,
    request_heavy_rendition,
    run_worker_once,
    seed_event,
    seed_forecast,
    seed_run,
    subject_of,
)


# ══════════════════════════════════════════════════════════════════════
# AC01/§6: каталог видов D01-D12
# ══════════════════════════════════════════════════════════════════════


class TestKindCatalog:
    def test_catalog_twelve_kinds_d01_d12(self):
        from apps.api.report_snapshot import DOCUMENT_KINDS

        assert list(DOCUMENT_KINDS) == [f"D{n:02d}" for n in range(1, 13)]
        assert DOCUMENT_KINDS["D12"] == (
            "forecast_vs_actual",
            "Сверка прогноза с фактом",
            None,
        )
        assert DOCUMENT_KINDS["D11"][0] == "final_report"

    def test_alias_resolution_unknown_rejected(self):
        from apps.api.report_snapshot import resolve_kinds

        assert resolve_kinds(["forecast_release"]) == ["D08"]
        assert resolve_kinds(["D02", "source_passport"]) == ["D02"]
        with pytest.raises(ValueError):
            resolve_kinds(["D99"])
        with pytest.raises(ValueError):
            resolve_kinds([])


# ══════════════════════════════════════════════════════════════════════
# AC02/AC09: заморозка и идемпотентность снимка
# ══════════════════════════════════════════════════════════════════════


class TestSnapshotFreezeContract:
    def test_idempotent_rebuild_same_state_same_snapshot(self):
        seed_run()
        seed_event()
        snap1, created1 = _build_with_flag(kinds=["D02"])
        snap2, created2 = _build_with_flag(kinds=["D02"])
        assert created1 is True and created2 is False
        assert snap1.snapshot_id == snap2.snapshot_id
        records = _snapshot_records()
        assert len([r for r in records if r.kinds == ["D02"]]) == 1

    def test_explicit_key_different_body_conflict_409_semantics(self):
        seed_run()
        seed_event()
        from apps.api.report_snapshot import SnapshotIdempotencyConflictError
        from apps.api.snapshot_builder import SnapshotService

        subject = subject_of(SESSION_A)
        service = SnapshotService.create_default()
        service.build_snapshot(
            RUN_A, subject, session_id=SESSION_A,
            kinds=["D02"], idempotency_key="e2c-key-1",
        )
        with pytest.raises(SnapshotIdempotencyConflictError):
            service.build_snapshot(
                RUN_A, subject, session_id=SESSION_A,
                kinds=["D02", "D08"], idempotency_key="e2c-key-1",
            )

    def test_memory_registry_conflict_gate_direct(self):
        """Гейт реестра (защита в глубину): регистрация снимка с занятым
        idempotency_key и ДРУГИМ отпечатком -- SnapshotIdempotencyConflictError
        на уровне самого реестра (service-гейт затеняет его через API,
        но контракт реестра публичен -- предрегистрация DOCLOG-CERT)."""
        seed_run()
        seed_event()
        from apps.api.report_snapshot import (
            ReportSnapshot,
            SnapshotIdempotencyConflictError,
        )
        from apps.api.report_snapshot import get_snapshot_registry

        base = dict(
            research_run_id=RUN_A,
            context_id=CTX_A,
            data_revision=3,
        )
        snap_a = ReportSnapshot(
            snapshot_id="rs-e2cgate0000000000000000000001",
            idempotency_key="e2c-gate-key",
            request_fingerprint="fp-a",
            **base,
        )
        snap_b = ReportSnapshot(
            snapshot_id="rs-e2cgate0000000000000000000002",
            idempotency_key="e2c-gate-key",
            request_fingerprint="fp-b",
            **base,
        )
        registry = get_snapshot_registry()
        registered, created = registry.register_snapshot(snap_a, [])
        assert created is True
        with pytest.raises(SnapshotIdempotencyConflictError):
            registry.register_snapshot(snap_b, [])

    def test_snapshot_pins_knowledge_version(self):
        seed_run()
        seed_event()
        from apps.api.report_snapshot import knowledge_registry_version

        snapshot = build_snapshot(kinds=["D02"])
        expected = knowledge_registry_version()
        assert snapshot.knowledge_version == expected
        assert snapshot.knowledge_version is not None  # реестр в комплекте

    def test_dangling_ref_honest_unknown_not_fabricated(self):
        seed_run()
        seed_event(result_ref={"artifact_id": "art-e2c-nonexistent-0001"})
        snapshot = build_snapshot(kinds=["D02"])
        section = _section(snapshot, "D02")
        claims = section["claims"]
        assert claims, "секция D02 без claims недопустима"
        assert any(
            c.get("validity") == "unknown" for c in claims
        ), f"честный unknown не найден: {claims}"

    def test_corrupted_artifact_bytes_honest_t8_unknown(self, monkeypatch):
        seed_run()
        seed_forecast()
        from apps.api.artifact_store import get_artifact_object_store

        def _broken_read(storage_key):
            return b"tampered-bytes-not-json"

        monkeypatch.setattr(
            get_artifact_object_store(), "read_bytes", _broken_read
        )
        snapshot = build_snapshot(kinds=["D08"])
        section = _section(snapshot, "D08")
        assert any(
            c.get("validity") == "unknown" and "повреждены" in c.get("text", "")
            for c in section["claims"]
        ), "T8-отказ не отражён честным unknown-claim"

    def test_snapshot_payload_frozen_after_new_events(self):
        """AC02: замороженный снимок не смешивает контексты -- новые
        события run не меняют уже собранный payload."""
        seed_run()
        seed_event(payload={"dataset": "e2c-v1"})
        snapshot = build_snapshot(kinds=["D02"])
        payload_before = snapshot.to_dict()
        seed_event(payload={"dataset": "e2c-v2-after-freeze"})
        assert snapshot.to_dict() == payload_before


# ══════════════════════════════════════════════════════════════════════
# AC03: паритет фактов форматов + AC16: безопасность вывода
# ══════════════════════════════════════════════════════════════════════


DATASET_TEXT = "=HYPERLINK('http://evil.example','клик')"
SCRIPT_TEXT = "<script>alert(1)</script>javascript:alert(2)"


class TestCrossFormatFactParity:
    def _snapshot(self):
        seed_run()
        seed_event(payload={"name": "e2c-датасет-безопасный"})
        seed_forecast()
        return build_snapshot(kinds=["D02", "D08"])

    def test_claim_texts_present_in_all_p0_formats(self):
        from apps.api.document_renditions import (
            render_snapshot_csv,
            render_snapshot_html,
            render_snapshot_json,
            render_snapshot_jsonl,
            render_snapshot_markdown,
        )

        snapshot = self._snapshot()
        # Первый claim D02 от события upload_completed -- безопасный
        # текст «Загружен датасет ...» (малиновые тексты -- в
        # TestOutputSafety, там экранирование проверяется отдельно).
        texts = [c["text"] for c in snapshot.sections[0]["claims"]]
        safe = next(t for t in texts if "Загружен датасет" in t)
        assert safe

        json_bytes = render_snapshot_json(snapshot)
        jsonl_text = render_snapshot_jsonl(snapshot)
        md_text = render_snapshot_markdown(snapshot)
        html_text = render_snapshot_html(snapshot)
        csv_text = render_snapshot_csv(snapshot)

        parsed = json.loads(json_bytes.decode("utf-8"))
        rendered_texts = [
            c["text"] for c in parsed["sections"][0]["claims"]
        ]
        assert rendered_texts == texts
        jsonl_texts = [
            json.loads(line)["text"]
            for line in jsonl_text.strip().splitlines()
        ]
        assert safe in jsonl_texts
        assert safe in md_text
        assert safe in html_text
        assert safe in csv_text

    def test_format_byte_hashes_differ(self):
        from apps.api.document_renditions import (
            render_snapshot_csv,
            render_snapshot_html,
            render_snapshot_json,
            render_snapshot_markdown,
        )

        snapshot = self._snapshot()
        hashes = {
            "json": hashlib.sha256(render_snapshot_json(snapshot)).hexdigest(),
            "md": hashlib.sha256(
                render_snapshot_markdown(snapshot).encode()
            ).hexdigest(),
            "html": hashlib.sha256(
                render_snapshot_html(snapshot).encode()
            ).hexdigest(),
            "csv": hashlib.sha256(
                render_snapshot_csv(snapshot).encode()
            ).hexdigest(),
        }
        assert len(set(hashes.values())) == len(hashes)


class TestOutputSafety:
    @staticmethod
    def _crafted_snapshot(claim_text: str):
        """Минимальный снимок с ОДНИМ злонамеренным claim-текстом
        (спецификация AC16: renderer обязан нейтрализовать опасное
        содержимое Frozen-данных, а не доверять им)."""
        from apps.api.report_snapshot import ReportSnapshot

        return ReportSnapshot(
            snapshot_id="rs-e2csafe0000000000000000000000",
            research_run_id=RUN_A,
            sections=[
                {
                    "code": "D02",
                    "kind": "source_passport",
                    "title": "Паспорт источника",
                    "methodology_stage": "upload",
                    "claims": [
                        {
                            "text": claim_text,
                            "event_refs": [],
                            "result_refs": [],
                            "validity": "current",
                            "evidence_level": "server_result",
                        }
                    ],
                }
            ],
        )

    def test_csv_formula_injection_neutralized(self):
        from apps.api.document_renditions import render_snapshot_csv

        snapshot = self._crafted_snapshot(DATASET_TEXT)
        csv_text = render_snapshot_csv(snapshot)
        assert "'=HYPERLINK" in csv_text, (
            "опасный префикс формулы не нейтрализован апострофом"
        )
        for line in csv_text.splitlines():
            first_cell = line.split(",")[0]
            assert not first_cell.startswith("="), line

    def test_csv_text_cell_prefixes_honest(self):
        from apps.api.document_renditions import _csv_text

        assert _csv_text("=cmd").startswith("'")
        assert _csv_text("+1cmd").startswith("'")
        assert _csv_text("@x").startswith("'")
        assert _csv_text("-5").startswith("'")  # текстовая ячейка
        assert _csv_text("обычный текст") == "обычный текст"

    def test_html_escapes_script_and_uri(self):
        from apps.api.document_renditions import render_snapshot_html

        snapshot = self._crafted_snapshot(SCRIPT_TEXT)
        html_text = render_snapshot_html(snapshot)
        assert "<script>" not in html_text
        assert "javascript:" not in html_text
        assert "&lt;script&gt;" in html_text

    def test_evidence_zip_no_traversal_manifest_honest(self):
        from apps.api.document_renditions import render_evidence_zip

        seed_run()
        seed_event()
        seed_forecast()
        snapshot = build_snapshot(kinds=["D02", "D08"])
        raw = render_evidence_zip(snapshot)
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            names = archive.namelist()
            assert all(not name.startswith("/") for name in names)
            assert all(".." not in name for name in names)
            assert "manifest.json" in names and "report.json" in names
            manifest = json.loads(archive.read("manifest.json"))
            assert manifest["data_included"] is False
            assert manifest["reproducibility"] == "limited"
            member_names = [m["name"] for m in manifest["members"]]
            assert member_names == [
                "report.json", "document.md", "table_claims.csv",
                "chart_claims.svg", "table_schema.json",
            ]
            for member in manifest["members"]:
                raw_member = archive.read(member["name"])
                assert (
                    hashlib.sha256(raw_member).hexdigest()
                    == member["sha256"]
                )


def _build_with_flag(kinds: list[str]):
    from apps.api.snapshot_builder import SnapshotService

    snapshot, created = SnapshotService.create_default().build_snapshot(
        RUN_A,
        subject_of(SESSION_A),
        session_id=SESSION_A,
        kinds=kinds,
    )
    return snapshot, created


def _snapshot_records():
    from apps.api.report_snapshot import peek_snapshot_registry

    return peek_snapshot_registry().list_records(RUN_A)


def _section(snapshot, code: str) -> dict:
    for section in snapshot.sections:
        if section["code"] == code:
            return section
    raise AssertionError(f"секция {code} отсутствует")


# ══════════════════════════════════════════════════════════════════════
# AC08/AC09: worker -- lease, crash, retry
# ══════════════════════════════════════════════════════════════════════


class TestWorkerCrashSemantics:
    def _queued_job(self, fmt: str = "xlsx"):
        seed_run()
        seed_event()
        snapshot = build_snapshot(kinds=["D02"])
        _service, job, _rendition = request_heavy_rendition(
            snapshot, fmt=fmt
        )
        return snapshot, job

    def test_lease_reclaim_resets_to_queued_without_attempt_growth(self):
        from apps.api.document_jobs import get_document_registry
        from apps.api.document_render_worker import DocumentRenderWorker

        _snapshot, job = self._queued_job()
        registry = get_document_registry()
        past = (datetime.now(timezone.utc) - timedelta(seconds=30)).isoformat()
        registry.update_job(
            replace(
                job,
                state="rendering",
                attempt=1,
                claimed_at=past,
                lease_expires_at=past,
                tenant_id="tenant-default",
            )
        )
        worker = DocumentRenderWorker(interval=None)
        report = worker.run_once()
        reclaimed_job = registry.get_job(job.job_id)
        assert report["ready"] == 1, "после реклейма рендер должен пройти"
        assert reclaimed_job.state == "ready"
        assert reclaimed_job.attempt == 1, "реклейм не растит attempt (AC08)"

    def test_foreign_live_lease_not_reclaimed(self):
        from apps.api.document_jobs import get_document_registry
        from apps.api.document_render_worker import DocumentRenderWorker

        _snapshot, job = self._queued_job()
        registry = get_document_registry()
        future = (
            datetime.now(timezone.utc) + timedelta(seconds=120)
        ).isoformat()
        registry.update_job(
            replace(
                job,
                state="rendering",
                claimed_at=now_iso(),
                lease_expires_at=future,
                tenant_id="tenant-default",
            )
        )
        DocumentRenderWorker(interval=None).run_once()
        assert registry.get_job(job.job_id).state == "rendering"

    def test_crash_render_honest_failed_no_ready_rendition(self, monkeypatch):
        from apps.api import document_jobs
        from apps.api.document_jobs import get_document_registry
        from apps.api.document_render_worker import DocumentRenderWorker

        _snapshot, job = self._queued_job()

        def _boom(*args, **kwargs):
            raise RuntimeError("e2c render crash")

        monkeypatch.setattr(
            document_jobs, "render_snapshot_xlsx", _boom
        )
        # render_failed -- transient: requeue до исчерпания попыток;
        # max_attempts=1 -> requeue (attempt 0->1), затем terminal failed.
        # request_rendition ставит job с attempt=1; requeue растит до 2;
        # max_attempts=2 -> первая неудача requeue, вторая terminal failed.
        worker = DocumentRenderWorker(interval=None, max_attempts=2)
        first = worker.run_once()
        assert first["requeued"] == 1
        report = worker.run_once()
        registry = get_document_registry()
        failed = registry.get_job(job.job_id)
        assert failed.state == "failed"
        assert failed.error_code == "render_failed"
        renditions = registry.list_renditions(job.snapshot_id)
        assert not [r for r in renditions if r.state == "ready"]
        assert report["failed"] == 1

    def test_retry_limit_exceeded_honest(self):
        from apps.api.document_jobs import (
            MAX_JOB_ATTEMPTS,
            DocumentRetryLimitExceeded,
            get_document_registry,
        )

        seed_run()
        seed_event()
        snapshot = build_snapshot(kinds=["D02"])
        registry = get_document_registry()
        for _ in range(MAX_JOB_ATTEMPTS):
            registry.register_job(_failed_job_stub(snapshot))
        with pytest.raises(DocumentRetryLimitExceeded):
            _service, _job, _rend = request_heavy_rendition(
                snapshot, fmt="xlsx"
            )


def _failed_job_stub(snapshot):
    """Честный failed-предшественник той же цели (для retry-лимита)."""
    from apps.api.document_jobs import DocumentJobRecord, new_job_id

    return DocumentJobRecord(
        job_id=new_job_id(),
        run_id=snapshot.research_run_id,
        snapshot_id=snapshot.snapshot_id,
        format="xlsx",
        state="failed",
        error_code="render_failed",
        attempt=1,
        tenant_id="tenant-default",
        created_by=subject_of(SESSION_A).subject_id,
    )


# ══════════════════════════════════════════════════════════════════════
# AC11: telemetry resilience + mandatory audit fail-closed
# ══════════════════════════════════════════════════════════════════════


class _BrokenSink:
    def write(self, record) -> bool:
        raise RuntimeError("e2c collector down")

    def readiness_probe(self) -> dict:
        return {"ok": False, "backend": "broken"}


class _FalseSink:
    def write(self, record) -> bool:
        return False

    def readiness_probe(self) -> dict:
        return {"ok": False, "backend": "false"}


class TestTelemetryResilience:
    def test_raising_sink_does_not_break_emit_loss_visible(self):
        from apps.api.telemetry import emit, set_telemetry_sink_for_testing, _pipeline

        pipeline = _pipeline
        pipeline.set_sink(_BrokenSink())
        try:
            result = emit(
                "e2cert.resilience_probe",
                "info",
                message_template="e2c resilience probe",
            )
            assert result is False, "запись при сломанном sink не может пройти"
        finally:
            pipeline.set_sink(None)
        counters = pipeline.counters()
        visible = sum(
            value
            for name, value in counters.items()
            if name
            in (
                "telemetry_dropped_total",
                "telemetry_sink_failures_total",
                "telemetry_spool_total",
                "telemetry_emergency_total",
            ) or "dropped" in name or "spool" in name
        )
        assert visible >= 1, f"потеря записи невидима: {counters}"

    def test_false_sink_counts_dropped(self):
        from apps.api.telemetry import emit, set_telemetry_sink_for_testing, _pipeline

        pipeline = _pipeline
        pipeline.set_sink(_FalseSink())
        try:
            emit(
                "e2cert.false_sink_probe",
                "info",
                message_template="e2c false sink probe",
            )
        finally:
            pipeline.set_sink(None)
        assert pipeline.counters().get("telemetry_dropped_total", 0) >= 1

    def test_recovery_after_collector_restored(self):
        from apps.api.telemetry import emit, set_telemetry_sink_for_testing, _pipeline

        pipeline = _pipeline
        pipeline.set_sink(_BrokenSink())
        try:
            emit("e2cert.spool_probe", "info", message_template="e2c probe")
        finally:
            pipeline.set_sink(None)
        ok = emit("e2cert.recovery_probe", "info", message_template="ok")
        assert ok is True


class TestMandatoryAuditFailClosed:
    def test_approve_fails_closed_on_broken_sink(self, monkeypatch):
        from apps.api import security_audit
        from apps.api.document_lifecycle import DocumentLifecycleService
        from apps.api.security_audit import MandatoryAuditFailure

        seed_run()
        seed_event()
        snapshot = build_snapshot(kinds=["D02"])
        _document, revision = ensure_revision(snapshot)
        service = DocumentLifecycleService.create_default()
        subject = subject_of(SESSION_A)
        service.request_approval(
            revision.revision_id, subject, session_id=SESSION_A
        )

        class _Broken:
            def append(self, record) -> bool:
                raise RuntimeError("audit down")

        monkeypatch.setattr(
            security_audit, "get_audit_sink", lambda: _Broken()
        )
        with pytest.raises(MandatoryAuditFailure):
            service.decide_approval(
                revision.revision_id,
                subject,
                session_id=SESSION_A,
                decision="approve",
                reason="e2cert",
            )
        assert service.registry.latest_approval(revision.revision_id) is None

    def test_false_sink_mandatory_fails_closed(self, monkeypatch):
        from apps.api import security_audit
        from apps.api.document_lifecycle import DocumentLifecycleService
        from apps.api.security_audit import MandatoryAuditFailure

        seed_run()
        seed_event()
        snapshot = build_snapshot(kinds=["D02"])
        _document, revision = ensure_revision(snapshot)
        service = DocumentLifecycleService.create_default()
        subject = subject_of(SESSION_A)
        service.request_approval(
            revision.revision_id, subject, session_id=SESSION_A
        )

        class _Silent:
            def append(self, record) -> bool:
                return False  # sink «молча проглотил» -- запись НЕ зафиксирована

        monkeypatch.setattr(
            security_audit, "get_audit_sink", lambda: _Silent()
        )
        with pytest.raises(MandatoryAuditFailure):
            service.decide_approval(
                revision.revision_id,
                subject,
                session_id=SESSION_A,
                decision="approve",
                reason="e2cert",
            )
        assert service.registry.latest_approval(revision.revision_id) is None

    def test_standard_audit_failure_does_not_break_read(self, monkeypatch):
        from apps.api import security_audit
        from apps.api.document_jobs import DocumentDeliveryService

        seed_run()
        seed_event()
        snapshot = build_snapshot(kinds=["D02"])
        ensure_revision(snapshot)

        class _Broken:
            def append(self, record) -> bool:
                raise RuntimeError("audit down")

        monkeypatch.setattr(
            security_audit, "get_audit_sink", lambda: _Broken()
        )
        docs = DocumentDeliveryService.create_default().list_documents(
            RUN_A, subject_of(SESSION_A), session_id=SESSION_A
        )
        assert docs, "чтение не должно ломаться от standard-аудита (AC05)"


# ══════════════════════════════════════════════════════════════════════
# AC12/AC15/§6.1: мониторинг -- честные метрики и vintages
# ══════════════════════════════════════════════════════════════════════


class TestMonitoringHonesty:
    def test_units_mismatch_rejected_without_conversion(self):
        from apps.api.monitoring import MonitoringUnitsMismatchError

        seed_run()
        artifact = seed_forecast()
        batch = register_batch(units="tons")
        with pytest.raises(MonitoringUnitsMismatchError):
            build_comparison(
                artifact=artifact, batch=batch, forecast_units="percent"
            )

    def test_units_mismatch_rejected_with_zero_factor(self):
        from apps.api.monitoring import MonitoringValidationError

        seed_run()
        artifact = seed_forecast()
        batch = register_batch(units="tons")
        with pytest.raises(MonitoringValidationError):
            build_comparison(
                artifact=artifact,
                batch=batch,
                forecast_units="percent",
                units_conversion={"factor": 0.0, "note": "e2c"},
            )

    def test_units_unknown_honest_not_as_is(self):
        seed_run()
        artifact = seed_forecast()  # units в артефакте не объявлены
        batch = register_batch(units="percent")
        record = build_comparison(artifact=artifact, batch=batch)
        assert record.units_check == "unknown"
        assert "не объявлены" in (record.units_note or "")

    def test_immature_horizons_excluded_explicitly_not_zero_error(self):
        seed_run()
        artifact = seed_forecast()  # Sep-Dec 2026
        batch = register_batch(
            periods=[("2026-09-01", 4.8), ("2026-10-01", 6.1)],
            as_of="2026-10-15T00:00:00+00:00",
        )
        record = build_comparison(artifact=artifact, batch=batch)
        result = record.result
        pairs = result["pairs"]
        assert len(pairs) == 2
        assert result["alignment"]["excluded_labels"] == [
            "2026-11-01", "2026-12-01"
        ]
        assert result["alignment"]["out_of_horizon_labels"] == []
        for pair in pairs:
            assert pair["absolute_error"] is not None
        assert result["aggregates"]["mae_reason"] is None

    def test_out_of_horizon_fact_labeled_not_in_pairs(self):
        seed_run()
        artifact = seed_forecast()  # Sep-Dec 2026
        batch = register_batch(
            periods=[("2026-10-01", 6.0), ("2027-01-01", 3.0)],
            as_of="2027-01-05T00:00:00+00:00",
        )
        record = build_comparison(artifact=artifact, batch=batch)
        result = record.result
        assert "2027-01-01" in result["alignment"]["out_of_horizon_labels"]
        assert all(p["date"] != "2027-01-01" for p in result["pairs"])

    def test_zero_actual_honest_nulls(self):
        seed_run()
        artifact = seed_forecast()
        batch = register_batch(
            periods=[("2026-09-01", 0.0), ("2026-10-01", 6.1)],
            as_of="2026-10-15T00:00:00+00:00",
        )
        record = build_comparison(artifact=artifact, batch=batch)
        pairs = record.result["pairs"]
        zero_pair = next(p for p in pairs if p["date"] == "2026-09-01")
        assert zero_pair["ape"] is None
        assert zero_pair["ape_undefined_reason"] == "actual_zero"
        aggregates = record.result["aggregates"]
        assert aggregates["mape"] is None
        assert aggregates["mape_reason"] is not None

    def test_mase_null_without_scale(self):
        seed_run()
        artifact = seed_forecast()
        batch = register_batch()
        record = build_comparison(artifact=artifact, batch=batch)
        aggregates = record.result["aggregates"]
        assert aggregates["mase"] is None
        assert aggregates["mase_reason"] == "mase_scale_required"

    def test_mase_invalid_scale_rejected(self):
        from apps.api.monitoring import MonitoringValidationError

        seed_run()
        artifact = seed_forecast()
        batch = register_batch()
        with pytest.raises(MonitoringValidationError):
            build_comparison(
                artifact=artifact, batch=batch, mase_scale=-1.0
            )

    def test_new_vintage_freezes_old_comparison(self):
        seed_run()
        artifact = seed_forecast()
        batch1 = register_batch(
            periods=[("2026-09-01", 4.8), ("2026-10-01", 6.1)],
            as_of="2026-10-15T00:00:00+00:00",
            idempotency_key="e2c-batch-1",
        )
        service = monitoring_service()
        cmp1, _c1 = service.build_comparison(
            RUN_A, subject_of(SESSION_A),
            forecast_artifact_id=artifact.artifact_id,
            actual_batch_id=batch1.batch_id,
            idempotency_key="e2c-cmp-1",
        )
        frozen_pairs = cmp1.result["pairs"]
        batch2 = register_batch(
            periods=[("2026-09-01", 9.9), ("2026-10-01", 9.9)],
            as_of="2026-11-15T00:00:00+00:00",
            idempotency_key="e2c-batch-2",
        )
        cmp2, _c2 = service.build_comparison(
            RUN_A, subject_of(SESSION_A),
            forecast_artifact_id=artifact.artifact_id,
            actual_batch_id=batch2.batch_id,
            idempotency_key="e2c-cmp-2",
        )
        assert cmp2.comparison_id != cmp1.comparison_id
        reread = service.get_comparison(
            RUN_A, subject_of(SESSION_A), cmp1.comparison_id
        )
        assert reread.result["pairs"] == frozen_pairs
        assert reread.result["pairs"][0]["actual_value"] == 4.8

    def test_idempotent_comparison_same_key_same_body(self):
        seed_run()
        artifact = seed_forecast()
        batch = register_batch(idempotency_key="e2c-batch-3")
        service = monitoring_service()
        rec1, created1 = service.build_comparison(
            RUN_A, subject_of(SESSION_A),
            forecast_artifact_id=artifact.artifact_id,
            actual_batch_id=batch.batch_id,
            idempotency_key="e2c-cmp-3",
        )
        rec2, created2 = service.build_comparison(
            RUN_A, subject_of(SESSION_A),
            forecast_artifact_id=artifact.artifact_id,
            actual_batch_id=batch.batch_id,
            idempotency_key="e2c-cmp-3",
        )
        assert created1 is True and created2 is False
        assert rec1.comparison_id == rec2.comparison_id

    def test_threshold_fact_decision_separate_record(self):
        from apps.api.monitoring import MonitoringValidationError

        seed_run()
        artifact = seed_forecast()
        batch = register_batch()
        service = monitoring_service()
        record, _created = service.build_comparison(
            RUN_A, subject_of(SESSION_A),
            forecast_artifact_id=artifact.artifact_id,
            actual_batch_id=batch.batch_id,
            threshold={"metric": "mae", "operator": ">", "value": 0.1},
        )
        # Порог -- ФАКТ: exceeded; decision_action в сверке всегда null.
        assert record.result["threshold"]["status"] == "exceeded"
        assert record.result["decision_action"] is None
        with pytest.raises(MonitoringValidationError):
            service.record_decision(
                RUN_A, subject_of(SESSION_A),
                comparison_id=record.comparison_id,
                action="investigate",
                rationale="",
            )
        decision = service.record_decision(
            RUN_A, subject_of(SESSION_A),
            comparison_id=record.comparison_id,
            action="investigate",
            rationale="e2c: расхождение требует изучения",
        )
        assert decision.action == "investigate"


# ══════════════════════════════════════════════════════════════════════
# §15.1: support grants + эффективный доступ к журналам
# ══════════════════════════════════════════════════════════════════════


@dataclass
class _PrincipalStub:
    subject_id: str = ""
    tenant_id: str = "tenant-default"
    role: object = None
    scopes: tuple = ()

    @property
    def is_anonymous(self) -> bool:
        return not self.subject_id


class TestSupportGrants:
    def _service(self):
        from apps.api.admin_logs import SupportGrantService

        return SupportGrantService()

    def test_grant_validation_fail_closed(self):
        from apps.api.admin_logs import GrantValidationError

        service = self._service()
        base = dict(
            ticket="E2C-TICKET-1",
            purpose="сквозная приёмка",
            subject_id=SUBJECT_LOGS,
            tenant_id=TENANT_2,
            scopes=("logs.read",),
            ttl_hours=24.0,
            run_id=None,
            created_by=SUBJECT_ADMIN,
        )
        # Успешная валидация: создание возвращает запись (не tuple).
        ok_grant = service.create_grant(**base)
        assert ok_grant.grant_id
        for field, value in (
            ("ticket", ""),
            ("subject_id", "subj-not-hex"),
            ("tenant_id", ""),
            ("ttl_hours", 0),
            ("ttl_hours", 169.0),
        ):
            kwargs = dict(base)
            kwargs[field] = value
            with pytest.raises(GrantValidationError):
                service.create_grant(**kwargs)
        kwargs = dict(base)
        kwargs["scopes"] = ("logs.read", "artifact.data.read")
        with pytest.raises(GrantValidationError):
            service.create_grant(**kwargs)

    def test_grant_scopes_catalog_locked(self):
        from apps.api.admin_logs import GRANT_SCOPES

        assert GRANT_SCOPES == frozenset(
            {"audit.read", "logs.export", "logs.read"}
        )

    def test_grant_lifecycle_create_list_revoke(self):
        service = self._service()
        grant = service.create_grant(
            ticket="E2C-TICKET-2",
            purpose="поддержка инцидента",
            subject_id=SUBJECT_NOSCOPE,
            tenant_id=TENANT_2,
            scopes=("logs.read",),
            ttl_hours=2.0,
            run_id=RUN_A,
            created_by=SUBJECT_ADMIN,
        )
        listed = [
            g
            for g in service.list_grants(include_revoked=True)
            if g.subject_id == SUBJECT_NOSCOPE
        ]
        assert any(g.grant_id == grant.grant_id for g in listed)
        revoked = service.revoke_grant(
            grant.grant_id,
            revoked_by=SUBJECT_ADMIN,
            reason="инцидент закрыт",
        )
        assert revoked.revoked_at
        listed_after = [
            g
            for g in service.list_grants(include_revoked=True)
            if g.subject_id == SUBJECT_NOSCOPE
        ]
        active = [
            g for g in listed_after
            if g.grant_id == grant.grant_id and not g.revoked_at
        ]
        assert not active


class TestEffectiveLogAccess:
    def _access(self, principal):
        from apps.api.admin_logs import resolve_effective_log_access

        return resolve_effective_log_access(principal)

    def test_admin_full_catalog(self):
        access = self._access(
            _PrincipalStub(subject_id=SUBJECT_ADMIN, role="admin")
        )
        assert access.telemetry and access.audit and access.delivery
        assert access.export and access.grants_management

    def test_scope_narrowing_honest(self):
        access = self._access(
            _PrincipalStub(
                subject_id=SUBJECT_LOGS,
                scopes=("logs.read", "audit.read", "logs.export"),
            )
        )
        assert access.telemetry and access.audit and access.export
        assert not access.grants_management

    def test_no_scope_no_access(self):
        access = self._access(_PrincipalStub(subject_id=SUBJECT_NOSCOPE))
        assert not access.telemetry and not access.audit
        assert not access.export and not access.grants_management

    def test_grant_extends_subject_and_revoke_closes(self):
        from apps.api.admin_logs import SupportGrantService

        service = SupportGrantService()
        grant = service.create_grant(
            ticket="E2C-TICKET-3",
            purpose="временная диагностика",
            subject_id=SUBJECT_NOSCOPE,
            tenant_id=TENANT_2,
            scopes=("logs.read", "audit.read", "logs.export"),
            ttl_hours=1.0,
            run_id=None,
            created_by=SUBJECT_ADMIN,
        )
        access = self._access(
            _PrincipalStub(subject_id=SUBJECT_NOSCOPE, tenant_id=TENANT_2)
        )
        assert access.telemetry and access.audit and access.export
        assert TENANT_2 in access.tenants
        service.revoke_grant(
            grant.grant_id, revoked_by=SUBJECT_ADMIN, reason="e2c"
        )
        access_after = self._access(
            _PrincipalStub(subject_id=SUBJECT_NOSCOPE, tenant_id=TENANT_2)
        )
        assert not access_after.telemetry and not access_after.audit


# ══════════════════════════════════════════════════════════════════════
# DOCLOG-9: профиль организации, валидатор, подпись
# ══════════════════════════════════════════════════════════════════════


class TestOrgProfileContract:
    def _service(self):
        from apps.api.doc_profiles import OrgProfileService

        return OrgProfileService.create_default()

    def _admin(self):
        return _PrincipalStub(subject_id=SUBJECT_ADMIN, role="admin")

    def test_create_and_resolve_profile(self):
        service = self._service()
        profile = service.create_profile(
            name="e2c-корпоративный",
            version_no=1,
            format="pdfa",
            subject=self._admin(),
            title_prefix="[E2C]",
            footer_text="Служебный документ e2cert",
            organization="E2C Org",
        )
        resolved = service.resolve_profile(
            profile.profile_id, fmt="pdfa", subject=subject_of(SESSION_A)
        )
        assert resolved.profile_id == profile.profile_id

    def test_resolve_honest_errors(self):
        from apps.api.doc_profiles import (
            OrgProfileFormatMismatch,
            OrgProfileNotFound,
            OrgProfileRetired,
        )

        service = self._service()
        with pytest.raises(OrgProfileNotFound):
            service.resolve_profile(
                "prof-e2c-missing", fmt="pdfa", subject=subject_of(SESSION_A)
            )
        profile = service.create_profile(
            name="e2c-для-отзыва",
            version_no=1,
            format="pdfa",
            subject=self._admin(),
        )
        service.retire_profile(profile.profile_id, self._admin())
        with pytest.raises(OrgProfileRetired):
            service.resolve_profile(
                profile.profile_id, fmt="pdfa", subject=subject_of(SESSION_A)
            )
        profile_docx = service.create_profile(
            name="e2c-docx-профиль",
            version_no=1,
            format="docx",
            subject=self._admin(),
        )
        with pytest.raises(OrgProfileFormatMismatch):
            service.resolve_profile(
                profile_docx.profile_id,
                fmt="pdfa",
                subject=subject_of(SESSION_A),
            )

    def test_policy_admin_required(self):
        from apps.api.doc_profiles import OrgProfileAccessDenied

        service = self._service()
        with pytest.raises(OrgProfileAccessDenied):
            service.create_profile(
                name="e2c-без-прав",
                version_no=1,
                format="pdfa",
                subject=_PrincipalStub(
                    subject_id=SUBJECT_LOGS,
                    scopes=("logs.read", "audit.read", "logs.export"),
                ),
            )

    def test_pdfa_validator_structural_not_by_filename(self):
        from apps.api.doc_profiles import _pdfa_structural_validate
        from apps.api.document_renditions import render_snapshot_pdf

        seed_run()
        seed_event()
        seed_forecast()
        snapshot = build_snapshot(kinds=["D02", "D08"])
        plain_pdf = render_snapshot_pdf(snapshot)
        verdict = _pdfa_structural_validate(plain_pdf)
        assert verdict.result == "failed"
        assert verdict.findings, "отказ без причин недопустим"
        assert any("pdfaid" in f for f in verdict.findings)

    def test_pdfa_validator_accepts_conformant_bytes(self):
        from apps.api.doc_profiles import _pdfa_structural_validate

        conformance_pdf = b"\n".join(
            [
                b"%PDF-1.4",
                b"1 0 obj << /Type /Catalog >> endobj",
                b"2 0 obj << /Type /OutputIntent /S /GTS_PDFA1 "
                b"/DestOutputProfile 3 0 R >> endobj",
                b"3 0 obj << /N 3 >> stream\nfake-icc-acsp\nendstream endobj",
                b"4 0 obj << /Type /Font /FontDescriptor 5 0 R >> endobj",
                b"5 0 obj << /FontFile2 6 0 R >> endobj",
                b"6 0 obj << /Length 4 >> stream\nABCD\nendstream endobj",
                b"7 0 obj << /Type /Metadata /Subtype /XML >> stream\n"
                b"<x:xmpmeta><rdf:RDF><rdf:Description>"
                b"<pdfaid:part>1</pdfaid:part>"
                b"<pdfaid:conformance>B</pdfaid:conformance>"
                b"</rdf:Description></rdf:RDF></x:xmpmeta>"
                b"\nendstream endobj",
                b"%%EOF",
            ]
        )
        verdict = _pdfa_structural_validate(conformance_pdf)
        assert verdict.result == "passed", verdict.findings


class TestSignatureHonesty:
    def test_hmac_signature_roundtrip_and_tamper(self, monkeypatch):
        from apps.api.doc_profiles import (
            sign_content,
            verify_signature_manifest,
        )

        monkeypatch.setenv("CISSTAT_DOC_SIGN_KEY", "e2c-sign-key-secret")
        seed_run()
        seed_event()
        snapshot = build_snapshot(kinds=["D02"])
        content = b"e2cert-content-bytes"
        manifest = sign_content(
            content,
            snapshot_sha256=snapshot.payload_sha256,
            profile_id="prof-e2c-1",
            profile_version_no=1,
            media_type="application/pdf",
            signed_by=SUBJECT_ADMIN,
        )
        assert verify_signature_manifest(content, manifest).result == "passed"
        tampered_content = content + b"tail"
        assert verify_signature_manifest(
            tampered_content, manifest
        ).result == "failed"

    def test_sign_without_key_honest_unavailable(self, monkeypatch):
        from apps.api.doc_profiles import (
            SignatureKeyUnavailable,
            sign_content,
        )

        monkeypatch.delenv("CISSTAT_DOC_SIGN_KEY", raising=False)
        with pytest.raises(SignatureKeyUnavailable):
            sign_content(
                b"bytes",
                snapshot_sha256="0" * 64,
                profile_id="prof-e2c-1",
            )

    def test_verify_without_key_fails_closed(self, monkeypatch):
        """Без ключа верификация невозможна -- честный отказ, не pass."""
        from apps.api.doc_profiles import (
            SignatureKeyUnavailable,
            verify_signature_manifest,
        )

        monkeypatch.delenv("CISSTAT_DOC_SIGN_KEY", raising=False)
        manifest = {"algorithm": "HMAC-SHA256", "mac": "ab" * 32}
        with pytest.raises(SignatureKeyUnavailable):
            verify_signature_manifest(b"bytes", manifest)


# ══════════════════════════════════════════════════════════════════════
# AC07: bound-hash согласование + §16: retention/hold
# ══════════════════════════════════════════════════════════════════════


class TestLifecycleApprovalBinding:
    def test_expected_hash_mismatch_rejected(self):
        from apps.api.document_lifecycle import (
            ApprovalHashMismatchError,
            DocumentLifecycleService,
        )

        seed_run()
        seed_event()
        snapshot = build_snapshot(kinds=["D02"])
        _document, revision = ensure_revision(snapshot)
        service = DocumentLifecycleService.create_default()
        subject = subject_of(SESSION_A)
        service.request_approval(
            revision.revision_id, subject, session_id=SESSION_A
        )
        with pytest.raises(ApprovalHashMismatchError):
            service.decide_approval(
                revision.revision_id,
                subject,
                session_id=SESSION_A,
                decision="approve",
                reason="e2cert",
                expected_snapshot_sha256="0" * 64,
            )

    def test_publish_reverifies_snapshot_hash(self, monkeypatch):
        """AC07 на publish: изменившийся payload_sha256 снимка после
        согласования -- публикация отказана (approval не переносится).
        Прямой путь: подмена отпечатка записи реестра (байты/hash
        расходятся -- путь недостижим через T8-loader, потому пинуется
        оракулом на уровне записи)."""
        from apps.api import report_snapshot
        from apps.api.document_lifecycle import (
            ApprovalNotApplicableError,
            DocumentLifecycleService,
        )

        seed_run()
        seed_event()
        snapshot = build_snapshot(kinds=["D02"])
        _document, revision = ensure_revision(snapshot)
        service = DocumentLifecycleService.create_default()
        subject = subject_of(SESSION_A)
        service.request_approval(
            revision.revision_id, subject, session_id=SESSION_A
        )
        service.decide_approval(
            revision.revision_id, subject,
            session_id=SESSION_A, decision="approve", reason="e2c",
        )
        registry = report_snapshot.peek_snapshot_registry()
        record = registry.get_snapshot_record(snapshot.snapshot_id)
        tampered = replace_record_field(record, payload_sha256="f" * 64)
        # Пин ТОЧНОЙ строки publish-верификации: подмена резолва записи
        # на уровне сервиса (полный путь через T8-loader недостижим --
        # честная граница, задокументирована в акте DOCLOG-CERT).
        monkeypatch.setattr(
            service,
            "_snapshot_record",
            lambda snapshot_id: tampered,
        )
        with pytest.raises(ApprovalNotApplicableError):
            service.publish(
                revision.revision_id, subject, session_id=SESSION_A
            )

    def test_publish_requires_approval(self):
        from apps.api.document_lifecycle import (
            DocumentLifecycleService,
            PublishRequiresApprovalError,
        )

        seed_run()
        seed_event()
        snapshot = build_snapshot(kinds=["D02"])
        _document, revision = ensure_revision(snapshot)
        service = DocumentLifecycleService.create_default()
        with pytest.raises(PublishRequiresApprovalError):
            service.publish(
                revision.revision_id,
                subject_of(SESSION_A),
                session_id=SESSION_A,
            )


class TestOrgProfileMismatchOnTarget:
    def test_ready_target_with_other_profile_conflict(self):
        """§11/DOCLOG-9: одна визуальная форма на цель -- готовая цель
        с ДРУГИМ профилем -- OrgProfileMismatchError (не вторая версия,
        не тихий возврат чужой формы)."""
        from apps.api.doc_profiles import OrgProfileMismatchError
        from apps.api.doc_profiles import OrgProfileService

        seed_run()
        seed_event()
        snapshot = build_snapshot(kinds=["D02"])
        profiles = OrgProfileService.create_default()
        admin = _PrincipalStub(
            subject_id=SUBJECT_ADMIN, role="admin"
        )
        prof_a = profiles.create_profile(
            name="e2c-профиль-А", version_no=1, format="pdfa",
            subject=admin,
        )
        prof_b = profiles.create_profile(
            name="e2c-профиль-Б", version_no=1, format="pdfa",
            subject=admin,
        )
        from apps.api.document_jobs import DocumentDeliveryService
        service = DocumentDeliveryService.create_default()
        subject = subject_of(SESSION_A)
        service.request_rendition(
            snapshot, format="pdfa", subject=subject,
            session_id=SESSION_A, org_profile_id=prof_a.profile_id,
        )
        run_worker_once()  # цель становится готовой (ready)
        with pytest.raises(OrgProfileMismatchError):
            service.request_rendition(
                snapshot, format="pdfa", subject=subject,
                session_id=SESSION_A, org_profile_id=prof_b.profile_id,
            )


class TestRetentionHonesty:
    def test_hold_priority_and_purge_tombstone(self):
        from apps.api.document_jobs import (
            DocumentDeliveryService,
            RenditionPurgedError,
        )
        from apps.api.document_lifecycle import DocumentLifecycleService

        seed_run()
        seed_event()
        snapshot = build_snapshot(kinds=["D02"])
        document, revision = ensure_revision(snapshot)
        _service, _job, _rend = request_heavy_rendition(snapshot, fmt="xlsx")
        run_worker_once()
        delivery = DocumentDeliveryService.create_default()
        ready = [
            r for r in delivery.registry.list_renditions(snapshot.snapshot_id)
            if r.state == "ready"
        ]
        assert ready, "rendition не готова после worker-цикла"
        lifecycle = DocumentLifecycleService.create_default()
        subject = subject_of(SESSION_A)
        # (1) hold приоритетен: purge не трогает документ под hold.
        lifecycle.set_retention(
            document.document_id, subject,
            session_id=SESSION_A, action="hold", reason="e2c hold",
        )
        report_hold = lifecycle.sweep_retention(
            RUN_A, subject, session_id=SESSION_A
        )
        assert report_hold["skipped_hold_documents"] >= 1
        assert report_hold["purged_renditions"] == 0
        # (2) release + устаревшая rendition -> purge -> честный tombstone.
        lifecycle.set_retention(
            document.document_id, subject,
            session_id=SESSION_A, action="release", reason="e2c release",
        )
        rend = delivery.registry.get_rendition(ready[0].rendition_id)
        past = (
            datetime.now(timezone.utc) - timedelta(days=30)
        ).isoformat()
        delivery.registry.update_rendition(
            replace(rend, created_at=past)
        )
        report_sweep = lifecycle.sweep_retention(
            RUN_A, subject, session_id=SESSION_A
        )
        assert report_sweep["purged_renditions"] >= 1
        purged = delivery.registry.get_rendition(ready[0].rendition_id)
        assert purged.state == "purged"
        with pytest.raises(RenditionPurgedError):
            delivery.read_rendition_content(
                purged, subject, session_id=SESSION_A
            )

    def test_published_document_not_swept(self):
        from apps.api.document_jobs import DocumentDeliveryService
        from apps.api.document_lifecycle import DocumentLifecycleService

        seed_run()
        seed_event()
        snapshot = build_snapshot(kinds=["D02"])
        _document, revision = ensure_revision(snapshot)
        _svc, _job, _rend = request_heavy_rendition(snapshot, fmt="xlsx")
        run_worker_once()
        lifecycle = DocumentLifecycleService.create_default()
        subject = subject_of(SESSION_A)
        lifecycle.request_approval(
            revision.revision_id, subject, session_id=SESSION_A
        )
        lifecycle.decide_approval(
            revision.revision_id, subject,
            session_id=SESSION_A, decision="approve", reason="e2c",
        )
        lifecycle.publish(revision.revision_id, subject, session_id=SESSION_A)
        delivery = DocumentDeliveryService.create_default()
        rend = delivery.registry.list_renditions(snapshot.snapshot_id)[0]
        past = (
            datetime.now(timezone.utc) - timedelta(days=30)
        ).isoformat()
        delivery.registry.update_rendition(replace(rend, created_at=past))
        report = lifecycle.sweep_retention(
            RUN_A, subject, session_id=SESSION_A
        )
        assert report["kept_published_documents"] >= 1
        assert report["purged_renditions"] == 0


# ══════════════════════════════════════════════════════════════════════
# AC04: pinned published артефакт переживает утрату TTL-сессии
# ══════════════════════════════════════════════════════════════════════


class TestPublishedSurvivesSessionLoss:
    def test_published_rendition_bytes_survive_session_reset(self):
        from apps.api.document_jobs import DocumentDeliveryService
        from apps.api.document_lifecycle import DocumentLifecycleService
        from apps.api.session_store import reset_session_store_for_testing

        seed_run()
        seed_event()
        snapshot = build_snapshot(kinds=["D02"])
        _document, revision = ensure_revision(snapshot)
        _svc, _job, _rend = request_heavy_rendition(snapshot, fmt="xlsx")
        run_worker_once()
        lifecycle = DocumentLifecycleService.create_default()
        subject = subject_of(SESSION_A)
        lifecycle.request_approval(
            revision.revision_id, subject, session_id=SESSION_A
        )
        lifecycle.decide_approval(
            revision.revision_id, subject,
            session_id=SESSION_A, decision="approve", reason="e2c",
        )
        lifecycle.publish(revision.revision_id, subject, session_id=SESSION_A)
        delivery = DocumentDeliveryService.create_default()
        ready = [
            r for r in delivery.registry.list_renditions(snapshot.snapshot_id)
            if r.state == "ready"
        ]
        content_before = delivery.read_rendition_content(
            ready[0], subject, session_id=SESSION_A
        )
        # Утрата TTL-сессии: store сброшен; субъект восстанавливается
        # детерминированным псевдонимом (restore-континуитет §15.1).
        reset_session_store_for_testing()
        from .conftest import seed_session

        seed_session(SESSION_A)
        content_after = delivery.read_rendition_content(
            ready[0], subject, session_id=SESSION_A
        )
        assert content_after == content_before
        # Состояние публикации не изменилось.
        assert revision_state(revision.revision_id) == "published"

    def test_run_record_and_snapshot_intact_after_session_reset(self):
        from apps.api.research_runs import get_research_run_store
        from apps.api.session_store import reset_session_store_for_testing

        seed_run()
        seed_event()
        snapshot = build_snapshot(kinds=["D02"])
        run_before = get_research_run_store().get_run(RUN_A)
        reset_session_store_for_testing()
        from .conftest import seed_session

        seed_session(SESSION_A)
        run_after = get_research_run_store().get_run(RUN_A)
        assert run_after.owner_subject == run_before.owner_subject
        records = _snapshot_records()
        assert any(r.snapshot_id == snapshot.snapshot_id for r in records)


def replace_record_field(record, **changes):
    from dataclasses import replace as _replace

    return _replace(record, **changes)


def revision_state(revision_id: str) -> str:
    from apps.api.document_lifecycle import DocumentLifecycleService

    return DocumentLifecycleService.create_default().revision_state(
        revision_id
    )
