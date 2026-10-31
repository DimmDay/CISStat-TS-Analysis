from datetime import datetime
from typing import Literal
from uuid import UUID
from pydantic import AwareDatetime, BaseModel, ConfigDict
from apps.api.plans import Role


class DurableRecord(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Identity(DurableRecord):
    subject_id: UUID
    kind: Literal["person", "service"]
    platform_role: Role
    status: Literal["active", "suspended"]
    subject_version: int
    created_at: AwareDatetime
    updated_at: AwareDatetime


class ExternalIdentity(DurableRecord):
    issuer: str
    external_subject: str
    subject_id: UUID
    email: str | None
    email_verified: bool
    created_at: AwareDatetime
