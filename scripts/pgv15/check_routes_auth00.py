#!/usr/bin/env python3
"""PGV-15: сверка роутов печатных семейств с картой AUTH-00.

Постановка: PGV-15 ДОБАВЛЯЕТ ровно один HTTP-маршрут документации
(spec §11/§13, строка PGV-15): GET
/v1/documentation/runs/{run_id}/print-documents -- versioned-листинг
сохранённых печатных документов V01/P01/P02 (субстрат фильтров
«Визуализации»/«Паспорта свойств»). Маршруты PGV-13 (passport-sources,
passport-documents) сохраняются; прочие маршруты документации -- прежние.

Скрипт stdlib-only:
  1. AST-сверка маршрутов routers/documentation.py с ЗАКОММИТОВАННОЙ
     картой (git show fc510f0:docs/auth00/inventory.json): разница --
     ровно три новых ID (2x PGV-13 + 1x PGV-15), удалённых нет;
  2. новый маршрут присутствует в policy_review.json и
     access_registry.v1.json (operation + binding, policy document.object);
  3. печатный basis-каталог document_jobs покрывает V01+P01+P02;
  4. листинг -- read-only: ни одного POST/научного вызова в
     list_print_document_deliveries (AC06/§11).

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
    "api:GET:/v1/documentation/runs/{run_id}/print-documents": (
        "list_print_documents_route"
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


def base_documentation_routes() -> dict[str, str]:
    committed = subprocess.run(
        ["git", "show", f"{BASE_COMMIT}:docs/auth00/inventory.json"],
        cwd=ROOT,
        capture_output=True,
        check=True,
        text=True,
    ).stdout
    inventory = json.loads(committed)
    return {
        entry["id"]: entry["operation"]
        for entry in inventory["entries"]
        if entry["kind"] == "api" and "/v1/documentation" in entry["id"]
    }


def main() -> int:
    sys.path.insert(0, str(ROOT))

    # 1. Разница ПОЛНОЙ карты -- ровно три новых маршрута (паритет pgv13).
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
        print("FAIL: diff карты не равен трём новым маршрутам")
        print("added:", added)
        print("removed:", removed)
        return 1

    # 2. Функции маршрутов, классификации и binding (паритет pgv13).
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
    classification = review["entries"]["api:GET:/v1/documentation/runs/{run_id}/print-documents"]
    if classification.get("policy") != "document.object" or classification.get(
        "effects"
    ) != ["read"]:
        print("FAIL: классификация print-documents не read/document.object")
        return 1

    # Печатный каталог basis (§10.2/PGV-09/13) и read-only листинг (§11).
    jobs_source = (ROOT / "apps/api/document_jobs.py").read_text(encoding="utf-8")
    jobs_tree = ast.parse(jobs_source)
    basis_kinds: set[str] = set()
    for node in ast.walk(jobs_tree):
        literal: ast.AST | None = None
        if isinstance(node, ast.Assign):
            target = node.targets[0] if node.targets else None
            if isinstance(target, ast.Name) and target.id == "PRINT_RENDER_BASIS_KINDS":
                literal = node.value
        if isinstance(literal, ast.Call) and getattr(literal.func, "id", "") == "frozenset":
            literal = literal.args[0] if literal.args else None
        if isinstance(literal, (ast.Set, ast.List, ast.Tuple)):
            basis_kinds = {
                elt.value
                for elt in literal.elts
                if isinstance(elt, ast.Constant) and isinstance(elt.value, str)
            }
    expected_basis = {
        "visual_print_snapshot",
        "passport_print_snapshot",
        "passport_comparison_snapshot",
    }
    if basis_kinds != expected_basis:
        print(f"FAIL: PRINT_RENDER_BASIS_KINDS={sorted(basis_kinds)}")
        return 1
    listing_fn = next(
        (
            node
            for node in ast.walk(jobs_tree)
            if isinstance(node, ast.FunctionDef)
            and node.name == "list_print_document_deliveries"
        ),
        None,
    )
    if listing_fn is None:
        print("FAIL: list_print_document_deliveries missing")
        return 1
    forbidden_calls = {
        "request_passport_document",
        "request_visual_export",
        "ensure_print_document_revision",
        "request_print_rendition",
        "request_rendition",
    }
    called = {
        node.func.id
        for node in ast.walk(listing_fn)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    if called & forbidden_calls:
        print(f"FAIL: listing performs write actions: {sorted(called & forbidden_calls)}")
        return 1
    print(
        "PASS: routes delta vs fc510f0 == 3 added/0 removed; "
        "classification/binding present; basis catalog V01/P01/P02; "
        "listing is read-only"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
