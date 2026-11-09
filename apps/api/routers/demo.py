"""AUTH-15 first-party forum entry and named MFA campaign administration."""

import secrets
from uuid import UUID

from fastapi import APIRouter, Request, Response
from pydantic import AwareDatetime, Field, SecretStr

from apps.api.authentication.csrf import _cookie, auth_cookie, trusted_origin
from apps.api.authentication.demo import (
    RESUME_COOKIE,
    CampaignPolicy,
    DemoService,
    resume_digest,
)
from apps.api.routers.authentication import (
    AuthBody,
    SafeAuthRoute,
    _authenticated,
    _clear,
    _entry,
)

router = APIRouter(route_class=SafeAuthRoute)


def service(request):
    return DemoService(store=getattr(request.app.state, "auth_access_store", None))


class CreateBody(AuthBody):
    alias: str = Field(min_length=3, max_length=128)
    policy: CampaignPolicy
    reason: str = Field(min_length=1, max_length=256, pattern=r"\S")


class CommandBody(AuthBody):
    expected_version: int = Field(ge=1, strict=True)
    reason: str = Field(min_length=1, max_length=256, pattern=r"\S")


class UpdateBody(CommandBody):
    policy: CampaignPolicy


class EnterBody(AuthBody):
    login: str = Field(min_length=3, max_length=128)
    password: SecretStr = Field(min_length=1, max_length=1024)
    admission_code: SecretStr | None = Field(default=None, max_length=64)


def _origin(request, mutation=False):
    _entry(request, mutation)
    if not mutation and not request.headers.get("origin"):
        from apps.api.authentication.context import auth_error

        if request.headers.get("sec-fetch-site") not in (
            None,
            "same-origin",
            "same-site",
            "none",
        ):
            auth_error(403, "csrf_invalid")
        return None
    return trusted_origin(request)


def _entered(response, result):
    _clear(response)
    return _authenticated(response, result)


@router.post("/auth/demo/prepare")
def prepare(request: Request, response: Response):
    _origin(request, True)
    token = _cookie(request, RESUME_COOKIE)
    if token:
        resume_digest(token)
    else:
        token = "d1_" + secrets.token_urlsafe(32)
    response.set_cookie(
        RESUME_COOKIE,
        token,
        max_age=90 * 86400,
        secure=True,
        httponly=True,
        samesite="lax",
        path="/",
    )
    return {"prepared": True}


@router.post("/auth/demo/enter")
def enter(request: Request, response: Response, payload: EnterBody):
    origin = _origin(request, True)
    result = service(request).enter(
        payload.login,
        payload.password.get_secret_value(),
        _cookie(request, RESUME_COOKIE),
        origin,
        request.client.host if request.client else "unknown",
        old_token=auth_cookie(request),
        admission_code=payload.admission_code.get_secret_value()
        if payload.admission_code
        else None,
    )
    return _entered(response, result)


@router.post("/auth/demo/resume")
def resume(request: Request, response: Response):
    origin = _origin(request, True)
    return _entered(
        response,
        service(request).resume(
            _cookie(request, RESUME_COOKIE),
            origin,
            old_token=auth_cookie(request),
            peer=request.client.host if request.client else "unknown",
        ),
    )


@router.post("/auth/demo/leave")
def leave(request: Request, response: Response):
    _origin(request, True)
    service(request).leave(
        _cookie(request, RESUME_COOKIE), old_token=auth_cookie(request)
    )
    _clear(response)
    response.delete_cookie(
        RESUME_COOKIE, path="/", secure=True, httponly=True, samesite="lax"
    )
    return {"ended": True}


@router.get("/auth/demo/me")
def demo_me(request: Request):
    _origin(request)
    from apps.api.authentication.context import auth_error, resolve_request_context

    ctx = resolve_request_context(request)
    if not ctx.demo_grant_id:
        auth_error(401, "authentication_required")
    return {
        "grant_id": ctx.demo_grant_id,
        "account_id": ctx.account_id,
        "expires_at": ctx.plan_expires_at,
        "capabilities": ctx.as_principal().capabilities,
    }


@router.get("/admin/demo-campaigns")
def campaigns(request: Request):
    return {"campaigns": service(request).list(auth_cookie(request), _origin(request))}


@router.post("/admin/demo-campaigns")
def create(request: Request, payload: CreateBody):
    return service(request).create(
        auth_cookie(request),
        _origin(request, True),
        payload.alias,
        payload.policy,
        payload.reason,
    )


@router.patch("/admin/demo-campaigns/{campaign_id}")
def update(request: Request, campaign_id: UUID, payload: UpdateBody):
    return service(request).command(
        auth_cookie(request),
        _origin(request, True),
        campaign_id,
        "update",
        payload.expected_version,
        payload.reason,
        payload.policy,
    )


@router.post("/admin/demo-campaigns/{campaign_id}/activate")
def activate(request: Request, campaign_id: UUID, payload: CommandBody):
    return service(request).command(
        auth_cookie(request),
        _origin(request, True),
        campaign_id,
        "activate",
        payload.expected_version,
        payload.reason,
    )


@router.post("/admin/demo-campaigns/{campaign_id}/pause")
def pause(request: Request, campaign_id: UUID, payload: CommandBody):
    return service(request).command(
        auth_cookie(request),
        _origin(request, True),
        campaign_id,
        "pause",
        payload.expected_version,
        payload.reason,
    )


@router.post("/admin/demo-campaigns/{campaign_id}/resume")
def resume_campaign(request: Request, campaign_id: UUID, payload: CommandBody):
    return service(request).command(
        auth_cookie(request),
        _origin(request, True),
        campaign_id,
        "resume",
        payload.expected_version,
        payload.reason,
    )


@router.post("/admin/demo-campaigns/{campaign_id}/revoke")
def revoke(request: Request, campaign_id: UUID, payload: CommandBody):
    return service(request).command(
        auth_cookie(request),
        _origin(request, True),
        campaign_id,
        "revoke",
        payload.expected_version,
        payload.reason,
    )


@router.post("/admin/demo-campaigns/{campaign_id}/rotate-credential")
def rotate(request: Request, campaign_id: UUID, payload: CommandBody):
    return service(request).command(
        auth_cookie(request),
        _origin(request, True),
        campaign_id,
        "rotate-credential",
        payload.expected_version,
        payload.reason,
    )


@router.get("/admin/demo-campaigns/{campaign_id}/usage")
def usage(request: Request, campaign_id: UUID):
    return service(request).usage(auth_cookie(request), _origin(request), campaign_id)


class AdmissionsBody(CommandBody):
    count: int = Field(ge=1, le=200, strict=True)
    expires_at: AwareDatetime


@router.post("/admin/demo-campaigns/{campaign_id}/admissions")
def admissions(request: Request, campaign_id: UUID, payload: AdmissionsBody):
    from apps.api.authentication.demo_lifecycle import LifecycleService

    return LifecycleService(
        store=getattr(request.app.state, "auth_access_store", None)
    ).issue_codes(
        auth_cookie(request),
        _origin(request, True),
        campaign_id,
        payload.expected_version,
        payload.count,
        payload.expires_at,
        payload.reason,
    )


@router.get("/auth/demo/limits")
def limits(request: Request):
    _origin(request)
    from apps.api.authentication.context import auth_error, resolve_request_context
    from apps.api.authentication.demo_lifecycle import LifecycleService

    ctx = resolve_request_context(request)
    if not ctx.demo_grant_id:
        auth_error(401, "authentication_required")
    return LifecycleService(
        store=getattr(request.app.state, "auth_access_store", None)
    ).remaining(ctx)
