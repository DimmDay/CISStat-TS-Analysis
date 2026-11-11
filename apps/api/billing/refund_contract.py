"""AUTH-23 validated browser command. The refund is always the FULL amount of
the credited order (whole unused lot, §13.7); the browser supplies nothing but
the target order id."""

from uuid import UUID

from pydantic import Field

from apps.api.accounts.team_contract import Command


class RefundRequest(Command):
    order_id: UUID
