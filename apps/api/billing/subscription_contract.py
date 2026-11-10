"""Immutable seat quote input; integer-only subscription arithmetic."""

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from apps.api.accounts.team_contract import Command


class Quote(Command):
    request_id: UUID


class Confirm(BaseModel):
    model_config = ConfigDict(extra="forbid")
    quote_digest: str = Field(pattern=r"^[a-f0-9]{64}$")


def _ints(*values):
    if any(type(v) is not int for v in values):
        raise ValueError("integer units required")


def prorate(delta, price, remaining, duration):
    _ints(delta, price, remaining, duration)
    if not 0 <= price <= 10**12 or not 0 <= remaining <= duration or duration <= 0:
        raise ValueError("invalid period/price")
    n = max(0, delta) * price * remaining
    return (n + duration - 1) // duration


def cumulative_allocation(base, numerator, duration):
    _ints(base, numerator, duration)
    if base < 0 or duration <= 0:
        raise ValueError("invalid allocation")
    return max(0, base + numerator // duration)


def micros(delta):
    return (delta.days * 86400 + delta.seconds) * 1000000 + delta.microseconds
