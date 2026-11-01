"""Safe browser context shared by API validation and TS generation."""

from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict

from apps.api.plans import Role


class AuthMeResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    subject_id: UUID
    account_id: UUID
    tenant_id: UUID
    membership_role: Literal["owner", "member"]
    role: Role
    auth_method: Literal["auth_session"]
    auth_session_id: UUID
    auth_time: AwareDatetime
    mfa_verified_at: AwareDatetime | None
