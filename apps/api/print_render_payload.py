# apps/api/print_render_payload.py
"""
Task PGV-09 (spec_passport_graphics_visual.md §4/§6/§11/§13, строка
PGV-09): мост frozen durable-входов -> pgv.render_payload/1
контейнера PGV-08.

§4.1: «Renderer получает frozen typed payload и закреплённые result
refs. Источником не служат текущий DOM аналитика, cookie-relative GET
с расчётами или произвольный HTML клиента». Сборка payload'а -- ЧИСТАЯ
функция от durable-пару (visual_print_snapshot + visual_result):
никакой науки, никакого DOM, никакого fetch (AC06).

СОСТАВ PAYLOAD (контракт rendererCore.tsx PGV-08):
  schema_version = pgv.render_payload/1;
  request_id     -- от document job (pgv:job-<id>);
  snapshot       -- VisualPrintSnapshot/1 (метаданные PGV-01);
  sections       -- КОНТЕНТ секций по display.sections[].section_id.

СОДЕРЖИМОЕ СЕКЦИЙ (§6: «Producer adapter фиксирует print input»):
источник -- durable visual_result артефакт (зависимость print
snapshot'а), payload.data. Канонические формы (паритет адаптеров
PGV-03, apps/api/visual_producers.py):

  html_table    {columns, rows}        -> headings/rows-контент
                 {headings, rows}      -> контент-форма напрямую
  html_cards    {cards}                -> контент-форма напрямую
  html_heatmap  {row_headings, column_headings, cells, ...}
                 {columns, matrix}     -> матрица (rows==columns
                                          семантика адаптеров
                                          missing_correlation/
                                          feature_matrix)
  ih_conditional {ih_input}            -> контент-форма напрямую
  recharts_svg  {svg_xml}|{svg}        -> frozen экранный SVG

ВСЁ ОСТАЛЬНОЕ -- PrintRenderPayloadIncomplete (terminal
missing_section_content в job-терминах): §3.6 «Отсутствие, усечение,
агрегация, panel и reused checkpoint маркируются; неполнота не
подменяется нулями». В частности recharts_svg без frozen svg_xml не
рендерится: Python-сторона НЕ перерисовывает Recharts-геометрию
(единственная реализация рендера -- общий print-бандл PGV-07, §4.1);
frozen SVG появится с render-site адаптерами PGV-10…12 -- gap виден,
не фабрикуется.

Таблица: строки -- СПИСКИ строковых ячеек (первая колонка данных --
row heading по духу §7 «row headers»); значения канонизируются в
строки честно (None -> пустая ячейка -- отсутствие значения, не ноль).
"""
from __future__ import annotations

from typing import Any, Mapping

# Контракт версии payload'а (паритет rendererCore.tsx PGV-08).
RENDER_PAYLOAD_VERSION = "pgv.render_payload/1"

_SECTION_KINDS = ("recharts_svg", "html_table", "html_heatmap", "html_cards", "ih_conditional")


class PrintRenderPayloadIncomplete(RuntimeError):
    """§3.6: контент секции отсутствует/неполн -- честный отказ сборки
    (job-код missing_section_content)."""


class PrintRenderPayloadInvalid(RuntimeError):
    """Snapshot не прошёл preflight печатной схемы (job-код
    invalid_payload)."""


def _rec(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _cell(value: Any) -> str:
    """Канонизация ячейки: отсутствие значения -- пустая строка, не
    ноль (§3.6)."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            return ""
        return repr(value)
    return str(value)


def _table_content(data: Mapping[str, Any]) -> dict[str, Any] | None:
    """{headings, rows} (контент-форма) либо {columns, rows} (форма
    адаптеров PGV-03) -> строки контента html_table. Заголовки -- зона
    метаданных снапшота (authority состава печати): resolver несёт
    headings только для контент-формы, чтобы build_render_payload мог
    предпочесть метаданные PGV-01. PGV-10: форма {columns, matrix}
    корреляционных срезов (строки == колонки) разворачивается в таблицу
    с row-headers из имён колонок (§7 «row headers»)."""
    headings = data.get("headings")
    rows = data.get("rows")
    if isinstance(headings, dict) and isinstance(rows, list):
        row_headings = [str(h) for h in headings.get("row", [])]
        column_headings = [str(h) for h in headings.get("column", [])]
        normalized = [
            [_cell(cell) for cell in row] if isinstance(row, (list, tuple)) else [_cell(row)]
            for row in rows
        ]
        content: dict[str, Any] = {
            "headings": {"row": row_headings, "column": column_headings},
            "rows": normalized,
        }
        if "caption" in data:
            content["caption"] = data.get("caption")
        return content
    columns = data.get("columns")
    if isinstance(columns, list) and isinstance(rows, list):
        names = [str(c) for c in columns]
        normalized = []
        for row in rows:
            if isinstance(row, Mapping):
                normalized.append([_cell(row.get(name)) for name in names])
            elif isinstance(row, (list, tuple)):
                normalized.append([_cell(cell) for cell in row])
            else:
                normalized.append([_cell(row)])
        content = {"rows": normalized}
        # PGV-11: caption печатной формы (честная пометка о шкале/
        # знаменателе) переносится и для формы {columns, rows}.
        if isinstance(data.get("caption"), str):
            content["caption"] = data.get("caption")
        return content
    matrix = data.get("matrix")
    if isinstance(columns, list) and isinstance(matrix, list):
        names = [str(c) for c in columns]
        normalized = []
        for row in matrix:
            if isinstance(row, (list, tuple)):
                normalized.append([_cell(cell) for cell in row])
            else:
                normalized.append([_cell(row)])
        content = {"rows": normalized}
        if isinstance(data.get("caption"), str):
            content["caption"] = data.get("caption")
        return content
    return None


def _cards_content(data: Mapping[str, Any]) -> dict[str, Any] | None:
    """{cards: [{label, value, unit?}]} -> контент html_cards."""
    cards = data.get("cards")
    if not isinstance(cards, list) or not cards:
        return None
    normalized = []
    for card in cards:
        card_rec = _rec(card)
        label = card_rec.get("label")
        if label is None:
            return None  # карточка без label -- неканоничная форма
        unit = card_rec.get("unit")
        normalized.append(
            {
                "label": str(label),
                "value": _cell(card_rec.get("value")),
                "unit": unit if (unit is None or isinstance(unit, dict)) else None,
            }
        )
    return {"cards": normalized}


def _heatmap_content(data: Mapping[str, Any]) -> dict[str, Any] | None:
    """{row_headings, column_headings, cells, ...} (контент-форма) либо
    {columns, matrix} (семантика адаптеров корреляционных матриц) ->
    контент html_heatmap."""
    row_headings = data.get("row_headings")
    column_headings = data.get("column_headings")
    cells = data.get("cells")
    if (
        isinstance(row_headings, list)
        and isinstance(column_headings, list)
        and isinstance(cells, list)
    ):
        content: dict[str, Any] = {
            "row_headings": [str(h) for h in row_headings],
            "column_headings": [str(h) for h in column_headings],
            "cells": cells,
        }
        if isinstance(data.get("cell_texts"), list):
            content["cell_texts"] = data["cell_texts"]
        if isinstance(data.get("domain"), (list, tuple)) and len(data["domain"]) == 2:
            content["domain"] = list(data["domain"])
        return content
    columns = data.get("columns")
    matrix = data.get("matrix")
    if isinstance(columns, list) and isinstance(matrix, list):
        names = [str(c) for c in columns]
        return {
            "row_headings": names,  # матрица N×N: строки == колонки
            "column_headings": names,
            "cells": matrix,
        }
    return None


def _svg_content(data: Mapping[str, Any]) -> dict[str, Any] | None:
    """{svg_xml}|{svg} -> контент recharts_svg (frozen экранный SVG)."""
    svg = data.get("svg_xml") or data.get("svg")
    if isinstance(svg, str) and svg.strip():
        content: dict[str, Any] = {"svg_xml": svg}
        height = data.get("height_px")
        if isinstance(height, (int, float)) and height > 0:
            content["height_px"] = height
        return content
    return None


def _ih_content(data: Mapping[str, Any]) -> dict[str, Any] | None:
    """{ih_input} -> контент ih_conditional (frozen IH-вход)."""
    ih = data.get("ih_input")
    if isinstance(ih, dict) and ih:
        return {"ih_input": ih}
    return None


_CONTENT_BUILDERS = {
    "html_table": _table_content,
    "html_cards": _cards_content,
    "html_heatmap": _heatmap_content,
    "recharts_svg": _svg_content,
    "ih_conditional": _ih_content,
}


def _snapshot_section_svg(section: Mapping[str, Any]) -> dict[str, Any] | None:
    """PGV-10: frozen экранный SVG из СЕКЦИИ снапшота (клиент
    сериализует узел конкретного view -- не первый SVG документа;
    identity снапшота включает sha256 геометрии)."""
    svg = section.get("screen_svg")
    if isinstance(svg, str) and svg.strip():
        content: dict[str, Any] = {"svg_xml": svg}
        height = section.get("height_px")
        if isinstance(height, (int, float)) and height > 0:
            content["height_px"] = height
        return content
    return None


def section_content_from_visual_result(
    snapshot_payload: Mapping[str, Any],
    visual_result_payload: Mapping[str, Any],
) -> dict[str, dict[str, Any]]:
    """Контент секций из frozen visual_result (payload.data).

    Ключ -- section_id секции snapshot'а. PGV-10: каждая секция строится
    СВОИМ строителем по renderer_kind СЕКЦИИ (mixed-сайт -- несколько
    секций из ОДНОГО frozen data, §6); recharts_svg предпочитает
    screen_svg СЕКЦИИ снапшота, fallback -- {svg_xml} в frozen data.
    Отсутствие канонической формы для ЛЮБОЙ секции -- честный отказ
    (§3.6 «неполнота не подменяется нулями»)."""
    result_payload = _rec(visual_result_payload.get("payload"))
    data = result_payload.get("data")
    if not isinstance(data, dict):
        raise PrintRenderPayloadIncomplete(
            "missing_section_content: visual_result без frozen data "
            "(§3.6: контент не фабрикуется)"
        )
    sections = _rec(snapshot_payload.get("display")).get("sections") or []
    out: dict[str, dict[str, Any]] = {}
    for section in sections:
        section_rec = _rec(section)
        section_id = section_rec.get("section_id")
        kind = section_rec.get("renderer_kind")
        if not isinstance(section_id, str) or not section_id:
            continue
        builder = _CONTENT_BUILDERS.get(kind)
        if builder is None:  # pragma: no cover -- каталог фиксирован
            raise PrintRenderPayloadIncomplete(
                f"missing_section_content: неизвестный renderer_kind {kind!r}"
            )
        if kind == "recharts_svg":
            # Frozen экранный SVG: секция снапшота (PGV-10) -- первичный
            # источник; {svg_xml} в data -- совместимость (§4.1 passthrough).
            content = _snapshot_section_svg(section_rec) or builder(data)
        else:
            content = builder(data)
        if content is None:
            raise PrintRenderPayloadIncomplete(
                f"missing_section_content: срез результата {section_id!r} "
                f"не содержит канонической формы контента для {kind!r} "
                "(§3.6: неполнота не фабикуется)"
            )
        out[section_id] = content
    if not out:
        raise PrintRenderPayloadIncomplete(
            "missing_section_content: ни одна секция не имеет контента"
        )
    return out


def build_render_payload(
    snapshot_payload: Mapping[str, Any],
    content_by_section: Mapping[str, Mapping[str, Any]],
    *,
    request_id: str,
) -> dict[str, Any]:
    """Сборка pgv.render_payload/1 (ЧИСТАЯ функция; AC06).

    Контент -- только из content_by_section (источник -- durable
    visual_result); лишние ключи content_by_section игнорируются
    (снапшот -- authority состава печати), отсутствующий контент секции
    -- честный отказ."""
    if not isinstance(snapshot_payload, Mapping) or not snapshot_payload:
        raise PrintRenderPayloadInvalid(
            "invalid_payload: frozen snapshot обязателен"
        )
    schema_version = snapshot_payload.get("schema_version")
    if schema_version != "pgv.visual_print_snapshot/1":
        raise PrintRenderPayloadInvalid(
            "invalid_payload: ожидается pgv.visual_print_snapshot/1, "
            f"получено {schema_version!r}"
        )
    sections_meta = _rec(snapshot_payload.get("display")).get("sections") or []
    if not isinstance(sections_meta, list) or not sections_meta:
        raise PrintRenderPayloadInvalid(
            "invalid_payload: снапшот обязан нести хотя бы одну секцию"
        )
    sections: list[dict[str, Any]] = []
    for section in sections_meta:
        section_rec = _rec(section)
        section_id = section_rec.get("section_id")
        kind = section_rec.get("renderer_kind")
        if not isinstance(section_id, str) or not section_id:
            raise PrintRenderPayloadInvalid(
                "invalid_payload: section_id обязателен"
            )
        if kind not in _SECTION_KINDS:
            raise PrintRenderPayloadInvalid(
                f"invalid_payload: недопустимый renderer_kind {kind!r}"
            )
        content = content_by_section.get(section_id)
        if content is None:
            raise PrintRenderPayloadIncomplete(
                f"missing_section_content: секция {section_id!r} без "
                "frozen контента (§3.6)"
            )
        composed: dict[str, Any] = {"section_id": section_id, "kind": kind}
        title = section_rec.get("title")
        if isinstance(title, str) and title:
            composed["title"] = title
        if kind == "html_table":
            if "rows" not in content:
                raise PrintRenderPayloadIncomplete(
                    f"missing_section_content: таблица {section_id!r} без "
                    "frozen rows"
                )
            # Заголовки -- из метаданных снапшота (authority, PGV-01);
            # контент-форма может нести собственные -- fallback.
            meta_headings = _rec(section_rec.get("table_headings"))
            meta_row = [
                str(h) for h in meta_headings.get("row", []) if isinstance(h, str)
            ]
            meta_column = [
                str(h) for h in meta_headings.get("column", []) if isinstance(h, str)
            ]
            if meta_row or meta_column:
                composed["headings"] = {"row": meta_row, "column": meta_column}
            elif isinstance(content.get("headings"), dict):
                composed["headings"] = content["headings"]
            else:
                raise PrintRenderPayloadIncomplete(
                    f"missing_section_content: таблица {section_id!r} без "
                    "заголовков (ни в снапшоте, ни в контенте)"
                )
            composed["rows"] = content["rows"]
            if isinstance(content.get("caption"), str):
                composed["caption"] = content["caption"]
        elif kind == "html_heatmap":
            for key in ("row_headings", "column_headings", "cells"):
                if key not in content:
                    raise PrintRenderPayloadIncomplete(
                        f"missing_section_content: теплокарта {section_id!r} "
                        f"без {key}"
                    )
                composed[key] = content[key]
            if isinstance(content.get("cell_texts"), list):
                composed["cell_texts"] = content["cell_texts"]
            if isinstance(content.get("domain"), (list, tuple)):
                composed["domain"] = list(content["domain"])
        elif kind == "html_cards":
            if "cards" not in content:
                raise PrintRenderPayloadIncomplete(
                    f"missing_section_content: карточки {section_id!r} без cards"
                )
            composed["cards"] = content["cards"]
        elif kind == "ih_conditional":
            if "ih_input" not in content:
                raise PrintRenderPayloadIncomplete(
                    f"missing_section_content: IH {section_id!r} без ih_input"
                )
            composed["ih_input"] = content["ih_input"]
        elif kind == "recharts_svg":
            svg = content.get("svg_xml")
            if not isinstance(svg, str) or not svg.strip():
                raise PrintRenderPayloadIncomplete(
                    f"missing_section_content: {section_id!r} без frozen "
                    "svg_xml (экранный SVG не фабрикуется; §4.1)"
                )
            composed["svg_xml"] = svg
            if isinstance(content.get("height_px"), (int, float)):
                composed["height_px"] = content["height_px"]
        sections.append(composed)
    return {
        "schema_version": RENDER_PAYLOAD_VERSION,
        "request_id": request_id,
        "snapshot": dict(snapshot_payload),
        "sections": sections,
    }


# ── Durable-чтение печатного входа (worker, AC05/§6) ─────────────────


class PrintRenderBasisUnavailable(RuntimeError):
    """Basis-артефакт печатной ревизии недоступен/нечитаем/чужой
    (job-код render_basis_unavailable; честный отказ -- §8 «durable
    документ не обещается до commit», T8-дух integrity)."""


def load_print_render_input(basis_artifact_id: str) -> dict[str, Any]:
    """Системное чтение frozen печатного входа по basis-артефакту
    (БЕЗ subject: job был авторизован при постановке; worker -- часть
    того же контура, паритет load_snapshot_system DOCLOG-5).

    ТОЛЬКО durable-слой (registry + ObjectStore) с проверкой
    payload_sha256 (T8-дух); зависимость visual_result резолвится из
    pins/dependencies артефакта (§16: metadata graph хранит причины
    ссылок). Никакой науки (AC06), никакого SessionStore (§8).

    Возвращает {"snapshot": ..., "visual_result": ..., "basis_sha256"}.
    Отсутствие/чужой kind/расхождение digest -- честные исключения."""
    import hashlib
    import json

    from apps.api.artifact_store import (
        ArtifactIntegrityError,
        get_artifact_object_store,
        get_artifact_registry,
    )

    registry = get_artifact_registry()
    artifact = registry.get_artifact(basis_artifact_id)
    if artifact is None:
        raise PrintRenderBasisUnavailable(
            "render_basis_unavailable: basis-артефакт печатной ревизии "
            "отсутствует в реестре"
        )
    if artifact.kind != "visual_print_snapshot":
        raise PrintRenderBasisUnavailable(
            f"render_basis_unavailable: kind {artifact.kind!r} не является "
            "visual_print_snapshot"
        )
    try:
        data = get_artifact_object_store().read_bytes(artifact.storage_key)
    except ArtifactIntegrityError as exc:
        raise PrintRenderBasisUnavailable(
            f"render_basis_unavailable: content_key_mismatch ({exc})"
        ) from None
    except (FileNotFoundError, OSError) as exc:
        raise PrintRenderBasisUnavailable(
            f"render_basis_unavailable: content_unreadable ({type(exc).__name__})"
        ) from None
    if artifact.payload_sha256 and (
        hashlib.sha256(data).hexdigest() != artifact.payload_sha256
    ):
        raise PrintRenderBasisUnavailable(
            "render_basis_unavailable: payload_sha256_mismatch (T8-дух)"
        )
    try:
        snapshot_payload = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PrintRenderBasisUnavailable(
            f"render_basis_unavailable: payload_not_json ({exc})"
        ) from None
    if not isinstance(snapshot_payload, dict):
        raise PrintRenderBasisUnavailable(
            "render_basis_unavailable: payload_not_object"
        )
    # Зависимость visual_result (§6: «результат переносится из
    # фактического response в durable слой» -- контент секций).
    result_payload: dict[str, Any] | None = None
    for dependency_id in artifact.dependencies:
        dependency = registry.get_artifact(dependency_id)
        if dependency is None or dependency.kind != "visual_result":
            continue
        try:
            dep_bytes = get_artifact_object_store().read_bytes(
                dependency.storage_key
            )
        except Exception:  # noqa: BLE001 -- зависимость нечитаема: gap
            continue
        try:
            candidate = json.loads(dep_bytes.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue
        if isinstance(candidate, dict):
            result_payload = candidate
            break
    if result_payload is None:
        raise PrintRenderBasisUnavailable(
            "render_basis_unavailable: у печатного снапшота нет читаемой "
            "зависимости visual_result (контент секций -- §6)"
        )
    return {
        "snapshot": snapshot_payload,
        "visual_result": result_payload,
        "basis_sha256": artifact.payload_sha256 or "",
    }


def build_print_render_payload_from_basis(
    basis: Mapping[str, Any], *, request_id: str
) -> dict[str, Any]:
    """Сборка pgv.render_payload/1 из загруженного basis (префетч
    load_print_render_input + preflight PGV-01 до постановки байтов в
    сеть -- «preflight либо явный отказ», §7)."""
    snapshot_payload = basis.get("snapshot")
    visual_result_payload = basis.get("visual_result")
    content = section_content_from_visual_result(
        snapshot_payload, visual_result_payload
    )
    return build_render_payload(
        snapshot_payload, content, request_id=request_id
    )
