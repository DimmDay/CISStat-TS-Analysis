# apps/api/document_renditions.py
"""
DOCLOG-4 (spec_documentation_logging.md §7, §12.3, §19 строка DOCLOG-4,
§20 AC05/AC16): рендеры MVP-выдачи -- ЧИСТЫЕ функции от замороженного
ReportSnapshot.

DOCLOG-5 (§7 очередь P1, §12.3, §18, §19 строка DOCLOG-5, §20
AC03/AC08/AC16): тяжёлые форматы и evidence-пакет -- те же ЧИСТЫЕ
функции от снимка, но выполняются асинхронным worker'ом
(document_render_worker; §18: «тяжёлый PDF не создаётся синхронно»):
  pdf     -- фиксированное представление версии с кириллицей и
             ВСТРОЕННЫМ шрифтом (allowlist TTF), invariant-метаданные
             (детерминизм), без внешних URL/изображений (AC16:
             «PDF renderer работает без исходящего сетевого доступа
             и с ограничением local file access»);
  xlsx    -- листы Summary/Metadata/Results/Methods/Warnings;
             недоверенный текст -- СТРОКИ (формулоподобные «=...» не
             становятся формулами: §7 «XLSX пишет недоверенный текст
             как строки, не формулы»), управляющие символы убираются,
             честное усечение по пределам Excel;
  parquet -- typed-таблица claims (refs -- list<string>, числовые
             cutoff -- int64 nullable); отсутствие движка -- честный
             RenderDependencyError, не тихая подмена;
  svg/png -- ChartSpec-проекция снимка (утверждения по секциям) в
             фиксированной светлой print-теме; SVG -- рукописный
             детерминированный XML БЕЗ script/xlink/внешних URL
             (§12.3/AC16); PNG -- PIL с тем же allowlist-шрифтом;
  zip     -- evidence-пакет §7: manifest.json (sha256 каждого члена
             КРОМЕ самого манифеста -- циклическое определение
             запрещено §13.3), report.json, human rendition, таблица,
             график, schema.json; фиксированные имена членов (path
             traversal невозможен по построению, AC16); данные в пакет
             НЕ включаются -- честные data_included=false и
             reproducibility=limited (§7 абзац о ZIP без данных).

ПОСТАНОВКА (§19, строка DOCLOG-4): «Раздел документов, stage entry
points, HTML/MD/JSON/JSONL/существующие таблицы, job states». Рендеры
строят формат ИЗ снимка (R06: «MD/HTML/PDF/DOCX/XLSX строятся из одного
снимка; формат обмена не становится источником истины»): они НЕ читают
живой run/сессию/артефакты, НЕ запускают fit/query, НЕ меняют научное
состояние (AC05).

ФОРМАТЫ P0 (§7):
  json  -- канонические байты снимка (та же сериализация DOCLOG-1/2:
           sort_keys, компактные разделители, allow_nan=False);
  jsonl -- построчный экспорт claims с envelope (§7: «один event на
           строку, schema_version, диапазон/порядок»);
  md    -- переносимый человекочитаемый текст с честными
           unknown/partial/gaps (R07);
  html  -- основной доступный preview (§12.3/AC16): экранирование
           ВСЕГО содержимого снимка (недоверенный вход), статический
           inline CSS, БЕЗ script/внешних ссылок/on*-атрибутов;
           нейтрализация javascript:/data:/vbscript: схем;
  csv   -- плоская таблица claims (§7: quoting, ISO-даты,
           spreadsheet-safe профиль: строки с префиксом =,+,-,@ и
           управляющие символы нейтрализуются ТОЛЬКО в текстовых
           значениях; числовые значения не превращаются в текст).

Согласованность фактов (AC03): все форматы -- проекции одного снимка;
байты форматов различны, факты совпадают.
"""
from __future__ import annotations

import csv
import html as _html
import io
import json
import os
import re
import zipfile
from dataclasses import dataclass, field
from typing import Any, Optional

from apps.api.artifact_store import canonical_json_bytes
from apps.api.report_snapshot import ReportSnapshot

# ── Каталог форматов P0 + P1 (§7; DOCLOG-4/DOCLOG-5) ──────────────────


@dataclass(frozen=True)
class RenditionFormatSpec:
    """Формат выдачи: media_type/расширение/человекочитаемая метка."""

    format: str
    media_type: str
    extension: str
    label: str


RENDITION_FORMATS: dict[str, RenditionFormatSpec] = {
    "json": RenditionFormatSpec(
        "json", "application/json", "json", "JSON (снимок)"
    ),
    "jsonl": RenditionFormatSpec(
        "jsonl", "application/x-ndjson", "jsonl", "JSONL (утверждения)"
    ),
    "md": RenditionFormatSpec(
        "md", "text/markdown", "md", "Markdown"
    ),
    "html": RenditionFormatSpec(
        "html", "text/html", "html", "HTML (предпросмотр)"
    ),
    "csv": RenditionFormatSpec(
        "csv", "text/csv", "csv", "CSV (таблица утверждений)"
    ),
    # ── DOCLOG-5: тяжёлые форматы §7 (очередь P1) -- асинхронный
    #    рендер-контур (§18), не синхронный POST.
    "pdf": RenditionFormatSpec(
        "pdf", "application/pdf", "pdf", "PDF (кириллица, встроенный шрифт)"
    ),
    "xlsx": RenditionFormatSpec(
        "xlsx",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "xlsx",
        "XLSX (Summary/Metadata/Results/Methods/Warnings)",
    ),
    "parquet": RenditionFormatSpec(
        "parquet", "application/vnd.apache.parquet", "parquet",
        "Parquet (typed-таблица утверждений)",
    ),
    "svg": RenditionFormatSpec(
        "svg", "image/svg+xml", "svg", "SVG (ChartSpec, светлая print-тема)"
    ),
    "png": RenditionFormatSpec(
        "png", "image/png", "png", "PNG (ChartSpec, растровый fallback)"
    ),
    "zip": RenditionFormatSpec(
        "zip", "application/zip", "zip", "ZIP (evidence-пакет)"
    ),
}

# Тяжёлые форматы (§7 P1): рендер выполняет worker (§18), POST только
# ставит job в очередь. P0 остаются синхронными (пин DOCLOG-4).
HEAVY_RENDITION_FORMATS = frozenset({"pdf", "xlsx", "parquet", "svg", "png", "zip"})

JSONL_SCHEMA_VERSION = "doclog.rendition/1"
CSV_SCHEMA_VERSION = "doclog.rendition.csv/1"

# §7 spreadsheet-safe: управляющие символы (без \t/\n/\r -- их берёт
# quoting) и опасные префиксы формул.
_CSV_FORMULA_PREFIXES = ("=", "+", "-", "@")
_CSV_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
# §12.3/AC16: схемы-исполнители в тексте нейтрализуются (двоеточие
# экранируется -- браузер не видит URI-схему, человек видит текст).
_HTML_SCHEME_RE = re.compile(r"(?i)\b(javascript|data|vbscript)\s*:")


def _iso_date(value: Optional[str]) -> str:
    """ISO-даты в машиночитаемом профиле (§7); None -- честная пустота."""
    return value or ""


# ── JSON (канон снимка) ──────────────────────────────────────────────


def render_snapshot_json(snapshot: ReportSnapshot) -> bytes:
    """Канонические байты снимка (та же сериализация, что сохранена
    в object store DOCLOG-2) -- формат JSON и есть снимок (§7 P0)."""
    return canonical_json_bytes(snapshot.to_dict())


# ── JSONL (envelope, одна claim -- одна строка) ──────────────────────


def render_snapshot_jsonl(snapshot: ReportSnapshot) -> str:
    """§7 JSONL/NDJSON: одна claim на строку с envelope: schema_version,
    snapshot_id, section_code/kind, text, refs, validity, evidence_level,
    порядок секций/claims снимка (диапазон/порядок = порядок frozen
    корпуса)."""
    lines: list[str] = []
    for section in snapshot.sections:
        for claim in section.get("claims", []):
            envelope = {
                "schema_version": JSONL_SCHEMA_VERSION,
                "snapshot_id": snapshot.snapshot_id,
                "research_run_id": snapshot.research_run_id,
                "section_code": section.get("code"),
                "section_kind": section.get("kind"),
                "text": claim.get("text", ""),
                "event_refs": list(claim.get("event_refs", [])),
                "result_refs": list(claim.get("result_refs", [])),
                "validity": claim.get("validity", "unknown"),
                "evidence_level": claim.get("evidence_level"),
                "captured_at": _iso_date(snapshot.captured_at),
            }
            lines.append(
                canonical_json_bytes(envelope).decode("utf-8")
            )
    return "\n".join(lines) + ("\n" if lines else "")


# ── Markdown ─────────────────────────────────────────────────────────


_VALIDITY_LABELS = {
    "current": "актуально",
    "stale": "устарело",
    "unknown": "неизвестно",
}


def render_snapshot_markdown(snapshot: ReportSnapshot) -> str:
    """§7 Markdown: переносимый человекочитаемый текст; предупреждения
    о неполноте честны (R07: отсутствие ref -- unknown, не current)."""
    completeness = snapshot.completeness or {}
    reproducibility = snapshot.reproducibility or {}
    lines: list[str] = [
        f"# Документ исследования (снимок {snapshot.snapshot_id})",
        "",
        f"- Снимок: {snapshot.snapshot_id}",
        f"- Запуск: {snapshot.research_run_id}",
        f"- Дата снимка: {_iso_date(snapshot.captured_at) or '—'}",
        f"- Контекст: {snapshot.context_id or '—'}",
        f"- Ревизия данных: {snapshot.data_revision if snapshot.data_revision is not None else '—'}",
        f"- Шаблон: {snapshot.template.get('id', '—')} v{snapshot.template.get('version', '—')}",
        f"- Классификация: {snapshot.classification}",
        f"- Профиль раскрытия: {snapshot.redaction_profile}",
        f"- Знание-версия: {snapshot.knowledge_version or '—'}",
    ]
    missing = list(completeness.get("missing_refs", []))
    if completeness.get("status") == "complete" and not missing:
        lines.append("- Полнота: complete")
    else:
        lines.append(
            f"- Полнота: partial (неполный снимок; отсутствуют refs: "
            f"{len(missing)})"
        )
        for ref in missing:
            lines.append(f"  - отсутствует: {ref}")
    reasons = list(reproducibility.get("reasons", []))
    if reproducibility.get("status") == "ready" and not reasons:
        lines.append("- Воспроизводимость: ready")
    else:
        lines.append(
            f"- Воспроизводимость: {reproducibility.get('status', 'limited')}"
            + (f" (причины: {', '.join(reasons)})" if reasons else "")
        )
    # Согласование (approval) -- DOCLOG-6; снимок честно фиксирует null.
    lines.append("- Согласование: — (не выпущено; D11 — контур DOCLOG-6)")
    lines.append("")
    for section in snapshot.sections:
        lines.append(f"## {section.get('title', '—')} ({section.get('code', '—')})")
        stage = section.get("methodology_stage")
        if stage:
            lines.append(f"*Методология: этап {stage} (ref реестра знаний)*")
        claims = section.get("claims", [])
        if not claims:
            lines.append("")
            lines.append("_Утверждений секция не зафиксировала._")
        for claim in claims:
            validity = _VALIDITY_LABELS.get(
                str(claim.get("validity", "unknown")),
                str(claim.get("validity", "unknown")),
            )
            lines.append("")
            lines.append(f"- {claim.get('text', '')} **[{validity}]**")
            evidence = claim.get("evidence_level")
            refs = [
                *list(claim.get("event_refs", [])),
                *list(claim.get("result_refs", [])),
            ]
            basis = ", ".join(filter(None, [evidence, *refs]))
            if basis:
                lines.append(f"  - Основание: {basis}")
    return "\n".join(lines).rstrip() + "\n"


# ── HTML (безопасный preview, §12.3/AC16) ────────────────────────────

_HTML_CSS = (
    "body{font-family:system-ui,-apple-system,'Segoe UI',sans-serif;"
    "max-width:56rem;margin:2rem auto;padding:0 1.5rem;color:#17202a;"
    "line-height:1.55}"
    "h1{font-size:1.4rem}h2{font-size:1.15rem;margin-top:1.8rem;"
    "border-bottom:1px solid #d6dbe1;padding-bottom:.3rem}"
    ".meta{color:#4a5560}.meta ul{list-style:none;padding-left:0}"
    ".meta li{margin:.15rem 0}"
    ".facts{padding-left:1.2rem}.facts li{margin:.4rem 0}"
    ".basis{color:#5a6572;font-size:.86rem;margin-top:.15rem}"
    ".basis code{font-family:ui-monospace,SFMono-Regular,monospace;"
    "font-size:.82em;background:#f5f7fa;border:1px solid #dfe5ec;"
    "border-radius:4px;padding:0 .25rem;margin-right:.3rem}"
    ".gaps{background:#fdf6ec;border:1px solid #e7d9b8;border-radius:8px;"
    "padding:.6rem .9rem;font-size:.9rem}"
    ".status{font-weight:600}"
)


def _escape_text(value: Any) -> str:
    """Экранирование недоверенного текста (§12.3: «HTML/SVG из внешних
    источников не исполняются»): html.escape + нейтрализация
    javascript:/data:/vbscript: схем (двоеточие -> &amp;#58;)."""
    escaped = _html.escape(str(value), quote=True)
    return _HTML_SCHEME_RE.sub(r"\1&#58;", escaped)


def _html_meta_list(snapshot: ReportSnapshot) -> str:
    completeness = snapshot.completeness or {}
    reproducibility = snapshot.reproducibility or {}
    missing = list(completeness.get("missing_refs", []))
    reasons = list(reproducibility.get("reasons", []))
    completeness_label = (
        "complete"
        if completeness.get("status") == "complete" and not missing
        else "partial (неполный снимок)"
    )
    rows = [
        ("Снимок", snapshot.snapshot_id),
        ("Запуск", snapshot.research_run_id),
        ("Дата снимка", _iso_date(snapshot.captured_at) or "—"),
        ("Контекст", snapshot.context_id or "—"),
        (
            "Ревизия данных",
            snapshot.data_revision
            if snapshot.data_revision is not None
            else "—",
        ),
        ("Классификация", snapshot.classification),
        ("Профиль раскрытия", snapshot.redaction_profile),
        ("Знание-версия", snapshot.knowledge_version or "—"),
        ("Полнота", completeness_label),
        (
            "Воспроизводимость",
            f"{reproducibility.get('status', 'limited')}"
            + (f" ({', '.join(reasons)})" if reasons else ""),
        ),
        ("Согласование", "— (не выпущено; D11 — контур DOCLOG-6)"),
    ]
    items = "".join(
        f"<li><strong>{_escape_text(label)}:</strong> {_escape_text(value)}</li>"
        for label, value in rows
    )
    return f'<ul class="meta">{items}</ul>'


def render_snapshot_html(snapshot: ReportSnapshot) -> str:
    """§7 HTML: основной доступный preview. Безопасность по построению
    (§12.3/AC16): весь контент снимка экранирован; CSS статический
    inline; НЕТ script/link/img/iframe/on*-атрибутов/внешних URL;
    refs -- текстовые <code>, не ссылки."""
    missing = list((snapshot.completeness or {}).get("missing_refs", []))
    parts: list[str] = [
        "<!doctype html>",
        '<html lang="ru">',
        "<head>",
        '<meta charset="utf-8">',
        "<title>Документ исследования</title>",
        f"<style>{_HTML_CSS}</style>",
        "</head>",
        "<body>",
        "<h1>Документ исследования</h1>",
        _html_meta_list(snapshot),
    ]
    if missing:
        gaps = "".join(
            f"<li><code>{_escape_text(ref)}</code></li>" for ref in missing
        )
        parts.append(
            '<div class="gaps"><strong>Отсутствующие зависимости '
            "(gaps):</strong><ul>" + gaps + "</ul></div>"
        )
    parts.append('<main role="main" id="sections">')
    for section in snapshot.sections:
        parts.append(
            f'<section id="{_escape_text(section.get("code", ""))}">'
        )
        parts.append(
            f'<h2>{_escape_text(section.get("title", "—"))} '
            f'<small>(<code>{_escape_text(section.get("code", "—"))})</code>)</small></h2>'
        )
        stage = section.get("methodology_stage")
        if stage:
            parts.append(
                f'<p class="basis">Методология: этап <code>'
                f"{_escape_text(stage)}</code> (ref реестра знаний)</p>"
            )
        claims = section.get("claims", [])
        if not claims:
            parts.append("<p><em>Утверждений секция не зафиксировала.</em></p>")
        else:
            parts.append('<ul class="facts">')
            for claim in claims:
                validity = _VALIDITY_LABELS.get(
                    str(claim.get("validity", "unknown")),
                    str(claim.get("validity", "unknown")),
                )
                parts.append(
                    "<li>"
                    f"{_escape_text(claim.get('text', ''))} "
                    f'<span class="status">[{_escape_text(validity)}]</span>'
                )
                basis_bits = [
                    *list(claim.get("event_refs", [])),
                    *list(claim.get("result_refs", [])),
                ]
                if claim.get("evidence_level") or basis_bits:
                    codes = "".join(
                        f"<code>{_escape_text(bit)}</code>"
                        for bit in (
                            [claim.get("evidence_level"), *basis_bits]
                            if claim.get("evidence_level")
                            else basis_bits
                        )
                        if bit
                    )
                    parts.append(
                        f'<div class="basis">Основание: {codes}</div>'
                    )
                parts.append("</li>")
            parts.append("</ul>")
        parts.append("</section>")
    parts.append("</main>")
    parts.append("</body></html>")
    return "\n".join(parts)


# ── CSV (таблица claims, spreadsheet-safe §7) ────────────────────────


def _csv_text(value: Any) -> str:
    """Spreadsheet-safe текстовая ячейка (§7): строки с префиксом
    =,+,-,@ и управляющие символы нейтрализуются апострофом; обычный
    текст не трогается. ЧИСЛА сюда не попадают (отдельная ветка)."""
    text = str(value if value is not None else "")
    text = _CSV_CONTROL_RE.sub("", text)
    if text.startswith(_CSV_FORMULA_PREFIXES):
        return "'" + text
    return text


def render_snapshot_csv(snapshot: ReportSnapshot) -> str:
    """§7 CSV UTF-8: плоская таблица claims снимка. quoting по RFC,
    ISO-даты, числовые значения (event_count/last_sequence) -- в
    каноническом машинном профиле БЕЗ нейтрализации."""
    cutoff = snapshot.source_cutoff or {}
    event_count = cutoff.get("event_count")
    last_sequence = cutoff.get("last_sequence")
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\r\n")
    writer.writerow([
        "schema_version",
        "snapshot_id",
        "research_run_id",
        "captured_at",
        "section_code",
        "section_title",
        "claim",
        "validity",
        "evidence_level",
        "event_refs",
        "result_refs",
        "event_count",
        "last_sequence",
    ])
    for section in snapshot.sections:
        for claim in section.get("claims", []):
            writer.writerow([
                CSV_SCHEMA_VERSION,
                snapshot.snapshot_id,
                snapshot.research_run_id,
                _iso_date(snapshot.captured_at),
                _csv_text(section.get("code")),
                _csv_text(section.get("title")),
                _csv_text(claim.get("text", "")),
                _csv_text(claim.get("validity", "unknown")),
                _csv_text(claim.get("evidence_level")),
                _csv_text(", ".join(claim.get("event_refs", []))),
                _csv_text(", ".join(claim.get("result_refs", []))),
                event_count if isinstance(event_count, int) else "",
                last_sequence if isinstance(last_sequence, int) else "",
            ])
    return buffer.getvalue()


# ═════════════════════════════════════════════════════════════════════
# Тяжёлые форматы DOCLOG-5 (§7 P1; AC16 -- безопасный вывод)
# ═════════════════════════════════════════════════════════════════════


class RenderDependencyError(RuntimeError):
    """Отсутствие обязательной зависимости рендера (шрифт/движок
    parquet) -- честный отказ (job failed render_dependency_unavailable/
    font_unavailable), НЕ тихая подмена форматом и НЕ битый файл."""


# Allowlist шрифтов (AC16: «renderer не получает сеть/произвольную
# ФС» -- единственное чтение ФС, разрешённое рендерам, -- TTF из этого
# фиксированного списка; кириллица требует встроенного шрифта §7 PDF).
_PDF_FONT_CANDIDATES: tuple[tuple[str, str, str], ...] = (
    (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "DejaVuSans",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ),
    (
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "LiberationSans",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    ),
)


def _resolve_font() -> tuple[str, str]:
    """Возвращает (путь regular TTF, имя шрифта) из allowlist; честный
    отказ, если ни одного файла нет."""
    for path, name, _bold in _PDF_FONT_CANDIDATES:
        if os.path.isfile(path):
            return path, name
    raise RenderDependencyError(
        "font_unavailable: ни один allowlist-шрифт не найден "
        f"(кандидаты: {[path for path, _n, _b in _PDF_FONT_CANDIDATES]})"
    )


def _iter_claims(snapshot: ReportSnapshot):
    """Плоский обход (section, claim) в порядке frozen корпуса."""
    for section in snapshot.sections:
        for claim in section.get("claims", []):
            yield section, claim


# ── PDF (ReportLab, кириллица/встроенный шрифт, §7 P1) ───────────────


def render_snapshot_pdf(snapshot: ReportSnapshot) -> bytes:
    """§7 PDF: фиксированное представление выбранной версии с
    кириллицей/встроенными шрифтами, номером версии/статусом; НЕ
    «электронная подпись». Безопасность (§12.3/AC16): нет внешних
    URL/изображений/скриптов; чтение ФС ограничено allowlist-шрифтами;
    весь недоверенный текст экранируется перед Paragraph (mini-XML)."""
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.platypus import (
        BaseDocTemplate,
        Frame,
        PageTemplate,
        Paragraph,
        Spacer,
    )

    font_path, font_name = _resolve_font()
    bold_path = next(
        (
            bold
            for path, name, bold in _PDF_FONT_CANDIDATES
            if name == font_name and os.path.isfile(bold)
        ),
        None,
    )
    pdfmetrics.registerFont(TTFont(font_name, font_path))
    if bold_path:
        from reportlab.pdfbase.pdfmetrics import registerFontFamily

        pdfmetrics.registerFont(TTFont(f"{font_name}-Bold", bold_path))
        registerFontFamily(
            font_name, normal=font_name, bold=f"{font_name}-Bold",
            italic=font_name, boldItalic=f"{font_name}-Bold",
        )

    base = ParagraphStyle(
        "base", fontName=font_name, fontSize=9.5, leading=13.5,
        textColor="#17202a",
    )
    h1 = ParagraphStyle("h1", parent=base, fontSize=17, leading=22)
    h2 = ParagraphStyle("h2", parent=base, fontSize=12.5, leading=17,
                        spaceBefore=10)
    meta = ParagraphStyle("meta", parent=base, fontSize=8.8, leading=12.4)
    claim = ParagraphStyle("claim", parent=base, leftIndent=10)
    basis = ParagraphStyle(
        "basis", parent=base, fontSize=8.2, leading=11,
        textColor="#4a5560", leftIndent=20,
    )

    buffer = io.BytesIO()
    # invariant=1 -- детерминированные метаданные (AC03-дух: одинаковый
    # снимок -> одинаковые байты PDF в этой среде).
    document = BaseDocTemplate(
        buffer, pagesize=A4, title="Документ исследования",
        author="CISStat TS Analysis", subject=snapshot.snapshot_id,
        invariant=1,
    )
    frame = Frame(
        18 * mm, 18 * mm, A4[0] - 36 * mm, A4[1] - 36 * mm, id="main"
    )

    def _draw_page(canvas, _doc) -> None:
        canvas.saveState()
        canvas.setFont(font_name, 7.5)
        canvas.setFillColor("#4a5560")
        # Номер версии/статус на каждой странице (§7 PDF).
        canvas.drawString(
            18 * mm, 12 * mm,
            f"снимок {snapshot.snapshot_id} · версия frozen · "
            f"классификация {snapshot.classification}",
        )
        canvas.drawRightString(
            A4[0] - 18 * mm, 12 * mm, f"стр. {canvas.getPageNumber()}"
        )
        canvas.restoreState()

    document.addPageTemplates(
        [PageTemplate(id="page", frames=[frame], onPage=_draw_page)]
    )

    def esc(value: Any) -> str:
        return _html.escape(str(value if value is not None else ""), quote=True)

    completeness = snapshot.completeness or {}
    reproducibility = snapshot.reproducibility or {}
    missing = list(completeness.get("missing_refs", []))
    reasons = list(reproducibility.get("reasons", []))
    completeness_label = (
        "complete"
        if completeness.get("status") == "complete" and not missing
        else "partial (неполный снимок)"
    )
    story: list[Any] = [
        Paragraph("Документ исследования", h1),
        Spacer(1, 4),
        Paragraph(
            f"Снимок: {esc(snapshot.snapshot_id)}<br/>"
            f"Запуск: {esc(snapshot.research_run_id)}<br/>"
            f"Дата снимка: {esc(_iso_date(snapshot.captured_at) or '—')}<br/>"
            f"Контекст: {esc(snapshot.context_id or '—')}<br/>"
            f"Ревизия данных: {esc(snapshot.data_revision if snapshot.data_revision is not None else '—')}<br/>"
            f"Шаблон: {esc(snapshot.template.get('id', '—'))} "
            f"v{esc(snapshot.template.get('version', '—'))}<br/>"
            f"Классификация: {esc(snapshot.classification)}<br/>"
            f"Профиль раскрытия: {esc(snapshot.redaction_profile)}<br/>"
            f"Знание-версия: {esc(snapshot.knowledge_version or '—')}<br/>"
            f"Полнота: {esc(completeness_label)}<br/>"
            f"Воспроизводимость: {esc(reproducibility.get('status', 'limited'))}"
            + (esc(f" ({', '.join(reasons)})") if reasons else "")
            + "<br/>"
            "Согласование: — (не выпущено; D11 — контур DOCLOG-6)",
            meta,
        ),
    ]
    if missing:
        story.append(Spacer(1, 6))
        story.append(Paragraph(
            "Отсутствующие зависимости (gaps): "
            + "; ".join(esc(ref) for ref in missing),
            meta,
        ))
    for section in snapshot.sections:
        story.append(Paragraph(
            f"{esc(section.get('title', '—'))} "
            f"(<font size='8.5'>{esc(section.get('code', '—'))})</font>",
            h2,
        ))
        stage = section.get("methodology_stage")
        if stage:
            story.append(Paragraph(
                f"Методология: этап {esc(stage)} (ref реестра знаний)",
                basis,
            ))
        claims = section.get("claims", [])
        if not claims:
            story.append(Paragraph(
                "<i>Утверждений секция не зафиксировала.</i>", claim
            ))
        for item in claims:
            validity = _VALIDITY_LABELS.get(
                str(item.get("validity", "unknown")),
                str(item.get("validity", "unknown")),
            )
            story.append(Paragraph(
                f"• {esc(item.get('text', ''))}  [{esc(validity)}]", claim
            ))
            refs = [
                *list(item.get("event_refs", [])),
                *list(item.get("result_refs", [])),
            ]
            basis_bits = [
                *([item.get("evidence_level")] if item.get("evidence_level") else []),
                *refs,
            ]
            if basis_bits:
                story.append(Paragraph(
                    "Основание: " + ", ".join(esc(bit) for bit in basis_bits),
                    basis,
                ))
    document.build(story)
    return buffer.getvalue()


# ── XLSX (openpyxl, §7 P1: недоверенный текст -- строки) ─────────────


MAX_XLSX_CELL_CHARS = 32767  # предел Excel для ячейки
_XLSX_ILLEGAL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_XLSX_TRUNCATION_MARKER = "…[усечено до предела Excel 32767 символов]"


def _xlsx_cell_text(value: Any) -> str:
    """Недоверенный текст -> строка ячейки: управляющие символы
    убираются (IllegalCharacterError openpyxl); усечение по пределу
    Excel -- честное, с маркером (§7: «лимиты Excel проверяются»)."""
    text = _XLSX_ILLEGAL_RE.sub("", str(value if value is not None else ""))
    if len(text) > MAX_XLSX_CELL_CHARS:
        text = (
            text[: MAX_XLSX_CELL_CHARS - len(_XLSX_TRUNCATION_MARKER)]
            + _XLSX_TRUNCATION_MARKER
        )
    return text


def _xlsx_set_string(sheet: Any, row: int, column: int, value: Any) -> None:
    """Запись недоверенного текста СТРОКОЙ: openpyxl выводит строки,
    начинающиеся с '=', как формулы (data_type 'f') -- после присвоения
    тип принудительно возвращается в строку ('s'): §7 «XLSX пишет
    недоверенный текст как строки, не формулы» (AC16)."""
    cell = sheet.cell(row=row, column=column, value=_xlsx_cell_text(value))
    if cell.data_type == "f":
        cell.data_type = "s"
    return cell


def render_snapshot_xlsx(snapshot: ReportSnapshot) -> bytes:
    """§7 XLSX: листы Summary/Metadata/Results/Methods/Warnings, units
    и типы; строки формул экранированы (строками), лимиты Excel
    проверяются, без макросов. Кириллица/переводы строк -- native
    (UTF-8 xlsx)."""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font

    workbook = Workbook()
    workbook.remove(workbook.active)

    header_font = Font(bold=True)
    wrap = Alignment(wrap_text=True, vertical="top")

    def _sheet(name: str) -> Any:
        return workbook.create_sheet(title=name)

    def _row(sheet: Any, row: int, values: list[Any]) -> None:
        for column, value in enumerate(values, start=1):
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                sheet.cell(row=row, column=column, value=value)
            else:
                _xlsx_set_string(sheet, row, column, value)
            sheet.cell(row=row, column=column).alignment = wrap

    # Summary
    summary = _sheet("Summary")
    total_claims = sum(
        len(section.get("claims", [])) for section in snapshot.sections
    )
    _row(summary, 1, ["Документ исследования"])
    summary["A1"].font = header_font
    _row(summary, 2, ["Снимок", snapshot.snapshot_id])
    _row(summary, 3, ["Запуск", snapshot.research_run_id])
    _row(summary, 4, ["Дата снимка", _iso_date(snapshot.captured_at)])
    _row(summary, 5, ["Классификация", snapshot.classification])
    _row(summary, 6, ["Профиль раскрытия", snapshot.redaction_profile])
    _row(summary, 7, ["Секций", len(snapshot.sections)])
    _row(summary, 8, ["Утверждений", total_claims])
    _row(summary, 9, ["Схема", "doclog.rendition.xlsx/1"])

    # Metadata
    metadata = _sheet("Metadata")
    completeness = snapshot.completeness or {}
    reproducibility = snapshot.reproducibility or {}
    rows: list[tuple[str, Any]] = [
        ("schema_version", "doclog.rendition.xlsx/1"),
        ("snapshot_id", snapshot.snapshot_id),
        ("research_run_id", snapshot.research_run_id),
        ("context_id", snapshot.context_id or "—"),
        ("data_revision", snapshot.data_revision),
        ("captured_at", _iso_date(snapshot.captured_at)),
        ("template", f"{snapshot.template.get('id', '—')} "
                     f"v{snapshot.template.get('version', '—')}"),
        ("knowledge_version", snapshot.knowledge_version or "—"),
        ("locale", snapshot.locale),
        ("display_timezone", snapshot.display_timezone),
        ("classification", snapshot.classification),
        ("redaction_profile", snapshot.redaction_profile),
        ("completeness", completeness.get("status", "partial")),
        ("reproducibility", reproducibility.get("status", "limited")),
        ("approval", "— (не выпущено; D11 — контур DOCLOG-6)"),
        ("source_cutoff.event_count", (snapshot.source_cutoff or {}).get("event_count")),
        ("source_cutoff.last_sequence", (snapshot.source_cutoff or {}).get("last_sequence")),
    ]
    _row(metadata, 1, ["Поле", "Значение"])
    for index, (key, value) in enumerate(rows, start=2):
        _row(metadata, index, [key, value])
    for row_index in range(2, len(rows) + 1):
        metadata.cell(row=row_index, column=1).font = header_font

    # Results: таблица claims (числа остаются числами; текст -- строки).
    results = _sheet("Results")
    _row(results, 1, [
        "section_code", "section_title", "claim", "validity",
        "evidence_level", "event_refs", "result_refs",
    ])
    row_index = 2
    for section, claim in _iter_claims(snapshot):
        _row(results, row_index, [
            section.get("code"),
            section.get("title"),
            claim.get("text", ""),
            claim.get("validity", "unknown"),
            claim.get("evidence_level"),
            ", ".join(claim.get("event_refs", [])),
            ", ".join(claim.get("result_refs", [])),
        ])
        row_index += 1

    # Methods: методология/шаблоны по секциям.
    methods = _sheet("Methods")
    _row(methods, 1, ["section_code", "methodology_stage", "section_kind"])
    row_index = 2
    for section in snapshot.sections:
        _row(methods, row_index, [
            section.get("code"),
            section.get("methodology_stage") or "—",
            section.get("kind"),
        ])
        row_index += 1
    if row_index == 2:
        _row(methods, 2, ["—", "—", "—"])

    # Warnings: честные неполнота/ограничения/усечения.
    warnings = _sheet("Warnings")
    _row(warnings, 1, ["Тип", "Детали"])
    warning_rows: list[tuple[str, str]] = []
    missing = list(completeness.get("missing_refs", []))
    if missing:
        warning_rows.append((
            "missing_refs",
            "Отсутствующие refs: " + ", ".join(missing),
        ))
    if completeness.get("status") != "complete":
        warning_rows.append((
            "completeness",
            f"Статус полноты: {completeness.get('status', 'partial')}",
        ))
    reasons = list(reproducibility.get("reasons", []))
    if reasons or reproducibility.get("status") != "ready":
        warning_rows.append((
            "reproducibility",
            f"Статус воспроизводимости: "
            f"{reproducibility.get('status', 'limited')}"
            + (f"; причины: {', '.join(reasons)}" if reasons else ""),
        ))
    warning_rows.append((
        "approval",
        "Согласование не выпущено (D11 — контур DOCLOG-6)",
    ))
    warning_rows.append((
        "data_not_included",
        "Исходные данные в файл не включены (документный слой §7)",
    ))
    truncations = sum(
        1
        for _section, claim in _iter_claims(snapshot)
        if len(_XLSX_ILLEGAL_RE.sub("", str(claim.get("text", ""))))
        > MAX_XLSX_CELL_CHARS
    )
    if truncations:
        warning_rows.append((
            "truncation",
            f"Ячеек усечено до предела Excel: {truncations}",
        ))
    for index, (kind, details) in enumerate(warning_rows, start=2):
        _row(warnings, index, [kind, details])

    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


# ── Parquet (pyarrow, §7 P1: typed-таблица) ──────────────────────────


PARQUET_SCHEMA_VERSION = "doclog.rendition.parquet/1"


def render_snapshot_parquet(snapshot: ReportSnapshot) -> bytes:
    """§7 Parquet + schema: typed-таблица claims снимка; refs --
    list<string>, числовые cutoff -- int64 nullable. Отсутствие
    движка -- честный RenderDependencyError (не тихая подмена).
    Изображение схемы отдельно: claims_table_schema()/evidence ZIP."""
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ImportError as exc:  # честная граница зависимости
        raise RenderDependencyError(
            "dependency_unavailable: pyarrow недоступен для parquet-рендера"
        ) from exc

    rows: list[dict[str, Any]] = []
    cutoff = snapshot.source_cutoff or {}
    event_count = cutoff.get("event_count")
    last_sequence = cutoff.get("last_sequence")
    for section, claim in _iter_claims(snapshot):
        rows.append({
            "schema_version": PARQUET_SCHEMA_VERSION,
            "snapshot_id": snapshot.snapshot_id,
            "research_run_id": snapshot.research_run_id,
            "captured_at": _iso_date(snapshot.captured_at),
            "section_code": section.get("code") or "",
            "section_kind": section.get("kind") or "",
            "claim": claim.get("text", ""),
            "validity": claim.get("validity", "unknown"),
            "evidence_level": claim.get("evidence_level"),
            "event_refs": list(claim.get("event_refs", [])),
            "result_refs": list(claim.get("result_refs", [])),
            "event_count": (
                int(event_count) if isinstance(event_count, int) else None
            ),
            "last_sequence": (
                int(last_sequence)
                if isinstance(last_sequence, int)
                else None
            ),
        })
    table = pa.Table.from_pylist(rows, schema=pa.schema([
        pa.field("schema_version", pa.string()),
        pa.field("snapshot_id", pa.string()),
        pa.field("research_run_id", pa.string()),
        pa.field("captured_at", pa.string()),
        pa.field("section_code", pa.string()),
        pa.field("section_kind", pa.string()),
        pa.field("claim", pa.string()),
        pa.field("validity", pa.string()),
        pa.field("evidence_level", pa.string()),
        pa.field("event_refs", pa.list_(pa.string())),
        pa.field("result_refs", pa.list_(pa.string())),
        pa.field("event_count", pa.int64()),
        pa.field("last_sequence", pa.int64()),
    ]))
    sink = io.BytesIO()
    pq.write_table(table, sink, compression="snappy")
    return sink.getvalue()


def claims_table_schema(snapshot: ReportSnapshot) -> dict[str, Any]:
    """schema.json для таблицы claims (§7: CSV/Parquet с описанием
    типов/локали/усечения; units честны)."""
    return {
        "schema_version": "doclog.claims_table/1",
        "snapshot_id": snapshot.snapshot_id,
        "research_run_id": snapshot.research_run_id,
        "locale": snapshot.locale,
        "display_timezone": snapshot.display_timezone,
        "captured_at": _iso_date(snapshot.captured_at),
        "row_semantics": "одна строка -- одно утверждение секции",
        "columns": [
            {"name": "schema_version", "type": "string", "unit": None},
            {"name": "snapshot_id", "type": "string", "unit": None},
            {"name": "research_run_id", "type": "string", "unit": None},
            {"name": "captured_at", "type": "string(ISO-8601)", "unit": None},
            {"name": "section_code", "type": "string", "unit": None},
            {"name": "section_kind", "type": "string", "unit": None},
            {"name": "claim", "type": "string", "unit": "текст"},
            {"name": "validity", "type": "string", "unit": None},
            {"name": "evidence_level", "type": "string|null", "unit": None},
            {"name": "event_refs", "type": "list<string>", "unit": None},
            {"name": "result_refs", "type": "list<string>", "unit": None},
            {"name": "event_count", "type": "int64|null", "unit": "событий"},
            {"name": "last_sequence", "type": "int64|null", "unit": "позиция"},
        ],
        "spreadsheet_safe": "формулоподобные строки -- строками (XLSX), "
                            "числовые значения не текст",
    }


# ── ChartSpec SVG/PNG (§7 P1; фиксированная светлая print-тема) ──────


CHARTSPEC_SCHEMA_VERSION = "doclog.chartspec/1"


@dataclass(frozen=True)
class ChartSpec:
    """Детерминированная проекция снимка для графика (§224-дух:
    ChartSpec + data table ref + renderer refs; картинка НЕ числовой
    первоисточник -- B08)."""

    schema_version: str
    title: str
    unit: str
    chart_id: str
    source_ref: str
    snapshot_id: str
    series: tuple[tuple[str, int], ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "title": self.title,
            "unit": self.unit,
            "chart_id": self.chart_id,
            "source_ref": self.source_ref,
            "snapshot_id": self.snapshot_id,
            "series": [list(item) for item in self.series],
        }


def build_chart_spec(snapshot: ReportSnapshot) -> ChartSpec:
    """Чистая проекция: число утверждений по секциям frozen корпуса
    (детерминировано снимком; ref источника = chartspec:snapshot)."""
    series = tuple(
        (str(section.get("code") or ""), len(section.get("claims", [])))
        for section in snapshot.sections
    )
    return ChartSpec(
        schema_version=CHARTSPEC_SCHEMA_VERSION,
        title="Утверждения по секциям документа",
        unit="утв.",
        chart_id="chart-claims-by-section",
        source_ref=f"chartspec:report_snapshot/{snapshot.snapshot_id}",
        snapshot_id=snapshot.snapshot_id,
        series=series,
    )


# Светлая print-тема (§7 SVG/PNG: «фиксированная светлая print-тема»).
_CHART_BG = "#ffffff"
_CHART_TEXT = "#17202a"
_CHART_MUTED = "#5a6572"
_CHART_BAR = "#3b6ea5"
_CHART_GRID = "#dfe5ec"
_CHART_WIDTH = 720
_CHART_ROW_HEIGHT = 46
_CHART_TOP = 74
_CHART_BOTTOM = 44


def _chart_geometry(spec: ChartSpec) -> tuple[int, int, int, int, int]:
    """(height, chart_left, bar_area_width, max_value, row_count)."""
    max_value = max((value for _label, value in spec.series), default=0) or 1
    rows = max(len(spec.series), 1)
    height = _CHART_TOP + rows * _CHART_ROW_HEIGHT + _CHART_BOTTOM
    left = 190
    bar_width = _CHART_WIDTH - left - 150
    return height, left, bar_width, max_value, rows


def render_snapshot_svg(snapshot: ReportSnapshot) -> str:
    """§7 SVG: детерминированный рукописный XML (без библиотечных
    метаданных), фиксированная светлая print-тема, БЕЗ script/xlink/
    внешних URL/<image>; подписи и ChartSpec ref на графике; весь
    недоверенный текст XML-экранирован (§12.3/AC16)."""
    from xml.sax.saxutils import escape, quoteattr

    spec = build_chart_spec(snapshot)
    height, left, bar_width, max_value, rows = _chart_geometry(spec)
    parts: list[str] = [
        "<?xml version=\"1.0\" encoding=\"UTF-8\"?>",
        f"<!-- {escape(spec.schema_version)} -->",
        f"<svg xmlns=\"http://www.w3.org/2000/svg\" "
        f"width=\"{_CHART_WIDTH}\" height=\"{height}\" "
        f"viewBox=\"0 0 {_CHART_WIDTH} {height}\" "
        f"role=\"img\" aria-label={quoteattr(spec.title)}>",
        f"<rect x=\"0\" y=\"0\" width=\"{_CHART_WIDTH}\" "
        f"height=\"{height}\" fill=\"{_CHART_BG}\"/>",
        f"<text x=\"24\" y=\"34\" font-family=\"sans-serif\" "
        f"font-size=\"17\" fill=\"{_CHART_TEXT}\">{escape(spec.title)}</text>",
        f"<text x=\"24\" y=\"54\" font-family=\"monospace\" "
        f"font-size=\"10\" fill=\"{_CHART_MUTED}\">"
        f"{escape(spec.schema_version)} · {escape(spec.source_ref)} · "
        f"unit: {escape(spec.unit)}</text>",
    ]
    # Сетка/шкала: детерминированные деления.
    for tick in range(5):
        ratio = tick / 4
        x = left + int(bar_width * ratio)
        value = round(max_value * ratio)
        parts.append(
            f"<line x1=\"{x}\" y1=\"{_CHART_TOP - 8}\" x2=\"{x}\" "
            f"y2=\"{_CHART_TOP + rows * _CHART_ROW_HEIGHT}\" "
            f"stroke=\"{_CHART_GRID}\" stroke-width=\"1\"/>"
        )
        parts.append(
            f"<text x=\"{x}\" y=\"{_CHART_TOP - 14}\" "
            f"font-family=\"sans-serif\" font-size=\"9\" "
            f"fill=\"{_CHART_MUTED}\" text-anchor=\"middle\">{value}</text>"
        )
    for index, (label, value) in enumerate(spec.series):
        y = _CHART_TOP + index * _CHART_ROW_HEIGHT
        bar_length = int(bar_width * (value / max_value)) if max_value else 0
        parts.append(
            f"<text x=\"{left - 8}\" y=\"{y + 22}\" "
            f"font-family=\"sans-serif\" font-size=\"11\" "
            f"fill=\"{_CHART_TEXT}\" text-anchor=\"end\">"
            f"{escape(label)}</text>"
        )
        parts.append(
            f"<rect x=\"{left}\" y=\"{y + 8}\" width=\"{bar_length}\" "
            f"height=\"20\" fill=\"{_CHART_BAR}\"/>"
        )
        parts.append(
            f"<text x=\"{left + bar_length + 6}\" y=\"{y + 23}\" "
            f"font-family=\"sans-serif\" font-size=\"11\" "
            f"fill=\"{_CHART_TEXT}\">{value} {escape(spec.unit)}</text>"
        )
    if not spec.series:
        parts.append(
            f"<text x=\"24\" y=\"{_CHART_TOP + 20}\" "
            f"font-family=\"sans-serif\" font-size=\"12\" "
            f"fill=\"{_CHART_MUTED}\">Секций в снимке нет — данные "
            f"честно пусты.</text>"
        )
    parts.append("</svg>")
    return "\n".join(parts)


def render_snapshot_png(snapshot: ReportSnapshot) -> bytes:
    """§7 PNG: растровый fallback того же ChartSpec (PIL, фиксированная
    светлая print-тема, allowlist-шрифт; детерминированные байты --
    PIL не пишет timestamp по умолчанию)."""
    from PIL import Image, ImageDraw, ImageFont

    font_path, _name = _resolve_font()
    spec = build_chart_spec(snapshot)
    height, left, bar_width, max_value, rows = _chart_geometry(spec)
    scale = 2  # чёткая графика для публикаций (§7)
    image = Image.new("RGB", (_CHART_WIDTH * scale, height * scale), "#ffffff")
    draw = ImageDraw.Draw(image)
    font_regular = ImageFont.truetype(font_path, 11 * scale)
    font_small = ImageFont.truetype(font_path, 9 * scale)
    font_title = ImageFont.truetype(font_path, 17 * scale)

    def _text(x: int, y: int, text: str, font, fill: str) -> None:
        draw.text((x * scale, y * scale), text, font=font, fill=fill)

    def _text_right(x: int, y: int, text: str, font, fill: str) -> None:
        box = draw.textbbox((0, 0), text, font=font)
        width = box[2] - box[0]
        draw.text((x * scale - width, y * scale), text, font=font, fill=fill)

    _text(24, 22, spec.title, font_title, _CHART_TEXT)
    _text(
        24, 46,
        f"{spec.schema_version} · {spec.source_ref} · unit: {spec.unit}",
        font_small, _CHART_MUTED,
    )
    for tick in range(5):
        ratio = tick / 4
        x = left + int(bar_width * ratio)
        value = round(max_value * ratio)
        draw.line(
            [(x * scale, (_CHART_TOP - 8) * scale),
             (x * scale, (_CHART_TOP + rows * _CHART_ROW_HEIGHT) * scale)],
            fill=_CHART_GRID, width=1,
        )
        box = draw.textbbox((0, 0), str(value), font=font_small)
        _text(
            x - (box[2] - box[0]) // 2 // scale, _CHART_TOP - 24,
            str(value), font_small, _CHART_MUTED,
        )
    for index, (label, value) in enumerate(spec.series):
        y = _CHART_TOP + index * _CHART_ROW_HEIGHT
        bar_length = int(bar_width * (value / max_value)) if max_value else 0
        _text_right(left - 8, y + 14, label, font_regular, _CHART_TEXT)
        draw.rectangle(
            [left * scale, (y + 8) * scale,
             (left + bar_length) * scale, (y + 28) * scale],
            fill=_CHART_BAR,
        )
        _text(
            left + bar_length + 6, y + 14,
            f"{value} {spec.unit}", font_regular, _CHART_TEXT,
        )
    if not spec.series:
        _text(
            24, _CHART_TOP + 10,
            "Секций в снимке нет — данные честно пусты.",
            font_regular, _CHART_MUTED,
        )
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=False)
    return buffer.getvalue()


# ── Evidence ZIP (§7 P1; манифест без собственного hash §13.3) ───────

EVIDENCE_ZIP_SCHEMA_VERSION = "doclog.evidence/1"
EVIDENCE_ZIP_MEMBERS: tuple[str, ...] = (
    "manifest.json",
    "report.json",
    "document.md",
    "table_claims.csv",
    "chart_claims.svg",
    "table_schema.json",
)
# Детерминированный ZIP: фиксированная дата членов ZipInfo.
_ZIP_FIXED_DATE_TIME = (1980, 1, 1, 0, 0, 0)


def render_evidence_zip(snapshot: ReportSnapshot) -> bytes:
    """§7 ZIP: manifest.json, report.json, human rendition, tables,
    charts, refs и checksums; данные ТОЛЬКО с явным разрешением -- в
    MVP пакет данные НЕ включаются: data_included=false и
    reproducibility=limited честно (§7 абзац). Path traversal
    невозможен по построению: имена членов фиксированы (AC16).
    Манифест НЕ содержит собственного hash (циклическое определение
    запрещено §13.3)."""
    members: dict[str, bytes] = {
        "report.json": render_snapshot_json(snapshot),
        "document.md": render_snapshot_markdown(snapshot).encode("utf-8"),
        "table_claims.csv": render_snapshot_csv(snapshot).encode("utf-8"),
        "chart_claims.svg": render_snapshot_svg(snapshot).encode("utf-8"),
        "table_schema.json": canonical_json_bytes(
            claims_table_schema(snapshot)
        ),
    }
    import hashlib

    reproducibility = snapshot.reproducibility or {}
    manifest = {
        "schema_version": EVIDENCE_ZIP_SCHEMA_VERSION,
        "snapshot_id": snapshot.snapshot_id,
        "research_run_id": snapshot.research_run_id,
        "captured_at": _iso_date(snapshot.captured_at),
        "classification": snapshot.classification,
        "redaction_profile": snapshot.redaction_profile,
        "knowledge_version": snapshot.knowledge_version,
        "completeness": {
            "status": (snapshot.completeness or {}).get("status", "partial"),
            "missing_refs": list(
                (snapshot.completeness or {}).get("missing_refs", [])
            ),
        },
        "reproducibility": (
            "limited" if reproducibility.get("status") != "ready"
            else reproducibility.get("status", "limited")
        ),
        "data_included": False,
        "approval": None,
        "notes": [
            "Исходные данные в пакет не включены (data_included=false); "
            "воспроизводимость ограничена (limited) без разрешённого "
            "доступа к закреплённым данным.",
            "Манифест не содержит собственного sha256 (§13.3: "
            "циклическое определение запрещено).",
        ],
        "members": [
            {
                "name": name,
                "media_type": {
                    "report.json": "application/json",
                    "document.md": "text/markdown",
                    "table_claims.csv": "text/csv",
                    "chart_claims.svg": "image/svg+xml",
                    "table_schema.json": "application/json",
                }[name],
                "sha256": hashlib.sha256(members[name]).hexdigest(),
                "size_bytes": len(members[name]),
            }
            for name in (
                "report.json", "document.md", "table_claims.csv",
                "chart_claims.svg", "table_schema.json",
            )
        ],
    }
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, payload in [
            ("manifest.json", canonical_json_bytes(manifest)),
            *members.items(),
        ]:
            info = zipfile.ZipInfo(name, date_time=_ZIP_FIXED_DATE_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o600 << 16
            archive.writestr(info, payload)
    return buffer.getvalue()


# ── Имена файлов (безопасный Content-Disposition, §15.2) ────────────


def filename_for(revision_id: str, fmt: str) -> str:
    """Безопасное имя файла: только [A-Za-z0-9_-] от ID (мусор/пути
    вырезаются), расширение из каталога форматов."""
    spec = RENDITION_FORMATS.get(fmt)
    extension = spec.extension if spec is not None else "bin"
    safe_id = re.sub(r"[^A-Za-z0-9_-]", "", str(revision_id)) or "unknown"
    return f"document-{safe_id}.{extension}"
