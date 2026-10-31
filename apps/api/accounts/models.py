from typing import Literal
from uuid import UUID
from pydantic import AwareDatetime
from apps.api.authentication.models import DurableRecord


class Account(DurableRecord):
    account_id: UUID
    tenant_id: UUID
    account_type: Literal["mono", "multi"]
    plan: Literal["demo", "starter", "professional", "enterprise", "internal"]
    status: Literal["active", "suspended", "closed"]
    seats: int
    entitlement_version: int
    plan_expires_at: AwareDatetime | None
    created_at: AwareDatetime
    updated_at: AwareDatetime


class Membership(DurableRecord):
    account_id: UUID
    subject_id: UUID
    account_role: Literal["owner", "member"]
    status: Literal["active", "revoked"]
    joined_at: AwareDatetime
