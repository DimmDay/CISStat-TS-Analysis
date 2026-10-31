#!/usr/bin/env python3
# scripts/pgv11/package_delivery.py
"""Упаковка поставки PGV-11: zip только новых/изменённых файлов текущей
задачи. Сверяет точное множество, побайтное содержимое каждого файла
архива и печатает SHA-256. Без внешней сети; AGENTS.md: без commit/push."""
from __future__ import annotations

import hashlib
import sys
import zipfile
from pathlib import Path

REPO = Path("/home/z/my-project/CISStat-TS-Analysis")
OUT = Path("/home/z/my-project/download/cisstat-pgv11-eda-tasks-exports.zip")

# (путь, статус: N=new, M=modified)
FILES: list[tuple[str, str]] = [
    # ── backend ──
    ("apps/api/visual_exports.py", "M"),
    ("apps/api/visual_producers.py", "M"),
    ("apps/api/print_render_payload.py", "M"),
    # ── UI: кнопки экспорта ──
    ("packages/ui/components/EdaDescriptiveOverview.tsx", "M"),
    ("packages/ui/components/EdaCorrelationOverview.tsx", "M"),
    ("packages/ui/components/EdaIhOverview.tsx", "M"),
    ("packages/ui/components/EdaSeasonalityOverview.tsx", "M"),
    ("packages/ui/components/EdaStationarityOverview.tsx", "M"),
    ("packages/ui/components/EdaDistributionOverview.tsx", "M"),
    ("packages/ui/components/EdaStructuralBreaksOverview.tsx", "M"),
    ("packages/ui/components/EdaFeatureSelectionOverview.tsx", "M"),
    ("packages/ui/components/EdaValidationStrategyOverview.tsx", "M"),
    ("packages/ui/components/EdaModelMatrixOverview.tsx", "M"),
    ("packages/ui/components/TasksCauses.tsx", "M"),
    ("packages/ui/lib/visualExportRegistry.pgv11coverage.test.ts", "N"),
    # ── тесты ──
    ("tests/api/test_pgv11_visual_exports.py", "N"),
    ("tests/api/test_pgv10_visual_exports.py", "M"),
    ("tests/api/test_p10cert_oracles.py", "M"),
    # ── AUTH-00 карта роутов ──
    ("docs/auth00/policy_review.json", "M"),
    ("docs/auth00/inventory.json", "M"),
    ("docs/auth00/inventory.md", "M"),
    ("docs/auth00/operation_variants.md", "M"),
    # ── документация/скрипты поставки ──
    ("docs/pgv11_eda_tasks_exports.md", "N"),
    ("scripts/pgv11/check_routes_auth00.py", "N"),
    ("scripts/pgv11/wire_ui.py", "N"),
    ("scripts/pgv11/package_delivery.py", "N"),
    ("scripts/pgv11/preview_server.py", "N"),
    ("scripts/pgv11/protocols/red_protocol.txt", "N"),
    ("worklog/worklog11.md", "M"),
]


def main() -> int:
    missing = [p for p, _ in FILES if not (REPO / p).is_file()]
    if missing:
        print("MISSING FILES:", missing)
        return 1
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED) as zf:
        for rel, _ in FILES:
            zf.write(REPO / rel, arcname="CISStat-TS-Analysis/" + rel)
    # Побайтная сверка каждого файла архива с рабочим деревом.
    bad: list[str] = []
    with zipfile.ZipFile(OUT) as zf:
        names = set(zf.namelist())
        expected = {"CISStat-TS-Analysis/" + p for p, _ in FILES}
        if names != expected:
            print("SET MISMATCH:", sorted(names ^ expected))
            return 1
        for rel, _ in FILES:
            if zf.read("CISStat-TS-Analysis/" + rel) != (REPO / rel).read_bytes():
                bad.append(rel)
    if bad:
        print("BYTE MISMATCH:", bad)
        return 1
    digest = hashlib.sha256(OUT.read_bytes()).hexdigest()
    print(
        "OK",
        OUT.name,
        f"{OUT.stat().st_size} bytes",
        f"{len(FILES)} files",
        f"sha256={digest}",
        sep=" | ",
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
