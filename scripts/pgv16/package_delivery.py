#!/usr/bin/env python3
"""PGV-16 package_delivery: ZIP новых/обновлённых файлов текущей задачи
в открытый контейнер сессии (download/) + files.txt (паритет pgv13/14/15)."""
from __future__ import annotations
import hashlib, zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = Path("/home/z/my-project/download")
OUT.mkdir(parents=True, exist_ok=True)

NEW = [
    # OPS-1: facts-only статус контейнера печати для /health/ops (§12)
    "apps/api/print_renderer_ops.py",
    # дизайн/риски/разрывы
    "docs/pgv16_security_retention_ops_coverage.md",
    # COV-1: fail-closed CERT-гейт покрытия реестра (§5)
    "scripts/pgv16/coverage_gate.py",
    "scripts/pgv16/package_delivery.py",
    "scripts/pgv16/protocols/red_python.txt",
    "scripts/pgv16/protocols/green_python.txt",
    "scripts/pgv16/protocols/green_gate_unit.txt",
    # SEC-1/SEC-2/RET-1/OPS-1 оракулы (TDD)
    "tests/api/test_pgv16_security_retention_ops.py",
    "tests/unit/test_pgv16_coverage_gate.py",
]
CHANGED = [
    # SEC-1: честная mandatory-тройка выдачи (content/preview)
    "apps/api/routers/documentation.py",
    # SEC-2: SSRF-префлайт внешних ресурсов screen_svg (AC19)
    "apps/api/visual_exports.py",
    # RET-1: registry.list_print_renditions (ABC/Memory/Postgres)
    "apps/api/document_jobs.py",
    # RET-1: sweep печатных renditions + retention_print_days()
    "apps/api/document_lifecycle.py",
    # OPS-1: секция print_renderer в /health/ops
    "apps/api/main.py",
    # COV-1: registry_version (FNV-1a/64) в сериализаторе реестра
    "packages/ui/lib/visualExportRegistry.ts",
    # перегенерированный штатным scripts/pgv00/export_registry.ts
    "config/visual_registry.json",
    # карта роутов AUTH-00: отпечатки источников (added=[]/removed=[])
    "docs/auth00/inventory.json",
    "docs/auth00/inventory.md",
    # new default-гейт pgv16 + раздел в описании
    "scripts/local_gates.py",
    "scripts/local_gates.md",
    # запись задачи
    "worklog/worklog12.md",
]
FILES = NEW + CHANGED

missing = [f for f in FILES if not (ROOT / f).exists()]
assert not missing, f"файлы поставки отсутствуют: {missing}"

zip_path = OUT / "cisstat-pgv16-security-retention-ops-coverage.zip"
with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
    for rel in FILES:
        zf.write(ROOT / rel, arcname=rel)
    manifest = "\n".join(
        f"{hashlib.sha256((ROOT / f).read_bytes()).hexdigest()}  {f}" for f in FILES
    )
    zf.writestr("files.txt", "\n".join(FILES) + "\n\nSHA256:\n" + manifest + "\n")
print(f"OK: {zip_path} -- {len(FILES)} файлов, {zip_path.stat().st_size} байт")
