#!/usr/bin/env python3
"""PGV-10 doc-contract гвард (паттерн scripts/pgv00..09/check_documents.py):
согласованность документации поставки с кодом и журналом.

Проверки:
  D1  -- docs/pgv10_visual_exports.md существует и несёт ключевые разделы;
  D2  -- спека §13 содержит строку PGV-10 (план -- не выполненные работы);
  D3  -- скоуп: 38 pgv-03 research view трёх остановок (реестр-твин);
  D4  -- API-маршруты §11: visual-sources + visuals зарегистрированы;
  D5  -- 12 добранных адаптеров отсутствуют в UNWIRED_PGV03_VIEWS;
  D6  -- identity снапшота: svg-член в visual_artifacts.py;
  D7  -- сериализация -- scoped (не document.querySelector);
  D8  -- coverage-гвард и тест-корпус существуют;
  D9  -- worklog11.md содержит запись Task ID: PGV-10 (2026-10-30).
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
CHECKS = 0
FAILED = 0


def check(condition: bool, label: str) -> None:
    global CHECKS, FAILED
    CHECKS += 1
    if condition:
        print(f"  ok  {label}")
    else:
        FAILED += 1
        print(f"FAIL  {label}")


def main() -> int:
    doc = REPO / "docs/pgv10_visual_exports.md"

    # D1 -- документ поставки
    check(doc.is_file(), "D1 docs/pgv10_visual_exports.md существует")
    if doc.is_file():
        text = doc.read_text(encoding="utf-8")
        for marker in (
            "PGV-10", "visual-sources", "screen_svg", "не первый SVG",
            "missing_section_content", "09c79aa", "дельта-0",
        ):
            check(marker in text, f"D1 маркер «{marker}» в документе")
    else:
        text = ""

    # D2 -- строка плана спеки
    spec = (REPO / "spec_passport_graphics_visual.md").read_text(encoding="utf-8")
    check(re.search(r"\|\s*PGV-10\s*\|", spec) is not None, "D2 спека §13 несёт строку PGV-10")

    # D3 -- скоуп 38
    registry = json.loads(
        (REPO / "config/visual_registry.json").read_text(encoding="utf-8")
    )
    scope = [
        site
        for site in registry["sites"]
        if site["module_id"] in ("upload", "validation", "preprocessing")
        and str(site.get("source_adapter", "")).startswith("pgv-03/")
        and site.get("applicability") != "static_demo"
    ]
    check(len(scope) == 38, f"D3 скоуп 38 view (факт {len(scope)})")

    # D4 -- маршруты
    docs_router = (REPO / "apps/api/routers/documentation.py").read_text(encoding="utf-8")
    check('"/runs/{run_id}/visual-sources"' in docs_router, "D4 GET visual-sources зарегистрирован")
    check('"/runs/{run_id}/visuals"' in docs_router, "D4 POST visuals зарегистрирован")

    # D5 -- добор адаптеров
    producers = (REPO / "apps/api/visual_producers.py").read_text(encoding="utf-8")
    unwired_match = re.search(
        r"UNWIRED_PGV03_VIEWS(?::\s*frozenset\[str\])?\s*=\s*frozenset\(\s*\{(.*?)\}\)",
        producers,
        re.S,
    )
    check(unwired_match is not None, "D5 UNWIRED_PGV03_VIEWS найден")
    if unwired_match:
        unwired = set(re.findall(r'"([a-z_.]+)"', unwired_match.group(1)))
        stale = [v for v in unwired if v.startswith("preprocessing.")]
        check(not stale, f"D5 UNWIRED без preprocessing (остались: {stale})")
        for view in (
            "preprocessing.regularity.overview", "preprocessing.regularity.gap_map",
            "preprocessing.decomposition.overview", "preprocessing.variance_stab.series",
            "preprocessing.variance_stab.diagnostics", "preprocessing.stationarity.overview",
            "preprocessing.spectral.periodogram", "preprocessing.feature_eng.overview",
            "preprocessing.scaling.overview",
        ):
            check(f'"{view}": _spec(' in producers, f"D5 адаптер {view}")

    # D6 -- svg-член identity
    artifacts = (REPO / "apps/api/visual_artifacts.py").read_text(encoding="utf-8")
    check("screen_svg_sha256" in artifacts, "D6 identity снапшота несёт screen_svg digest")

    # D7 -- сериализация scoped
    serializer = (REPO / "packages/ui/lib/serializeChartSvg.ts").read_text(encoding="utf-8")
    check('container.querySelector("svg")' in serializer, "D7 сериализация scoped (свой контейнер)")
    check("document.querySelector" not in serializer, "D7 без document.querySelector")

    # D8 -- тесты
    check(
        (REPO / "tests/api/test_pgv10_visual_exports.py").is_file(),
        "D8 тест-корпус PGV-10 существует",
    )
    check(
        (REPO / "packages/ui/lib/visualExportRegistry.pg10coverage.test.ts").is_file(),
        "D8 coverage-гвард существует",
    )

    # D9 -- worklog
    worklog = (REPO / "worklog/worklog11.md").read_text(encoding="utf-8")
    check("## Task ID: PGV-10 (2026-10-30)" in worklog, "D9 worklog11 содержит запись PGV-10")

    print(f"\nИтог: {CHECKS - FAILED}/{CHECKS}")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
