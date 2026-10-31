# apps/api/visual_exports.py
"""
Task PGV-10 (spec_passport_graphics_visual.md §10.1/§11/§13, строка
PGV-10): Export upload/validation/preprocessing -- «Скачать PNG» на
всех render sites трёх остановок.

КРИТЕРИЙ ЗАВЕРШЕНИЯ (§13): «Верный PNG каждого view, before/after/
sampling, не первый SVG».

АРХИТЕКТУРА (§4/§10.1/§11 -- «Python jobs остаются authority»):
  GET  /v1/documentation/runs/{run_id}/visual-sources -- доступные
       frozen inputs/views/applicability/metadata БЕЗ запуска науки;
  POST /v1/documentation/runs/{run_id}/visuals -- view_id [+result_ref
       +profile +screen_svg +expected_context] -> freeze durable
       visual_result -> VisualPrintSnapshot/1 -> V01 revision -> PNG
       job (PGV-09) -> 202 + status_url.

КЛЮЧЕВЫЕ РЕШЕНИЯ:
1. ЭКСПОРТ ИЗ DURABLE-СЛОЯ БЕЗ НАУКИ (AC06): источник -- visual_result
   артефакт, замороженный notify_visual_result в момент фактического
   ответа (PGV-03). Прямой пересчёт/GET запрещены; сохранённый ответ
   кэша (freeze_saved_visual, producer_first_export) -- fallback ТОЛЬКО
   для результата, не попавшего в durable слой (lazy transfer §6).
2. НЕ «ПЕРВЫЙ SVG» (критерий §13): recharts-геометрия -- СЕРИАЛИЗОВАННЫЙ
   frozen SVG КОНКРЕТНОГО view (клиент сериализует свой chart-узел,
   packages/ui/lib/serializeChartSvg.ts), анонимный документный скан
   запрещён. SVG проходит санитайзер контейнера (PGV-08, AC19) и
   замораживается В СЕКЦИИ снапшота с sha256 -- identity print input'а
   включает геометрию (иной frozen print input -- другой immutable
   снапшот, §8 «старые snapshots не переписываются»; AC08: скрытой
   подмены отображения нет).
3. BEFORE/AFTER/SAMPLING (критерий §13): sampling frozen результата
   (full/windowed/downsampled/truncated) переносится в снапшот
   (detail_level=sampling при неполном показе); before/after -- состав
   frozen data (пары серий до/после) + CAS expected_context (смена
   ревизии данных между показом и экспортом -- 409 context_changed,
   PGV-AC07).
4. MIXED-САЙТЫ (6 view Предобработки): печатная композиция >=2 секций
   разных kinds (правила PGV-01); все секции строятся из ОДНОГО frozen
   data (chart -- из screen_svg, таблица -- из {columns, rows}).
5. ИДЕМПОТЕНТНОСТЬ (§11/AC09/§12.2): identity снапшота =
   pgv.print_snapshot:{view_id}:{result_digest}[:svg16]; повторный клик
   находит существующий frozen input по producer key ДО сборки payload
   (снапшот хранит СВОЁ время фиксации, старые не переписываются) ->
   та же V01 ревизия (basis_fingerprint) -> тот же активный/ready job.
6. ЧЕСТНЫЕ ГРАНИЦЫ: passport/comparison view -- PGV-04/13; EDA/tasks --
   PGV-11; modeling/forecasting -- PGV-12 (отказ с именем добирающей
   задачи); дата-колонка и цель -- обязательные refs research-снапшота
   (run.target_column + сессия/запрос: структура остановки).

Инвариант §3.1: модуль ТОЛЬКО переносит уже вычисленное в печатный
контур; никакой науки, никакого SessionStore-расчёта, никакого DOM.
"""
from __future__ import annotations

import hashlib
from typing import Any, Mapping, Optional

# ── Ошибки (роутер маппит: 404/409/422) ───────────────────────────────


class VisualExportError(RuntimeError):
    """Базовая ошибка экспорта (честная, без дисклоужения)."""


class UnknownExportView(VisualExportError):
    """view_id вне реестра PGV-00 (unknown site -- §5)."""


class VisualExportOutOfScope(VisualExportError):
    """view вне скоупа PGV-10 (паспорта/demo/EDA/modeling/forecast/tasks)
    -- честный отказ с именем добирающей задачи."""


class VisualExportAccessDenied(VisualExportError):
    """Чужой/несуществующий run -- uniform отказ (R09/AC18)."""


class VisualSourceUnavailable(VisualExportError):
    """Frozen результат для экспорта недоступен (§11
    source_unavailable); пересчёт науки запрещён."""


class PrintScreenSvgRequired(VisualExportError):
    """recharts-секция без frozen геометрии -- preflight до постановки
    job'а (§3.6: график не фабрикуется)."""


class InvalidScreenSvg(VisualExportError):
    """screen_svg не является честной сериализацией chart-узла
    (защита в глубину до санитайзера контейнера, AC19)."""


# ── Реестр/скоуп (spec §5/§13: «Все render sites этих stops») ─────────


@_lru_cache() if False else (lambda fn: fn)  # noqa: E731 -- см. ниже
def _noop(fn):  # pragma: no cover -- маркер структуры
    return fn


def _site_for(view_id: str) -> Optional[dict[str, Any]]:
    from apps.api.print_schema import load_visual_registry

    for site in load_visual_registry()["sites"]:
        if site.get("view_id") == view_id:
            return site
    return None


def pgv10_export_view_ids() -> tuple[str, ...]:
    """Скоуп PGV-10: pgv-03 research view модулей upload/validation/
    preprocessing (38 сайтов; паспорта pgv-04/13 и static_demo вне)."""
    from apps.api.print_schema import load_visual_registry

    return tuple(
        sorted(
            str(site["view_id"])
            for site in load_visual_registry()["sites"]
            if site["module_id"] in ("upload", "validation", "preprocessing")
            and str(site.get("source_adapter", "")).startswith("pgv-03/")
            and site.get("applicability") != "static_demo"
        )
    )


def pgv11_export_view_ids() -> tuple[str, ...]:
    """Скоуп PGV-11 (spec §13 «Export EDA/IH/tasks»): pgv-03 research
    view остановок EDA (16) и задач (tasks.causes.fold_importance);
    паспорта pgv-04/13 и static_demo -- вне (честный отказ)."""
    from apps.api.print_schema import load_visual_registry

    return tuple(
        sorted(
            str(site["view_id"])
            for site in load_visual_registry()["sites"]
            if site["module_id"] in ("eda", "tasks")
            and str(site.get("source_adapter", "")).startswith("pgv-03/")
            and site.get("applicability") != "static_demo"
        )
    )


def export_view_ids() -> tuple[str, ...]:
    """Объединённый скоуп экспорта визуализаций (PGV-10 ∪ PGV-11 --
    55 view): список visual-sources и валидация view_id."""
    return tuple(sorted(set(pgv10_export_view_ids()) | set(pgv11_export_view_ids())))


def resolve_export_view(view_id: str) -> dict[str, Any]:
    """Сайт реестра для экспорта: unknown -- UnknownExportView; вне
    скоупа -- VisualExportOutOfScope с добирающей задачей (§5: unknown
    site блокирует CERT; честные границы скоупа; PGV-11 -- EDA/tasks)."""
    site = _site_for(view_id)
    if site is None:
        raise UnknownExportView(
            f"view {view_id!r} вне реестра PGV-00 (unknown site -- §5)"
        )
    adapter = str(site.get("source_adapter", "") or "unknown")
    module_id = str(site.get("module_id", ""))
    if adapter.startswith("pgv-03/"):
        if module_id in ("upload", "validation", "preprocessing"):
            if site.get("applicability") == "static_demo":
                raise VisualExportOutOfScope(
                    f"view {view_id!r} -- статическое демо Навигатора, не "
                    "результат исследования (spec §1)"
                )
            return site
        if module_id in ("eda", "tasks"):
            # PGV-11: Export EDA/IH/tasks (spec §13)
            return site
        if module_id == "navigator":
            task = "static demo -- не результат исследования (spec §1)"
        elif module_id in ("modeling", "forecasting"):
            task = "PGV-12 (modeling/forecasting)"
        else:
            task = "PGV-11 (EDA/tasks)"
        raise VisualExportOutOfScope(
            f"view {view_id!r} вне скоупа экспорта "
            f"(source_adapter={adapter!r}; добирающая задача: {task})"
        )
    if adapter.startswith("pgv-04/"):
        task = "PGV-04 (паспорта)"
    elif adapter.startswith("pgv-13/"):
        task = "PGV-13 (P01/P02)"
    elif module_id == "navigator":
        task = "static demo -- не результат исследования (spec §1)"
    else:
        task = "PGV-00"
    raise VisualExportOutOfScope(
        f"view {view_id!r} вне скоупа экспорта "
        f"(source_adapter={adapter!r}; добирающая задача: {task})"
    )


# ── Печатные спецификации view (заголовки/оси/составы секций) ─────────
# Честные человекочитаемые подписи печати (§7: заголовок/источник/оси).
# Оси -- value XOR null-причина (§6: «Не выдумывать единицы»).

_X_TIME = {"name": "Время ряда", "units": {"value": None, "reason": "legacy_unknown"}}
_X_CATEGORY = {"name": "Категория", "units": {"value": None, "reason": "dimensionless"}}
_Y_VALUE = {"name": "Значение", "units": {"value": None, "reason": "legacy_unknown"}}
_Y_COUNT = {"name": "Число наблюдений", "units": {"value": "dimensionless", "reason": None}}
_Y_DENSITY = {"name": "Плотность", "units": {"value": None, "reason": "legacy_unknown"}}


def _axes(x: dict, y: dict) -> list[dict[str, Any]]:
    return [
        {**x, "scale": "linear", "limits": None},
        {**y, "scale": "linear", "limits": None},
    ]


CHART_AXES: dict[str, list[dict[str, Any]]] = {
    "upload.chart.series": _axes(_X_TIME, _Y_VALUE),
    "upload.chart.decomposition_series": _axes(_X_TIME, _Y_VALUE),
    "upload.distribution.scatter": _axes(_Y_VALUE, _Y_VALUE),
    "upload.distribution.histogram": _axes(_Y_VALUE, _Y_COUNT),
    "upload.distribution.kde": _axes(_Y_VALUE, _Y_DENSITY),
    "validation.formats.chart": _axes(_X_CATEGORY, _Y_COUNT),
    "preprocessing.outliers.series_profile": _axes(_X_TIME, _Y_VALUE),
    "preprocessing.regularity.gap_map": _axes(_X_TIME, _Y_COUNT),
    "preprocessing.decomposition.overview": _axes(_X_TIME, _Y_VALUE),
    "preprocessing.variance_stab.series": _axes(_X_TIME, _Y_VALUE),
    "preprocessing.variance_stab.rolling": _axes(_X_TIME, _Y_VALUE),
    "preprocessing.variance_stab.methods": _axes(
        _X_CATEGORY,
        {"name": "Score нестабильности", "units": {"value": None, "reason": "dimensionless"}},
    ),
    "preprocessing.variance_stab.distribution": _axes(_Y_VALUE, _Y_DENSITY),
    "preprocessing.smoothing.overview": _axes(_X_TIME, _Y_VALUE),
    "preprocessing.stationarity.overview": _axes(_X_TIME, _Y_VALUE),
    "preprocessing.spectral.periodogram": _axes(
        {"name": "Частота", "units": {"value": None, "reason": "legacy_unknown"}},
        {"name": "Спектральная плотность", "units": {"value": None, "reason": "legacy_unknown"}},
    ),
    "preprocessing.feature_eng.overview": _axes(_X_TIME, _Y_VALUE),
    "preprocessing.scaling.overview": _axes(_X_TIME, _Y_VALUE),
    # ── PGV-11: оси chart-секций EDA/tasks (AC01: свой график, не
    # другой subplot; units честны: value XOR reason) ──
    "eda.descriptive.distribution.scatter": _axes(_Y_VALUE, _Y_VALUE),
    "eda.descriptive.distribution.histogram": _axes(_Y_VALUE, _Y_COUNT),
    "eda.descriptive.distribution.kde": _axes(_Y_VALUE, _Y_DENSITY),
    "eda.correlation.acf_pacf": _axes(
        {"name": "Лаг", "units": {"value": "dimensionless", "reason": None}},
        {"name": "Коэффициент корреляции", "units": {"value": "dimensionless", "reason": None}},
    ),
    "eda.ih.results": _axes(
        {"name": "Фактор", "units": {"value": "dimensionless", "reason": None}},
        {"name": "R(Y|X)", "units": {"value": "dimensionless", "reason": None}},
    ),
    "eda.seasonality.spectrum": _axes(
        {"name": "Частота", "units": {"value": None, "reason": "legacy_unknown"}},
        {"name": "Спектральная мощность", "units": {"value": None, "reason": "legacy_unknown"}},
    ),
    "eda.stationarity.tests": _axes(
        {"name": "Тест", "units": {"value": "dimensionless", "reason": None}},
        {"name": "p-значение", "units": {"value": "dimensionless", "reason": None}},
    ),
    "eda.distribution.tests": _axes(
        {"name": "Тест", "units": {"value": "dimensionless", "reason": None}},
        {"name": "p-значение", "units": {"value": "dimensionless", "reason": None}},
    ),
    "eda.structural.breakpoints": _axes(_X_TIME, _Y_VALUE),
    "eda.feature_select.scores": _axes(
        {"name": "Признак", "units": {"value": "dimensionless", "reason": None}},
        {"name": "Коэффициент связи", "units": {"value": "dimensionless", "reason": None}},
    ),
    "eda.validation_strategy.windows": _axes(
        {"name": "Fold", "units": {"value": "dimensionless", "reason": None}},
        {"name": "Число наблюдений", "units": {"value": "dimensionless", "reason": None}},
    ),
    "eda.model_matrix.applicability": _axes(
        {"name": "Модель / семейство", "units": {"value": "dimensionless", "reason": None}},
        {"name": "Число моделей", "units": {"value": "dimensionless", "reason": None}},
    ),
    "tasks.causes.fold_importance": _axes(
        {"name": "Признак", "units": {"value": "dimensionless", "reason": None}},
        {"name": "Средняя доля важности (fold)", "units": {"value": "dimensionless", "reason": None}},
    ),
}

# Заголовки таблиц печати (row -- ярлыки колонок сетки, column --
# ярлык(и) столбца значений; паритет seed-конвенции PGV-09).
TABLE_HEADINGS: dict[str, dict[str, list[str]]] = {
    "upload.overview.preview": {
        "row": ["Колонка", "Значение"], "column": ["Строки"],
    },
    "upload.overview.tech_table": {
        "row": ["Колонка", "Тип", "Иконка", "Непустых", "Пропусков", "Уникальных"],
        "column": ["Значение"],
    },
    "upload.structure.schema": {
        "row": ["Поле", "Выбрано"], "column": ["Деталь"],
    },
    "validation.data_types.matrix": {
        "row": ["Проверка", "Статус", "Число", "Область", "Правило", "Режим", "Ошибка"],
        "column": ["Значение"],
    },
    "validation.ranges.overview": {
        "row": ["Проверка", "Статус", "Число", "Область", "Правило", "Режим", "Ошибка"],
        "column": ["Значение"],
    },
    "validation.consistency.overview": {
        "row": ["Проверка", "Статус", "Число", "Область", "Правило", "Режим", "Ошибка"],
        "column": ["Значение"],
    },
    "validation.uniqueness.overview": {
        "row": ["Проверка", "Статус", "Число", "Область", "Правило", "Режим", "Ошибка"],
        "column": ["Значение"],
    },
    "validation.inclusion.overview": {
        "row": ["Проверка", "Статус", "Число", "Область", "Правило", "Режим", "Ошибка"],
        "column": ["Значение"],
    },
    "validation.referential.overview": {
        "row": ["Проверка", "Статус", "Число", "Область", "Правило", "Режим", "Ошибка"],
        "column": ["Значение"],
    },
    "validation.text_quality.overview": {
        "row": ["Проверка", "Статус", "Число", "Область", "Правило", "Режим", "Ошибка"],
        "column": ["Значение"],
    },
    "validation.regularity.overview": {
        "row": ["Проверка", "Статус", "Число", "Область", "Правило", "Режим", "Ошибка"],
        "column": ["Значение"],
    },
    "validation.sufficiency.overview": {
        "row": ["Проверка", "Статус", "Число", "Область", "Правило", "Режим", "Ошибка"],
        "column": ["Значение"],
    },
    "preprocessing.missing.overview": {
        "row": ["Колонка", "Пропусков", "Доля, %"], "column": ["Значение"],
    },
    "preprocessing.missing.correlation": {
        "row": ["Колонка"], "column": ["Корреляция"],
    },
    "preprocessing.outliers.overview": {
        "row": ["Колонка", "Выбросов"], "column": ["Значение"],
    },
    "preprocessing.regularity.overview": {
        "row": ["Поле", "Значение"], "column": ["Профиль оси"],
    },
    "eda.descriptive.stats": {
        "row": ["Показатель"], "column": ["Значение"],
    },
    # ── PGV-11: заголовки печатных таблиц EDA (конвенция PGV-09/10:
    # row -- ярлыки колонок данных, column -- ярлык значений) ──
    "eda.ih.metrics_table": {
        "row": ["Фактор", "Тип", "N", "I(X;Y)", "H(X)", "R(Y|X)", "R adj.", "p", "q (FDR)"],
        "column": ["Значение"],
    },
}

_VALIDATION_TABLE_HEADINGS = {
    "row": ["Проверка", "Статус", "Число", "Область", "Правило", "Режим", "Ошибка"],
    "column": ["Значение"],
}
for _view in (
    "validation.data_types.matrix",
    "validation.ranges.overview",
    "validation.consistency.overview",
    "validation.uniqueness.overview",
    "validation.inclusion.overview",
    "validation.referential.overview",
    "validation.text_quality.overview",
    "validation.regularity.overview",
    "validation.sufficiency.overview",
):
    TABLE_HEADINGS[_view] = dict(_VALIDATION_TABLE_HEADINGS)

# Печатные композиции mixed-сайтов (>=2 секции разных kinds -- PGV-01;
# все секции строятся из ОДНОГО frozen data -- §6).
MIXED_SECTIONS: dict[str, list[dict[str, Any]]] = {
    "preprocessing.outliers.series_profile": [
        {"section_id": "chart", "renderer_kind": "recharts_svg",
         "title": "Ряд с границами метода"},
        {"section_id": "bounds", "renderer_kind": "html_table",
         "title": "Границы метода по колонкам",
         "table_headings": {"row": ["Колонка", "Нижняя", "Верхняя"],
                            "column": ["Значение"]}},
    ],
    "preprocessing.regularity.gap_map": [
        {"section_id": "chart", "renderer_kind": "recharts_svg",
         "title": "Таймлайн событий регулярности"},
        {"section_id": "events", "renderer_kind": "html_table",
         "title": "События (разрыв/дубль/сортировка)",
         "table_headings": {"row": ["Дата", "Тип", "Группа"],
                            "column": ["Значение"]}},
    ],
    "preprocessing.stationarity.overview": [
        {"section_id": "chart", "renderer_kind": "recharts_svg",
         "title": "Ряд до и после преобразования"},
        {"section_id": "tests", "renderer_kind": "html_table",
         "title": "Сравнение тестов до/после",
         "table_headings": {"row": ["Тест", "p до", "p после"],
                            "column": ["Значение"]}},
    ],
    "preprocessing.spectral.periodogram": [
        {"section_id": "chart", "renderer_kind": "recharts_svg",
         "title": "Спектральная плотность (Welch)"},
        {"section_id": "bands", "renderer_kind": "html_table",
         "title": "Доли мощности по диапазонам",
         "table_headings": {"row": ["Диапазон", "Доля"],
                            "column": ["Значение"]}},
    ],
    "preprocessing.feature_eng.overview": [
        {"section_id": "chart", "renderer_kind": "recharts_svg",
         "title": "Превью сгенерированных признаков"},
        {"section_id": "catalog", "renderer_kind": "html_table",
         "title": "Каталог признаков",
         "table_headings": {"row": ["Признак", "Семейство", "Доступность"],
                            "column": ["Значение"]}},
    ],
    "preprocessing.scaling.overview": [
        {"section_id": "chart", "renderer_kind": "recharts_svg",
         "title": "Ряд до и после масштабирования"},
        {"section_id": "ranges", "renderer_kind": "html_table",
         "title": "Сравнение масштабов (log10 σ)",
         "table_headings": {"row": ["Колонка", "До", "После"],
                            "column": ["Значение"]}},
    ],
    # ── PGV-11: композиции mixed-сайтов EDA/tasks (>=2 секции разных
    # kinds из ОДНОГО frozen data, §6; chart -- frozen screen_svg) ──
    "eda.correlation.acf_pacf": [
        {"section_id": "chart", "renderer_kind": "recharts_svg",
         "title": "ACF/PACF с доверительными интервалами"},
        {"section_id": "values", "renderer_kind": "html_table",
         "title": "Значения коэффициентов по лагам",
         "table_headings": {"row": ["Лаг", "ACF", "PACF"],
                            "column": ["Значение"]}},
    ],
    "eda.ih.results": [
        {"section_id": "ranking", "renderer_kind": "recharts_svg",
         "title": "Рейтинг IH-информативности"},
        {"section_id": "table", "renderer_kind": "html_table",
         "title": "Результаты IH-анализа",
         "table_headings": {
             "row": ["Фактор", "Тип", "N", "I(X;Y)", "H(X)", "R(Y|X)", "R adj.", "p", "q (FDR)"],
             "column": ["Значение"]}},
    ],
    "eda.seasonality.spectrum": [
        {"section_id": "chart", "renderer_kind": "recharts_svg",
         "title": "Периодограмма (FFT)"},
        {"section_id": "candidates", "renderer_kind": "html_table",
         "title": "Доминантные частоты и сезонности",
         "table_headings": {"row": ["Ранг", "Период", "Доля мощности"],
                            "column": ["Значение"]}},
    ],
    "eda.stationarity.tests": [
        {"section_id": "chart", "renderer_kind": "recharts_svg",
         "title": "P-значения тестов"},
        {"section_id": "tests", "renderer_kind": "html_table",
         "title": "Тесты стационарности",
         "table_headings": {"row": ["Тест", "Статистика", "p", "Вывод"],
                            "column": ["Значение"]}},
    ],
    "eda.distribution.tests": [
        {"section_id": "chart", "renderer_kind": "recharts_svg",
         "title": "Гистограмма и QQ-plot"},
        {"section_id": "tests", "renderer_kind": "html_table",
         "title": "Тесты нормальности",
         "table_headings": {"row": ["Тест", "Статистика", "p", "Отклонение от нормальности"],
                            "column": ["Значение"]}},
    ],
    "eda.structural.breakpoints": [
        {"section_id": "chart", "renderer_kind": "recharts_svg",
         "title": "Ряд с точками перелома (CUSUM/PELT)"},
        {"section_id": "segments", "renderer_kind": "html_table",
         "title": "Сегменты режима",
         "table_headings": {"row": ["Сегмент", "Период", "N", "Среднее", "σ", "Наклон"],
                            "column": ["Значение"]}},
    ],
    "eda.validation_strategy.windows": [
        {"section_id": "chart", "renderer_kind": "recharts_svg",
         "title": "Окна валидации по fold"},
        {"section_id": "folds", "renderer_kind": "html_table",
         "title": "Параметры окон стратегии",
         "table_headings": {"row": ["Fold", "Train", "N train", "Gap", "Test", "N test"],
                            "column": ["Значение"]}},
    ],
    "eda.model_matrix.applicability": [
        {"section_id": "chart", "renderer_kind": "recharts_svg",
         "title": "Применимость моделей по семьям"},
        {"section_id": "models", "renderer_kind": "html_table",
         "title": "Модель → статус ряда → вывод",
         "table_headings": {"row": ["Модель", "Семейство", "Применимость", "Платформа", "Мин. N"],
                            "column": ["Значение"]}},
    ],
    "tasks.causes.fold_importance": [
        {"section_id": "chart", "renderer_kind": "recharts_svg",
         "title": "Fold-важность факторов"},
        {"section_id": "factors", "renderer_kind": "html_table",
         "title": "Средняя доля важности по признакам",
         "table_headings": {"row": ["Признак", "Средняя доля", "Fold'ов"],
                            "column": ["Значение"]}},
    ],
}

# PGV-11: печатные композиции НЕ-mixed сайтов, отличные от одной секции
# своего kind. Пока единственный случай -- AC02: IH-матрица печатается
# html_table ПОЛНОСТЬЮ; заголовки колонок -- динамические bins frozen
# результата (build_visual_print_snapshot строит их из ih_input, ключ
# «table_headings_from_frozen»); статические TABLE_HEADINGS не годятся:
# bins зависят от данных и параметров (§6: refs/заголовки не фабрикуются).
PRINT_COMPOSITIONS: dict[str, list[dict[str, Any]]] = {
    "eda.ih.conditional_map": [
        {
            "section_id": "main",
            "renderer_kind": "html_table",
            "title": "Условное распределение цели по интервалам фактора",
            "table_headings_from_frozen": "ih_conditional_map",
        },
    ],
}

# Заголовки печати (§7 верх страницы): view -> title.
VIEW_TITLES: dict[str, str] = {
    "upload.overview.preview": "Превью датасета",
    "upload.overview.tech_table": "Техническая информация по колонкам",
    "upload.chart.series": "Исследуемый признак по временной оси",
    "upload.chart.decomposition_shares": "Доли компонент декомпозиции",
    "upload.chart.decomposition_series": "Компоненты декомпозиции ряда",
    "upload.distribution.scatter": "Диаграмма рассеяния",
    "upload.distribution.histogram": "Гистограмма распределения",
    "upload.distribution.kde": "Ядерная оценка плотности",
    "upload.structure.schema": "Определение структуры данных",
    "upload.quality.teaser": "Показатели качества данных",
    "validation.data_types.matrix": "Валидация: типы данных",
    "validation.formats.chart": "Валидация: форматы и шаблоны",
    "validation.ranges.overview": "Валидация: диапазоны значений",
    "validation.consistency.overview": "Валидация: логика и хронология",
    "validation.uniqueness.overview": "Валидация: уникальность",
    "validation.inclusion.overview": "Валидация: включённость",
    "validation.referential.overview": "Валидация: ссылки и связи",
    "validation.text_quality.overview": "Валидация: качество текста",
    "validation.regularity.overview": "Валидация: регулярность",
    "validation.sufficiency.overview": "Валидация: достаточность",
    "preprocessing.missing.overview": "Пропуски: профиль",
    "preprocessing.missing.coverage_matrix": "Пропуски: тепловая карта покрытия",
    "preprocessing.missing.correlation": "Пропуски: корреляция индикаторов",
    "preprocessing.outliers.overview": "Выбросы: профиль",
    "preprocessing.outliers.series_profile": "Выбросы: ряд с границами метода",
    "preprocessing.regularity.overview": "Регулярность: профиль оси",
    "preprocessing.regularity.gap_map": "Регулярность: таймлайн событий",
    "preprocessing.decomposition.overview": "Декомпозиция ряда (STL)",
    "preprocessing.variance_stab.series": "Стабилизация дисперсии: до и после",
    "preprocessing.variance_stab.rolling": "Стабилизация дисперсии: скользящая σ",
    "preprocessing.variance_stab.methods": "Стабилизация дисперсии: методы",
    "preprocessing.variance_stab.distribution": "Стабилизация дисперсии: распределения",
    "preprocessing.variance_stab.diagnostics": "Стабилизация дисперсии: диагностика",
    "preprocessing.smoothing.overview": "Сглаживание: профиль",
    "preprocessing.stationarity.overview": "Стационарность: до и после",
    "preprocessing.spectral.periodogram": "Спектральный анализ: периодограмма",
    "preprocessing.feature_eng.overview": "Генерация признаков: превью",
    "preprocessing.scaling.overview": "Масштабирование: превью",
    # ── PGV-11: титулы печати EDA/tasks (§7: заголовок/источник) ──
    "eda.descriptive.stats": "Описательная статистика",
    "eda.descriptive.distribution.scatter": "EDA: диаграмма рассеяния",
    "eda.descriptive.distribution.histogram": "EDA: гистограмма распределения",
    "eda.descriptive.distribution.kde": "EDA: ядерная оценка плотности",
    "eda.correlation.acf_pacf": "Корреляции: ACF/PACF",
    "eda.ih.metrics_table": "Информационная эвристика: карта метрик",
    "eda.ih.conditional_map": "Информационная эвристика: условное распределение",
    "eda.ih.results": "Информационная эвристика: результаты",
    "eda.seasonality.spectrum": "Сезонность: спектр и периодограмма",
    "eda.stationarity.tests": "Стационарность: тесты",
    "eda.distribution.tests": "Распределение: тесты нормальности",
    "eda.structural.breakpoints": "Структурные сдвиги: режимы ряда",
    "eda.feature_select.scores": "Отбор признаков: оценки связи",
    "eda.feature_select.matrix": "Отбор признаков: корреляционная матрица",
    "eda.validation_strategy.windows": "Стратегия валидации: окна",
    "eda.model_matrix.applicability": "Матрица применимости моделей",
    "tasks.causes.fold_importance": "Причины: fold-важность факторов",
}


def mixed_sections_for(view_id: str, renderer_kind: str) -> list[dict[str, Any]]:
    """Печатная композиция снапшота: явная композиция (MIXED_SECTIONS
    для mixed-сайтов; PRINT_COMPOSITIONS -- не-mixed исключения вроде
    AC02) либо одна секция своего kind (состав печати -- по реестру
    PGV-00)."""
    composition = PRINT_COMPOSITIONS.get(view_id)
    if composition:
        return [dict(section) for section in composition]
    if renderer_kind == "mixed":
        sections = MIXED_SECTIONS.get(view_id)
        if not sections:
            raise VisualExportError(
                f"mixed-сайт {view_id!r} без печатной композиции -- честный "
                "gap поставки (состав не фабрикуется)"
            )
        return [dict(section) for section in sections]
    section: dict[str, Any] = {"section_id": "main", "renderer_kind": renderer_kind}
    headings = TABLE_HEADINGS.get(view_id)
    if renderer_kind == "html_table":
        if not headings:
            raise VisualExportError(
                f"табличный сайт {view_id!r} без заголовков печати -- честный "
                "gap поставки"
            )
        section["table_headings"] = dict(headings)
    return [section]


def _ih_conditional_frozen_headings(
    data: Mapping[str, Any],
) -> Optional[dict[str, Any]]:
    """AC02: динамические заголовки печати IH-матрицы -- из ТЕХ ЖЕ
    frozen bins (feature/target/y_bins из ih_input). Отсутствие bins --
    None (честный gap, заголовки не фабрикуются)."""
    ih_input = data.get("ih_input")
    if not isinstance(ih_input, dict):
        return None
    y_bins = [str(b) for b in ih_input.get("y_bins") or []]
    if not y_bins:
        return None
    feature = str(ih_input.get("feature_label") or "фактор")
    target = str(ih_input.get("target_label") or "цель")
    return {
        "row": [f"Интервал «{feature}» \\ «{target}»"],
        "column": y_bins + ["Сумма строки, %"],
    }


# ── screen_svg: honest preflight (защита в глубину до AC19) ───────────


def validate_screen_svg(screen_svg: str) -> None:
    """Минимальная честная проверка сериализации chart-узла: SVG-корень,
    без <script>/foreignObject/on*-атрибутов (санитайзер контейнера --
    второй слой, rendererCore PGV-08)."""
    stripped = (screen_svg or "").strip()
    if not stripped.startswith(("<svg", "<?xml")):
        raise InvalidScreenSvg(
            "screen_svg не является сериализацией SVG chart-узла "
            "(не первый SVG документа -- сериализуйте узел конкретного view)"
        )
    lowered = stripped.lower()
    if "<script" in lowered or "foreignobject" in lowered:
        raise InvalidScreenSvg(
            "screen_svg содержит запрещённое содержимое (<script>/"
            "foreignObject) -- AC19"
        )
    import re

    if re.search(r"\son[a-z]+\s*=", lowered):
        raise InvalidScreenSvg("screen_svg содержит on*-обработчики (AC19)")


def _screen_svg_digest(screen_svg: Optional[str]) -> Optional[str]:
    if not screen_svg:
        return None
    return hashlib.sha256(screen_svg.encode("utf-8")).hexdigest()


# ── Durable-резолв результата (без науки, AC06) ───────────────────────


def resolve_frozen_result(
    run_id: str,
    view_id: str,
    *,
    result_ref: Optional[str] = None,
) -> tuple[Any, dict[str, Any]]:
    """Frozen visual_result запуска: по явному result_ref либо последний
    зафиксированный для view (durable registry, БЕЗ SessionStore/науки).
    Fallback lazy transfer (§6): результат отсутствует в durable слое,
    но жив в кэше сохранённых ответов -- freeze_saved_visual
    (producer_first_export, CAS ВСЕГДА)."""
    artifacts = list_visual_results(run_id, view_id=view_id)
    if result_ref:
        artifacts = [
            a for a in artifacts if a.refs.get("result_ref") == result_ref
        ]
        if not artifacts:
            artifacts = _freeze_saved_fallback(run_id, view_id, result_ref)
            if not artifacts:
                raise VisualSourceUnavailable(
                    "Frozen результат для экспорта недоступен (result_ref "
                    f"{result_ref!r} не зафиксирован в durable слое; "
                    "пересчёт науки запрещён) -- обновите представление"
                )
    else:
        if not artifacts:
            artifacts = _freeze_saved_fallback(run_id, view_id, None)
        if not artifacts:
            raise VisualSourceUnavailable(
                "Frozen результат view отсутствует в durable слое (view не "
                "открывался либо freeze не удался) -- откройте "
                "представление и повторите экспорт"
            )
    artifact = artifacts[-1]  # последний зафиксированный
    payload = _artifact_payload(artifact)
    return artifact, payload


def _freeze_saved_fallback(
    run_id: str, view_id: str, result_ref: Optional[str]
) -> list[Any]:
    """Lazy transfer (§6): «первый explicit export ещё доступного
    проверенного результата» -- freeze СОХРАНЁННОГО ответа из кэша
    (producer_first_export, CAS ВСЕГДА, без пересчёта науки)."""
    if not result_ref:
        return []
    try:
        from apps.api.visual_producers import freeze_saved_visual

        freeze_saved_visual(
            run_id,
            _system_subject_for(run_id),
            view_id=view_id,
            result_ref=result_ref,
        )
    except Exception:  # noqa: BLE001 -- кэш недоступен/конфликт: честный gap
        return []
    return [
        a for a in list_visual_results(run_id, view_id=view_id)
        if a.refs.get("result_ref") == result_ref
    ]


def _system_subject_for(run_id: str) -> Any:
    """Субъект lazy-transfer freeze: владелец запуска (run.owner_subject)
    -- операция переносит ЕГО сохранённый ответ, авторизация проверяется
    _authorized_run'ом PGV-02 (owner-гейт)."""
    from apps.api.artifact_store import ArtifactAccessError
    from apps.api.identity import SubjectRef
    from apps.api.research_runs import get_research_run_store

    run = get_research_run_store().get_run(run_id)
    if run is None or not run.owner_subject:
        raise ArtifactAccessError("запуск недоступен")
    return SubjectRef.from_session(run.session_id or "")


def _artifact_payload(artifact: Any) -> dict[str, Any]:
    import json

    from apps.api.artifact_store import get_artifact_object_store

    return json.loads(
        get_artifact_object_store().read_bytes(artifact.storage_key).decode("utf-8")
    )


def list_visual_results(run_id: str, *, view_id: Optional[str] = None):
    from apps.api.visual_artifacts import list_visual_results as _list

    return _list(run_id, view_id=view_id)


# ── Сборка VisualPrintSnapshot/1 (контракт PGV-01) ────────────────────


def _heatmap_domain(cells: list) -> list[float]:
    """Домен шкалы из ФАКТИЧЕСКИХ ячеек frozen data (детерминированно;
    пусто -- честный [0, 1], паритет defaultHeatDomain rendererCore)."""
    values = [
        float(cell)
        for row in cells
        if isinstance(row, list)
        for cell in row
        if isinstance(cell, (int, float)) and not isinstance(cell, bool)
    ]
    if not values:
        return [0.0, 1.0]
    return [min(values), max(values)]


def build_visual_print_snapshot(
    run_id: str,
    *,
    site_view_id: str,
    result_artifact: Any,
    result_payload: Mapping[str, Any],
    profile_id: str = "figure-landscape",
    screen_svg: Optional[str] = None,
    expected_context_id: Optional[str] = None,
    expected_data_revision: Optional[int] = None,
    date_column: Optional[str] = None,
    render_requested_at: str,
) -> dict[str, Any]:
    """Сборка pgv.visual_print_snapshot/1 из frozen visual_result
    (ЧИСТАЯ функция от durable-фактов; правила PGV-01 -- валидатор).
    screen_svg замораживается в recharts-секции с sha256 (identity
    print input'а включает геометрию -- AC08)."""
    from apps.api.print_schema import (
        PRINT_SNAPSHOT_SCHEMA_VERSION,
        load_visual_registry,
        resolve_scope,
    )

    site = _site_for(site_view_id)
    if site is None:
        raise UnknownExportView(site_view_id)
    if screen_svg:
        validate_screen_svg(screen_svg)

    payload_rec = result_payload.get("payload") or {}
    data = payload_rec.get("data")
    if not isinstance(data, dict):
        raise VisualSourceUnavailable(
            "frozen visual_result без data -- печатный вход неполон (§3.6)"
        )
    execution = result_payload.get("execution") or {}
    parameters = result_payload.get("parameters") or {}
    sampling = result_payload.get("sampling") or {}
    units = result_payload.get("units") or []
    view_params = [str(k) for k in site.get("view_params", [])]
    trusted_params = {
        key: value
        for key, value in (parameters.get("parameters") or {}).items()
        if key in view_params
    }

    sections: list[dict[str, Any]] = []
    for section_spec in mixed_sections_for(site_view_id, str(site["renderer_kind"])):
        section: dict[str, Any] = {
            "section_id": str(section_spec["section_id"]),
            "renderer_kind": str(section_spec["renderer_kind"]),
            "title": section_spec.get("title"),
            "units": [dict(unit) for unit in units] or [{"value": None, "reason": "dimensionless"}],
            "axes": [],
            "legend_ordering": [],
            "table_headings": None,
            "heatmap_scale": None,
        }
        kind = section["renderer_kind"]
        if kind == "recharts_svg":
            if not screen_svg:
                raise PrintScreenSvgRequired(
                    f"view {site_view_id!r}: печатная секция графика требует "
                    "frozen экранный SVG (сериализация узла конкретного "
                    "view -- не первый SVG документа)"
                )
            section["axes"] = [
                dict(axis) for axis in CHART_AXES.get(site_view_id, _axes(_X_TIME, _Y_VALUE))
            ]
            section["screen_svg"] = screen_svg
            section["screen_svg_sha256"] = _screen_svg_digest(screen_svg)
        elif kind == "html_table":
            # PGV-11: композиция может нести динамические заголовки из
            # frozen данных (AC02: bins зависят от данных -- заголовки
            # замораживаются В СНАПШОТЕ из тех же bins, не фабрикуются).
            frozen_builder = section_spec.get("table_headings_from_frozen")
            headings: Optional[dict[str, Any]]
            if frozen_builder:
                if frozen_builder != "ih_conditional_map":  # pragma: no cover -- каталог фиксирован
                    raise VisualExportError(
                        f"неизвестный строитель заголовков {frozen_builder!r}"
                    )
                headings = _ih_conditional_frozen_headings(data)
                if not headings:
                    raise VisualExportError(
                        f"табличная секция {site_view_id!r}: заголовки печати "
                        "не выводятся из frozen данных (bins отсутствуют) -- "
                        "честный отказ, заголовки не фабрикуются"
                    )
            else:
                headings = section_spec.get("table_headings") or TABLE_HEADINGS.get(
                    site_view_id
                )
                if not headings:
                    raise VisualExportError(
                        f"табличная секция {site_view_id!r} без заголовков печати"
                    )
            section["table_headings"] = dict(headings)
        elif kind == "html_heatmap":
            cells = data.get("cells") or []
            section["heatmap_scale"] = {
                "domain": _heatmap_domain(cells),
                "units": {"value": None, "reason": "legacy_unknown"},
            }
        sections.append(section)

    sampling_mode = str(sampling.get("mode") or "full")
    detail_level = (
        "sampling"
        if sampling_mode in ("downsampled", "windowed", "truncated", "aggregated")
        else "expanded"
    )
    context_id = expected_context_id
    data_revision = expected_data_revision
    if context_id is None:
        context_id = getattr(result_artifact, "context_id", None)
    if data_revision is None:
        data_revision = getattr(result_artifact, "data_revision", None)

    refs, missing_ref = _snapshot_refs(
        run_id,
        site,
        result_payload,
        date_column=date_column,
    )
    if missing_ref:
        raise VisualSourceUnavailable(
            f"обязательный ref снапшота недоступен: {missing_ref} "
            "(честный отказ -- refs не фабрикуются)"
        )

    from apps.api.artifact_store import canonical_json_bytes

    snapshot: dict[str, Any] = {
        "schema_version": PRINT_SNAPSHOT_SCHEMA_VERSION,
        "view_id": site_view_id,
        "scope": resolve_scope(site),
        "refs": refs,
        "result": {
            "result_artifact_id": getattr(result_artifact, "artifact_id", None),
            "result_ref": execution.get("result_ref"),
            "result_schema_version": result_payload.get("schema_version"),
            "result_digest": payload_rec.get("digest"),
            "result_digest_reason": payload_rec.get("digest_reason"),
            # PGV-10: identity frozen print input'а включает экранный SVG
            # (иной frozen print input -- другой снапшот, AC08).
            "screen_svg_sha256": _screen_svg_digest(screen_svg),
        },
        "data_artifact": {
            "artifact_id": getattr(result_artifact, "artifact_id", None),
            "artifact_version": str(
                getattr(result_artifact, "data_revision", "") or ""
            ),
            "source_hash": payload_rec.get("digest"),
            "hash_algorithm": "sha256(canonical_json)",
            "hash_reason": None,
        },
        "expected_context": {
            "context_id": context_id,
            "data_revision": (
                str(data_revision) if data_revision is not None else None
            ),
        },
        "times": {
            "computed_at": execution.get("computed_at"),
            "computed_at_reason": execution.get("computed_at_reason"),
            "captured_at": getattr(result_artifact, "created_at", None),
            "captured_at_reason": (
                None
                if getattr(result_artifact, "created_at", None)
                else "producer_not_reported"
            ),
            "render_requested_at": render_requested_at,
            "timezone": "UTC",
            "locale": "ru-RU",
        },
        "checkpoint": {"reused": False},
        "display": {
            "title": VIEW_TITLES.get(site_view_id, site_view_id),
            "subtitle": site.get("notes"),
            "detail_level": detail_level,
            "sections": sections,
        },
        "method": {
            "origin": parameters.get("origin"),
            "method": parameters.get("method"),
            "parameters": trusted_params,
        },
        "selection": {
            "allowlist": view_params,
            "values": dict(trusted_params),
        },
        "sampling": dict(sampling),
        "dimensions": {
            "mode": "univariate",
            "entity_column": None,
            "entity_id": None,
        },
        "print": {
            "profile_id": profile_id,
            "page_count": 1,
            "theme": "light-print",
        },
        "renderer_env": {
            "dependency_status": "unknown",
            "unavailable_reason": None,
            "renderer_version": "print-renderer/1",
            "font_profile": "print-fonts-dejavu/1",
        },
        "sensitive": {
            "raw_data_included": False,
            "sensitive_fields_policy": "metadata-only; raw данные не вкладываются (spec §11)",
        },
        "annotations": {"revision": 0},
    }
    # Согласованность: канонизируемость payload -- гейт persist PGV-02;
    # здесь -- ранняя честная проверка сериализуемости снапшота.
    try:
        canonical_json_bytes(snapshot)
    except Exception as exc:  # noqa: BLE001 -- неканоничный вход
        raise VisualExportError(
            f"снапшот неканоничен (честный отказ): {exc}"
        ) from exc
    return snapshot


def _snapshot_refs(
    run_id: str,
    site: Mapping[str, Any],
    result_payload: Mapping[str, Any],
    *,
    date_column: Optional[str],
) -> tuple[dict[str, str], Optional[str]]:
    """refs research-снапшота (context/revision -- durable run; target --
    run.target_column; date -- сессия/запрос; grouping/frequency
    (structure.schema) -- из frozen data). Отсутствие обязательного
    refs -- честный отказ (не фабрикуется)."""
    from apps.api.research_runs import get_research_run_store

    run = get_research_run_store().get_run(run_id)
    if run is None:
        return {}, "run"
    refs: dict[str, str] = {
        "context_id": str(run.context_id or "") or "",
        "data_revision": (
            str(run.data_revision) if run.data_revision is not None else ""
        ),
        "target_column": str(run.target_column or "") or "",
    }
    for key, value in (
        ("context_id", run.context_id),
        ("data_revision", run.data_revision),
        ("target_column", run.target_column),
    ):
        if value is None or str(value) == "":
            return {}, key
    resolved_date = date_column
    if not resolved_date:
        resolved_date = _session_date_column(run)
    if not resolved_date:
        return {}, "date_column"
    refs["date_column"] = resolved_date
    if "grouping_column" in set(site.get("required_refs", [])):
        data = (result_payload.get("payload") or {}).get("data") or {}
        # «(не использовать)» -- легитимное подтверждённое значение
        # структуры (PROGR-14-A); отсутствие -- не фабрикация.
        refs["grouping_column"] = str(
            data.get("entity_column") or "(не используется)"
        )
        refs["frequency_hint"] = str(
            data.get("frequency") or "(не определена)"
        )
    if "modeling_artifact_ref" in set(site.get("required_refs", [])):
        # PGV-11 (tasks): карта моделей, для которой вычислена важность
        # -- из frozen card (без фабрикации: нет id -- честный отказ).
        data = (result_payload.get("payload") or {}).get("data") or {}
        artifact_ref = str(data.get("modeling_artifact_ref") or "")
        if not artifact_ref:
            return {}, "modeling_artifact_ref"
        refs["modeling_artifact_ref"] = artifact_ref
    return refs, None


def _session_date_column(run: Any) -> Optional[str]:
    """date_column из сессии запуска (структура «Загрузки»); сессия
    утрачена -- None (ref недоступен -- честный отказ наверху)."""
    try:
        from apps.api.session_store import get_session_store

        session = get_session_store().get_or_create(run.session_id)
        return session.date_column or None
    except Exception:  # noqa: BLE001 -- сессия недоступна: честный None
        return None


# ── Сервис экспорта (freeze -> snapshot -> V01 -> job) ────────────────


def list_visual_sources(run_id: str, subject: Any, *, session_id: str = "") -> dict[str, Any]:
    """GET visual-sources (§11): доступные frozen inputs/views/
    applicability/metadata БЕЗ запуска науки (только чтение реестров)."""
    from apps.api.artifact_promotion import (
        ArtifactAccessDenied,
        PromotionDenied,
        PromotionService,
    )

    service = PromotionService.create_default()
    try:
        service._authorized_run(run_id, subject, session_id, action="read")
    except (PromotionDenied, ArtifactAccessDenied) as exc:
        raise VisualExportAccessDenied("visual-sources недоступны") from exc

    sources: list[dict[str, Any]] = []
    for view_id in export_view_ids():
        site = _site_for(view_id) or {}
        results = list_visual_results(run_id, view_id=view_id)
        snapshots = _list_snapshots(run_id, view_id=view_id)
        latest_result: Optional[dict[str, Any]] = None
        if results:
            artifact = results[-1]
            payload = _artifact_payload(artifact)
            execution = payload.get("execution") or {}
            latest_result = {
                "artifact_id": artifact.artifact_id,
                "result_ref": execution.get("result_ref"),
                "digest": (payload.get("payload") or {}).get("digest"),
                "computed_at": execution.get("computed_at"),
                "computed_at_reason": execution.get("computed_at_reason"),
                "context_id": getattr(artifact, "context_id", None),
                "data_revision": getattr(artifact, "data_revision", None),
            }
        latest_snapshot: Optional[dict[str, Any]] = None
        if snapshots:
            snapshot_artifact = snapshots[-1]
            latest_snapshot = {
                "artifact_id": snapshot_artifact.artifact_id,
                "profile_id": (snapshot_artifact.refs or {}).get("profile_id"),
                "captured_at": getattr(snapshot_artifact, "created_at", None),
            }
        sources.append(
            {
                "view_id": view_id,
                "module_id": site.get("module_id"),
                "stop_id": site.get("stop_id"),
                "renderer_kind": site.get("renderer_kind"),
                "applicability": site.get("applicability"),
                "title": VIEW_TITLES.get(view_id, view_id),
                "export_ready": latest_result is not None,
                "latest_result": latest_result,
                "latest_snapshot": latest_snapshot,
                "unavailable_reason": (
                    None
                    if latest_result is not None
                    else "result_not_frozen -- откройте представление, "
                    "чтобы зафиксировать результат"
                ),
            }
        )
    return {"run_id": run_id, "sources": sources}


def _list_snapshots(run_id: str, *, view_id: Optional[str] = None):
    from apps.api.visual_artifacts import list_visual_print_snapshots

    return list_visual_print_snapshots(run_id, view_id=view_id)


def request_visual_export(
    run_id: str,
    subject: Any,
    *,
    view_id: str,
    session_id: str = "",
    result_ref: Optional[str] = None,
    profile_id: str = "figure-landscape",
    screen_svg: Optional[str] = None,
    expected_context_id: Optional[str] = None,
    expected_data_revision: Optional[int] = None,
    date_column: Optional[str] = None,
    redaction_profile: str = "default",
    render_requested_at: str,
) -> dict[str, Any]:
    """POST /visuals (§10.1/§11): «Скачать PNG» -> freeze ->
    VisualPrintSnapshot/1 -> V01 revision -> PNG job (PGV-09) -> 202.

    Идемпотентность (§11/AC09/§12.2): identity снапшота вычисляется ДО
    сборки payload; существующий frozen input переиспользуется (его
    время фиксации не переписывается) -> та же ревизия -> тот же
    активный/ready job. Иной screen_svg -- другой print input (новый
    immutable снапшот, §8)."""
    site = resolve_export_view(view_id)
    from apps.api.artifact_promotion import (
        ArtifactAccessDenied,
        PromotionDenied,
        PromotionService,
    )
    from apps.api.print_schema import resolve_print_profile

    # Авторизация -- ПЕРВЫЙ шаг (R09/§11): чужой/несуществующий run --
    # uniform отказ ДО чтения durable-содержимого.
    _promotion_gate = PromotionService.create_default()
    try:
        _promotion_gate._authorized_run(run_id, subject, session_id, action="write")
    except (PromotionDenied, ArtifactAccessDenied) as exc:
        raise VisualExportAccessDenied("экспорт недоступен") from exc

    if resolve_print_profile(profile_id) is None:
        raise VisualExportError(
            f"invalid_profile: профиль {profile_id!r} вне каталога PGV-01"
        )
    if screen_svg:
        validate_screen_svg(screen_svg)
    if screen_svg and len(screen_svg) > 8_000_000:
        raise VisualExportError(
            "export_too_large: сериализованный SVG превышает 8 MiB "
            "(лимит тела рендера PGV-08)"
        )

    result_artifact, result_payload = resolve_frozen_result(
        run_id, view_id, result_ref=result_ref
    )
    payload_rec = result_payload.get("payload") or {}
    svg_digest = _screen_svg_digest(screen_svg)

    # 1) Идемпотентный повтор: существующий frozen print input по
    #    producer key (до сборки payload -- §12.2 «повторный клик не
    #    создаёт дубли»; старые snapshots не переписываются, §8).
    identity = payload_rec.get("digest") or payload_rec.get("digest_reason") or "unknown"
    producer_key = f"pgv.print_snapshot:{view_id}:{identity}"
    if svg_digest:
        producer_key = f"{producer_key}:{svg_digest[:16]}"
    from apps.api.artifact_promotion import PromotionService

    promotion = PromotionService.create_default()
    existing_snapshot = promotion.find_by_producer(run_id, producer_key)
    if existing_snapshot is not None:
        snapshot_artifact = existing_snapshot
    else:
        snapshot_payload = build_visual_print_snapshot(
            run_id,
            site_view_id=view_id,
            result_artifact=result_artifact,
            result_payload=result_payload,
            profile_id=profile_id,
            screen_svg=screen_svg,
            expected_context_id=expected_context_id,
            expected_data_revision=expected_data_revision,
            date_column=date_column,
            render_requested_at=render_requested_at,
        )
        # 2) CAS freeze снапшота (PGV-02; expected_context -- ожидание
        #    клиента либо контекст frozen результата).
        from apps.api.visual_artifacts import freeze_visual_print_snapshot

        try:
            snapshot_artifact = freeze_visual_print_snapshot(
                run_id,
                subject,
                payload=snapshot_payload,
                session_id=session_id,
                result_artifact_id=getattr(result_artifact, "artifact_id", None),
            )
        except (PromotionDenied, ArtifactAccessDenied) as exc:
            # Чужой/несуществующий run -- uniform отказ (R09/AC18).
            raise VisualExportAccessDenied("экспорт недоступен") from exc

    # 3) V01 печатная ревизия (basis = frozen print input; идемпотентность
    #    по basis_fingerprint, §10.2/§12.2).
    from apps.api.document_jobs import DocumentDeliveryService

    documents = DocumentDeliveryService.create_default()
    _document, revision, _created = documents.ensure_print_document_revision(
        run_id,
        subject,
        session_id=session_id,
        print_kind="V01",
        basis_kind="visual_print_snapshot",
        basis_artifact_ids=[snapshot_artifact.artifact_id],
        profile_id=profile_id,
    )

    # 4) PNG job через печатный конвейер PGV-09 (lease/staging/CAS --
    #    общий жизненный цикл; renderer-контейнер PGV-08).
    job, rendition = documents.request_print_rendition(
        revision.print_revision_id,
        format="png",
        subject=subject,
        session_id=session_id,
        redaction_profile=redaction_profile,
    )
    return {
        "run_id": run_id,
        "view_id": view_id,
        "result_artifact_id": getattr(result_artifact, "artifact_id", None),
        "result_ref": (result_payload.get("execution") or {}).get("result_ref"),
        "snapshot_artifact_id": snapshot_artifact.artifact_id,
        "document_id": _document.document_id,
        "print_revision_id": revision.print_revision_id,
        "print_kind": "V01",
        "profile_id": profile_id,
        "job": _job_json(job, rendition),
        "status_url": f"/v1/documentation/jobs/{job.job_id}",
    }


def _job_json(job: Any, rendition: Any) -> dict[str, Any]:
    """Плоская проекция job'а для ответа API (паритет _job_json
    роутера документации; без содержимого)."""
    out = {
        "job_id": job.job_id,
        "state": job.state,
        "format": job.format,
        "attempt": job.attempt,
        "print_revision_id": getattr(job, "print_revision_id", "") or None,
        "error_code": job.error_code,
        "created_at": job.created_at,
    }
    if rendition is not None:
        out["rendition_id"] = rendition.rendition_id
        out["rendition_state"] = rendition.state
    return out
