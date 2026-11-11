"""OWNER browser commands and an independent untrusted provider wake-up endpoint."""

from uuid import UUID

from fastapi import APIRouter, Request

from apps.api.authentication.context import auth_error
from apps.api.authentication.csrf import auth_cookie
from apps.api.billing.subscription_contract import Confirm, Quote
from apps.api.billing.subscriptions import SubscriptionService
from apps.api.billing.topup_contract import TopupOrder, TopupQuote
from apps.api.billing.topups import TopupService
from apps.api.routers.accounts import entry
from apps.api.routers.authentication import SafeAuthRoute

router = APIRouter(route_class=SafeAuthRoute)


def service(request):
    return getattr(
        request.app.state, "auth_subscription_service", None
    ) or SubscriptionService(getattr(request.app.state, "auth_access_store", None))


def topup_service(request):
    return getattr(request.app.state, "auth_topup_service", None) or TopupService(
        getattr(request.app.state, "auth_access_store", None)
    )


@router.get("/{account_id}/subscription")
def subscription(request: Request, account_id: UUID):
    return service(request).show(auth_cookie(request), entry(request), account_id)


@router.post("/{account_id}/quotes")
def quote(request: Request, account_id: UUID, payload: Quote):
    return service(request).quote(
        auth_cookie(request), entry(request, True), account_id, payload
    )


@router.post("/{account_id}/quotes/{quote_id}/confirm")
def confirm(request: Request, account_id: UUID, quote_id: UUID, payload: Confirm):
    return service(request).confirm(
        auth_cookie(request), entry(request, True), account_id, quote_id, payload
    )


@router.get("/{account_id}/topups")
def topups(request: Request, account_id: UUID):
    return topup_service(request).show(auth_cookie(request), entry(request), account_id)


@router.post("/{account_id}/topup-quotes")
def topup_quote(request: Request, account_id: UUID, payload: TopupQuote):
    return topup_service(request).quote(
        auth_cookie(request), entry(request, True), account_id, payload
    )


@router.post("/{account_id}/topups")
def topup_order(request: Request, account_id: UUID, payload: TopupOrder):
    return topup_service(request).confirm(
        auth_cookie(request), entry(request, True), account_id, payload
    )


@router.post("/webhooks/yookassa")
async def webhook(request: Request):
    # No cookie authority/CSRF exemption for other commands. SafeAuthRoute bounds body.
    try:
        body = await request.json()
        if body.get("type") != "notification":
            raise ValueError()
        obj = body["object"]
        payment_id = obj["id"]
        event = body["event"]
        metadata = obj.get("metadata") or {}
        hint = metadata.get("order_id")
        hint = UUID(hint) if isinstance(hint, str) else None
        subscription = service(request).notify(payment_id, event, hint)
        topup = topup_service(request).notify(payment_id, event, hint)
        # Bounded untrusted wake-ups only; neither may credit anything.
        return {"received": bool(subscription or topup)}
    except (ValueError, KeyError, TypeError, AttributeError):
        auth_error(422, "invalid_request")
