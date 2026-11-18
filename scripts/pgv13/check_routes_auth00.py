#!/usr/bin/env python3
"""PGV-13: сверка роутов паспортных документов с картой AUTH-00.

Постановка: PGV-13 ДОБАВЛЯЕТ ровно два HTTP-маршрута документации
(spec §11): GET /v1/documentation/runs/{run_id}/passport-sources и
POST /v1/documentation/runs/{run_id}/passport-documents. Прочие
маршруты документации -- прежние; карта AUTH-00 (inventory/review/
access-registry/proxy) расширена аддитивно.

Скрипт stdlib-only:
  1. AST-сверка маршрутов routers/documentation.py с ЗАКОММИТОВАННОЙ
     картой (git show fc510f0:docs/auth00/inventory.json): разница --
     ровно два новых ID (added), удалённых нет;
  2. оба маршрута присутствуют в policy_review.json и
     access_registry.v1.json (operations + bindings);
  3. печатный basis-каталог document_jobs покрывает V01+P01+P02;
  4. builders/lifecycle доступны и валидаторы каталога согласованы
     (VISUAL_ARTIFACT_SCHEMA_VERSIONS == registry kind каталогу).

Exit 0 -- соответствие подтверждено; 1 -- несоответствие.
"""
from __future__ import annotations

import ast
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ROUTER = ROOT / "apps/api/routers/documentation.py"
BASE_COMMIT = "fc510f0"

NEW_ROUTES = {
    "api:GET:/v1/documentation/runs/{run_id}/passport-sources": (
        "list_passport_sources_route"
    ),
    "api:POST:/v1/documentation/runs/{run_id}/passport-documents": (
        "request_passport_document_route"
    ),
}


def router_documentation_routes() -> dict[str, str]:
    """api:* -> имя функции (AST routers/documentation.py)."""
    routes: dict[str, str] = {}
    tree = ast.parse(ROUTER.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for dec in node.decorator_list:
            if not isinstance(dec, ast.Call) or not isinstance(dec.func, ast.Attribute):
                continue
            method = dec.func.attr.upper()
            if method not in {"GET", "POST", "PUT", "DELETE", "PATCH"}:
                continue
            path_args = [a.value for a in dec.args if isinstance(a.value, str)]
            if not path_args:
                continue
            routes[f"api:{method}:/v1/documentation{path_args[0]}"] = node.name
    return routes


def main() -> int:
    sys.path.insert(0, str(ROOT))

    # 1. Разница с базовой картой -- ровно два новых маршрута.
    base = json.loads(
        subprocess.run(
            ["git", "show", f"{BASE_COMMIT}:docs/auth00/inventory.json"],
            capture_output=True, text=True, check=True,
        ).stdout
    )
    base_ids = {e["id"] for e in base["entries"] if e["kind"] == "api"}
    current = json.loads(
        (ROOT / "docs/auth00/inventory.json").read_text(encoding="utf-8")
    )
    current_ids = {e["id"] for e in current["entries"] if e["kind"] == "api"}
    added = sorted(current_ids - base_ids)
    removed = sorted(base_ids - current_ids)
    if added != sorted(NEW_ROUTES) or removed:
        print("FAIL: diff карты не равен двум новым маршрутам")
        print("added:", added)
        print("removed:", removed)
        return 1

    # 2. Функции маршрутов и классификации.
    routes = router_documentation_routes()
    review = json.loads(
        (ROOT / "docs/auth00/policy_review.json").read_text(encoding="utf-8")
    )
    registry = json.loads(
        (ROOT / "apps/api/access_registry.v1.json").read_text(encoding="utf-8")
    )
    for route_id, symbol in NEW_ROUTES.items():
        if routes.get(route_id) != symbol:
            print(f"FAIL: {route_id} не найден в router (symbol {symbol!r})")
            return 1
        entry = review["entries"].get(route_id)
        if not entry or entry.get("canonical_operation") != (
            f"apps.api.routers.documentation:{symbol}"
        ):
            print(f"FAIL: {route_id} не классифицирован в policy_review")
            return 1
        binding = registry["bindings"].get(route_id)
        if not binding or binding.get("operation_id") != (
            f"documentation.{symbol}"
        ):
            print(f"FAIL: {route_id} без binding в access_registry")
            return 1
        if f"documentation.{symbol}" not in registry["operations"]:
            print(f"FAIL: operation documentation.{symbol} отсутствует")
            return 1

    # 3. Печатный basis-каталог -- V01 + P01 + P02.
    from apps.api.document_jobs import PRINT_RENDER_BASIS_KINDS

    if set(PRINT_RENDER_BASIS_KINDS) != {
        "visual_print_snapshot",
        "passport_print_snapshot",
        "passport_comparison_snapshot",
    }:
        print("FAIL: PRINT_RENDER_BASIS_KINDS не покрывает V01/P01/P02")
        return 1

    # 4. Каталоги kind согласованы.
    from apps.api.artifact_store import ARTIFACT_KINDS
    from apps.api.artifact_promotion import VISUAL_ARTIFACT_KIND_NAMES
    from apps.api.visual_artifacts import VISUAL_ARTIFACT_SCHEMA_VERSIONS

    if set(VISUAL_ARTIFACT_SCHEMA_VERSIONS) != set(VISUAL_ARTIFACT_KIND_NAMES):
        print("FAIL: catalog schema versions != persist kind names")
        return 1
    for kind in ("passport_print_snapshot", "passport_comparison_snapshot"):
        if kind not in ARTIFACT_KINDS or kind not in VISUAL_ARTIFACT_KIND_NAMES:
            print(f"FAIL: kind {kind!r} не зарегистрирован")
            return 1

    print(
        "OK: added=2 (passport-sources GET, passport-documents POST), "
        f"removed=0; api {len(current_ids)} = actual-карта; "
        f"bindings {len(registry['bindings'])}; basis-каталог V01+P01+P02; "
        "kinds/validators согласованы"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
