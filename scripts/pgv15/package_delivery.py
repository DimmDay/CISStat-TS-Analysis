#!/usr/bin/env python3
"""PGV-15 package_delivery: ZIP новых/обновлённых файлов текущей задачи
в открытый контейнер сессии (download/) + files.txt (паритет pgv13/14)."""
from __future__ import annotations
import hashlib, zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = Path("/home/z/my-project/download")
OUT.mkdir(parents=True, exist_ok=True)

NEW = [
    "apps/api/routers/documentation.py",  # +1 маршрут GET print-documents (PGV-15)
    "tests/api/test_pgv15_print_documents_ui.py",
    "packages/ui/lib/passportDocuments.ts",
    "packages/ui/lib/passportDocuments.test.ts",
    "packages/ui/components/PassportDocumentsPanel.tsx",
    "packages/ui/components/PassportDocumentsPanel.test.tsx",
    "packages/ui/components/PrintDocumentsPanel.tsx",
    "packages/ui/components/PrintDocumentsPanel.test.tsx",
    "packages/ui/components/DocumentationWorkspace.pgv15.test.tsx",
    "docs/pgv15_documents_picker_ui.md",
    "scripts/pgv15/check_routes_auth00.py",
    "scripts/pgv15/update_route_map.py",
    "scripts/pgv15/package_delivery.py",
    "scripts/pgv15/protocols/red_python.txt",
    "scripts/pgv15/protocols/red_ts.txt",
    "scripts/pgv15/protocols/green_python.txt",
    "scripts/pgv15/protocols/green_ts_pgv15.txt",
    "scripts/pgv15/protocols/check_routes_pgv15.txt",
]
CHANGED = [
    # сервис/роутер: листинг печатных документов (PGV-15)
    "apps/api/document_jobs.py",
    # клиент документации: аддитивные поля ready job DTO (PGV-14 паритет)
    "packages/ui/lib/documentation.ts",
    # DocumentationWorkspace: фильтр семейств (§10.2)
    "packages/ui/components/DocumentationWorkspace.tsx",
    # экспорт компонентов/типов
    "packages/ui/index.ts",
    # PGV-00 coverage-оракул: исключение пикера печатных семейств (+JSON-твин)
    "packages/ui/lib/visualExportRegistry.ts",
    "packages/ui/lib/visualExportRegistry.coverage.test.ts",
    "packages/ui/lib/visualExportRegistry.pgv00fix.test.ts",
    "config/visual_registry.json",
    # тёмная тема: аддитивная 4-я бейдж-область (пин количества h2)
    "packages/ui/doclog4-badge-dark.test.tsx",
    # карта роутов AUTH-00/AUTH-01 и производные (аддитивно +1 READ)
    "apps/api/access_registry.v1.json",
    "docs/auth00/inventory.json",
    "docs/auth00/inventory.md",
    "docs/auth00/policy_review.json",
    "packages/ui/server/proxy-routes.generated.json",
    "packages/ui/lib/access-contract.generated.ts",
    "docs/auth01/openapi.json",
    # эксплуатационная документация
    "scripts/local_gates.md",
    "worklog/worklog12.md",
]
FILES = NEW + CHANGED

missing = [f for f in FILES if not (ROOT / f).exists()]
assert not missing, f"файлы поставки отсутствуют: {missing}"

zip_path = OUT / "cisstat-pgv15-documents-picker-ui.zip"
with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
    for rel in FILES:
        zf.write(ROOT / rel, arcname=rel)
    manifest = "\n".join(
        f"{hashlib.sha256((ROOT / f).read_bytes()).hexdigest()}  {f}" for f in FILES
    )
    zf.writestr("files.txt", "\n".join(FILES) + "\n\nSHA256:\n" + manifest + "\n")
print(f"OK: {zip_path} -- {len(FILES)} файлов, {zip_path.stat().st_size} байт")
