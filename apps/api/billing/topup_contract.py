"""AUTH-22 validated browser commands. IDs select targets; the browser never
supplies price, currency or units (server-side package snapshot, design D1)."""

from uuid import UUID

from pydantic import Field

from apps.api.accounts.team_contract import Command


class TopupQuote(Command):
    package_id: UUID


class TopupOrder(Command):
    quote_id: UUID
    quote_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
