# scripts/doclogrecheckfixcert/test_cert_oracle_unit.py
"""
Собственные сертификационные оракулы DOCLOG-E2E-RECHECK-1-FIX (аудит
исправлений, база 9401fa5). Дополняют repo-корпус tests/api/
test_doclog_recheck_fix.py по границам, которые тот не покрывает:

  O1 -- sweep-промоушен моделирования (backtest/card/forecast):
        артефакты создаются, повтор -- честные нулевые счётчики
        (идемпотентность AC09 в счётчиках, не только в реестре);
  O2 -- каталог обязательных gaps D02: отсутствие data_ref даёт
        missing_data_artifact даже при наличии паспорта (ось C05);
  O3 -- CAS-гейт #2 (F-D5C1): гонка «cancel во время рендера» --
        готовые байты не выдаются, staged rendition честно failed;
  O4 -- граница промоушена версии данных: 250k строк -- честный
        пропуск (документированная граница fix-модуля).

Namespace дизъюнктен: RUN-RCFCERT*, recheck-cert-*.
"""
from __future__ import annotations

import dataclasses
from types import SimpleNamespace

import pytest


# ══════════════════════════════════════════════════════════════════════
# O1: sweep-промоушен моделирования + идемпотентные счётчики
# ══════════════════════════════════════════════════════════════════════


@pytest.fixture()
def promotion_world(monkeypatch, tmp_path):
    """Изолированный мир промоушена: memory-реестры + фейковая сессия с
    modeling_artifacts (собственные данные, не чужие сиды)."""
    monkeypatch.setenv("CISSTAT_DATA_DIR", str(tmp_path / "rcfcert-data"))
    monkeypatch.setenv("CISSTAT_STORAGE_MODE", "advisory")
    monkeypatch.setenv("CISSTAT_RUNS_BACKEND", "memory")
    monkeypatch.setenv("CISSTAT_ARTIFACTS_BACKEND", "memory")
    monkeypatch.setenv("CISSTAT_IDENTITY_MODE", "session_scoped")
    monkeypatch.setenv("CISSTAT_AUDIT_BACKEND", "memory")
    for name in ("DATABASE_URL", "REDIS_URL"):
        monkeypatch.delenv(name, raising=False)

    from apps.api import artifact_store, research_runs, security_audit

    artifact_store.reset_artifact_registry_for_testing()
    artifact_store.reset_artifact_object_store_for_testing()
    research_runs.reset_research_run_store_for_testing()
    security_audit.reset_audit_for_testing()

    from apps.api.research_runs import ResearchRun, get_research_run_store

    run_id = "RUN-RCFCERT-SWEEP"
    get_research_run_store().upsert_run(
        ResearchRun(
            run_id=run_id,
            owner_subject="recheck-cert-subject",
            tenant_id="recheck-cert-tenant",
            ownership="bound",
        )
    )

    session = SimpleNamespace(
        run_id=run_id,
        current_context_id=lambda: "ctx-rcfcert-sweep",
        data_revision=3,
        target_column="value",
        date_column="date",
        modeling_artifacts={
            "backtests": {"bt-recheck-1": {"metrics": {"mae": 1.5}}},
            "model_cards": {"mc-recheck-1": {"model": "naive"}},
            "forecasts": {"fc-recheck-1": {"horizon": 6}},
        },
        passport_history=[],
    )
    subject = SimpleNamespace(
        is_anonymous=False,
        role="analyst",
        subject_id="recheck-cert-subject",
        tenant_id="recheck-cert-tenant",
        via="api_key",
        scopes=frozenset({"artifacts.write"}),
    )
    request = SimpleNamespace(
        cookies={"cisstat_session": "recheck-cert-cookie"}
    )
    # unit-проба: субъект промоушена фиксируется монкипатчем
    # (единая точка читает его из request; здесь -- владелец рана)
    from apps.api import promotion_integration as _pi

    monkeypatch.setattr(
        _pi, "_promotion_subject", lambda request: subject, raising=True
    )
    yield SimpleNamespace(
        run_id=run_id, session=session, subject=subject, request=request
    )
    from apps.api import artifact_store, research_runs, security_audit

    artifact_store.reset_artifact_registry_for_testing()
    artifact_store.reset_artifact_object_store_for_testing()
    research_runs.reset_research_run_store_for_testing()
    security_audit.reset_audit_for_testing()


def test_o1_modeling_sweep_promotes_three_kinds(promotion_world):
    """Sweep переносит backtest/card/forecast в durable-слой (собственные
    данные сессии, без предзаполненных артефактов)."""
    from apps.api import promotion_integration

    counts = promotion_integration.notify_modeling_artifacts_updated(
        promotion_world.request,
        promotion_world.session,
    )
    assert counts == {"oof_backtest": 1, "model_card": 1, "forecast": 1}, counts
    from apps.api.artifact_store import get_artifact_registry

    kinds = sorted(
        a.kind
        for a in get_artifact_registry().list_artifacts(promotion_world.run_id)
    )
    assert kinds == ["forecast", "model_card", "oof_backtest"], kinds


def test_o1_modeling_sweep_repeat_reports_zero_new(promotion_world):
    """Повторный sweep на том же состоянии: реестр не плодит дублей (AC09),
    а счётчики ЧЕСТНО равны нулю (документированный контракт fix-модуля:
    «счётчики НОВЫХ артефактов»)."""
    from apps.api import promotion_integration

    promotion_integration.notify_modeling_artifacts_updated(
        promotion_world.request, promotion_world.session
    )
    counts = promotion_integration.notify_modeling_artifacts_updated(
        promotion_world.request, promotion_world.session
    )
    assert counts == {"oof_backtest": 0, "model_card": 0, "forecast": 0}, counts
    from apps.api.artifact_store import get_artifact_registry

    assert (
        len(get_artifact_registry().list_artifacts(promotion_world.run_id)) == 3
    )


# ══════════════════════════════════════════════════════════════════════
# O2: обязательный gap data_ref (ось C05, без HTTP-пути)
# ══════════════════════════════════════════════════════════════════════


def test_o2_d02_gap_requires_data_artifact():
    """Каталог обязательных элементов D02: БЕЗ текущего паспорта И без
    data_ref -- оба кода gap присутствуют; удаление одного из них --
    регрессия C05."""
    from apps.api.snapshot_builder import SnapshotService, _BuildCtx

    service = SnapshotService.__new__(SnapshotService)
    ctx = _BuildCtx(
        run="RUN-RCFCERT-GAPS",
        events=[],
        index={"passport": [], "validation_result": [], "correction_recipe": []},
        artifacts_by_id={},
        target_ctx="ctx-rcfcert-gaps",
        target_rev=None,
    )
    # индекс пуст: ни паспорта, ни данных (собственный пустой мир)
    service._mandatory_kind_gaps(ctx, ["D02"], data_ref=None)
    assert "missing_source_passport_artifact" in ctx.missing_mandatory
    assert "missing_data_artifact" in ctx.missing_mandatory

    # паспорт/данные на месте (текущий контекст) -- gaps не выставляются
    ctx2 = _BuildCtx(
        run="RUN-RCFCERT-GAPS2",
        events=[],
        index={},
        artifacts_by_id={},
        target_ctx="ctx-rcfcert-gaps",
        target_rev=None,
    )
    passport = SimpleNamespace(
        artifact_id="art-rcfcert-passport",
        kind="passport",
        context_id="ctx-rcfcert-gaps",
        data_revision=None,
        refs={"stage": "start"},
        panel={},
    )
    ctx2.index = {
        "passport": [passport],
        "validation_result": [],
        "correction_recipe": [],
    }
    ctx2.events = []
    # artifact_validity сверяет context_id артефакта с target_ctx
    service._mandatory_kind_gaps(ctx2, ["D02"], data_ref="art-rcfcert-data")
    assert ctx2.missing_mandatory == [], ctx2.missing_mandatory


# ══════════════════════════════════════════════════════════════════════
# O3: CAS-гейт #2 -- гонка «cancel во время рендера»
# ══════════════════════════════════════════════════════════════════════


def test_o3_cancel_during_render_marks_rendition_failed(tmp_path):
    """Гонка F-D5C1 на середине рендера: cancel приходит ПОСЛЕ входа в
    complete_render (гейт #1 прошёл -- fresh ещё rendering), ДО финальной
    готовности. Гейт #2 обязан: job остаётся cancelled, staged rendition --
    failed («готовые байты не выдаются», паритет fail_render)."""
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
        registry, ArtifactObjectStore(root=str(tmp_path / "o3-objects"))
    )
    job = DocumentJobRecord(
        job_id=new_job_id(),
        run_id="RUN-RCFCERT-CAS2",
        snapshot_id="snap-rcfcert-cas2",
        format="pdf",
        state=JOB_RENDERING,
        attempt=1,
    )
    registry.register_job(job)

    # Симуляция гонки: первый get_job (гейт #1) -- ещё rendering,
    # последующие (гейт #2 и далее) -- уже cancelled.
    real_get_job = registry.get_job
    calls = {"n": 0}

    def racing_get_job(job_id: str):
        calls["n"] += 1
        fetched = real_get_job(job_id)
        if calls["n"] >= 2 and fetched is not None:
            return dataclasses.replace(fetched, state=JOB_CANCELLED)
        return fetched

    registry.get_job = racing_get_job  # type: ignore[method-assign]

    from apps.api.report_snapshot import ReportSnapshot

    snapshot = ReportSnapshot(
        snapshot_id="snap-rcfcert-cas2",
        research_run_id="RUN-RCFCERT-CAS2",
        payload_sha256="c" * 64,
    )
    updated, rendition = service.complete_render(
        job,
        SimpleNamespace(media_type="application/pdf"),
        b"%PDF-1.4 recheck-cert-o3",
        snapshot,
    )
    assert updated.state == JOB_CANCELLED, (
        "гейт #2 пропустил перезапись отмены (F-D5C1)"
    )
    # staged rendition (создан гейтом #1-пропуском) обязан быть failed
    stored = registry.list_renditions("snap-rcfcert-cas2")
    assert stored, "rendition не создан -- ветка гейта #2 не достигнута"
    from apps.api.document_jobs import RENDITION_FAILED

    assert all(
        r.state == RENDITION_FAILED for r in stored
    ), (
        "staged rendition не помечен failed -- байты «висят в очереди»: "
        + ", ".join(r.state for r in stored)
    )


# ══════════════════════════════════════════════════════════════════════
# O4: граница промоушена версии данных (честный пропуск сверхлиста)
# ══════════════════════════════════════════════════════════════════════


def test_o4_data_version_row_limit_honest_skip(promotion_world):
    """Сверхлистный фрейм (>250k строк) -- честный пропуск без артефакта
    и без receipt (документированная граница fix-модуля)."""
    import pandas as pd

    from apps.api import promotion_integration
    from apps.api.artifact_store import get_artifact_registry

    big = pd.DataFrame({"date": range(250_001), "value": range(250_001)})
    session = SimpleNamespace(
        run_id=promotion_world.session.run_id,
        current_context_id=lambda: "ctx-rcfcert-big",
        data_revision=1,
        target_column="value",
        date_column="date",
        dataframe=big,
        passport_history=[],
    )
    result = promotion_integration.notify_data_version_registered(
        promotion_world.request, session, reason="upload"
    )
    assert result is None
    assert get_artifact_registry().list_artifacts(promotion_world.run_id) == []
