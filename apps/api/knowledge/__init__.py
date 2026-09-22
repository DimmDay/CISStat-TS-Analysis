# apps/api/knowledge/__init__.py
"""
Микросервис «Обучение и база знаний» — backend-контур слоя знаний.

Task EDU-API-1 (Шаг 4 EDU): промоушен реестров знаний из TS-источника
(packages/ui/lib/knowledge — единый источник истины) в backend БЕЗ
перенабора контента. Артефакт промоушена -- registry_data.json рядом
с этим пакетом (генератор: scripts/promote_knowledge_registry.test.ts,
паритет байт-в-байт застрахован jest-тестом; целостность backend-стороны
-- tests/api/test_knowledge_api.py).

Контракты:
  spec_education.md §1 (модель KnowledgeArticle/Citation), §2.1
  (GET /v1/knowledge/articles -> статья | честный null «справка
  готовится»), §2.2 (POST /v1/learning/track {directions} ->
  LearningStack, порядок пайплайна §13), §7.2 (образование бесплатно,
  вне тарифной сетки -- эндпоинты открыты, без API-ключа);
  docs/education_knowledge_base_architecture.md §6 Шаг 4.

Модули:
  models.py   -- KnowledgeArticle, Citation, GlossaryTerm, HelpEntry,
                 сериализация блоков в body_md (§3 арх.док п.1)
  registry.py -- загрузка артефакта промоушена, индексы, выдача
  router.py   -- FastAPI-роутеры /v1/knowledge и /v1/learning
"""
