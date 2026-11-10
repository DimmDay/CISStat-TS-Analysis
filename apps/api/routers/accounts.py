"""Personal Account endpoints; no provider/seat approval or actor claims in HTTP."""

from uuid import UUID

from fastapi import APIRouter, Request, Response

from apps.api.accounts.team import TeamService
from apps.api.accounts.team_contract import (
    Accept,
    Command,
    Convert,
    Invite,
    SeatRequest,
    Transfer,
)
from apps.api.authentication.csrf import auth_cookie
from apps.api.routers.authentication import (
    SafeAuthRoute,
    _authenticated,
    _clear,
    _entry,
    _session,
)
from apps.api.routers.demo import _origin

router = APIRouter(route_class=SafeAuthRoute)


def service(request):
    return getattr(request.app.state, "auth_team_service", None) or TeamService(
        getattr(request.app.state, "auth_access_store", None)
    )


def entry(request, mutation=False):
    _entry(request, mutation)
    _session(request)
    return _origin(request, mutation)


@router.get("")
def list_accounts(request: Request):
    return service(request).list_accounts(auth_cookie(request), entry(request))


@router.get("/{account_id}")
def account(request: Request, account_id: UUID):
    return service(request).show(auth_cookie(request), entry(request), account_id)


@router.post("/invitations/accept")
def accept(request: Request, payload: Accept):
    return service(request).accept(auth_cookie(request), entry(request, True), payload)


@router.post("/{account_id}/select")
def select(request: Request, response: Response, account_id: UUID):
    result = service(request).select(
        auth_cookie(request), entry(request, True), account_id
    )
    _clear(response)
    return _authenticated(response, result)


@router.post("/{account_id}/invitations")
def invite(request: Request, account_id: UUID, payload: Invite):
    return service(request).invite(
        auth_cookie(request), entry(request, True), account_id, payload
    )


@router.post("/{account_id}/invitations/{invitation_id}/revoke")
def revoke_invite(
    request: Request, account_id: UUID, invitation_id: UUID, payload: Command
):
    return service(request).command(
        auth_cookie(request),
        entry(request, True),
        account_id,
        "revoke-invite",
        payload,
        target=invitation_id,
    )


@router.post("/{account_id}/type")
def convert(request: Request, account_id: UUID, payload: Convert):
    return service(request).command(
        auth_cookie(request), entry(request, True), account_id, "convert", payload
    )


@router.post("/{account_id}/members/{subject_id}/remove")
def remove(request: Request, account_id: UUID, subject_id: UUID, payload: Command):
    return service(request).command(
        auth_cookie(request),
        entry(request, True),
        account_id,
        "remove",
        payload,
        target=subject_id,
    )


@router.post("/{account_id}/ownership-transfer")
def transfer(request: Request, account_id: UUID, payload: Transfer):
    return service(request).command(
        auth_cookie(request), entry(request, True), account_id, "transfer", payload
    )


@router.post("/{account_id}/seat-requests")
def request_seats(request: Request, account_id: UUID, payload: SeatRequest):
    return service(request).command(
        auth_cookie(request), entry(request, True), account_id, "seat-request", payload
    )


@router.post("/{account_id}/seat-requests/{request_id}/cancel")
def cancel_seats(
    request: Request, account_id: UUID, request_id: UUID, payload: Command
):
    return service(request).command(
        auth_cookie(request),
        entry(request, True),
        account_id,
        "cancel-seat-request",
        payload,
        target=request_id,
    )
