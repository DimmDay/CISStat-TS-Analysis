# apps/api/routers/doc_profiles.py
"""
DOCLOG-9 (spec_documentation_logging.md §15, §17, §19 строка DOCLOG-9):
маршруты организационных профилей документа.

Права (§15): создание/retire -- policy.admin (scopes, роль ADMIN даёт
полный каталог; cookie-суррогат права не фантазирует); чтение списка --
аутентификация (аноним -- uniform 404, решающая таблица DOCLOG-0:
контур не дисклоужается); validations/verify-signature -- право read на
run рендер-цели (чужой rendition -- uniform 404, T7/T15).

Аудит (§14.1): org_profile_created/org_profile_retired -- mandatory
fail-closed (класс «смена шаблона/policy»); fail-closed реализует
security_audit.record_mandatory (MandatoryAuditFailure прерывает
операцию).

Коды ошибок (§17): 400/404/403/409/422 плоским {code,message} --
паритет routers/documentation.py; 503 durable-слой недоступен.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from apps.api.doc_profiles import (
    OrgProfileAccessDenied,
    OrgProfileDuplicate,
    OrgProfileError,
    OrgProfileFormatMismatch,
    OrgProfileNotFound,
    OrgProfileRetired,
    org_profile_service,
)
from apps.api.document_jobs import (
    DocumentAccessDenied,
    DocumentIntegrityError,
    RenditionPurgedError,
)

router = APIRouter()

_PROFILES_NOT_FOUND_DETAIL = {
    "code": "org_profile_not_found",
    "message": "Профили организации недоступны",
}


def _subject_and_session(request: Request) -> tuple[Any, str]:
    from apps.api.routers.documentation import _subject_and_session as _resolve

    return _resolve(request)


def _profile_json(profile: Any) -> dict[str, Any]:
    return profile.to_dict()


@router.get("/org-profiles")
def list_org_profiles(request: Request, format: str = "") -> JSONResponse:
    """Список профилей организации (опциональный фильтр по формату).
    Аноним -- uniform 404 (решающая таблица DOCLOG-0)."""
    subject, _session_id = _subject_and_session(request)
    try:
        profiles = org_profile_service().list_profiles(
            subject, fmt=(format or "").strip().lower() or None
        )
    except OrgProfileNotFound:
        return JSONResponse(
            status_code=404, content={"detail": _PROFILES_NOT_FOUND_DETAIL}
        )
    except Exception:  # noqa: BLE001 -- безопасная ошибка §17
        return JSONResponse(
            status_code=404, content={"detail": _PROFILES_NOT_FOUND_DETAIL}
        )
    return JSONResponse(
        status_code=200,
        content={
            "profiles": [_profile_json(profile) for profile in profiles],
            "count": len(profiles),
        },
    )


@router.post("/org-profiles")
def create_org_profile(request: Request, payload: dict[str, Any]) -> JSONResponse:
    """Создать профиль (версия name+version_no). Только policy.admin."""
    subject, _session_id = _subject_and_session(request)
    try:
        profile = org_profile_service().create_profile(
            name=str(payload.get("name", "")),
            version_no=payload.get("version_no", 1)
            if isinstance(payload.get("version_no", 1), int)
            else 0,
            format=str(payload.get("format", "")).strip().lower(),
            subject=subject,
            language=str(payload.get("language", "ru") or "ru"),
            title_prefix=str(payload.get("title_prefix", "") or ""),
            footer_text=str(payload.get("footer_text", "") or ""),
            organization=str(payload.get("organization", "") or ""),
            sign_contents=bool(payload.get("sign_contents", False)),
            anchor_registry=bool(payload.get("anchor_registry", False)),
            worm_lock=bool(payload.get("worm_lock", False)),
        )
    except OrgProfileAccessDenied as exc:
        raise HTTPException(
            status_code=403,
            detail={"code": "insufficient_scope", "message": str(exc)},
        ) from None
    except OrgProfileDuplicate as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": "org_profile_duplicate", "message": str(exc)},
        ) from None
    except OrgProfileFormatMismatch as exc:
        raise HTTPException(
            status_code=422,
            detail={"code": "org_profile_format_mismatch", "message": str(exc)},
        ) from None
    except OrgProfileError as exc:
        raise HTTPException(
            status_code=422,
            detail={"code": "org_profile_invalid", "message": str(exc)},
        ) from None
    except RuntimeError as exc:  # durable-слой недоступен -- честный 503
        raise HTTPException(
            status_code=503,
            detail={"code": "storage_unavailable", "message": str(exc)},
        ) from None
    return JSONResponse(status_code=201, content={"profile": _profile_json(profile)})


@router.post("/org-profiles/{profile_id}/retire")
def retire_org_profile(request: Request, profile_id: str) -> JSONResponse:
    """Вывести профиль из действия (append-статусная запись;
    идемпотентно). Только policy.admin."""
    subject, _session_id = _subject_and_session(request)
    try:
        profile = org_profile_service().retire_profile(profile_id, subject)
    except OrgProfileAccessDenied as exc:
        raise HTTPException(
            status_code=403,
            detail={"code": "insufficient_scope", "message": str(exc)},
        ) from None
    except OrgProfileNotFound:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "org_profile_not_found",
                "message": "Профиль не найден",
            },
        ) from None
    except RuntimeError as exc:
        raise HTTPException(
            status_code=503,
            detail={"code": "storage_unavailable", "message": str(exc)},
        ) from None
    return JSONResponse(status_code=200, content={"profile": _profile_json(profile)})


def _authorized_rendition_or_404(
    request: Request, rendition_id: str, action: str = "read"
) -> tuple[Any, Any]:
    """Право read на run рендер-цели; чужое/несуществующее -- uniform 404
    (T7/T15: знание rendition_id не является правом)."""
    from apps.api.document_jobs import DocumentDeliveryService

    service = DocumentDeliveryService.create_default()
    rendition = service.registry.get_rendition(rendition_id)
    if rendition is None:
        raise DocumentAccessDenied("Выпуск недоступен")
    subject, session_id = _subject_and_session(request)
    service._authorized_run(
        rendition.run_id, subject, session_id=session_id, action=action
    )
    return service, rendition


@router.get("/renditions/{rendition_id}/validations")
def list_rendition_validations(
    request: Request, rendition_id: str
) -> JSONResponse:
    """Записи валидации выпуска (доказательство «подтверждён
    валидатором»; passed и failed -- обе честно перечислены)."""
    try:
        service, rendition = _authorized_rendition_or_404(
            request, rendition_id
        )
        records = org_profile_service().registry.list_validations(rendition_id)
    except DocumentAccessDenied:
        return JSONResponse(
            status_code=404,
            content={
                "detail": {
                    "code": "rendition_not_found",
                    "message": "Выпуск недоступен",
                }
            },
        )
    except Exception:  # noqa: BLE001 -- безопасная ошибка §17
        return JSONResponse(
            status_code=503,
            content={
                "detail": {
                    "code": "storage_unavailable",
                    "message": "Слой валидаций недоступен",
                }
            },
        )
    return JSONResponse(
        status_code=200,
        content={
            "validations": [record.to_dict() for record in records],
            "count": len(records),
        },
    )


@router.post("/renditions/{rendition_id}/verify-signature")
def verify_rendition_signature(
    request: Request, rendition_id: str
) -> JSONResponse:
    """Независимая верификация detached-подписи выпуска против текущих
    байтов (HMAC-манифест; НЕ юридическая ЭП)."""
    from apps.api.doc_profiles import verify_signature_manifest

    try:
        service, rendition = _authorized_rendition_or_404(
            request, rendition_id
        )
        records = org_profile_service().registry.list_validations(rendition_id)
    except DocumentAccessDenied:
        return JSONResponse(
            status_code=404,
            content={
                "detail": {
                    "code": "rendition_not_found",
                    "message": "Выпуск недоступен",
                }
            },
        )
    signature_records = [
        record
        for record in records
        if record.validator == "signature/1"
        and record.result == "passed"
        and record.signature_manifest
    ]
    if not signature_records:
        return JSONResponse(
            status_code=200,
            content={
                "verification": {
                    "validator": "signature/1",
                    "result": "not_signed",
                    "findings": [
                        "подпись для этого выпуска не зафиксирована"
                    ],
                }
            },
        )
    try:
        content = service.read_rendition_content(
            rendition,
            _subject_and_session(request)[0],
            session_id=_subject_and_session(request)[1],
        )
    except RenditionPurgedError:
        return JSONResponse(
            status_code=410,
            content={
                "detail": {
                    "code": "purged_artifact",
                    "message": "Файл удалён политикой хранения (§16.1)",
                }
            },
        )
    except DocumentIntegrityError:
        return JSONResponse(
            status_code=500,
            content={
                "detail": {
                    "code": "integrity_mismatch",
                    "message": "Байты выпуска не совпадают с content_sha256",
                }
            },
        )
    record = signature_records[-1]
    verification = verify_signature_manifest(
        content, dict(record.signature_manifest or {})
    )
    return JSONResponse(
        status_code=200,
        content={"verification": verification.to_dict()},
    )
