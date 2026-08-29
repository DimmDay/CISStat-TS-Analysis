from __future__ import annotations

import ast
from pathlib import Path


MODULE_PATH = Path(__file__).parents[2] / "apps" / "api" / "outliers_correction.py"


def test_outliers_correction_is_production_module_not_api_test_copy():
    """Не допускает повторную подмену production-модуля тестовым файлом."""
    tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
    imported_modules = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    imported_from = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }

    assert "pytest" not in imported_modules
    assert "fastapi.testclient" not in imported_from
    assert "apps.api.main" not in imported_from


def test_outliers_correction_exports_every_session_dependency():
    tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
    function_names = {
        node.name for node in tree.body if isinstance(node, ast.FunctionDef)
    }

    assert {
        "detect_mask_on_residual",
        "preview_outlier_corrections",
        "outlier_boxplot_groups",
    } <= function_names
