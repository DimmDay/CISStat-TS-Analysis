# apps/api/document_renditions.py
"""
DOCLOG-4 (spec_documentation_logging.md §7, §12.3, §19 строка DOCLOG-4,
§20 AC05/AC16): рендеры MVP-выдачи -- ЧИСТЫЕ функции от замороженного
ReportSnapshot.

ПОСТАНОВКА (§19, строка DOCLOG-4): «Раздел документов, stage entry
points, HTML/MD/JSON/JSONL/существующие таблицы, job states». Рендеры
строят формат ИЗ снимка (R06: «MD/HTML/PDF/DOCX/XLSX строятся из одного
снимка; формат обмена не становится источником истины»): они НЕ читают
живой run/сессию/артефакты, НЕ запускают fit/query, НЕ меняют научное
состояние (AC05). Тяжёлые форматы (PDF/XLSX/Parquet/ChartSpec SVG-PNG/
ZIP) -- DOCLOG-5: в каталоге P0 их нет, роутер отвечает 400
unsupported_format.

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
import re
from dataclasses import dataclass
from typing import Any, Optional

from apps.api.artifact_store import canonical_json_bytes
from apps.api.report_snapshot import ReportSnapshot

# ── Каталог форматов P0 (§7) ─────────────────────────────────────────


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
}

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


# ── Имена файлов (безопасный Content-Disposition, §15.2) ────────────


def filename_for(revision_id: str, fmt: str) -> str:
    """Безопасное имя файла: только [A-Za-z0-9_-] от ID (мусор/пути
    вырезаются), расширение из каталога форматов."""
    spec = RENDITION_FORMATS.get(fmt)
    extension = spec.extension if spec is not None else "bin"
    safe_id = re.sub(r"[^A-Za-z0-9_-]", "", str(revision_id)) or "unknown"
    return f"document-{safe_id}.{extension}"
