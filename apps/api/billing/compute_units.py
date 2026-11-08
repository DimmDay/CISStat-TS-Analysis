"""Versioned fixed-point CU quotes over measured, bounded scientific work."""

from decimal import Decimal, localcontext, ROUND_CEILING, DecimalException
from typing import Literal
from pydantic import Field, field_validator, model_validator
from .contract import Contract, MAX_UNITS

RULE = "attempted-unit-ceil/1"


class Workload(Contract):
    key: str = Field(pattern=r"^(pelt|tuning:[a-z0-9_]+)$")
    rows: int = Field(gt=0, le=10**7, strict=True)
    columns: int = Field(gt=0, le=10000, strict=True)
    units: int = Field(gt=0, le=100000, strict=True)
    horizon: int = Field(default=1, gt=0, strict=True)
    seasonal_period: int = Field(default=1, gt=0, strict=True)
    grid_points: int = Field(default=1, gt=0, le=250, strict=True)
    folds: int = Field(default=1, gt=0, strict=True)
    trials: int = Field(default=1, gt=0, strict=True)

    @property
    def volume(self):
        return self.rows * self.columns * self.grid_points


class Coefficient(Contract):
    key: str
    base_micro_cu: Decimal = Field(gt=0, le=MAX_UNITS)
    exponent: Decimal = Field(ge=0, le=3)
    min_rows: int = Field(default=1, gt=0, strict=True)
    max_rows: int = Field(gt=0, strict=True)
    max_columns: int = Field(gt=0, strict=True)
    max_units: int = Field(gt=0, le=100000, strict=True)
    max_horizon: int = Field(gt=0, strict=True)
    max_period: int = Field(gt=0, strict=True)
    max_folds: int = Field(default=64, gt=0, strict=True)
    max_trials: int = Field(default=64, gt=0, strict=True)
    wall_ms: int = Field(gt=0, le=7200000, strict=True)
    memory_mb: int = Field(gt=0, le=4096, strict=True)

    @field_validator("base_micro_cu", "exponent")
    @classmethod
    def finite(cls, value):
        if not value.is_finite():
            raise ValueError("finite measured coefficient required")
        return value

    @model_validator(mode="after")
    def domain(self):
        if self.min_rows > self.max_rows:
            raise ValueError("empty measured domain")
        return self


class Quote(Contract):
    rule: Literal["attempted-unit-ceil/1"] = RULE
    profile_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    workload: Workload
    coefficient: Coefficient
    unit_micro_cu: int = Field(gt=0, le=MAX_UNITS, strict=True)
    capacity: int = Field(default=1, ge=1, le=32, strict=True)

    @property
    def reserved_micro_cu(self):
        return self.unit_micro_cu * self.workload.units

    @property
    def version(self):
        return "cu14/" + self.profile_hash


def quote_work(work: Workload, coefficient: Coefficient, *, profile_hash: str) -> Quote:
    c = coefficient
    if work.key != c.key or not c.min_rows <= work.rows <= c.max_rows:
        raise ValueError("work outside measured domain")
    for actual, maximum in (
        (work.columns, c.max_columns),
        (work.units, c.max_units),
        (work.horizon, c.max_horizon),
        (work.seasonal_period, c.max_period),
        (work.folds, c.max_folds),
        (work.trials, c.max_trials),
    ):
        if actual > maximum:
            raise ValueError("work exceeds calibrated ceiling")
    try:
        with localcontext() as ctx:
            ctx.prec = 60
            value = c.base_micro_cu * (Decimal(work.volume) ** c.exponent)
            unit = int(value.to_integral_value(rounding=ROUND_CEILING))
    except (DecimalException, OverflowError):
        raise ValueError("CU overflow") from None
    if not 1 <= unit <= MAX_UNITS or unit > MAX_UNITS // work.units:
        raise ValueError("CU overflow")
    return Quote(
        profile_hash=profile_hash, workload=work, coefficient=c, unit_micro_cu=unit
    )


def charge_units(quote: Quote, units: int) -> int:
    if type(units) is not int or not 0 <= units <= quote.workload.units:
        raise ValueError("actual work exceeds reservation")
    return units * quote.unit_micro_cu
