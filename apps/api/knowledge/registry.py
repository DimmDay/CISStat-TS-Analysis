# apps/api/knowledge/registry.py
"""
Реестр знаний backend-стороны (Шаг 4 EDU) -- загрузка артефакта
промоушена registry_data.json и доступ к нему.

Источник истины контента -- TS-реестры packages/ui/lib/knowledge
(articles.ts / glossary.ts / help.ts). Этот модуль НЕ содержит
методологических текстов: он загружает механический артефакт промоушена
(генератор scripts/promote_knowledge_registry.test.ts -- jest, паритет
байт-в-байт с TS-реестрами застрахован тем же тестом при каждом прогоне;
регистрация изменений контента без перегенерации невозможна).

Семантика выдачи зеркалит фронтовый knowledge.ts (единый контракт слоя):
  - published-статьи в порядке пайплайна (spec_education.md §13);
  - честные промахи: find_article возвращает None -> роутер отдаёт
    literal null («справка готовится», no fabricated results);
  - build_learning_stack -- §2.2: множество направлений, дедупликация,
    порядок строго по пайплайну (не по порядку выбора чекбоксов),
    missing_directions -- выбранные направления без published-статей,
    термины -- только связанные со статьями стека.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Iterable, Optional

from apps.api.knowledge.models import (
    Citation,
    GlossaryTerm,
    HelpEntry,
    KnowledgeArticle,
)

REGISTRY_PATH = Path(__file__).with_name("registry_data.json")


class RegistryIntegrityError(RuntimeError):
    """Артефакт промоушена отсутствует или структурно некорректен."""


@dataclass(frozen=True)
class LearningStack:
    """Результат сборки персонального стека (spec_education.md §2.2)."""

    directions: tuple
    articles: tuple
    terms: tuple
    missing_directions: tuple


class KnowledgeRegistry:
    """Индексированный доступ к артефакту промоушена (immutable)."""

    def __init__(self, data: dict):
        try:
            self.stage_ids: tuple = tuple(data["stages"])
            self.direction_ids: tuple = tuple(data["directions"])
            self._stage_labels_ru: dict = dict(data["stage_labels_ru"])
            self._direction_labels_ru: dict = dict(data["direction_labels_ru"])
            raw_articles = data["articles"]
            raw_help = data["help_entries"]
            raw_glossary = data["glossary"]
        except (KeyError, TypeError) as exc:
            raise RegistryIntegrityError(
                f"registry_data.json некорректен: {exc}"
            ) from exc

        self._stage_order = {s: i for i, s in enumerate(self.stage_ids)}
        self._direction_order = {d: i for i, d in enumerate(self.direction_ids)}

        # ── библиотечные статьи хаба (facet="library", node_id=None) ──
        self._library: tuple[KnowledgeArticle, ...] = tuple(
            self._article_from_promotion(raw) for raw in raw_articles
        )
        # ── вербатим-записи справки узлов (Шаг 3) ─────────────────────
        self._help_entries: tuple[HelpEntry, ...] = tuple(
            HelpEntry(
                entry_id=raw["entry_id"],
                stage_id=raw["stage_id"],
                node_id=raw["node_id"],
                facet=raw["facet"],
                superseded_constant=raw["superseded_constant"],
                text=raw["text"],
            )
            for raw in raw_help
        )
        # Справка промотируется в ту же модель KnowledgeArticle (§1):
        # article_id=entry_id, title=первая строка текста (механический
        # вывод, без перенабора), body_md=текст вербатим, directions
        # пуст (§14: направления опциональны), sources пуст (текст
        # самодостаточен), status=published (живая справка продукта).
        self._help_articles: tuple[KnowledgeArticle, ...] = tuple(
            self._article_from_help(entry) for entry in self._help_entries
        )

        self._glossary: tuple[GlossaryTerm, ...] = tuple(
            GlossaryTerm(
                term_id=raw["term_id"],
                term=raw["term"],
                definition=raw["definition"],
                related_article_ids=tuple(raw["related_article_ids"]),
                stage_ids=tuple(raw["stage_ids"]),
            )
            for raw in raw_glossary
        )

        # ── индексы ────────────────────────────────────────────────
        # Ключ (stage_id, node_id, facet) уникален для СПРАВКИ узлов
        # (§2.1: секция окна «Описание» однозначно адресует запись).
        # Библиотечные статьи адресуются article_id и списком по этапу
        # (несколько статей на этап с node_id=None -- ключ неуникален
        # по построению), поэтому в key_index они не входят.
        self._key_index: dict = {}
        for article in self._help_articles:
            key = (article.stage_id, article.node_id, article.facet)
            if key in self._key_index:
                raise RegistryIntegrityError(f"дубль ключа справки: {key}")
            self._key_index[key] = article

        self._article_index = {
            a.article_id: a for a in self._all_articles()
        }
        if len(self._article_index) != len(self._library) + len(self._help_articles):
            raise RegistryIntegrityError("дубль article_id в реестре")

        self._published_library: tuple[KnowledgeArticle, ...] = tuple(
            sorted(
                (a for a in self._library if a.status == "published"),
                key=lambda a: (
                    self._stage_order[a.stage_id],
                    a.title,
                ),
            )
        )

    # ── построение моделей ─────────────────────────────────────────

    def _article_from_promotion(self, raw: dict) -> KnowledgeArticle:
        return KnowledgeArticle(
            article_id=raw["article_id"],
            stage_id=raw["stage_id"],
            node_id=raw["node_id"],
            facet=raw["facet"],
            directions=frozenset(raw["directions"]),
            title=raw["title"],
            body_md=raw["body_md"],
            sources=tuple(
                Citation(kind=s["kind"], label=s["label"], url=s.get("url"))
                for s in raw["sources"]
            ),
            status=raw["status"],
            last_reviewed_at=raw.get("last_reviewed_at"),
            superseded_constant=raw.get("superseded_constant"),
            summary=raw.get("summary"),
            reading_minutes=raw.get("reading_minutes"),
            body_blocks=tuple(raw["body_blocks"]) if raw.get("body_blocks") else None,
        )

    def _article_from_help(self, entry: HelpEntry) -> KnowledgeArticle:
        title = entry.text.split("\n", 1)[0].strip()
        return KnowledgeArticle(
            article_id=entry.entry_id,
            stage_id=entry.stage_id,
            node_id=entry.node_id,
            facet=entry.facet,
            directions=frozenset(),
            title=title,
            body_md=entry.text,
            sources=(),
            status="published",
            last_reviewed_at=None,
            superseded_constant=entry.superseded_constant,
            summary=None,
            reading_minutes=None,
            body_blocks=None,
        )

    # ── доступ ─────────────────────────────────────────────────────

    def _all_articles(self) -> Iterable[KnowledgeArticle]:
        yield from self._library
        yield from self._help_articles

    @property
    def articles(self) -> tuple:
        """Библиотечные статьи (включая draft -- честная маркировка)."""
        return self._library

    @property
    def help_entries(self) -> tuple:
        return self._help_entries

    @property
    def glossary(self) -> tuple:
        """Термины словаря в каноническом порядке реестра (алфавит
        реестра поддерживается на стороне TS и застрахован тестами)."""
        return self._glossary

    def find_article(
        self, stage_id: str, node_id: Optional[str], facet: str
    ) -> Optional[KnowledgeArticle]:
        """Поиск справки узла по ключу (stage_id, node_id, facet).
        Библиотечные статьи ключом не адресуются (несколько статей на
        этап с node_id=None) -- для них верните список через
        get_published_library(); здесь facet="library" -> None.
        Промах -> None («справка готовится» на вызывающей стороне, §2.1)."""
        if facet == "library":
            return None
        return self._key_index.get((stage_id, node_id, facet))

    def stage_label(self, stage_id: str) -> str:
        """RU-метка этапа пайплайна (stage_labels_ru артефакта промоушена,
        PROGR-7 §5.4): единая терминология с фронтовым knowledge.ts
        (STAGE_LABELS_RU) -- отчёт не изобретает названия этапов заново.
        Неизвестный этап -- честный id (no fabricated results)."""
        return self._stage_labels_ru.get(stage_id, stage_id)

    def get_published_library(
        self, stage_id: Optional[str] = None
    ) -> list[KnowledgeArticle]:
        """Published-статьи Библиотеки в порядке пайплайна (§13); draft
        не публикуется (принцип честности слоя знаний)."""
        if stage_id is None:
            return list(self._published_library)
        return [a for a in self._published_library if a.stage_id == stage_id]

    def get_glossary(self, stage_id: Optional[str] = None) -> list[GlossaryTerm]:
        if stage_id is None:
            return list(self._glossary)
        return [t for t in self._glossary if stage_id in t.stage_ids]

    # ── обучающие стеки (§2.2) ─────────────────────────────────────

    def build_learning_stack(self, raw_directions: Iterable[str]) -> LearningStack:
        """
        Персональный стек по МНОЖЕСТВУ направлений -- семантика
        buildLearningStack() фронтового knowledge.ts, 1:1:
          - направления дедуплицируются и нормализуются к каноническому
            порядку (детерминизм независимо от порядка чекбоксов);
          - пустой ввод -> пустой стек (no fabricated results);
          - статьи -- только published библиотеки, объединение без
            дублей, порядок строго по пайплайну (§13);
          - missing_directions -- выбранные направления без
            published-статей (честная маркировка «готовится»);
          - термины -- только связанные со статьями стека
            (related_article_ids), термины «в пустоту» не выдаются.
        """
        requested = set(raw_directions)
        directions = tuple(d for d in self.direction_ids if d in requested)
        if not directions:
            return LearningStack((), (), (), ())

        seen: set[str] = set()
        articles: list[KnowledgeArticle] = []
        for article in self._published_library:
            if article.directions & requested and article.article_id not in seen:
                seen.add(article.article_id)
                articles.append(article)
        articles.sort(
            key=lambda a: (self._stage_order[a.stage_id], a.title)
        )

        missing = tuple(
            d for d in directions if not any(d in a.directions for a in articles)
        )

        terms = tuple(
            t
            for t in self._glossary
            if any(ref in seen for ref in t.related_article_ids)
        )

        return LearningStack(directions, tuple(articles), terms, missing)


@lru_cache(maxsize=1)
def load_registry() -> KnowledgeRegistry:
    """Загрузка реестра (один экземпляр на процесс; артефакт immutable)."""
    if not REGISTRY_PATH.exists():
        raise RegistryIntegrityError(
            f"Артефакт промоушена не найден: {REGISTRY_PATH}. "
            "Перегенерируйте: PROMOTE_KNOWLEDGE=1 npx jest "
            "promote_knowledge_registry"
        )
    try:
        data = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RegistryIntegrityError(
            f"registry_data.json не читается: {exc}"
        ) from exc
    return KnowledgeRegistry(data)
