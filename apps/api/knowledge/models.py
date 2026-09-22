# apps/api/knowledge/models.py
"""
Модель данных базы знаний (spec_education.md §1) -- KnowledgeArticle,
Citation -- плюс GlossaryTerm и HelpEntry (артефакт промоушена).

Соответствие манифесту спеки (§17): этот модуль -- apps/api/knowledge/
models.py. Отличие от минимального контракта спеки -- промоушен-расширения
KnowledgeArticle (summary/reading_minutes/body_blocks): контент
TS-реестра переносится 1:1 без перенабора, терять поля хаба недопустимо.
spec_education.md §14 прямо разрешает: directions -- опционально,
«не блокирует публикацию»; расширения -- назад-совместимы.

Сериализация блоков в body_md (docs/education_knowledge_base_architecture.md
§3 п.1): paragraph -> абзац, bullets -> "- ", callout -> "> ", блоки
соединяются пустой строкой. Тот же алгоритм реализован в генераторе
промоушена (scripts/promote_knowledge_registry.test.ts); согласованность
двух реализаций страхуется кросс-проверкой на ВСЕХ реальных записях:
jest пишет body_md, pytest пересобирает его Python-версией из body_blocks
(test_knowledge_api.py::TestRegistryIntegrity).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Sequence

# Грани потребления (§2.1 ревизии 2026-09-22 +facet библиотеки хаба):
# metrics/pipeline/module_help/stage_overview -- секции окна «Описание»
# и справка модулей; library -- статьи Библиотеки хаба /education.
KNOWLEDGE_FACETS = (
    "metrics",
    "pipeline",
    "module_help",
    "stage_overview",
    "library",
)

ARTICLE_STATUSES = ("draft", "published", "needs_review")


@dataclass(frozen=True)
class Citation:
    """Источник статьи (spec_education.md §1, §7.1 -- официальные/авторитетные)."""

    kind: str  # "book" | "paper" | "official_docs"
    label: str
    url: Optional[str] = None


@dataclass(frozen=True)
class KnowledgeArticle:
    """
    Статья базы знаний (spec_education.md §1).

    Ключ справки узла -- (stage_id, node_id, facet), уникален и
    застрахован тестами обеих сторон. Для библиотечных статей хаба
    node_id=None, facet="library" (статья уровня этапа, §1: node_id
    None -- статья уровня всей стадии).

    directions -- frozenset по спеке §1; порядок выдачи нормализуется
    реестром (канонический порядок KNOWLEDGE_DIRECTIONS), не порядком
    хранения.
    """

    article_id: str
    stage_id: str
    node_id: Optional[str]
    facet: str
    directions: frozenset
    title: str
    body_md: str
    sources: tuple
    status: str
    last_reviewed_at: Optional[str] = None
    superseded_constant: Optional[str] = None
    # ── промоушен-расширения (сохранение контента TS-реестра 1:1) ──
    summary: Optional[str] = None
    reading_minutes: Optional[int] = None
    body_blocks: Optional[tuple] = None


@dataclass(frozen=True)
class HelpEntry:
    """Вербатим-запись справки узла (Шаг 3,KnowledgeHelpEntry TS-реестра)."""

    entry_id: str
    stage_id: str
    node_id: Optional[str]
    facet: str
    superseded_constant: str
    text: str


@dataclass(frozen=True)
class GlossaryTerm:
    """Термин словаря (Шаг 1); related_article_ids -- связность базы знаний."""

    term_id: str
    term: str
    definition: str
    related_article_ids: tuple
    stage_ids: tuple


def blocks_to_body_md(blocks: Sequence[dict]) -> str:
    """
    Сериализация структурированных блоков в markdown (арх.док §3 п.1):
    paragraph -> абзац, bullets -> строки "- ", callout -> "> ";
    блоки соединяются пустой строкой. Детерминирована и обратимо
    читаемы; используется при промоушене и в тесте паритета.
    """
    parts: list[str] = []
    for block in blocks:
        block_type = block["type"]
        if block_type == "paragraph":
            parts.append(block["text"])
        elif block_type == "bullets":
            parts.append("\n".join("- " + item for item in block["items"]))
        elif block_type == "callout":
            parts.append("> " + block["text"])
        else:
            raise ValueError(f"Неизвестный тип блока: {block_type!r}")
    return "\n\n".join(parts)
