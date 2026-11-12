"""OWNER browser commands and an independent untrusted provider wake-up endpoint."""

from uuid import UUID

from fastapi import APIRouter, Request

from apps.api.authentication.context import auth_error
from apps.api.authentication.csrf import auth_cookie
from apps.api.billing.refund_contract import RefundRequest
from apps.api.billing.refunds import RefundService
from apps.api.billing.subscription_contract import Confirm, Quote
from apps.api.billing.subscriptions import SubscriptionService
from apps.api.billing.topup_contract import TopupOrder, TopupQuote
from apps.api.billing.topups import TopupService
from apps.api.billing.wallet_views import WalletReadService
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


def refund_service(request):
    return getattr(request.app.state, "auth_refund_service", None) or RefundService(
        getattr(request.app.state, "auth_access_store", None)
    )


def wallet_service(request):
    return getattr(request.app.state, "auth_wallet_read_service", None) or WalletReadService(
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


@router.post("/{account_id}/topups/{order_id}/refunds")
def refund_request(request: Request, account_id: UUID, order_id: UUID, payload: RefundRequest):
    return refund_service(request).request(
        auth_cookie(request), entry(request, True), account_id, order_id, payload
    )


@router.get("/{account_id}/refunds/{refund_id}")
def refund_show(request: Request, account_id: UUID, refund_id: UUID):
    return refund_service(request).refund_get(
        auth_cookie(request), entry(request), account_id, refund_id
    )


@router.get("/{account_id}/wallet")
def wallet_show(request: Request, account_id: UUID):
    # AUTH-24: member usage projection; OWNER also receives the per-source
    # breakdown. Financial privacy is the projection's contract (design D1).
    return wallet_service(request).wallet(
        auth_cookie(request), entry(request), account_id
    )


@router.get("/{account_id}/wallet/ledger")
def wallet_ledger(request: Request, account_id: UUID):
    # AUTH-24: OWNER-only full financial journal (§13.8); MEMBER gets 403
    # owner_required and never sees money documents.
    return wallet_service(request).ledger(
        auth_cookie(request), entry(request), account_id
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
