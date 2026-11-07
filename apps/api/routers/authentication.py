"""Personal password/session/MFA endpoints; CLI bootstrap is never mounted."""

from uuid import UUID
from typing import Literal
from fastapi import APIRouter, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict, Field, SecretStr

from apps.api.authentication.context import (
    AuthHTTPException,
    auth_error,
    resolve_request_context,
    _request_id,
)
from apps.api.authentication.csrf import (
    AUTH_COOKIE,
    CSRF_COOKIE,
    auth_cookie,
    issue_csrf,
    check_csrf,
    trusted_origin,
)
from apps.api.authentication.sessions import service_for_request, AccountChoices
from apps.api.authentication.http_contract import AuthMeResponse
from apps.api.authentication.mfa import IssuedChallenge, mfa_for_request


class SafeAuthRoute(APIRoute):
    def get_route_handler(self):
        original = super().get_route_handler()

        async def handler(request):
            try:
                if request.method == "POST":
                    body = bytearray()
                    async for chunk in request.stream():
                        body.extend(chunk)
                        if len(body) > 16384:
                            response = JSONResponse(
                                status_code=413,
                                content={
                                    "detail": {
                                        "code": "invalid_request",
                                        "message": "Слишком большой запрос",
                                        "request_id": _request_id(request),
                                    }
                                },
                            )
                            response.headers["cache-control"] = "private, no-store"
                            return response
                    request._body = bytes(body)
                response = await original(request)
            except RequestValidationError:
                response = JSONResponse(
                    status_code=422,
                    content={
                        "detail": {
                            "code": "invalid_request",
                            "message": "Некорректные параметры запроса",
                            "request_id": _request_id(request),
                        }
                    },
                )
            except AuthHTTPException as exc:
                detail = dict(exc.detail)
                detail["request_id"] = _request_id(request)
                response = JSONResponse(
                    status_code=exc.status_code, content={"detail": detail}
                )
            except Exception:
                response = JSONResponse(
                    status_code=503,
                    content={
                        "detail": {
                            "code": "auth_authority_unavailable",
                            "message": "Сервис аутентификации недоступен",
                            "request_id": _request_id(request),
                        }
                    },
                )
            response.headers["cache-control"] = "private, no-store"
            response.headers["pragma"] = "no-cache"
            response.headers["x-content-type-options"] = "nosniff"
            return response

        return handler


router = APIRouter(route_class=SafeAuthRoute)


class AuthBody(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class LoginBody(AuthBody):
    login: str = Field(min_length=3, max_length=128)
    password: SecretStr = Field(min_length=1, max_length=1024)
    account_id: UUID | None = None


class PasswordBody(AuthBody):
    proof: SecretStr | None = Field(default=None, min_length=46, max_length=46)
    current_password: SecretStr = Field(min_length=1, max_length=1024)
    new_password: SecretStr = Field(min_length=15, max_length=1024)


def _entry(request, mutation=False):
    if "x-api-key" in request.headers or "authorization" in request.headers:
        auth_error(401, "invalid_credential")
    if mutation:
        check_csrf(request)


def _session(request):
    _entry(request)
    context = resolve_request_context(request)
    if context.auth_method != "auth_session":
        auth_error(401, "authentication_required")
    return context


def _clear(response):
    for name in (AUTH_COOKIE, CSRF_COOKIE):
        response.delete_cookie(
            name, path="/", secure=True, httponly=True, samesite="lax"
        )
    # Clear pointer, never delete/reassign the underlying scientific session.
    response.delete_cookie("cisstat_session_id", path="/")


@router.get("/csrf")
def csrf(request: Request, response: Response):
    _entry(request)
    proof = issue_csrf(request)
    response.set_cookie(
        CSRF_COOKIE,
        proof,
        max_age=600,
        secure=True,
        httponly=True,
        samesite="lax",
        path="/",
    )
    return {"csrf_token": proof, "expires_in": 600}


@router.post("/login")
def login(request: Request, response: Response, payload: LoginBody):
    _entry(request, True)
    result = service_for_request(request).login(
        payload.login,
        payload.password.get_secret_value(),
        payload.account_id,
        old_token=auth_cookie(request),
        origin=trusted_origin(request),
        peer=request.client.host if request.client else "unknown",
    )
    if isinstance(result, AccountChoices):
        return {"status": "account_required", "accounts": result.accounts}
    _clear(response)
    if isinstance(result, IssuedChallenge):
        return _challenge_json(result)
    return _authenticated(response, result)


def _challenge_json(challenge):
    return {
        "status": "challenge_required",
        "challenge_token": challenge.token,
        "purpose": challenge.purpose,
        "expires_at": challenge.expires_at.isoformat(),
    }


def _authenticated(response, result):
    response.set_cookie(
        AUTH_COOKIE,
        result.token,
        max_age=8 * 3600,
        secure=True,
        httponly=True,
        samesite="lax",
        path="/",
    )
    return {"status": "authenticated", "session": result.session}


@router.get("/me", response_model=AuthMeResponse)
def me(request: Request):
    ctx = _session(request)
    result = {
        key: (
            getattr(ctx, key).isoformat()
            if key in ("auth_time", "mfa_verified_at") and getattr(ctx, key)
            else getattr(ctx, key)
        )
        for key in (
            "subject_id",
            "account_id",
            "tenant_id",
            "membership_role",
            "role",
            "auth_method",
            "auth_session_id",
            "auth_time",
            "mfa_verified_at",
            "account_plan",
            "account_type",
            "plan_expires_at",
            "entitlement_version",
        )
    }
    result["capabilities"] = ctx.as_principal().capabilities
    return result


@router.get("/sessions")
def sessions(request: Request):
    _session(request)
    return {
        "sessions": service_for_request(request).list_sessions(auth_cookie(request))
    }


@router.post("/logout", status_code=204)
def logout(request: Request, response: Response):
    _entry(request, True)
    service_for_request(request).logout(auth_cookie(request))
    _clear(response)


@router.post("/sessions/revoke-all")
def revoke_all(request: Request, response: Response):
    _entry(request, True)
    _session(request)
    service_for_request(request).revoke(auth_cookie(request), all_sessions=True)
    _clear(response)
    return {"revoked": True}


@router.post("/sessions/{session_id}/revoke")
def revoke(request: Request, response: Response, session_id: UUID):
    _entry(request, True)
    ctx = _session(request)
    service_for_request(request).revoke(auth_cookie(request), session_id)
    if str(session_id) == ctx.auth_session_id:
        _clear(response)
    return {"revoked": True}


@router.post("/password")
def change_password(request: Request, response: Response, payload: PasswordBody):
    _entry(request, True)
    _session(request)
    service_for_request(request).change_password(
        auth_cookie(request),
        payload.current_password.get_secret_value(),
        payload.new_password.get_secret_value(),
        proof=payload.proof.get_secret_value() if payload.proof else None,
        origin=trusted_origin(request),
    )
    _clear(response)
    return {"password_changed": True, "sessions_revoked": True}


class ChallengeBody(AuthBody):
    challenge_token: SecretStr = Field(min_length=46, max_length=46)


class VerifyBody(ChallengeBody):
    code: SecretStr = Field(min_length=1, max_length=64)


class StepUpBody(AuthBody):
    password: SecretStr = Field(min_length=1, max_length=1024)
    action: Literal["mfa.replace", "recovery.rotate", "password.change"]


class ProofBody(AuthBody):
    proof: SecretStr = Field(min_length=46, max_length=46)


@router.post("/mfa/enroll")
def mfa_enroll(request: Request, payload: ChallengeBody):
    _entry(request, True)
    result = mfa_for_request(request).begin_enrollment(
        payload.challenge_token.get_secret_value(), origin=trusted_origin(request)
    )
    return {
        **_challenge_json(result.challenge),
        "secret": result.secret,
        "otpauth_uri": result.uri,
    }


@router.post("/mfa/verify")
def mfa_verify(request: Request, response: Response, payload: VerifyBody):
    _entry(request, True)
    result = mfa_for_request(request).complete(
        payload.challenge_token.get_secret_value(),
        payload.code.get_secret_value(),
        origin=trusted_origin(request),
        session_token=auth_cookie(request),
    )
    if result.proof:
        return _challenge_json(result.proof)
    _clear(response)
    body = _authenticated(response, result.session)
    if result.recovery_codes:
        body["recovery_codes"] = result.recovery_codes
    return body


@router.post("/step-up")
def step_up(request: Request, payload: StepUpBody):
    _entry(request, True)
    _session(request)
    return _challenge_json(
        mfa_for_request(request).start_step_up(
            auth_cookie(request),
            payload.password.get_secret_value(),
            payload.action,
            origin=trusted_origin(request),
        )
    )


@router.post("/mfa/replace")
def mfa_replace(request: Request, response: Response, payload: ProofBody):
    _entry(request, True)
    _session(request)
    result = mfa_for_request(request).replace_factor(
        auth_cookie(request),
        payload.proof.get_secret_value(),
        origin=trusted_origin(request),
    )
    _clear(response)
    return _challenge_json(result)


@router.post("/recovery")
def recovery(request: Request, response: Response, payload: VerifyBody):
    _entry(request, True)
    result = mfa_for_request(request).recover(
        payload.challenge_token.get_secret_value(),
        payload.code.get_secret_value(),
        origin=trusted_origin(request),
    )
    _clear(response)
    return _challenge_json(result)


@router.post("/recovery/rotate")
def recovery_rotate(request: Request, payload: ProofBody):
    _entry(request, True)
    _session(request)
    codes = mfa_for_request(request).rotate_recovery(
        auth_cookie(request),
        payload.proof.get_secret_value(),
        origin=trusted_origin(request),
    )
    return {"recovery_codes": codes}
