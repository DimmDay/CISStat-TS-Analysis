# scripts/pgv03cert/test_p3cert_findings_evidence.py
#
# PGV-03-CERT — Класс B: RED-свидетельства находок сертификации PGV-03
# (как в PGV-00/01/02-CERT: не xfail/skip -- честные падения на
# сертифицируемом дереве; после устранения находок обязаны стать GREEN
# БЕЗ правки смысла оракулов).
#
# Находки (акт docs/cert_pgv03_2026-10-28.md):
#   F-P3C1 -- CAS fail-open при экспорте из кэша с деградировавшим
#             контекстом: freeze_saved_visual декларирует «CAS ВСЕГДА
#             сверяет контекст сохранённого ответа с текущим durable-
#             состоянием запуска» (докстринг, док поставки §3.4), но
#             ожидания передаются as-is: saved.context_id=None /
#             saved.data_revision=None -> _check_context_cas целиком
#             пропускает сверку -> экспорт проходит при сменившемся
#             контексте/ревизии (класс находки F-P2C2).
#   F-P3C2 -- Подстановка wall-clock вместо честной причины: в
#             notify_visual_result (ЕДИНСТВЕННЫЙ wiring-канал всех 26
#             точек) computed_at = computed_at or _now_iso() -- при
#             неявившемся времени от обработчика подставляется время
#             вызова freeze, и execution.computed_at_reason=None, как
#             будто производитель время сообщил. Прямое противоречие
#             собственному контракту модуля (докстринг
#             build_visual_result_payload: «None -> честная причина
#             producer_not_reported, время вызова не подставляется»,
#             док поставки §3.3) -- honest-причина недостижима через
#             продуктовый канал.
#   F-P3C3 -- Кэш сохранённых ответов хранит поверхностную копию
#             (dict(response)): мутация вложенных структур ответа после
#             сохранения меняет контент, который заморозит экспорт --
#             «фактический ответ, сохранённый в момент выдачи»
#             (докстринг SavedVisualResponse) не защищён.

from __future__ import annotations

import sys
from dataclasses import replace as dc_replace
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

CERT_DIR = Path(__file__).resolve().parent
REPO = CERT_DIR.parents[1]
sys.path.insert(0, str(CERT_DIR))

import pytest  # noqa: E402

import p3cases  # noqa: E402
from apps.api.artifact_store import get_artifact_object_store  # noqa: E402
from apps.api.identity import DEFAULT_TENANT_ID, SubjectRef  # noqa: E402
from apps.api.research_runs import ResearchRun, get_research_run_store  # noqa: E402
from apps.api.visual_artifacts import (  # noqa: E402
    PrintContextConflict,
    list_visual_results,
)
from apps.api.visual_producers import (  # noqa: E402
    get_saved_visual_response,
    save_visual_response,
)

RUN_ID = "RUN-P3CF001A"
SESSION_ID = "p3cert-findings"
VIEW = "upload.chart.series"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _request() -> SimpleNamespace:
    from apps.api.session_store import SESSION_COOKIE_NAME

    return SimpleNamespace(cookies={SESSION_COOKIE_NAME: SESSION_ID}, headers={})


@pytest.fixture()
def seeded_run():
    store = get_research_run_store()
    subj = SubjectRef.from_session(SESSION_ID)
    store.upsert_run(
        ResearchRun(
            run_id=RUN_ID,
            session_id=SESSION_ID,
            dataset_fingerprint="p3" * 16,
            dataset_name="p3cert-findings-seed",
            target_column="value",
            created_at=_now(),
            last_active_at=_now(),
            status="active",
            owner_subject=subj.subject_id,
            tenant_id=DEFAULT_TENANT_ID,
            ownership="bound",
            context_id="ctx-p3cert-F1",
            data_revision=3,
        )
    )
    return RUN_ID


class _Session:
    def __init__(self, *, context_id: str | None = "ctx-p3cert-F1", data_revision: int = 3):
        self.run_id = RUN_ID
        self.session_id = SESSION_ID
        self.dataset = SimpleNamespace(dataset_id="p3cert-ds")
        self.data_revision = data_revision
        self._context_id = context_id

    def current_context_id(self) -> str | None:
        return self._context_id


def _payload_of(artifact) -> dict:
    import json

    return json.loads(
        get_artifact_object_store().read_bytes(artifact.storage_key).decode("utf-8")
    )


class TestFP3C1ExportCASFailOpen:
    """F-P3C1: «CAS ВСЕГДА» при экспорте не enforced -- деградировавший
    контекст сохранённого ответа отключает сверку целиком."""

    def test_export_conflicts_when_saved_context_degraded_and_run_moved(
        self, seeded_run, monkeypatch
    ):
        # Момент фиксации: контекст-компонент сессии деградировал
        # (исключение current_context_id -- честная деградация модуля).
        from apps.api import visual_producers as vp

        monkeypatch.setattr(
            vp, "_session_context_id", lambda session: None,
        )
        ref = save_visual_response(
            _Session(context_id=None), response=p3cases.timeseries_response()
        )
        monkeypatch.setattr(
            vp, "_session_context_id", lambda session: session.current_context_id(),
        )
        assert ref is not None
        saved = get_saved_visual_response(RUN_ID, ref)
        assert saved is not None and saved.context_id is None

        # Данные сменились между показом и экспортом: durable-зеркало
        # отражает НОВЫЙ контекст; ревизия не тронута -- изоляция
        # измерения «контекст»: только context-CAS мог бы поймать.
        store = get_research_run_store()
        store.upsert_run(
            dc_replace(
                store.get_run(RUN_ID),
                context_id="ctx-p3cert-F2",
                data_revision=3,
            )
        )

        # Контракт поставки («CAS ВСЕГДА», док §3.4): конфликт обязателен.
        with pytest.raises(PrintContextConflict):
            freeze_saved = vp.freeze_saved_visual
            freeze_saved(
                RUN_ID,
                SubjectRef.from_session(SESSION_ID),
                view_id=VIEW,
                result_ref=ref,
                session_id=SESSION_ID,
            )
        # Дополнительно: НИЧЕГО не зарегистрировано (дух AC07).
        assert list_visual_results(RUN_ID) == []

    def test_export_conflicts_when_saved_revision_degraded_and_run_moved(
        self, seeded_run, monkeypatch
    ):
        # Вариант той же находки: context сохранён, revision -- нет
        # (duck-typed сессия без int-ревизии -> saved.data_revision=None).
        from apps.api import visual_producers as vp

        session = _Session(context_id="ctx-p3cert-F1")
        session.data_revision = "seven"  # не int -- _session_data_revision -> None
        ref = save_visual_response(session, response=p3cases.timeseries_response())
        assert ref is not None
        saved = get_saved_visual_response(RUN_ID, ref)
        assert saved is not None and saved.data_revision is None

        store = get_research_run_store()
        store.upsert_run(dc_replace(store.get_run(RUN_ID), data_revision=4))

        with pytest.raises(PrintContextConflict):
            vp.freeze_saved_visual(
                RUN_ID,
                SubjectRef.from_session(SESSION_ID),
                view_id=VIEW,
                result_ref=ref,
                session_id=SESSION_ID,
            )
        assert list_visual_results(RUN_ID) == []


class TestFP3C2WallClockSubstitution:
    """F-P3C2: wiring-канал подставляет время вызова freeze вместо
    честной причины producer_not_reported."""

    def test_notify_without_handler_time_reports_honest_reason(self, seeded_run):
        from apps.api import promotion_integration

        session = _Session()
        outcome = promotion_integration.notify_visual_result(
            _request(), session, view_ids=(VIEW,),
            response=p3cases.timeseries_response(),  # обработчик время не сообщил
        )
        assert outcome is not None
        artifacts = list_visual_results(RUN_ID)
        assert len(artifacts) == 1
        payload = _payload_of(artifacts[0])
        # Контракт модуля (докстринг build_visual_result_payload,
        # док поставки §3.3): время вызова НЕ подставляется.
        assert payload["execution"]["computed_at"] is None
        assert payload["execution"]["computed_at_reason"] == "producer_not_reported"

    def test_notify_saved_moment_and_payload_time_agree(self, seeded_run):
        from apps.api import promotion_integration

        session = _Session()
        outcome = promotion_integration.notify_visual_result(
            _request(), session, view_ids=(VIEW,),
            response=p3cases.timeseries_response(),
        )
        saved = get_saved_visual_response(RUN_ID, outcome.result_ref)
        artifacts = list_visual_results(RUN_ID)
        payload = _payload_of(artifacts[0])
        # Один ответ -- одно время фиксации: payload producer_freeze
        # несёт время сохранённого ответа, а не собственный wall-clock.
        assert payload["execution"]["computed_at"] == saved.computed_at


class TestFP3C3CacheShallowCopy:
    """F-P3C3: кэш не изолирует вложенные структуры ответа."""

    def test_post_save_mutation_does_not_change_frozen_content(self, seeded_run):
        from apps.api import visual_producers as vp

        session = _Session()
        response = p3cases.timeseries_response(n_points=3)
        ref = save_visual_response(session, response=response)
        assert ref is not None
        # Мутация ответа ПОСЛЕ сохранения (общие ссылки на вложенные списки).
        response["points"].append({"x": 999, "y": 999.0})

        saved = get_saved_visual_response(RUN_ID, ref)
        assert len(saved.response["points"]) == 3, (
            "SavedVisualResponse -- «фактический ответ, сохранённый в момент "
            "выдачи»: пост-мутация источника не меняет сохранённое"
        )

        artifact = vp.freeze_saved_visual(
            RUN_ID,
            SubjectRef.from_session(SESSION_ID),
            view_id=VIEW,
            result_ref=ref,
            session_id=SESSION_ID,
        )
        payload = _payload_of(artifact)
        assert len(payload["payload"]["data"]["series"]) == 3, (
            "экспорт морозит момент фиксации, а не пост-мутационный контент"
        )
