#!/usr/bin/env python3
"""PGV-13 package_delivery: ZIP новых/обновлённых файлов текущей задачи
в открытый контейнер сессии (download/) + files.txt (паритет pgv11/12)."""
from __future__ import annotations
import hashlib, zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = Path("/home/z/my-project/download")
OUT.mkdir(parents=True, exist_ok=True)

NEW = [
    "apps/api/passport_documents.py",
    "tests/api/test_pgv13_passport_documents.py",
    "docs/pgv13_passport_documents.md",
    "scripts/pgv13/check_routes_auth00.py",
    "scripts/pgv13/package_delivery.py",
    "scripts/pgv13/protocols/red_python.txt",
    "scripts/pgv13/protocols/red_ts.txt",
    "scripts/pgv13/protocols/green_targeted.txt",
    "scripts/pgv13/protocols/green_ts_affected.txt",
    "scripts/pgv13/protocols/regression_affected.txt",
    "scripts/pgv13/protocols/check_routes_pgv13.txt",
]
CHANGED = [
    # durable слой/валидаторы/freeze
    "apps/api/artifact_store.py",
    "apps/api/artifact_promotion.py",
    "apps/api/visual_artifacts.py",
    # builders/lifecycle мост рендера и печатный каталог basis
    "apps/api/print_render_payload.py",
    "apps/api/document_jobs.py",
    # роутер документации (2 новых маршрута)
    "apps/api/routers/documentation.py",
    # контейнер рендера (секции паспорта/сравнения)
    "apps/print-renderer/src/rendererCore.tsx",
    "apps/print-renderer/src/rendererCore.test.ts",
    # карта роутов AUTH-00 и производные (аддитивно +2)
    "apps/api/access_registry.v1.json",
    "docs/auth00/inventory.json",
    "docs/auth00/inventory.md",
    "docs/auth00/policy_review.json",
    "packages/ui/server/proxy-routes.generated.json",
    "packages/ui/lib/access-contract.generated.ts",
    "docs/auth01/openapi.json",
    # затронутые пины/гварды
    "tests/api/test_pgv02_durable_inputs.py",
    # эксплуатационная документация
    "scripts/local_gates.md",
    "worklog/worklog12.md",
]
FILES = NEW + CHANGED

missing = [f for f in FILES if not (ROOT / f).exists()]
assert not missing, f"файлы поставки отсутствуют: {missing}"

zip_path = OUT / "cisstat-pgv13-passport-documents.zip"
with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
    for rel in FILES:
        zf.write(ROOT / rel, arcname=rel)
    manifest = "\n".join(
        f"{hashlib.sha256((ROOT / f).read_bytes()).hexdigest()}  {f}" for f in FILES
    )
    zf.writestr("files.txt", "\n".join(FILES) + "\n\nSHA256:\n" + manifest + "\n")
print(f"OK: {zip_path} -- {len(FILES)} файлов, {zip_path.stat().st_size} байт")
