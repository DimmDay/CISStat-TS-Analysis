"""Finite integer resource amounts and canonical normalized-input identities."""

import hashlib
import json
from datetime import UTC, datetime
from typing import Literal

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from apps.api.access_registry import ModelWorkload

MAX_UNITS = 2**63 - 1


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)


class Cost(Contract):
    micro_cu: int = Field(ge=0, le=MAX_UNITS, strict=True)
    version: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9_.:/-]+$")


class Admission(Contract):
    entry_id: str = Field(min_length=1, max_length=240)
    resource_kind: Literal["run", "dataset", "stateless"]
    resource_id: str = Field(
        min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_.:-]+$"
    )
    idempotency_key: str = Field(min_length=1, max_length=128, repr=False)
    payload: dict = Field(repr=False)
    cost: Cost
    deadline: AwareDatetime
    analysis_run_id: str | None = Field(
        default=None, min_length=1, max_length=128, pattern=r"^RUN-[A-Za-z0-9-]+$"
    )
    slots: int = Field(default=1, ge=0, le=1, strict=True)
    workload: ModelWorkload | None = None
    stage: str | None = None

    @field_validator("deadline")
    @classmethod
    def normalize_deadline(cls, value):
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def paid_work_holds_slot(self):
        if self.cost.micro_cu and self.slots != 1:
            raise ValueError("CU work requires a concurrency reservation")
        return self


def digest_payload(value):
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
    return hashlib.sha256(encoded.encode()).hexdigest()


def utc_month(value: datetime):
    if value.tzinfo is None:
        raise ValueError("aware authority clock required")
    return value.astimezone(UTC).strftime("%Y-%m")
