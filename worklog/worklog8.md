# CISStat TS Analysis — Worklog

---

## Task ID: PROGR-1 (2026-09-23) — Микросервис «Прогресс»: сведение канонического TraceEvent (spec_progress.md §4.1) с apps/api/trace_events.py
Синхронизация: main@ab0ef57, рабочее дерево с незакоммиченными правками текущей задачи (commit/push запрещены AGENTS.md).

### Постановка

Спроектировать микросервис «Прогресс» (spec_progress.md v3 + spec_progress_review_and_v4_addendum.md), декомпозировать на подзадачи, выложить план работ в plan_progress.md, реализовать первую задачу. Порядок работ принят по аддендуму (Часть 5): сведение TraceEvent — задача №1, «не второстепенный пункт закрытого вопроса».

### Проектирование (plan_progress.md, в корне репо)

Верификация всех фактов обеих спецификаций по живому коду @ab0ef57 (аддендум п.2.1/4.2 требовал «первым шагом»): реестры CHECK_IDS / PREPROCESSING_CHECK_IDS / MODELING_STAGE_IDS / EDA CHECKS / STAGES — совпали дословно; w-80 у EventsLogDrawer подтверждён; единственный импортёр trace_events — forecasting_session.py (только make_trace_event), прямых конструкций TraceEvent(...) и читателей .timestamp вне модуля нет → миграция низкорискованная, аддитивная.
Ключевая верификационная находка: pydantic ForecastTraceEventSchema (apps/api/schemas.py) объявляет timestamp обязательным полем, а фронтенд-интерфейс ForecastTraceEvent (packages/ui/lib/forecasting.ts) его читает → переименование в ts без двойной записи сломало бы HTTP-контракт. Решение — to_dict() отдаёт 8 канонических ключей + legacy-алиас timestamp; pydantic фильтрует лишние ключи, контракт ответа не меняется.
Декомпозиция: PROGR-1 (сведение TraceEvent) → PROGR-2 (граф pipeline_graph.py + PipelineNodeState + свёртка §12 п.10 + вынос EDA CHECKS в общий JSON §12 п.2) → PROGR-3 (внутрисессионный слой трассы + хук записи) → PROGR-4 (UI: ProgressDrawer/кнопка-триггер по контракту §4.1–4.2 аддендума) → PROGR-5 (research_runs/Postgres, чекпоинты, restore) → PROGR-6 (Наставник §7.1/§7.2, пороги в rules/*.yaml) → PROGR-7 (отчёт §5.4) → PROGR-8 (admin §10 + офлайн §9, категория D).
TDD
RED: tests/api/test_trace_events.py (новый, 24 теста): канон 8 полей, uuid event_id, ISO ts, legacy-алиас timestamp, to_dict 9 ключей с глубокой копией payload, реестр STAGE_EVENT_TYPES по таблице §4.1 (run-level типы — отдельная строка «любая стадия», не растворены в стадиях), fail-closed на (stage, event_type)-пару и неизвестную стадию, нормализация legacy 3-польных stored-событий (normalize_trace_event_dict/from_dict, idempotent pass-through канона, без мутации входа), уникальность event_id, замороженность датакласса, не-распространение дефолтного payload, обратная совместимость сигнатуры 4 текущих вызовов Прогнозирования. ImportError на сборе — RED подтверждён.
GREEN: apps/api/trace_events.py — канонические 8 полей с дефолтами (порядок event_type/payload сохранён), property timestamp→ts, KNOWN_STAGES (локальная константа; равенство session_store.STAGES — import-инвариант теста PROGR-2: направленный импорт хранилища из контракта создал бы обратную зависимость), RUN_LEVEL_EVENT_TYPES, make_trace_event(*, stage="forecasting", node_id, run_id, actor, **payload) с гейтом на пару (stage, event_type), normalize_trace_event_dict (дефолт стадии "forecasting" — честное значение единственной реальной legacy-популяции; для канонического входа — pass-through), TraceEvent.from_dict.
Итерация по упавшим своим тестам: STAGE_EVENT_TYPES сначала был со «вплавленными» run-level типами — исправлен на чистый реестр по таблице §4.1 (строка «session» отдельно), гейт проверяет оба множества; дефолт стадии частичного канона в тесте заменён upload→forecasting (не изобретать ложные данные).

### Верификация

Свои сьюты: tests/api/test_trace_events.py — 24/24.
Потребитель: tests/api/test_forecasting_session.py — 22/22 (46 вместе).
Полный tests/api: с правкой 739 passed / 3 failed; контрольный замер базлайна на дереве без правки (stash trace_events.py): 715 passed / 3 failed — наборы падений идентичны (diff пустой), +24 теста = мои. Три предсущественных падения средовые: modeling_workflow (catalog-only-гейт), neural_capacity (память хоста), models_candidates (unsupported-model гейт) — к задаче не относятся, воспроизводятся на ab0ef57.
Средовой чинено окружение (не код): в venv отсутствовал apps/api/requirements.txt (prophet==1.4.0, statsforecast==2.1.1 и пины API-сервиса) — import-гейт models.py «Реестр готовности моделей расходится с production backtest dispatch» падал на сборе ВСЕГО tests/api (предсущественно); после установки — гейт 19==19, сьюты собираются. Нейро-группа не ставилась (дизайн допускает хосты без неё).
Deliverable
ZIP: cisstat-progr1-canonical-trace-event.zip — 4 файла (apps/api/trace_events.py — изменён; tests/api/test_trace_events.py, plan_progress.md — НОВЫЕ; worklog/worklog7.md), пути репозитория сохранены. Без commit/push (AGENTS.md).
Границы задачи: прогнозирующие вызовы forecasting_session.py не правились (совместимость через дефолты); фронтенд не трогался (pydantic-фильтр лишних ключей to_dict сохраняет контракт ответа дословно).
