#!/usr/bin/env python3
"""DOCLOG-5-CERT: мутационная кампания («мутанты на своих мутантах»).

Двухканальная схема:
  REPO    -- tests/api/test_doclog5_formats_worker.py + doclog4 пины;
  ORACLE  -- scripts/doclog5cert (собственный корпус сертификатора).

Классификация: DUAL-KILLED / REPO-ONLY / ORACLE-ONLY / SURVIVED.
Контрольные (no-op) мутанты обязаны остаться ALIVE в обоих каналах.

Мета-валидация («мутанты на своих мутантах»):
  MV1 patch-applies: каждый мутант обязан реально применяться
      (якорная строка найдена ровно один раз);
  MV2 classifier self-test: классификатор сверен с синтетикой
      (pass/pass=SURVIVED, fail/fail=DUAL, repo-only, oracle-only);
  MV3 RESTORE-FAIL: после каждого мутанта дерево обязано быть
      восстановлено байт-в-байт (счётчик должен быть 0);
  MV4 controls: 3 no-op контроля ALIVE (каналы не «косят» всё).

Resume: существующие protocols/mut_<name>.json не пересчитываются.
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

REPO = Path("/home/z/my-project/CISStat-TS-Analysis")
CERT_DIR = REPO / "scripts" / "doclog5cert"
PROTOCOLS = CERT_DIR / "protocols"

WORKER = REPO / "apps" / "api" / "document_render_worker.py"
JOBS = REPO / "apps" / "api" / "document_jobs.py"
RENDS = REPO / "apps" / "api" / "document_renditions.py"
ROUTER = REPO / "apps" / "api" / "routers" / "documentation.py"

REPO_CMD = [
    sys.executable, "-m", "pytest",
    "tests/api/test_doclog5_formats_worker.py",
    "tests/api/test_doclog4_document_delivery.py",
    "-q", "--tb=no", "-p", "no:cacheprovider",
]
ORACLE_CMD = [
    sys.executable, "-m", "pytest",
    "scripts/doclog5cert/test_d5cert_oracle_unit.py",
    "scripts/doclog5cert/test_d5cert_oracle_api.py",
    "scripts/doclog5cert/test_d5cert_oracle_static.py",
    "-q", "--tb=no", "-p", "no:cacheprovider",
]

# ── Мутанты: (имя, файл, старое, новое, класс) ────────────────────────

BATTLE: list[tuple[str, Path, str, str]] = [
    ("M01_steal_live_lease", WORKER,
     '''        for job in registry.list_open_jobs(limit=100):
            if job.state != JOB_RENDERING:
                continue
            expires = self._parse_iso(job.lease_expires_at or "")
            if expires is None or expires >= now:
                continue''',
     '''        for job in registry.list_open_jobs(limit=100):
            if job.state != JOB_RENDERING:
                continue
            expires = self._parse_iso(job.lease_expires_at or "")
            if expires is None:
                continue'''),
    ("M02_reclaim_attempt_grows", WORKER,
     '''                    state=JOB_QUEUED,
                    error_code="lease_reclaimed",
                    claimed_at=None,''',
     '''                    state=JOB_QUEUED,
                    error_code="lease_reclaimed",
                    attempt=job.attempt + 1,
                    claimed_at=None,'''),
    ("M03_reclaim_keeps_lease", WORKER,
     '''                    error_code="lease_reclaimed",
                    claimed_at=None,
                    lease_expires_at=None,''',
     '''                    error_code="lease_reclaimed",'''),
    ("M04_batch_over_by_one", WORKER,
     "            if len(claims) >= self._batch_size:",
     "            if len(claims) > self._batch_size:"),
    ("M05_tenant_over_limit", WORKER,
     "            if active_tenants[tenant] >= self._per_tenant_limit:",
     "            if active_tenants[tenant] > self._per_tenant_limit:"),
    ("M06_extra_attempt_before_terminal", WORKER,
     "if error_code in TRANSIENT_ERROR_CODES and job.attempt < self._max_attempts:",
     "if error_code in TRANSIENT_ERROR_CODES and job.attempt <= self._max_attempts:"),
    ("M07_no_attempt_increment", WORKER,
     "                    error_code=error_code,\n                    attempt=job.attempt + 1,",
     "                    error_code=error_code,\n                    attempt=job.attempt,"),
    ("M08_timeout_not_transient", WORKER,
     'TRANSIENT_ERROR_CODES = frozenset({"render_failed", "render_timeout"})',
     'TRANSIENT_ERROR_CODES = frozenset({"render_failed"})'),
    ("M09_unsupported_requeued", WORKER,
     'TRANSIENT_ERROR_CODES = frozenset({"render_failed", "render_timeout"})',
     'TRANSIENT_ERROR_CODES = frozenset({"render_failed", "render_timeout", "unsupported_format"})'),
    ("M10_timeout_never_raised", WORKER,
     "        if thread.is_alive():",
     "        if False:"),
    ("M11_integrity_check_off", WORKER,
     "        if actual != record.payload_sha256:",
     "        if False:"),
    ("M12_snapshot_hash_not_merged", WORKER,
     "    merged.payload_sha256 = record.payload_sha256",
     '    merged.payload_sha256 = ""'),
    ("M13_rendition_never_registered", JOBS,
     '''        if existing is not None:
            rendition = self.registry.update_rendition(rendition)
        else:
            rendition = self.registry.register_rendition(rendition)
        job = self.registry.update_job(
            replace_dataclass(
                job, state=JOB_READY, rendition_id=rendition.rendition_id
            )
        )''',
     '''        rendition = existing
        job = self.registry.update_job(
            replace_dataclass(
                job, state=JOB_READY, rendition_id=(
                    rendition.rendition_id if rendition else ""
                )
            )
        )'''),
    ("M14_p1_snapshot_hash_empty", JOBS,
     "            snapshot_payload_sha256=snapshot.payload_sha256 or \"\",",
     '            snapshot_payload_sha256="",'),
    ("M15_no_active_dup", JOBS,
     "        if active is not None:\n            return active, None",
     "        if False:\n            return active, None"),
    ("M16_retry_limit_off_by_one", JOBS,
     "        if len(prior_jobs) >= MAX_JOB_ATTEMPTS:",
     "        if len(prior_jobs) > MAX_JOB_ATTEMPTS:"),
    ("M17_quota_off_by_one", JOBS,
     "        if len(tenant_open) >= MAX_OPEN_JOBS_PER_TENANT:",
     "        if len(tenant_open) > MAX_OPEN_JOBS_PER_TENANT:"),
    ("M18_heavy_rendered_sync", JOBS,
     "        if format in HEAVY_RENDITION_FORMATS:",
     "        if False:"),
    ("M19_failed_job_keeps_ready_rendition", JOBS,
     '''        if existing is not None:
            self.registry.update_rendition(
                replace_dataclass(
                    existing, state=RENDITION_FAILED, job_id=job.job_id
                )
            )''',
     '''        if False:
            self.registry.update_rendition(
                replace_dataclass(
                    existing, state=RENDITION_FAILED, job_id=job.job_id
                )
            )'''),
    ("M20_content_integrity_off", JOBS,
     "        if artifact_content_sha256(content) != rendition.content_sha256:",
     "        if False:"),
    ("M21_retry_429_becomes_500", ROUTER,
     '''    if isinstance(exc, DocumentRetryLimitExceeded):
        # §18 retries: исчерпаны попытки рендера -- честный 429.
        return HTTPException(
            status_code=429,''',
     '''    if isinstance(exc, DocumentRetryLimitExceeded):
        # §18 retries: исчерпаны попытки рендера -- честный 429.
        return HTTPException(
            status_code=500,'''),
    ("M22_xlsx_formula_allowed", RENDS,
     '''    cell = sheet.cell(row=row, column=column, value=_xlsx_cell_text(value))
    if cell.data_type == "f":
        cell.data_type = "s"
    return cell''',
     '''    cell = sheet.cell(row=row, column=column, value=_xlsx_cell_text(value))
    return cell'''),
    ("M23_svg_label_unescaped", RENDS,
     '''            f"{escape(label)}</text>"''',
     '''            f"{label}</text>"'''),
    ("M24_zip_fixed_date_changed", RENDS,
     "            info = zipfile.ZipInfo(name, date_time=_ZIP_FIXED_DATE_TIME)",
     "            info = zipfile.ZipInfo(name, date_time=(2026, 10, 23, 12, 0, 0))"),
    ("M25_pdf_nondeterministic", RENDS,
     "        invariant=1,",
     "        invariant=0,"),
    ("M26_xlsx_truncation_over_excel", RENDS,
     "MAX_XLSX_CELL_CHARS = 32767  # предел Excel для ячейки",
     "MAX_XLSX_CELL_CHARS = 40000  # предел Excel для ячейки"),
    ("M27_parquet_refs_as_string", RENDS,
     '''            "event_refs": list(claim.get("event_refs", [])),
            "result_refs": list(claim.get("result_refs", [])),
            "event_count": (''',
     '''            "event_refs": ", ".join(claim.get("event_refs", [])),
            "result_refs": list(claim.get("result_refs", [])),
            "event_count": ('''),
]

CONTROLS: list[tuple[str, Path, str, str]] = [
    ("C1_docstring_only", WORKER,
     "in-process worker асинхронного рендера тяжёлых форматов документов",
     "in-process worker асинхронного рендера тяжёлых форматов документов (no-op контроль C1)"),
    ("C2_comment_only", JOBS,
     "# DOCLOG-5 (§18/§11): пределы рендер-контура. MAX_JOB_ATTEMPTS --",
     "# DOCLOG-5 (§18/§11) [контроль C2]: пределы рендер-контура. MAX_JOB_ATTEMPTS --"),
    ("C3_comment_only", RENDS,
     "MAX_XLSX_CELL_CHARS = 32767  # предел Excel для ячейки",
     "MAX_XLSX_CELL_CHARS = 32767  # предел Excel для ячейки (контроль C3)"),
]


def classify(repo_ok: bool, oracle_ok: bool) -> str:
    """MV2-классификатор (сверен с синтетикой в self_test)."""
    if repo_ok and oracle_ok:
        return "SURVIVED"
    if not repo_ok and not oracle_ok:
        return "DUAL-KILLED"
    if not repo_ok and oracle_ok:
        return "REPO-ONLY"
    return "ORACLE-ONLY"


def self_test_classifier() -> bool:
    return (
        classify(True, True) == "SURVIVED"
        and classify(False, False) == "DUAL-KILLED"
        and classify(False, True) == "REPO-ONLY"
        and classify(True, False) == "ORACLE-ONLY"
    )


def run_channel(cmd: list[str], cwd: Path, timeout: int = 240) -> tuple[bool, str]:
    result = subprocess.run(
        cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout
    )
    tail = "\n".join(result.stdout.strip().splitlines()[-6:])
    return result.returncode == 0, tail


def apply_mutant(path: Path, old: str, new: str) -> bool:
    """MV1: якорь обязан встречаться ровно один раз."""
    content = path.read_text(encoding="utf-8")
    if content.count(old) != 1:
        return False
    path.write_text(content.replace(old, new, 1), encoding="utf-8")
    return True


def restore(path: Path, original: str) -> bool:
    path.write_text(original, encoding="utf-8")
    return path.read_text(encoding="utf-8") == original


def run_one(name: str, path: Path, old: str, new: str, kind: str) -> dict:
    protocol_file = PROTOCOLS / f"mut_{name}.json"
    if protocol_file.exists():
        return json.loads(protocol_file.read_text(encoding="utf-8"))
    original = path.read_text(encoding="utf-8")
    entry: dict = {
        "name": name, "kind": kind, "file": path.name,
        "patch_applies": apply_mutant(path, old, new),  # MV1
    }
    if entry["patch_applies"]:
        time.sleep(0.2)
        repo_ok, repo_tail = run_channel(REPO_CMD, REPO)
        oracle_ok, oracle_tail = run_channel(ORACLE_CMD, REPO)
        entry.update({
            "repo_pass": repo_ok,
            "oracle_pass": oracle_ok,
            "classification": classify(repo_ok, oracle_ok),
            "repo_tail": repo_tail,
            "oracle_tail": oracle_tail,
            "restored": restore(path, original),  # MV3
        })
        if not entry["restored"]:
            entry["classification"] = "RESTORE-FAIL"
    else:
        entry.update({
            "repo_pass": None, "oracle_pass": None,
            "classification": "PATCH-FAIL", "restored": True,
        })
    protocol_file.write_text(
        json.dumps(entry, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    return entry


def main() -> int:
    PROTOCOLS.mkdir(parents=True, exist_ok=True)
    start = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    end = int(sys.argv[2]) if len(sys.argv) > 2 else 10**9
    universe = [
        (name, path, old, new, "battle")
        for name, path, old, new in BATTLE
    ] + [
        (name, path, old, new, "control")
        for name, path, old, new in CONTROLS
    ]
    if not self_test_classifier():
        print("MV2 classifier self-test FAILED")
        return 2
    print("MV2 classifier self-test OK")
    restore_failures = 0
    patch_failures = 0
    for index, (name, path, old, new, kind) in enumerate(universe):
        if not (start <= index < end):
            continue
        entry = run_one(name, path, old, new, kind)
        if entry["classification"] == "RESTORE-FAIL":
            restore_failures += 1
        if entry["classification"] == "PATCH-FAIL":
            patch_failures += 1
        print(
            f"[{index:02d}] {name:38s} {entry['classification']}"
        )
    print(f"restore_failures={restore_failures} patch_failures={patch_failures}")
    # сводка
    entries = []
    for name, path, old, new, kind in universe:
        f = PROTOCOLS / f"mut_{name}.json"
        if f.exists():
            entries.append(json.loads(f.read_text(encoding="utf-8")))
    summary = {
        "total": len(entries),
        "DUAL-KILLED": sum(e["classification"] == "DUAL-KILLED" for e in entries),
        "REPO-ONLY": sum(e["classification"] == "REPO-ONLY" for e in entries),
        "ORACLE-ONLY": sum(e["classification"] == "ORACLE-ONLY" for e in entries),
        "SURVIVED": sum(e["classification"] == "SURVIVED" for e in entries),
        "PATCH-FAIL": sum(e["classification"] == "PATCH-FAIL" for e in entries),
        "RESTORE-FAIL": sum(e["classification"] == "RESTORE-FAIL" for e in entries),
        "controls_alive": sum(
            e["classification"] == "SURVIVED"
            for e in entries if e["kind"] == "control"
        ),
    }
    (PROTOCOLS / "mutations_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
