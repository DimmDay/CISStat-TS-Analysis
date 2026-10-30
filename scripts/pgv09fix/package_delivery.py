#!/usr/bin/env python3
# scripts/pgv09fix/package_delivery.py
"""Упаковка поставки PGV-09-FIX: ZIP новых/обновлённых файлов ТОЛЬКО
по текущей задаче (AGENTS.md). Сверяет точное множество файлов и
каждый файл побайтно после записи архива; CRC-32 и SHA-256 архива
печатаются (сам манифест не ведётся -- конвенция серии).

Запуск из корня репозитория:
    python3 scripts/pgv09fix/package_delivery.py <zip-path>
"""
from __future__ import annotations

import hashlib
import sys
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

DELIVERY_FILES: tuple[str, ...] = (
    # -- новые (PGV-09-FIX) --
    "apps/api/migrations/0018_pgv9fix_print_rendition_keys.sql",
    "tests/api/test_pgv09fix_write_path.py",
    "scripts/pgv09fix/verify_local.py",
    "scripts/pgv09fix/mutation_campaign.py",
    "scripts/pgv09fix/package_delivery.py",
    "scripts/pgv09fix/preview_server.py",
    "scripts/pgv09fix/protocols/red_evidence.txt",
    "scripts/pgv09fix/protocols/green_evidence.txt",
    "scripts/pgv09fix/protocols/fix_mutation_campaign.json",
    "scripts/pgv09fix/protocols/verify_local.json",
    # -- обновлённые --
    "apps/api/document_jobs.py",
    "apps/api/png_renderer_client.py",
    "apps/api/research_runs.py",
    "docs/pgv09_jobs_renderer_integration.md",
    "tests/api/test_doclog3_telemetry_audit.py",
    "tests/api/test_doclog4_document_delivery.py",
    "tests/api/test_doclog5_formats_worker.py",
    "tests/api/test_doclog6_approvals_archive.py",
    "tests/api/test_doclog7_logs_support.py",
    "tests/api/test_doclog8_monitoring.py",
    "tests/api/test_doclog9_profiles.py",
    "worklog/worklog11.md",
)


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: package_delivery.py <zip-path>", file=sys.stderr)
        return 2
    zip_path = Path(sys.argv[1])
    zip_path.parent.mkdir(parents=True, exist_ok=True)

    missing = [rel for rel in DELIVERY_FILES if not (REPO_ROOT / rel).is_file()]
    if missing:
        print("MISSING FILES:", missing, file=sys.stderr)
        return 1

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for rel in DELIVERY_FILES:
            zf.write(REPO_ROOT / rel, arcname=rel)

    with zipfile.ZipFile(zip_path) as zf:
        names = sorted(zf.namelist())
        expected = sorted(DELIVERY_FILES)
        if names != expected:
            print("NAME MISMATCH:", set(names) ^ set(expected), file=sys.stderr)
            return 1
        for rel in DELIVERY_FILES:
            data = zf.read(rel)
            if hashlib.sha256(data).hexdigest() != hashlib.sha256(
                (REPO_ROOT / rel).read_bytes()
            ).hexdigest():
                print("BYTE MISMATCH:", rel, file=sys.stderr)
                return 1
        bad = zf.testzip()
        if bad is not None:
            print("CRC FAIL:", bad, file=sys.stderr)
            return 1

    size = zip_path.stat().st_size
    sha = hashlib.sha256(zip_path.read_bytes()).hexdigest()
    print(f"ZIP OK: {zip_path} ({size} bytes, {len(DELIVERY_FILES)} files)")
    print(f"zip_sha256: {sha}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
