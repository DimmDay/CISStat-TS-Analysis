# tests/api/test_knowledge_api.py
"""
Task EDU-API-1 (Шаг 4 EDU: backend-промоушен слоя знаний).

Контракты:
  spec_education.md §1 (модель KnowledgeArticle/Citation), §2.1 (GET
  /v1/knowledge/articles → статья | честный null «справка готовится»),
  §2.2 (POST /v1/learning/track {directions} → LearningStack, порядок
  пайплайна §13), §7.2 (образование не гейтится — без API-ключа);
  docs/education_knowledge_base_architecture.md §6 Шаг 4 (промоушен
  реестров без перенабора контента), §3 п.1 (сериализация блоков в
  body_md 1:1), §3 п.2 (словарь этапов 1:1 со STAGES).

Источники контента — TS-реестры packages/ui/lib/knowledge (источник
истины); registry_data.json — механический артефакт промоушена
(генератор scripts/promote_knowledge_registry.test.ts, паритет
байт-в-байт застрахован jest-тестом). Эти тесты страхуют backend-сторону:
целостность реестра, контракты HTTP, честность выдачи.
"""
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from apps.api.knowledge.models import blocks_to_body_md
from apps.api.knowledge.registry import KnowledgeRegistry, load_registry
from apps.api.main import app
from apps.api.session_store import STAGES

client = TestClient(app)

EXPECTED_ARTICLES = 13          # 12 published + 1 draft (честная маркировка)
EXPECTED_PUBLISHED = 12
EXPECTED_HELP_ENTRIES = 77      # вербатим-записи справки (Шаг 3)
# Постановка Шага 4 называла «25 терминов» — состояние словаря на момент
# Шага 1; реестр вырос до 28 (источник истины — TS-реестр, промоушен
# переносит его целиком, без отсечения «лишнего» контента).
EXPECTED_TERMS = 28
EXPECTED_DIRECTIONS = [
    "seasonality",
    "missing_outliers",
    "intervals",
    "volatility",
    "multivariate",
    "trees_boosting",
    "neural",
    "methodology_validation",
]
# 4 будущих прикладных модуля НЕ входят в словарь этапов базы знаний (§1.1)
FUTURE_STAGE_IDS = ["scenario", "causal", "decision", "monitoring"]


# ═══════════════════════════════════════════════════════════
# 1. Целостность реестра (артефакт промоушена)
# ═══════════════════════════════════════════════════════════

class TestRegistryIntegrity:
    """Реестр загружен, полон и структурно честен."""

    def setup_method(self):
        self.registry = load_registry()

    def test_counts_verbatim(self):
        assert len(self.registry.help_entries) == EXPECTED_HELP_ENTRIES
        assert len(self.registry.articles) == EXPECTED_ARTICLES
        published = [a for a in self.registry.articles if a.status == "published"]
        assert len(published) == EXPECTED_PUBLISHED
        assert len(self.registry.glossary) == EXPECTED_TERMS

    def test_stage_vocabulary_is_platform_stages(self):
        """Контракт §1.1: словарь этапов — ТЕ ЖЕ строки, что STAGES."""
        assert list(self.registry.stage_ids) == list(STAGES)
        # будущие прикладные модули в словарь базы знаний не входят
        for future in FUTURE_STAGE_IDS:
            assert future not in self.registry.stage_ids

    def test_direction_vocabulary_canonical(self):
        assert list(self.registry.direction_ids) == EXPECTED_DIRECTIONS

    def test_unique_keys(self):
        key_seen = set()
        for entry in self.registry.help_entries:
            key = (entry.stage_id, entry.node_id, entry.facet)
            assert key not in key_seen, f"дубль ключа справки {key}"
            key_seen.add(key)
        ids = [a.article_id for a in self.registry.articles]
        assert len(ids) == len(set(ids))
        entry_ids = [e.entry_id for e in self.registry.help_entries]
        assert len(entry_ids) == len(set(entry_ids))
        term_ids = [t.term_id for t in self.registry.glossary]
        assert len(term_ids) == len(set(term_ids))

    def test_help_entries_have_provenance_and_body(self):
        for entry in self.registry.help_entries:
            assert entry.superseded_constant, entry.entry_id
            assert entry.text.strip(), entry.entry_id
            assert entry.facet in ("metrics", "pipeline", "module_help", "stage_overview")

    def test_library_articles_body_md_matches_blocks(self):
        """§3 арх.док п.1: сериализация блоков в body_md без потери."""
        for article in self.registry.articles:
            assert article.body_md.strip(), article.article_id
            assert article.body_blocks is not None, article.article_id
            assert article.body_md == blocks_to_body_md(article.body_blocks), (
                article.article_id
            )

    def test_help_promotion_fields(self):
        """Справка → KnowledgeArticle: body_md вербатим, title = первая строка."""
        article = self.registry.find_article(
            stage_id="eda", node_id="correlation", facet="metrics"
        )
        assert article is not None
        assert article.article_id == "eda.correlation.metrics"
        assert article.body_md == article.body_md.strip("\n")
        assert article.body_md.split("\n", 1)[0].strip() == article.title
        assert article.status == "published"
        assert article.facet == "metrics"
        assert article.node_id == "correlation"

    def test_glossary_links_resolve(self):
        """Инвариант слоя: ссылка термина — только на существующую статью."""
        article_ids = {a.article_id for a in self.registry.articles}
        for term in self.registry.glossary:
            assert term.definition.strip(), term.term_id
            for ref in term.related_article_ids:
                assert ref in article_ids, f"{term.term_id} → {ref}"

    def test_glossary_stages_valid(self):
        stage_set = set(self.registry.stage_ids)
        for term in self.registry.glossary:
            for stage in term.stage_ids:
                assert stage in stage_set, f"{term.term_id}: {stage}"


# ═══════════════════════════════════════════════════════════
# 2. Сериализация блоков → body_md (§3 арх.док п.1)
# ═══════════════════════════════════════════════════════════

class TestBlocksToBodyMd:
    def test_paragraph(self):
        assert blocks_to_body_md([{"type": "paragraph", "text": "Абзац."}]) == "Абзац."

    def test_bullets(self):
        blocks = [{"type": "bullets", "items": ["первый", "второй"]}]
        assert blocks_to_body_md(blocks) == "- первый\n- второй"

    def test_callout(self):
        assert blocks_to_body_md([{"type": "callout", "text": "Важно."}]) == "> Важно."

    def test_mixed_blocks_joined_with_blank_line(self):
        blocks = [
            {"type": "paragraph", "text": "Вводный абзац."},
            {"type": "bullets", "items": ["пункт"]},
            {"type": "callout", "text": "Принцип."},
        ]
        assert blocks_to_body_md(blocks) == (
            "Вводный абзац.\n\n- пункт\n\n> Принцип."
        )

    def test_roundtrip_on_registry(self):
        """На всех реальных статьях сериализация детерминирована."""
        registry = load_registry()
        for article in registry.articles:
            twice = blocks_to_body_md(article.body_blocks)
            assert twice == blocks_to_body_md(article.body_blocks)


# ═══════════════════════════════════════════════════════════
# 3. GET /v1/knowledge/articles (§2.1: статья | честный null)
# ═══════════════════════════════════════════════════════════

class TestGetArticles:
    def test_no_params_returns_published_library(self):
        resp = client.get("/v1/knowledge/articles")
        assert resp.status_code == 200
        payload = resp.json()
        articles = payload["articles"]
        assert len(articles) == EXPECTED_PUBLISHED
        # draft не публикуется (принцип честности)
        statuses = {a["status"] for a in articles}
        assert statuses == {"published"}
        # только библиотечные статьи (не справка узлов)
        assert all(a["facet"] == "library" for a in articles)
        assert all(a["node_id"] is None for a in articles)

    def test_listing_order_follows_pipeline(self):
        """§13: порядок выдачи — порядок stage_id в пайплайне, внутри этапа по заголовку."""
        resp = client.get("/v1/knowledge/articles")
        articles = resp.json()["articles"]
        stage_order = {s: i for i, s in enumerate(STAGES)}
        keys = [(stage_order[a["stage_id"]], a["title"]) for a in articles]
        assert keys == sorted(keys)
        for a, b in zip(articles, articles[1:]):
            if a["stage_id"] == b["stage_id"]:
                assert a["title"] <= b["title"]

    def test_filter_by_stage(self):
        resp = client.get("/v1/knowledge/articles", params={"stage_id": "eda"})
        assert resp.status_code == 200
        articles = resp.json()["articles"]
        assert len(articles) == 4
        assert {a["stage_id"] for a in articles} == {"eda"}
        ids = {a["article_id"] for a in articles}
        assert ids == {
            "eda-descriptive-correlation",
            "eda-seasonality",
            "eda-stationarity",
            "eda-structural-breaks",
        }

    def test_article_shape(self):
        resp = client.get("/v1/knowledge/articles", params={"stage_id": "upload"})
        article = resp.json()["articles"][0]
        for field in (
            "article_id", "stage_id", "node_id", "facet", "directions",
            "title", "summary", "reading_minutes", "body_blocks", "body_md",
            "sources", "status", "last_reviewed_at", "superseded_constant",
        ):
            assert field in article, field
        assert article["article_id"] == "upload-structure"
        assert article["body_md"].startswith("Загрузка")

    def test_node_lookup_returns_help_article(self):
        resp = client.get(
            "/v1/knowledge/articles",
            params={"stage_id": "eda", "node_id": "correlation", "facet": "metrics"},
        )
        assert resp.status_code == 200
        article = resp.json()
        assert article is not None
        assert article["article_id"] == "eda.correlation.metrics"
        assert article["node_id"] == "correlation"
        assert article["facet"] == "metrics"
        assert article["superseded_constant"] == (
            "TsAnalysisEDA.tsx::CORRELATION_METRICS_DESCRIPTION"
        )
        # вербатим-текст (первая строка — заголовок секции окна «Описание»)
        assert article["body_md"].startswith("Метрики и алгоритм: Корреляция")

    def test_node_lookup_module_help_without_node(self):
        resp = client.get(
            "/v1/knowledge/articles",
            params={"stage_id": "validation", "facet": "module_help"},
        )
        assert resp.status_code == 200
        article = resp.json()
        assert article["article_id"] == "validation.module.module_help"
        assert article["node_id"] is None

    def test_node_lookup_stage_overview(self):
        resp = client.get(
            "/v1/knowledge/articles",
            params={"stage_id": "modeling", "node_id": "selection", "facet": "stage_overview"},
        )
        assert resp.status_code == 200
        assert resp.json()["article_id"] == "modeling.selection.stage_overview"

    def test_library_not_addressable_by_node_key(self):
        """Библиотека адресуется списком (несколько статей на этап с
        node_id=None -- ключ (stage, null, library) неуникален)."""
        assert (
            load_registry().find_article("eda", None, "library") is None
        )
        resp = client.get(
            "/v1/knowledge/articles",
            params={"stage_id": "eda", "facet": "library"},
        )
        assert resp.status_code == 422

    def test_honest_null_for_missing_help(self):
        """§2.1: несуществующий ключ → null («справка готовится»), не 404."""
        resp = client.get(
            "/v1/knowledge/articles",
            params={"stage_id": "eda", "node_id": "unknown_node", "facet": "metrics"},
        )
        assert resp.status_code == 200
        assert resp.json() is None

    def test_invalid_vocabulary_rejected(self):
        # неизвестный этап — ошибка словаря, а не «справка готовится»
        resp = client.get("/v1/knowledge/articles", params={"stage_id": "bogus"})
        assert resp.status_code == 422
        resp = client.get(
            "/v1/knowledge/articles",
            params={"stage_id": "eda", "node_id": "correlation", "facet": "bogus"},
        )
        assert resp.status_code == 422

    def test_incomplete_key_rejected(self):
        # node_id без facet — неполный ключ узла
        resp = client.get(
            "/v1/knowledge/articles",
            params={"stage_id": "eda", "node_id": "correlation"},
        )
        assert resp.status_code == 422
        # facet без stage_id — ключ неполон
        resp = client.get("/v1/knowledge/articles", params={"facet": "metrics"})
        assert resp.status_code == 422

    def test_no_api_key_required(self):
        """§7.2: образование вне тарифной сетки — эндпоинт открыт."""
        resp = client.get("/v1/knowledge/articles")
        assert resp.status_code == 200


# ═══════════════════════════════════════════════════════════
# 4. GET /v1/knowledge/glossary
# ═══════════════════════════════════════════════════════════

class TestGetGlossary:
    def test_all_terms_registry_order(self):
        resp = client.get("/v1/knowledge/glossary")
        assert resp.status_code == 200
        terms = resp.json()["terms"]
        assert len(terms) == EXPECTED_TERMS
        registry = load_registry()
        assert [t["term_id"] for t in terms] == [t.term_id for t in registry.glossary]

    def test_term_shape(self):
        resp = client.get("/v1/knowledge/glossary")
        term = resp.json()["terms"][0]
        for field in ("term_id", "term", "definition", "related_article_ids", "stage_ids"):
            assert field in term

    def test_filter_by_stage(self):
        resp = client.get("/v1/knowledge/glossary", params={"stage_id": "modeling"})
        assert resp.status_code == 200
        terms = resp.json()["terms"]
        assert terms, "у Моделирования есть термины"
        assert all("modeling" in t["stage_ids"] for t in terms)

    def test_invalid_stage(self):
        resp = client.get("/v1/knowledge/glossary", params={"stage_id": "bogus"})
        assert resp.status_code == 422


# ═══════════════════════════════════════════════════════════
# 5. POST /v1/learning/track (§2.2 → LearningStack)
# ═══════════════════════════════════════════════════════════

class TestLearningTrack:
    def _post(self, directions):
        return client.post("/v1/learning/track", json={"directions": directions})

    def test_stack_two_directions(self):
        resp = self._post(["seasonality", "intervals"])
        assert resp.status_code == 200
        stack = resp.json()
        # канонический порядок §2.2: seasonality(0) раньше intervals(2)
        assert stack["directions"] == ["seasonality", "intervals"]
        ids = [a["article_id"] for a in stack["articles"]]
        assert len(ids) == len(set(ids))  # без дублей
        assert set(ids) == {"preprocessing-regularity-stl", "modeling-backtest",
                            "forecasting-intervals", "forecasting-accuracy-metrics",
                            "eda-seasonality"}
        # порядок строго по пайплайну (§13)
        stage_order = {s: i for i, s in enumerate(STAGES)}
        stage_keys = [stage_order[a["stage_id"]] for a in stack["articles"]]
        assert stage_keys == sorted(stage_keys)
        # все статьи published и tagged выбранным направлением
        for article in stack["articles"]:
            assert article["status"] == "published"
            assert set(article["directions"]) & {"seasonality", "intervals"}
        assert stack["missing_directions"] == []

    def test_checkbox_order_does_not_matter(self):
        """§2.2/§13: порядок выбора чекбоксов не влияет на стек."""
        a = self._post(["intervals", "seasonality"]).json()
        b = self._post(["seasonality", "intervals"]).json()
        assert a == b

    def test_duplicate_directions_deduped(self):
        single = self._post(["seasonality"]).json()
        dup = self._post(["seasonality", "seasonality"]).json()
        assert dup == single

    def test_terms_linked_to_stack_articles_only(self):
        """Термины «в пустоту» не выдаются: связаны со статьями стека."""
        stack = self._post(["seasonality", "intervals"]).json()
        article_ids = {a["article_id"] for a in stack["articles"]}
        assert stack["terms"], "у стека есть связанные термины"
        for term in stack["terms"]:
            assert set(term["related_article_ids"]) & article_ids

    def test_empty_directions_empty_stack(self):
        """Пустой ввод → пустой стек (no fabricated results)."""
        resp = self._post([])
        assert resp.status_code == 200
        stack = resp.json()
        assert stack == {"directions": [], "articles": [], "terms": [],
                         "missing_directions": []}

    def test_direction_without_articles_is_honestly_missing(self):
        """volatility/multivariate пока без published-статей — честная маркировка."""
        resp = self._post(["volatility"])
        assert resp.status_code == 200
        stack = resp.json()
        assert stack["articles"] == []
        assert stack["terms"] == []
        assert stack["missing_directions"] == ["volatility"]

    def test_mixed_stack_reports_missing_part(self):
        stack = self._post(["seasonality", "volatility", "multivariate"]).json()
        # канонический порядок: volatility(3) раньше multivariate(4)
        assert stack["missing_directions"] == ["volatility", "multivariate"]
        assert stack["directions"] == ["seasonality", "volatility", "multivariate"]
        assert all("seasonality" in a["directions"] for a in stack["articles"])

    def test_unknown_direction_rejected(self):
        resp = self._post(["bogus"])
        assert resp.status_code == 422

    def test_directions_required(self):
        resp = client.post("/v1/learning/track", json={})
        assert resp.status_code == 422

    def test_stack_matches_registry_semantics(self):
        """Стек = объединение published-статей направлений (семантика фронта)."""
        registry = load_registry()
        selected = ["methodology_validation", "trees_boosting", "neural"]
        resp = self._post(selected).json()
        expected = set()
        for article in registry.articles:
            if article.status == "published" and set(article.directions) & set(selected):
                expected.add(article.article_id)
        assert {a["article_id"] for a in resp["articles"]} == expected


# ═══════════════════════════════════════════════════════════
# 6. Целостность OpenAPI-контракта
# ═══════════════════════════════════════════════════════════

class TestOpenApi:
    def test_routes_registered(self):
        paths = app.openapi()["paths"]
        assert "/v1/knowledge/articles" in paths
        assert "/v1/knowledge/glossary" in paths
        assert "/v1/learning/track" in paths
