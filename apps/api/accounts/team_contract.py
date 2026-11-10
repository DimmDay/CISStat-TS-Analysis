"""Validated browser commands. IDs select targets; never assert permission/payment."""

import hashlib
import re
from typing import Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    field_validator,
    model_validator,
)

from apps.api.authentication.context import auth_error


def normalize_email(value):
    if not isinstance(value, str):
        raise ValueError("email required")  # noqa: TRY004 -- Pydantic validators must produce safe ValidationError
    value = value.strip().lower()
    if len(value) > 254 or not re.fullmatch(
        r"[a-z0-9.!#$%&'*+/=?^_`{|}~-]+@[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?\.[a-z]{2,63}",
        value,
    ):
        raise ValueError("supported email required")
    return value


def invitation_digest(token):
    if not isinstance(token, str) or not re.fullmatch(r"i17_[A-Za-z0-9_-]{43}", token):
        auth_error(404, "invitation_unavailable")
    return hashlib.sha256(("cisstat.invitation/17\0" + token).encode()).hexdigest()


class Body(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class Command(Body):
    expected_version: int = Field(ge=1, strict=True)
    reason: str = Field(min_length=1, max_length=256, pattern=r"\S")
    idempotency_key: str = Field(min_length=1, max_length=128, repr=False)


class Invite(Command):
    target_subject_id: UUID | None = None
    email: str | None = None
    ttl_hours: int = Field(default=24, ge=1, le=168, strict=True)

    @field_validator("email", mode="before")
    @classmethod
    def email_value(cls, v):
        return normalize_email(v) if v is not None else None

    @model_validator(mode="after")
    def one_target(self):
        if (self.target_subject_id is None) == (self.email is None):
            raise ValueError("exactly one target required")
        return self


class Convert(Command):
    account_type: Literal["mono", "multi"]
    acknowledge_shared_access: bool = Field(default=False, strict=True)

    @model_validator(mode="after")
    def explicit_sharing(self):
        if self.account_type == "multi" and not self.acknowledge_shared_access:
            raise ValueError("explicit sharing acknowledgement required")
        return self


class Transfer(Command):
    target_subject_id: UUID


class SeatRequest(Command):
    seats: int = Field(ge=1, le=1000, strict=True)


class Accept(Body):
    invitation_token: SecretStr = Field(min_length=47, max_length=47)
    idempotency_key: str = Field(min_length=1, max_length=128, repr=False)
    reason: str = Field(
        default="accept invitation", min_length=1, max_length=256, pattern=r"\S"
    )
