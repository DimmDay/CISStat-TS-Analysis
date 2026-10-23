# scripts/doclog5cert/probe_findings.py
"""DOCLOG-5-CERT: строгие зонды НАХОДОК (вне мутационных каналов!).

Эти тесты формулируют ОЖИДАЕМОЕ ПО СПЕКЕ поведение и падают на целевой
базе -- это RED-доказательства находок акта (прецедент DOCLOG-4-CERT:
61 = 57 green + 4 RED). Файл исключён из ORACLE-канала mutations.py
(иначе падающий зонд делал бы каждый мутант ORACLE-ONLY).

F-D5C1 (§17/§18 «отмена»): cancel в окне, пока worker держит
claimed-запись, теряется -- complete_render безусловно переводит job в
READY (рендер+байты+rendition существуют вопреки отмене). Спека §18:
workers имеют «отмену»; §17: cancel идемпотентен. Пользователь,
отменивший задание, получает готовый файл.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from conftest import CERT_RUN_ID, CERT_SESSION, seed_cert_run


@pytest.fixture()
def _env(tmp_path):
    return tmp_path


def _seed():
    from apps.api.snapshot_builder import SnapshotService
    from apps.api.identity import SubjectRef

    seed_cert_run(CERT_RUN_ID, CERT_SESSION)
    snapshot, _created = SnapshotService.create_default().build_snapshot(
        CERT_RUN_ID,
        SubjectRef.from_session(CERT_SESSION),
        session_id=CERT_SESSION,
        kinds=["D01"],
    )
    return snapshot


def test_d5f01_cancel_during_render_must_hold():
    """RED-доказательство F-D5C1: после cancel(rendering) завершение
    worker'а ОБЯЗАНО не переводить job в ready (по спеке). ФАКТ: job
    становится ready, rendition регистрируется."""
    from apps.api.document_jobs import (
        DocumentDeliveryService,
        RENDITION_FORMATS,
    )
    from apps.api.document_renditions import render_snapshot_svg
    from apps.api.identity import SubjectRef

    snapshot = _seed()
    service = DocumentDeliveryService.create_default()
    subject = SubjectRef.from_session(CERT_SESSION)
    job, _ = service.request_rendition(
        snapshot, format="svg", subject=subject, session_id=CERT_SESSION,
    )
    registry = service.registry
    now = datetime.now(timezone.utc)
    claimed = registry.update_job(
        replace_job(
            registry.get_job(job.job_id),
            state="rendering",
            claimed_at=now.isoformat(),
            lease_expires_at=(now + timedelta(seconds=120)).isoformat(),
        )
    )
    service.cancel_job(job.job_id, subject, session_id=CERT_SESSION)
    assert registry.get_job(job.job_id).state == "cancelled"
    # worker завершает рендер по устаревшей claimed-записи
    spec = RENDITION_FORMATS["svg"]
    final_job, final_rendition = service.complete_render(
        claimed, spec, render_snapshot_svg(snapshot).encode(), snapshot
    )
    # ОЖИДАНИЕ ПО СПЕКЕ (падает -- находка F-D5C1):
    assert final_job.state == "cancelled", (
        "F-D5C1: complete_render перезаписал отмену (cancelled) в "
        f"{final_job.state}; rendition={final_rendition is not None}"
    )


def replace_job(job, **changes):
    from apps.api.document_jobs import replace_dataclass

    return replace_dataclass(job, **changes)
