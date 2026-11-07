"""AUTH-10 bounded request/response DTOs; only issue/rotate carries a secret."""

import re
from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator

API_SCOPES = frozenset({"api.read", "api.write", "api.compute", "api.database"})
KeyScope = Literal["api.read", "api.write", "api.compute", "api.database"]


class KeyBody(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)


class IssueKeyBody(KeyBody):
    label: str = Field(min_length=1, max_length=80)
    expires_in_days: int = Field(ge=1, le=365)
    scopes: list[KeyScope] = Field(min_length=1, max_length=4)

    @field_validator("label")
    @classmethod
    def safe_label(cls, value):
        value = value.strip()
        if not value or re.search(r"[\x00-\x1f\x7f]|csk_[A-Za-z0-9_-]{20,}", value):
            raise ValueError("safe label required")
        return value

    @field_validator("scopes")
    @classmethod
    def unique_scopes(cls, value):
        if len(set(value)) != len(value):
            raise ValueError("duplicate scopes")
        return value


class VersionBody(KeyBody):
    expected_version: int = Field(ge=1)


class RotateKeyBody(VersionBody):
    scopes: list[KeyScope] | None = Field(default=None, min_length=1, max_length=4)

    @field_validator("scopes")
    @classmethod
    def unique_scopes(cls, value):
        if value is not None and len(set(value)) != len(value):
            raise ValueError("duplicate scopes")
        return value


class KeyMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key_id: UUID
    family_id: UUID
    subject_id: UUID
    account_id: UUID
    label: str
    scopes: list[KeyScope]
    version: int
    created_at: AwareDatetime
    expires_at: AwareDatetime
    revoked_at: AwareDatetime | None
    replaced_by: UUID | None


class IssuedKeyResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    secret: str = Field(repr=False)
    key: KeyMetadata


class KeyListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    items: list[KeyMetadata]
    truncated: bool
