# apps/api/knowledge/router.py
"""
REST-контур микросервиса «Обучение и база знаний» (Шаг 4 EDU).

Контракты (spec_education.md, docs/education_knowledge_base_architecture.md
§6 Шаг 4):

  GET /v1/knowledge/articles
      Два режима одного ресурса (§2.1):
      - режим ключа узла: ?stage_id=&node_id=&facet= -> статья реестра
        (KnowledgeArticle) или честный null «справка готовится» -- HTTP 200
        с телом null, не 404: отсутствие справки -- нормальное состояние
        реестра, а не ошибка клиента (no fabricated results);
      - режим Библиотеки: без node_id/facet (stage_id опционален) ->
        {"articles": [...]} -- published-статьи хаба в порядке пайплайна
        (§13); draft не публикуется.
  GET /v1/knowledge/glossary?stage_id=
      Словарь терминов (25) в каноническом порядке реестра, фильтр по этапу.
  POST /v1/learning/track {"directions": [...]}
      Персональный обучающий стек (§2.2): множество направлений,
      порядок статей строго по пайплайну, missing_directions -- честная
      маркировка направлений без опубликованных статей.

АВТОРИЗАЦИЯ: эндпоинты ОТКРЫТЫ (без API-ключа) -- образование не гейтится
через Capabilities/тарифы по прямому определению задачи (spec_education.md
§7.2); контент -- статический реестр, пользовательских данных нет.

Словари валидации (stage_id/facet/directions) -- Literal: неизвестное
значение словаря -- ошибка клиента 422, а не «справка готовится»:
честный null зарезервирован для валидных ключей без статьи в реестре.
"""
from __future__ import annotations

from typing import List, Literal, Optional, Union

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from apps.api.knowledge.registry import load_registry
from apps.api.knowledge.models import KNOWLEDGE_FACETS

# Словари -- те же строки, что во всей платформе (§1.1 спеки). stage_id
# проверяется вручную (см. get_articles/get_glossary): Literal по
# динамическому артефакту промоушена невозможен, а ручная проверка даёт
# читаемый detail; расхождение словаря этапов ловится тестом
# test_stage_vocabulary_is_platform_stages (1:1 с STAGES) при каждом
# прогоне регрессии. Словарь граней facet -- models.KNOWLEDGE_FACETS.

DirectionLiteral = Literal[
    "seasonality",
    "missing_outliers",
    "intervals",
    "volatility",
    "multivariate",
    "trees_boosting",
    "neural",
    "methodology_validation",
]

# facet="library" в запросе ключа узла не принимается: библиотека
# читается списком (см. get_articles), а не по ключу узла.


class CitationOut(BaseModel):
    kind: str
    label: str
    url: Optional[str] = None


class KnowledgeArticleOut(BaseModel):
    article_id: str
    stage_id: str
    node_id: Optional[str]
    facet: str
    directions: List[str]
    title: str
    summary: Optional[str]
    reading_minutes: Optional[int]
    body_blocks: Optional[List[dict]]
    body_md: str
    sources: List[CitationOut]
    status: str
    last_reviewed_at: Optional[str]
    superseded_constant: Optional[str]


class ArticleListOut(BaseModel):
    articles: List[KnowledgeArticleOut]


class GlossaryTermOut(BaseModel):
    term_id: str
    term: str
    definition: str
    related_article_ids: List[str]
    stage_ids: List[str]


class GlossaryListOut(BaseModel):
    terms: List[GlossaryTermOut]


class LearningTrackRequest(BaseModel):
    directions: List[DirectionLiteral]


class LearningStackOut(BaseModel):
    directions: List[str]
    articles: List[KnowledgeArticleOut]
    terms: List[GlossaryTermOut]
    missing_directions: List[str]


def _article_out(article) -> KnowledgeArticleOut:
    return KnowledgeArticleOut(
        article_id=article.article_id,
        stage_id=article.stage_id,
        node_id=article.node_id,
        facet=article.facet,
        directions=sorted(
            article.directions,
            key=lambda d: load_registry().direction_ids.index(d),
        ),
        title=article.title,
        summary=article.summary,
        reading_minutes=article.reading_minutes,
        body_blocks=list(article.body_blocks) if article.body_blocks else None,
        body_md=article.body_md,
        sources=[
            CitationOut(kind=s.kind, label=s.label, url=s.url)
            for s in article.sources
        ],
        status=article.status,
        last_reviewed_at=article.last_reviewed_at,
        superseded_constant=article.superseded_constant,
    )


router = APIRouter()
learning_router = APIRouter()


@router.get(
    "/articles",
    response_model=Union[ArticleListOut, KnowledgeArticleOut, None],
    summary="Статьи базы знаний: Библиотека списком или статья по ключу узла",
)
def get_articles(
    stage_id: Optional[str] = None,
    node_id: Optional[str] = None,
    facet: Optional[str] = None,
):
    """
    Режим ключа узла (§2.1): задан facet -> статья (stage_id, node_id,
    facet) или null («справка готовится»). Режим Библиотеки: facet не
    задан -> список published-статей (stage_id -- фильтр этапа).

    Валидация словарей выполняется после маршрутизации, чтобы различать
    422 (незаконное значение словаря) и честный null (валидный ключ без
    статьи в реестре).
    """
    registry = load_registry()

    if facet is None and node_id is None:
        # ── режим Библиотеки ──
        if stage_id is not None and stage_id not in registry.stage_ids:
            raise HTTPException(
                status_code=422, detail=f"Неизвестный stage_id: {stage_id!r}"
            )
        return ArticleListOut(
            articles=[_article_out(a) for a in registry.get_published_library(stage_id)]
        )

    # ── режим ключа узла (§2.1) ──
    if stage_id is None or facet is None:
        raise HTTPException(
            status_code=422,
            detail=(
                "Ключ узла требует stage_id и facet одновременно "
                "(node_id опционален только для facet=module_help/stage_overview)"
            ),
        )
    if stage_id not in registry.stage_ids:
        raise HTTPException(
            status_code=422, detail=f"Неизвестный stage_id: {stage_id!r}"
        )
    if facet not in KNOWLEDGE_FACETS:
        raise HTTPException(status_code=422, detail=f"Неизвестный facet: {facet!r}")
    if facet == "library":
        # Библиотека адресуется списком (режим выше), не ключом узла:
        # несколько статей на этап с node_id=None -- ключ неуникален.
        raise HTTPException(
            status_code=422,
            detail="Библиотечные статьи читаются списком (без node_id/facet)",
        )

    article = registry.find_article(stage_id, node_id, facet)
    if article is None:
        return None  # честный null «справка готовится» (§2.1), HTTP 200
    return _article_out(article)


@router.get(
    "/glossary",
    response_model=GlossaryListOut,
    summary="Словарь терминов базы знаний",
)
def get_glossary(stage_id: Optional[str] = None):
    registry = load_registry()
    if stage_id is not None and stage_id not in registry.stage_ids:
        raise HTTPException(
            status_code=422, detail=f"Неизвестный stage_id: {stage_id!r}"
        )
    return GlossaryListOut(
        terms=[
            GlossaryTermOut(
                term_id=t.term_id,
                term=t.term,
                definition=t.definition,
                related_article_ids=list(t.related_article_ids),
                stage_ids=list(t.stage_ids),
            )
            for t in registry.get_glossary(stage_id)
        ]
    )


@learning_router.post(
    "/track",
    response_model=LearningStackOut,
    summary="Персональный обучающий стек по множеству направлений (§2.2)",
)
def build_learning_track(request: LearningTrackRequest):
    registry = load_registry()
    stack = registry.build_learning_stack(request.directions)
    return LearningStackOut(
        directions=list(stack.directions),
        articles=[_article_out(a) for a in stack.articles],
        terms=[
            GlossaryTermOut(
                term_id=t.term_id,
                term=t.term,
                definition=t.definition,
                related_article_ids=list(t.related_article_ids),
                stage_ids=list(t.stage_ids),
            )
            for t in stack.terms
        ],
        missing_directions=list(stack.missing_directions),
    )
