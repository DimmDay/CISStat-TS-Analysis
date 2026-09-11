# tests/unit/test_var_integration_paths.py
"""Task 132 fix -- канонические пути интеграции VAR-адаптера.

Regression-тест на ошибку коммита e6f6726: адаптер был закоммичен как
``apps/api/var.py`` вместо ``apps/api/model_impls/var.py``, а содержимое
``apps/api/model_impls/__init__.py`` -- перезаписано в ``apps/api/__init__.py``
(пакетный init API, который обязан оставаться пустым маркером пакета).

Последствия, фиксируемые этим тестом:
- ``import apps.api`` падал с ModuleNotFoundError -- бэкенд не поднимался,
  UI «Моделирование» получал устаревший каталог (15 «Подключённых»,
  семейство «Многомерные» отсутствовало);
- ``from apps.api.model_impls import run_var_backtest`` (routers/models.py,
  dispatch) падал с ImportError -- VAR не входил в _BACKTEST_IMPLEMENTATIONS;
- Dockerfile-проба (release-гейт 16-й модели) ссылалась на
  apps.api.model_impls.var и не воспроизводилась.

Контракт:
1. Адаптер живёт ТОЛЬКО в apps/api/model_impls/var.py (канонический путь
   всех адаптеров платформы; собственный docstring модуля, worklog3.md
   «apps/api/model_impls/var.py (NEW)» и 4 точки импорта).
2. apps/api/__init__.py -- пустой маркер пакета (статус-кво ef22027),
   без реэкспортов model_impls.
3. Экспорт-поверхность адаптеров -- apps/api/model_impls/__init__.py:
   run_var_backtest доступен рядом с run_catboost_backtest и др.
4. Реестр v2: var доступен в рантайме (statsmodels установлен) и входит
   в PRODUCTION_BACKTEST_MODEL_IDS -- иначе UI «Подключённые» не покажет
   семейство «Многомерные».
"""
from __future__ import annotations

import importlib
import importlib.util
import pathlib
import subprocess
import sys

from apps.api.model_impls.neural_runtime import (
    neuralforecast_runtime_available,
)

API_DIR = pathlib.Path(__file__).resolve().parents[2] / "apps" / "api"


class TestAdapterCanonicalLocation:
    """Адаптер VAR -- ровно один, по каноническому пути model_impls/."""

    def test_adapter_exists_at_canonical_path(self):
        assert (API_DIR / "model_impls" / "var.py").is_file(), (
            "VAR-адаптер обязан лежать в apps/api/model_impls/var.py -- "
            "канонический путь всех адаптеров платформы (prophet.py, "
            "random_forest.py, catboost.py, ...); по нему импортируют "
            "model_execution.py (_var_executor), Dockerfile-проба и "
            "test_var_adapter.py"
        )

    def test_no_stray_adapter_copy_at_api_root(self):
        assert not (API_DIR / "var.py").is_file(), (
            "Обнаружен дубль адаптера apps/api/var.py -- файл был "
            "закоммичен не в той директории (Task 132 fix); канонический "
            "путь -- apps/api/model_impls/var.py"
        )

    def test_adapter_module_docstring_pins_canonical_path(self):
        module = importlib.import_module("apps.api.model_impls.var")
        assert module.__doc__ is not None
        # Первая строка файла -- канонический путь (конвенция адаптеров).
        source = pathlib.Path(module.__file__).read_text(encoding="utf-8")
        first_line = source.splitlines()[0].strip("# ").strip()
        assert first_line == "apps/api/model_impls/var.py"


class TestApiPackageInitIsPureMarker:
    """apps/api/__init__.py -- пустой маркер пакета, без side-effect импортов.

    Пакетный init API не переэкспортирует реализации: реэкспорты ломают
    инициализацию всего пакета при любой ошибке адаптера (бэкенд не
    поднимается целиком) и дублируют экспорт-поверхность model_impls.
    """

    def test_api_init_has_no_model_impls_reexports(self):
        import apps.api as api_package

        leaked = [
            name for name in ("run_var_backtest", "run_catboost_backtest",
                              "run_ets_backtest", "run_prophet_backtest")
            if hasattr(api_package, name)
        ]
        assert leaked == [], (
            f"apps/api/__init__.py переэкспортирует {leaked}: содержимое "
            "apps/api/model_impls/__init__.py ошибочно записано в пакетный "
            "init API (Task 132 fix); init обязан быть пустым маркером"
        )

    def test_api_init_source_free_of_impl_imports(self):
        source = (API_DIR / "__init__.py").read_text(encoding="utf-8")
        assert "from apps.api.model_impls" not in source, (
            "apps/api/__init__.py содержит импорты model_impls -- пакетный "
            "init API должен оставаться пустым маркером пакета"
        )

    def test_import_apps_api_does_not_pull_impls(self):
        code = (
            "import sys; import apps.api; "
            "impls = [m for m in sys.modules if m.startswith("
            "'apps.api.model_impls.')]; "
            "print(','.join(sorted(impls)))"
        )
        result = subprocess.run(
            [sys.executable, "-c", code], cwd=str(API_DIR.parent.parent),
            capture_output=True, text=True, check=True,
        )
        loaded = result.stdout.strip()
        assert loaded == "", (
            f"import apps.api тянет реализации ({loaded}): пакетный init "
            "не должен исполнять side-effect импорты адаптеров"
        )


class TestModelImplsExportSurface:
    """run_var_backtest экспортируется реестром адаптеров model_impls."""

    def test_run_var_backtest_exported_from_model_impls(self):
        from apps.api.model_impls import run_var_backtest  # noqa: F401

    def test_run_var_backtest_exported_alongside_other_adapters(self):
        import apps.api.model_impls as impls

        for sibling in ("run_catboost_backtest", "run_lightgbm_backtest",
                        "run_random_forest_backtest"):
            assert hasattr(impls, sibling)
        assert hasattr(impls, "run_var_backtest"), (
            "apps/api/model_impls/__init__.py не экспортирует "
            "run_var_backtest: routers/models.py (dispatch "
            "_BACKTEST_IMPLEMENTATIONS) импортирует его отсюда"
        )

    def test_dunder_all_includes_var(self):
        import apps.api.model_impls as impls

        assert "run_var_backtest" in impls.__all__

    def test_adapter_importable_via_canonical_module(self):
        from apps.api.model_impls.var import (  # noqa: F401
            _var_fit_predict,
            run_var_backtest,
        )


class TestRegistrySeesVarAtRuntime:
    """VAR доступен в рантайме и входит в production backtest dispatch."""

    def test_var_runtime_available(self):
        from apps.api.model_execution import MODEL_EXECUTION_REGISTRY

        definition = MODEL_EXECUTION_REGISTRY.get("var")
        assert definition is not None
        assert definition.runtime_available(), (
            "runtime_available('var') = False: statsmodels должен быть "
            "импортируем; без этого UI-фильтр «Подключённые» не покажет VAR"
        )

    def test_var_in_production_backtest_ids(self):
        from apps.api.model_readiness import PRODUCTION_BACKTEST_MODEL_IDS

        assert "var" in PRODUCTION_BACKTEST_MODEL_IDS

    def test_dispatch_import_chain_executes(self):
        # Полная цепочка UI: import apps.api -> routers.models ->
        # dispatch -> readiness; падение любого звена = каталог не строится.
        code = (
            "from apps.api.model_impls.neural_runtime import "
            "neuralforecast_runtime_available; "
            "from apps.api.routers import models; "
            "from apps.api.model_readiness import PRODUCTION_BACKTEST_MODEL_IDS; "
            "print('ok', len(PRODUCTION_BACKTEST_MODEL_IDS), "
            "neuralforecast_runtime_available())"
        )
        result = subprocess.run(
            [sys.executable, "-c", code], cwd=str(API_DIR.parent.parent),
            capture_output=True, text=True,
        )
        assert result.returncode == 0, (
            f"Цепочка импортов dispatch сломана:\n{result.stderr[-2000:]}"
        )
        # Task 138/139/140: 19 базовых + lstm + nbeats + nhits при
        # установленной опциональной neural-группе (честный
        # runtime_available реестра v2).
        expected_count = "ok 22 True" if neuralforecast_runtime_available() else "ok 19 False"
        assert expected_count in result.stdout, (
            f"Ожидалось '{expected_count}' production backtest-моделей, "
            f"получено: {result.stdout.strip()}"
        )
