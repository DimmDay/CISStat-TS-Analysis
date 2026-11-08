"""Local calibrated profile integrity and exact environment compatibility; no fallback."""

import hashlib, os, platform
from pathlib import Path
from importlib import metadata
from pydantic import Field, model_validator
from .contract import Contract, digest_payload
from .compute_units import Coefficient, Workload, quote_work

ROOT = Path(__file__).resolve().parents[3]
PACKAGES = (
    "numpy",
    "pandas",
    "scipy",
    "statsmodels",
    "ruptures",
    "scikit-learn",
    "xgboost",
    "lightgbm",
    "catboost",
    "arch",
    "prophet",
    "statsforecast",
    "torch",
    "neuralforecast",
)


def kernel_digest():
    paths = [
        "apps/api/backtesting.py",
        "apps/api/modeling_tuning.py",
        "apps/api/model_execution.py",
        "apps/api/model_jobs.py",
        "app/eda/structural_breaks.py",
        "rules/modeling.yaml",
        "apps/api/routers/models.py",
    ]
    paths += [
        p.relative_to(ROOT).as_posix()
        for p in (ROOT / "apps/api/billing").glob("compute*.py")
    ]
    paths += [
        "apps/api/workers/process.py",
        "apps/api/workers/child.py",
        "apps/api/workers/execution.py",
        "apps/api/workers/bridge.py",
    ]
    paths += sorted(
        p.relative_to(ROOT).as_posix()
        for p in (ROOT / "apps/api/model_impls").glob("*.py")
    )
    return digest_payload(
        {
            p: hashlib.sha256(
                (ROOT / p).read_bytes().replace(b"\r\n", b"\n")
            ).hexdigest()
            for p in paths
        }
    )


def machine():
    cpu = platform.processor() or platform.machine()
    try:
        for line in Path("/proc/cpuinfo").read_text().splitlines():
            if line.startswith("model name"):
                cpu = line.split(":", 1)[1].strip()
                break
    except OSError:
        pass
    memory = None
    try:
        memory = os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
    except (OSError, ValueError, AttributeError):
        pass
    cpus = max(1, os.cpu_count() or 1)
    quota = None
    try:
        q, period = Path("/sys/fs/cgroup/cpu.max").read_text().split()
        if q != "max":
            quota = (int(q) * 1000) // int(period)
    except (OSError, ValueError):
        try:
            q = int(Path("/sys/fs/cgroup/cpu/cpu.cfs_quota_us").read_text())
            period = int(Path("/sys/fs/cgroup/cpu/cpu.cfs_period_us").read_text())
            if q > 0:
                quota = q * 1000 // period
        except (OSError, ValueError):
            pass
    try:
        value = Path("/sys/fs/cgroup/memory.max").read_text().strip()
        if value != "max":
            memory = min(memory or int(value), int(value))
    except (OSError, ValueError):
        try:
            limit = int(Path("/sys/fs/cgroup/memory/memory.limit_in_bytes").read_text())
            memory = min(memory or limit, limit)
        except (OSError, ValueError):
            pass
    versions = {}
    for name in PACKAGES:
        try:
            versions[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            versions[name] = None
    return {
        "system": platform.system(),
        "machine": platform.machine(),
        "cpu": cpu,
        "logical_cpus": cpus,
        "cpu_quota_milli": quota,
        "memory_limit_bytes": memory,
        "python": platform.python_version(),
        "packages": versions,
    }


class Profile(Contract):
    schema_version: str = "auth14.profile/1"
    environment: dict
    kernels: str = Field(pattern=r"^[0-9a-f]{64}$")
    evidence_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    coefficients: tuple[Coefficient, ...] = Field(min_length=1)
    max_concurrency: int = Field(ge=1, le=32, strict=True)

    @model_validator(mode="after")
    def unique(self):
        if self.schema_version != "auth14.profile/1" or len(
            {c.key for c in self.coefficients}
        ) != len(self.coefficients):
            raise ValueError("invalid calibrated profile")
        return self

    @property
    def digest(self):
        return digest_payload(self.model_dump(mode="json"))

    def quote(self, work: Workload):
        coefficient = next((c for c in self.coefficients if c.key == work.key), None)
        if coefficient is None:
            raise ValueError("operation has no measured coefficient")
        return quote_work(work, coefficient, profile_hash=self.digest).model_copy(
            update={"capacity": self.max_concurrency}
        )

    def check_environment(self):
        if self.environment != machine() or self.kernels != kernel_digest():
            raise ValueError("calibration environment changed")


def load_profile():
    path = os.environ.get("CISSTAT_CU_PROFILE", "").strip()
    expected = os.environ.get("CISSTAT_CU_PROFILE_SHA256", "").strip()
    if not path and not expected:
        return None
    if not path or not expected:
        raise ValueError("profile path and pinned checksum required")
    p = Path(path)
    if p.stat().st_size > 4 * 1024 * 1024:
        raise ValueError("profile too large")
    profile = Profile.model_validate_json(p.read_bytes())
    if profile.digest != expected:
        raise ValueError("profile checksum changed")
    profile.check_environment()
    return profile
