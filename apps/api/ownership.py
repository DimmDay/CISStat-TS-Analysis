"""AUTH-09 scientific pointers identify resources, never personal credentials."""

from uuid import uuid4

from fastapi import HTTPException


def session_pointer(request):
    from apps.api.authentication.context import resolve_request_context
    from apps.api.identity import authorize_run_access
    from apps.api.research_runs import get_research_run_store
    from apps.api.session_store import (
        SESSION_COOKIE_NAME,
        AnalysisSession,
        get_session_store,
    )

    cached = getattr(request.state, "_auth09_session_id", None)
    if cached:
        return cached
    context = resolve_request_context(request)
    subject = context.as_subject()
    pointer = request.cookies.get(SESSION_COOKIE_NAME)
    try:
        store = get_session_store()
        session = store.get(pointer) if pointer else None
        if session is not None:
            if session.owner_account_id is not None:
                if not authorize_run_access(session, subject, action="read").allowed:
                    raise HTTPException(404, "Запуск не найден")
            elif context.account_id is not None:
                if session.dataset is not None or session.run_id:
                    raise HTTPException(404, "Запуск не найден")
                session = None
            if session is not None and session.run_id:
                run = get_research_run_store().get_run(session.run_id)
                if (
                    run is not None
                    and (
                        run.owner_account_id is not None
                        or context.account_id is not None
                    )
                    and not authorize_run_access(
                        run, subject, session_id=pointer or "", action="read"
                    ).allowed
                ):
                    raise HTTPException(404, "Запуск не найден")
        if context.account_id is not None and session is None:
            pointer = uuid4().hex
            session = AnalysisSession(
                pointer,
                owner_subject=context.subject_id,
                tenant_id=context.tenant_id,
                owner_account_id=context.account_id,
            )
            store.save(session)
        elif not pointer:
            pointer = uuid4().hex
    except HTTPException:
        raise
    except Exception:  # noqa: BLE001 -- fail closed without database diagnostics
        raise HTTPException(503, "Сервис владения недоступен") from None
    request.state._auth09_session_id = pointer
    return pointer
