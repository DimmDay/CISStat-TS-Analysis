#!/usr/bin/env python3
"""PGV-12 package_delivery: ZIP новых/обновлённых файлов текущей задачи
в открытый контейнер сессии (download/) + files.txt (паритет pgv11)."""
from __future__ import annotations
import hashlib, zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = Path("/home/z/my-project/download")
OUT.mkdir(parents=True, exist_ok=True)

NEW = [
    "tests/api/test_pgv12_visual_exports.py",
    "packages/ui/lib/visualExportRegistry.pgv12coverage.test.ts",
    "docs/pgv12_modeling_forecast_exports.md",
    "scripts/pgv12/check_routes_auth00.py",
    "scripts/pgv12/package_delivery.py",
    "scripts/pgv12/protocols/red_protocol.txt",
]
CHANGED = [
    "apps/api/visual_producers.py",
    "apps/api/visual_exports.py",
    "apps/api/routers/modeling_session.py",
    "apps/api/routers/forecasting_session.py",
    "apps/api/routers/monitoring.py",
    "packages/ui/lib/visualExportRegistry.ts",
    "packages/ui/lib/visualExportRegistry.coverage.test.ts",
    "packages/ui/lib/visualExportRegistry.pgv00fix.test.ts",
    "config/visual_registry.json",
    "packages/ui/components/ModelingWorkflowOverview.tsx",
    "packages/ui/components/ModelingTraceabilityOverview.tsx",
    "packages/ui/components/BacktestComparisonChart.tsx",
    "packages/ui/components/BacktestOofChart.tsx",
    "packages/ui/components/TsAnalysisModeling.tsx",
    "packages/ui/components/TsAnalysisForecasting.tsx",
    "packages/ui/components/ForecastAccuracyPanel.tsx",
    "packages/ui/components/MonitoringComparisonPanel.tsx",
    "packages/ui/components/ForecastExportMenu.tsx",
    "worklog/worklog12.md",
    "docs/auth00/inventory.json",
    "docs/auth00/inventory.md",
    # Пиновые тесты, затронутые PGV-12 (denominator/скоуп/§10.1):
    "tests/api/test_pgv01_print_schema.py",
    "tests/api/test_pgv03_producer_adapters.py",
    "tests/api/test_pgv10_visual_exports.py",
    "tests/api/test_pgv11_visual_exports.py",
    "packages/ui/dkt5-open-questions.test.ts",
    "packages/ui/print/printSchema.test.ts",
    # Базовые страницы (byte-identical HEAD): без них inventory build
    # в клоне падает (page:*/upload unclassified) -- включены для
    # воспроизводимости; у тимлида уже в HEAD без изменений.
    "apps/embedded/app/upload/page.tsx",
    "apps/standalone/app/upload/page.tsx",
]
FILES = NEW + CHANGED
regression = ROOT / "scripts/pgv12/protocols/regression_full.txt"
if regression.exists() and regression.stat().st_size > 0:
    FILES.append("scripts/pgv12/protocols/regression_full.txt")

missing = [f for f in FILES if not (ROOT / f).exists()]
assert not missing, f"файлы поставки отсутствуют: {missing}"

zip_path = OUT / "cisstat-pgv12-modeling-forecast-exports.zip"
with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
    for rel in FILES:
        zf.write(ROOT / rel, arcname=rel)
    manifest = "\n".join(
        f"{hashlib.sha256((ROOT / f).read_bytes()).hexdigest()}  {f}" for f in FILES
    )
    zf.writestr("files.txt", "\n".join(FILES) + "\n\nSHA256:\n" + manifest + "\n")
print(f"OK: {zip_path} -- {len(FILES)} файлов, {zip_path.stat().st_size} байт")
