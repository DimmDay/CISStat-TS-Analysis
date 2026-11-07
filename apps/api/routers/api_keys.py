"""AUTH-10 personal API key lifecycle; bearer credentials cannot manage keys."""

from uuid import UUID

from fastapi import APIRouter, Request

from apps.api.authentication.api_key_contract import (
    IssuedKeyResponse,
    IssueKeyBody,
    KeyListResponse,
    KeyMetadata,
    RotateKeyBody,
    VersionBody,
)
from apps.api.authentication.api_keys import service_for_request
from apps.api.authentication.csrf import auth_cookie, trusted_origin
from apps.api.routers.authentication import SafeAuthRoute, _session

router = APIRouter(route_class=SafeAuthRoute)


def _owner(request):
    # _session rejects bearer/identity assertions; resolves CSRF/Origin and the
    # current personal session. The service revalidates it under writer locks.
    _session(request)
    return auth_cookie(request), (
        trusted_origin(request)
        if request.method != "GET" or request.headers.get("origin")
        else None
    )


@router.get("", response_model=KeyListResponse)
def list_api_keys(request: Request):
    token, origin = _owner(request)
    return service_for_request(request).list(token, origin=origin)


@router.post("", response_model=IssuedKeyResponse, status_code=201)
def issue_api_key(request: Request, payload: IssueKeyBody):
    token, origin = _owner(request)
    result = service_for_request(request).issue(token, payload, origin=origin)
    return IssuedKeyResponse(secret=result.secret, key=result.key)


@router.post("/{key_id}/rotate", response_model=IssuedKeyResponse)
def rotate_api_key(request: Request, key_id: UUID, payload: RotateKeyBody):
    token, origin = _owner(request)
    result = service_for_request(request).rotate(token, key_id, payload, origin=origin)
    return IssuedKeyResponse(secret=result.secret, key=result.key)


@router.post("/{key_id}/revoke", response_model=KeyMetadata)
def revoke_api_key(request: Request, key_id: UUID, payload: VersionBody):
    token, origin = _owner(request)
    return service_for_request(request).revoke(token, key_id, payload, origin=origin)
