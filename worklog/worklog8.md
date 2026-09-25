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

---

## Консультация (2026-09-23) — СУБД слоя знаний: следующий шаг, физическое размещение, порядок миграции (без кода)

### Контекст

- Web-сессия пересоздана (контейнер обновлён): рабочая копия и локальная
  незакоммиченная онбординг-запись прошлой сессии утрачены. Репозиторий
  клонирован заново; HEAD = ab0ef57 (origin/main) — включает EDU-API-1
  (63c3f0c) и аудит hardcoded KB (docs/audit_hardcoded_kb_63c3f0c_2026-09-22.md).
- Вопрос тимлида: (1) верно ли, что следующий логичный шаг — проектирование
  и написание реляционной СУБД; (2) где она будет расположена физически;
  (3) разворачивать сразу на собственном корпоративном сервере или позже
  можно перенести. Ответить с обоснованием. Код не писать.

### Фактура, на которую опирался ответ (все источники — из репо)

- spec_progress.md §12 (вводная зафиксирована версией 2 от 2026-09-08):
  целевая production-среда — собственный корпоративный сервер, Linux-VM,
  CPU-only, RAM в достатке; рекомендация п.1 — Postgres для
  research_runs/trace_events (обоснования а–г: SQL-агрегации админ-панели,
  фиксированная схема TraceEvent, Redis остаётся кэшем/сессиями с TTL,
  on-prem-опыт эксплуатации Postgres); «один инстанс Postgres на той же VM
  или соседней, без кластера».
- spec_education.md Часть II: KnowledgeArticle/Citation/база практик — та
  же СУБД, что research_runs/trace_events; RAGFlow — собственный индекс
  ВНЕ основной СУБД, синхронизация батч-джобом по событию draft→published.
- Аудит §10 п.1: инверсия источника истины — СУБД становится первичным
  носителем KnowledgeArticle/GlossaryTerm/справки; TS-реестр — кэш сборки.
- Текущая инфраструктура: API — Docker на Render free (эфемерный диск,
  холодный старт), сессии — MemorySessionStore/RedisSessionStore (Upstash
  free, REDIS_URL), фронт — Vercel с server-side прокси /api/v1/* через
  API_URL; СУБД в apps/api отсутствует (нет sqlalchemy/alembic/psycopg);
  контент знаний — registry_data.json в образе (переходное решение
  63c3f0c, паритет с TS-реестром застрахован тест-генератором).

### Ответы (суть)

1. Да, следующий шаг — проектирование реляционной схемы данных и внедрение
   готовой СУБД (PostgreSQL — рекомендация уже зафиксирована в
   spec_progress §12 п.1); «написание СУБД» — терминологически неверно:
   пишутся схема (Alembic-миграции), seed-контур переноса контента без
   перенабора и слой доступа. Состав сущностей: knowledge_articles,
   glossary_terms, help-записи (77), узловые привязки (M:N),
   learning_stack, research_runs, trace_events, телеметрия Q/ΔQ,
   админ-поля (версии, автор, last_reviewed_at, статус draft→published).
2. Физически — принцип «СУБД следует за API»: БД живёт в одной зоне с API,
   которое её обслуживает (латентность, транзакции, 5432 не покидает
   периметр). Целевое состояние — корпоративный сервер: Postgres на той же
   Linux-VM, что и API (или соседней), Docker Compose — совпадает с
   рекомендацией spec_progress §12 п.1. Недопустимая промежуточная
   конфигурация: API на Render + БД on-prem через интернет/туннель.
3. Порядок: если миграция платформы на собственный сервер близка (порядка
   недель, сервер provisionирован) — поднимать Postgres сразу там вместе с
   API (перенос всего бэкенда целиком; Vercel меняет только API_URL),
   минуя облачную БД — нет двойной инфраструктуры и двойной миграции.
   Если сроки неопределённы — временный управляемый облачный Postgres
   (Neon/Render Postgres/Supabase) рядом с Render и штатный перенос позже.
   Перенос дёшев: pg_dump/pg_restore или логическая репликация; объёмы
   этапа — единицы–десятки МБ; простой измеряется минутами. Переносимость
   обеспечивают три артефакта: схема в Alembic-миграциях (код), seed-файлы
   контента в репозитории, pg_dump операционных данных. Запреты: SQLite на
   диске Render как durable-хранилище (эфемерный ФС), схема «руками» без
   миграций, проброс 5432 в интернет. pgvector сейчас не нужен — индексацию
   по спеке ведёт сам RAGFlow.

### Статус

- Ответ-обоснование выдан в чат. Код не писался (по постановке),
  commit/push не выполнялись.
- Незакоммиченное изменение рабочего дерева: только эта запись worklog7.md.

---

## Task ID: PROGR-1-CERT (2026-09-23) — Независимая сертификация Task PROGR-1 (оракул- и мутационные тесты аудитора)

### Постановка

Честная сертификация первой задачи плана plan_progress.md (PROGR-1 — сведение
канонического TraceEvent §4.1 с apps/api/trace_events.py): оценка реализации
задач спецификаций по плану, изучение живой кодовой базы, независимые
оракул-тесты на СВОИХ данных аудитора, независимый мутационный прогон.
Методика — по прецедентам проекта (Task 144/145, FORECAST-1, IA-1) и AGENTS.md.

### Оценка плана PROGR-1..8 по живому коду @29d84a8

- PROGR-1 — РЕАЛИЗОВАНА (42e7354): канонические 8 полей, legacy-алиас
  timestamp, реестр STAGE_EVENT_TYPES + RUN_LEVEL_EVENT_TYPES отдельной
  строкой, fail-closed фабрика, normalize_trace_event_dict, from_dict,
  24 теста. PROGR-2..8 — не реализованы (артефакты отсутствуют:
  pipeline_graph.py, trace_hook.py, research_runs.py, mentor_rules.py,
  ProgressDrawer.tsx; EventsLogDrawer.tsx на месте, pipeline_trace нет) —
  очерёдность и зависимости плана соблюдены.

### Верификация приёмки PROGR-1 (все 3 критерия — OK)

1. 24/24 test_trace_events.py (RED задокументирован в worklog7).
2. Ноль правок forecasting_session.py (git show --stat 42e7354; 4 call-site
   целы — потребитель 22/22).
3. Полный tests/api: 739 passed / 3 failed; baseline-прогон с обратной
   подстановкой trace_events.py@d134f93 воспроизводит те же 3 падения
   (modeling_workflow catalog-only-гейт, neural_capacity память,
   models_candidates DeepAR panel-сообщение без нейро-группы) —
   предсущественные средовые, наборы совпадают.

### Оракул-тесты аудитора (свои данные) — scripts/progr1_cert_oracles.py

37/37 GREEN. Данные собственные: RUN-9F3KC7-CERT, свои timestamps/payload,
своя legacy-популяция (4 события прогнозного прогона), независимая кодировка
таблицы §4.1. Группы: A (канон полей, 9 — UUID event_id, серверный UTC ts
внутри границ момента фабрики, frozen, изоляция дефолтов), B (реестр, 7 —
дословное равенство таблице §4.1, run-level не вплавлены, исчерпывающий
позитивный обход, fail-closed x3), C (to_dict, 6 — ровно 9 ключей, pydantic
ForecastTraceEventSchema цел для всего реестра, изоляция плоского payload),
D (миграция, 12 — идемпотентность, не-мутация входа, pass-through, round-trip
from_dict(to_dict(e))==e на 37 парах, смешанный корпус с инвариантом двойной
записи ts==timestamp), E (совместимость 4 call-site + pydantic, факты без
сырых данных, 2).

### Мутационный прогон аудитора — scripts/progr1_cert_mutations.py

21 мутант (точечная порча контракта), каждый против собственного сьюта И
оракулов; восстановление файла верифицировано sha256. Итог: 20/21 KILLED,
0 errors. Дыры собственного сьюта задачи, закрытые ТОЛЬКО оракулами:
MUT-03 (наивный ts без TZ — сьют проверяет лишь парсимость ISO) и
MUT-20 (алиас payload в нормализации — тест не-мутации не ловит алиасирование).
SURVIVED 1 — MUT-19 (порча дефолтов датакласса): ожидаемо эквивалентный
мутант, дефолты недостижимы (фабрика/from_dict передают все 8 полей явно,
прямых конструкций TraceEvent() вне модуля нет).

### Находки (акт: docs/cert_progr1_trace_event_2026-09-23.md)

- R1: «глубокая копия payload» в worklog7 — неточная формулировка: копия
  поверхностная (вложенные структуры разделяются, C5b/D4b/MUT-20/22).
  Коду не дефект (спека глубину не требует, продовые payload плоские);
  уточнить формулировку либо сделать глубокой в PROGR-3.
- R2: legacy-маркер (timestamp без ts) игнорирует явную stage в словаре —
  граничный случай,_today_ без последствий; решение зафиксировать в PROGR-3.
- R3: normalize/from_dict не валидируют event_type на границе чтения
  (только стадию) — защитимое дизайн-решение, но зафиксировать осознанно.
- R4: дефолты датакласса декоративны (недостижимы) — в PROGR-3 при первых
  прямых потребителях станут живыми: покрыть тестом прямого конструирования.
- R5: средовой чек-лист прогонов (prophet 1.4.0, statsforecast 2.1.1,
  xgboost 2.1.3, lightgbm 4.5.0, catboost 1.2.8, arch, statsmodels>=0.15.0 —
  при 0.14.5 все 16 прогнозных E2E падают честным 422 о симуляции).

### Вердикт

**PASSED WITH REMARKS.** Все критерии приёмки выполнены; мутационная
устойчивость 20/21 (+1 ожидаемый эквивалентный выживший); замечания R1–R4
не блокируют и адресуются в PROGR-3. Deliverable: ZIP
cisstat-progr1-certification.zip (docs/cert_progr1_trace_event_2026-09-23.md,
scripts/progr1_cert_oracles.py, scripts/progr1_cert_mutations.py,
scripts/progr1_cert_mutation_results.txt, worklog/worklog8.md). Без
commit/push (AGENTS.md).

---

## Task ID: BRND-1 (2026-09-24) — Шапка standalone: кегль бренда «CISStat TS Analysis» = высоте логотипа

### Постановка

Логотип платформы имеет определённую высоту; за ним следует бренд
«CISStat TS Analysis». Сделать высоту шрифта бренда равной высоте
логотипа. Увеличение — пропорциональное, без смены самого шрифта и его
цвета; чуть уменьшить межбуквенное расстояние. По результатам — ZIP в
download. AGENTS.md соблюдены: проектирование → точки изменения → риски →
TDD RED→GREEN → повторные тесты → сборка → ZIP → worklog; без commit/push.

### Проектирование (точки изменения, риски)

- Поиск по репо: связка «логотип → бренд» единственная —
  apps/standalone/components/ProductHeader.tsx (шапка standalone,
  прод ts-standalone.vercel.app). EmbeddedHome — h1 без логотипа;
  ModuleNav логотипа не содержит; layout.tsx — favicon/metadata.
- Фактура: логотип — apps/standalone/public/logo_TS.png 1058×1034
  (почти квадрат), next/image fill + object-contain в боксе h-7 w-7 →
  видимая высота логотипа = 28px (h-7 = 1.75rem @ 16px root). Бренд —
  <strong> с text-[15px] font-bold text-brand.
- Решение: text-[28px] — кегль = высоте логотипа; font-bold и text-brand
  сохранены, семейство (Inter) по наследованию — пропорциональное
  масштабирование, сам шрифт и цвет не менялись; tracking-tight
  (-0.025em) — чуть уменьшенное межбуквенное расстояние; leading-none —
  строковый бокс 28px: вертикаль шапки остаётся обусловленной элементами
  h-7 (логотип, кнопка кабинета), текстовый блок равен логотипу.
- Риски: (1) рост высоты шапки из-за line-height ~1.5 при кегле 28px —
  закрыт leading-none; (2) тест, закрепляющий text-[15px], — обновлён в
  RED-фазе; (3) JIT-генерация arbitrary-класса text-[28px] — content-scan
  tailwind.config включает ./components/** (тест-гарант «Tailwind
  production scan» зелёный), дополнительно верифицировано по факту сборки.

### TDD

RED: apps/standalone/components/ProductHeader.test.tsx — тест кегля
обновлён (text-[28px], не text-[15px]) + 4 новых: равенство кегля высоте
логотипа (сопоставление text-[28px] и h-7 бокса логотипа на одном
рендере), гарант «шрифт и цвет не менялись» (font-bold + text-brand),
tracking-tight, leading-none. Прогон: 4 failed / 5 passed — RED
подтверждён; гарант-инвариант зелёный и на старом коде, как задумано.
GREEN: apps/standalone/components/ProductHeader.tsx — className бренда:
text-[15px] → «text-[28px] leading-none font-bold tracking-tight
text-brand»; в шапке файла — комментарий задачи. Прогон: 9/9.

### Верификация и сборка

- Полный jest: 135 сьют / 1563 теста — все зелёные (включая
  layout.test.tsx, рендерящий ProductHeader через корневой layout).
- typecheck standalone (tsc --noEmit) — чисто.
- next build (production, standalone) — успешно, 15 маршрутов; в
  собранном CSS верифицировано: font-size:28px, letter-spacing:-.025em,
  leading-none; text-[15px] в бандле отсутствует.

### Deliverable

ZIP: cisstat-brand-font-equals-logo.zip — 3 файла (пути репозитория
сохранены): apps/standalone/components/ProductHeader.tsx (изменён),
apps/standalone/components/ProductHeader.test.tsx (изменён),
worklog/worklog8.md (изменён — эта запись). Без commit/push (AGENTS.md).

---

## Task ID: BRND-2 (2026-09-24) — Шапка standalone: начертание бренда normal, починка теста, ссылка логотипа и бренда на главную

### Постановка

Синхронизация до c7d8344 (по прямому указанию тимлида; AGENTS.md разрешает
sync/clone по указанию). Заменить шрифт «CISStat TS Analysis» на normal,
починить тест apps/standalone/components/ProductHeader.test.tsx, поставить
ссылку на главную https://ts-standalone.vercel.app/ при клике на логотип И
на бренд. ZIP по результатам — в download. Без commit/push (AGENTS.md).

### Синхронизация и фактура

- main: 0a4252b → c7d8344. Новые коммиты: 626487e — BRND-1 (моя задача:
  ProductHeader.tsx/.test.tsx, spec_progress.md, запись worklog8 — включена
  тимлидом в коммит) и c7d8344 — правка тимлида font-bold → font-semibold
  в компоненте и первом тесте.
- Локальный незакоммиченный онбординг-запись worklog8 восстановлена после
  ff-pull (на удалении её нет); локально устаревшие правки ProductHeader
  (font-bold) отброшены в пользу состояния c7d8344.
- Найденная поломка: на дереве c7d8344 сьют «brand keeps its font identity
  and color» требует font-bold, а компонент после правки тимлида —
  font-semibold → тест падает (подтверждено прогоном). Это и есть тест,
  который поставлено починить.

### Проектирование (точки изменения, риски)

- Точка изменения та же: apps/standalone/components/ProductHeader.tsx +
  его тест. Связка «логотип → бренд» в репо единственная (проверено в
  BRND-1; layout.test.tsx брендовые классы не проверяет).
- Решение: (1) font-normal вместо font-semibold — начертание normal;
  <strong> сохранён как семантический акцент, визуальный вес задаёт
  класс; кегль 28px, tracking-tight, leading-none, text-brand — без
  изменений (постановка касается только начертания). (2) Логотип и бренд
  обёрнуты в ОДНУ ссылку <a href="https://ts-standalone.vercel.app/">
  — стандартный паттерн «лого ведёт на главную», покрывает оба клика
  из постановки; геометрия flex items-center gap-2 перенесена с div на
  <a> без изменений. Обычный <a> с явным URL (не next/link): адрес
  внешний абсолютный по постановке, клиентская навигация не требуется.
  aria-label «CISStat TS Analysis — на главную» — внятное имя ссылки и
  устранение дублирования alt логотипа с текстом бренда для скринридера.
- Риски: (1) сломанный тест-гарант на c7d8344 — обновлён под BRND-2;
  (2) дублирование accessible name у ссылки — закрыто aria-label;
  (3) потеря кликабельной зоны навигации — нет: обёртка не меняет
  раскладку flex-строки шапки; (4) JIT font-normal — content-scan
  включает components/**, верифицировано по собранному CSS.

### TDD

RED: ProductHeader.test.tsx — тест кегля переписан под normal
(font-normal, не font-semibold/font-bold), гарант переименован в
«brand keeps its color; weight is normal (BRND-2)», + 2 новых теста
ссылки (логотип и бренд внутри одной <a> с href
https://ts-standalone.vercel.app/; accessible name ссылки). Прогон:
4 failed / 7 passed — RED подтверждён.
GREEN: ProductHeader.tsx — font-semibold → font-normal; блок логотип+
бренд обёрнут в <a>; комментарий задачи в шапке файла. Прогон: 11/11.

### Верификация и сборка

- Полный jest: 135 сьют / 1565 тестов — все зелёные.
- typecheck standalone (tsc --noEmit) — чисто.
- next build (production) — успешно, 18/18 страниц; в собранном CSS есть
  font-weight:400 (font-normal), font-size:28px, letter-spacing:-.025em;
  в prerender-HTML главной — href="https://ts-standalone.vercel.app/",
  aria-label="CISStat TS Analysis — на главную",
  класс "font-normal tracking-tight" у бренда.

### Deliverable

ZIP: cisstat-brand-normal-home-link.zip — 3 файла (пути репозитория
сохранены): apps/standalone/components/ProductHeader.tsx (изменён),
apps/standalone/components/ProductHeader.test.tsx (изменён),
worklog/worklog8.md (изменён — эта запись). Без commit/push (AGENTS.md).

---

## Task ID: PROGR-2 (2026-09-24) — Граф пайплайна pipeline_graph.py + PipelineNodeState + свёртка статусов §12 п.10 + вынос EDA CHECKS в общий JSON §12 п.2
Синхронизация: main@0a4252b (рабочее дерево с незакоммиченными правками текущей задачи; commit/push запрещены AGENTS.md).

### Постановка
Реализовать вторую задачу плана plan_progress.md: единый граф узлов 6 стадий (spec_progress.md §2), модель узла PipelineNodeState (§3), свёртка статусов в 3 визуальных состояния (§12 п.10), опциональный §12 п.2 плана — EDA CHECKS из TsAnalysisEDA.tsx в общий JSON (рекомендация «вынести сейчас», включена в объём по постановке тимлида). TDD RED→GREEN по AGENTS.md; проверка реализованного кода PROGR-1 (trace_events.py) как основания: KNOWN_STAGES отложила инвариант STAGES-равенства в тест PROGR-2 — инвариант включён в сьют.

### Проектирование
Направление зависимостей — по риск-таблице плана: pipeline_graph → реестры Python-модулей (идентичность объектов is, не копия), инвариант STAGES == session_store.STAGES == trace_events.KNOWN_STAGES — тестом, не взаимным импортом (защита от цикла при подключении хука трассы в PROGR-3). EDA-id — из общего JSON shared/pipeline_nodes/eda_checks.json (§12 п.2), чтение fail-closed на импорте: битый/неполный реестр не даёт графу стартовать с частичной картиной. Классификация стадий: проверочные (CheckStatus) upload/validation/preprocessing/eda — upload по факту UPLOAD-1 (done/warning/pending — подмножество CheckStatus, StageStatus не выразил бы warning); процессные (StageStatus) modeling/forecasting. mode (auto/enabled/disabled) — только Валидация/Предобработка (§3 «где применимо»). Свёртка §12 п.10: warning/error (где угодно) → attention; все done → passed; done+skipped (есть хотя бы один done) → passed; started-признак (running/in_progress/partial done) → attention; пусто/все pending или skipped → not_started. Извлечение CHECKS из .tsx — дословно (скрипт миграции scripts/progr2_extract_eda_checks.py): ни одна видимая строка фронтенда не изменилась.

### TDD
RED: tests/api/test_pipeline_graph.py — ModuleNotFoundError подтверждён. GREEN: app/core/pipeline_graph.py (STAGES/STAGE_NODES/TOTAL_NODE_COUNT/EDA_CHECK_DEFS/EDA_STAGE_IDS, iter_all_nodes, is_known_node, frozen PipelineNodeState с валидацией в post_init — в т.ч. при прямом конструировании, фабрика make_node_state — паттерн make_trace_event, fold_status_values/fold_stage_status). Итерации по своим падениям: (1) all-skipped сначала дал passed — исправлено: skipped не заменяет пройденность, без одного done стадия «не начата»; (2) мутационный анализ вскрыл дыру «вшитая копия вместо чтения JSON» и кейс warning-only — добавлены subprocess reload-тест подмены файла (sha256-верификация восстановления) и warning/error-only-кейсы. Сьют: 144 теста (граф 17, общий JSON 7+5 загрузчик, узел 26, фабрика 3, свёртка ~40 + параметризация 46 узлов и 2×10 позиций проблемы).

### Верификация (свои данные)
Оракулы (scripts/progr2_oracles.py, независимая кодировка §2/§3/§12): 48/48 — граф/идентичность реестров/модель узла/полная матрица свёртки/структура JSON.
Мутационный прогон (scripts/progr2_mutations.py): 11/11 KILLED, 0 survived (precedence warning, границы skipped/пусто, потеря узла, копия вместо импорта, вшитая копия EDA, mode/счётчик-гейты, перестановка STAGES, частичная работа, дубликаты id); sha256 модуля после прогона совпадает.
Потребители PROGR-1: test_trace_events.py + test_forecasting_session.py — 46/46.
Полный tests/api: 883 passed / 3 failed — три падения дословно повторяют предсущественный средовой baseline PROGR-1-CERT (modeling_workflow catalog-only, neural_capacity память хоста, models_candidates unsupported-гейт); новых падений нет.
Frontend: полная регрессия 136 сюит / 1563 теста — зелёные (EDA-сьют 41/41, новый packages/ui/eda-checks-json.test.ts 4/4); typecheck:all (embedded+standalone) чисто; next build standalone — успешно (JSON-импорт работает в webpack-сборке).
Средовое восстановление контейнера: apps/api/requirements.txt + pandera/fakeredis/syrupy/httpx; statsmodels поднят 0.14.5→0.15.0 (падения 16 прогнозных E2E — средовые, чек-лист R5 PROGR-1-CERT).
Deliverable
ZIP: cisstat-progr2-pipeline-graph.zip — пути репозитория сохранены. НОВЫЕ: app/core/pipeline_graph.py, shared/pipeline_nodes/eda_checks.json, tests/api/test_pipeline_graph.py, packages/ui/eda-checks-json.test.ts, scripts/progr2_extract_eda_checks.py, scripts/progr2_oracles.py, scripts/progr2_mutations.py. ИЗМЕНЁННЫЕ: packages/ui/components/TsAnalysisEDA.tsx (вшитый CHECKS-литерал заменён импортом общего JSON — §12 п.2), jest.tsconfig.json (+resolveJsonModule), plan_progress.md (статус §5), worklog/worklog8.md (эта запись). Без commit/push (AGENTS.md).

Границы задачи: session.stages не тронут (§3.1); forecasting-узлы в графе есть (категория A §11 — строится сразу), потребители статусов и UI-панель — PROGR-3/PROGR-4; frozenset-мутации статусов не допускаются снаружи (кортежи/фрозенсеты).

---

## Task ID: PROGR-2-CERT (2026-09-24) — Независимая сертификация Task PROGR-2 (граф пайплайна: pipeline_graph.py + PipelineNodeState + свёртка §12 п.10 + EDA JSON §12 п.2)
Синхронизация: main@4467fae (ff-pull с 0a4252b; по указанию тимлида). Акт: docs/cert_progr2_pipeline_graph_2026-09-24.md.

### Постановка
Честная независимая сертификация задачи PROGR-2 из plan_progress.md, выполненной коллегой (commit 4467fae): воспроизведение заявлений исполнителя, изучение живой кодовой базы, кросс-верификация реестров по живым модулям, независимые оракул- и мутационные тесты на СВОИХ данных аудитора. Методика — по прецедентам PROGR-1-CERT / Task 144 / FORECAST-1; правила AGENTS.md (TDD-цикл исполнителя проверен post-hoc, commit/push запрещены).

### Воспроизведение заявлений исполнителя (8/8 ПОДТВЕРЖДЕНО)
144/144 test_pipeline_graph.py; оракулы 48/48; мутации 11/11 KILLED + sha256 восстановления; потребители PROGR-1 46/46; полный tests/api 883 passed / 3 failed — все 3 падения воспроизведены на 0a4252b git-worktree-прогоном (предсущественный средовой baseline: modeling_workflow catalog-only, neural_capacity память хоста, models_candidates unsupported-гейт) — новых падений нет; EDA-сьют 41/41; полный jest 135 сюит / 1565 тестов зелёные; typecheck:all (embedded+standalone) чисто. Среда по чек-листу R5 PROGR-1-CERT (prophet 1.4.0, statsforecast 2.1.1, xgboost 2.1.3, lightgbm 4.5.0, catboost 1.2.8, statsmodels 0.14.5→0.15.0); без манифеста — 54 ошибки коллекции (гейт «реестр↔dispatch»), что расширяет симптоматику R5.

### Кросс-верификация по живым модулям (27/27, scripts/progr2cert_crossverify.py)
Ожидания читаются из живых исходников regex-ом, не через граф: STAGES == session_store.STAGES == trace_events.KNOWN_STAGES; три Python-реестра дословно равны своим веткам STAGE_NODES; CheckStatus/StageStatus графа дословно равны StatusIcon.tsx / stages.ts; идентичность объектов is (§2 «не дублирует, а ссылается») подтверждена для всех трёх реестров; направление зависимостей «граф → реестры» соблюдено (риск-таблица плана); 10 узлов eda_checks.json ДОСЛОВНО (id/label/description) равны прежнему CHECKS-литералу TsAnalysisEDA.tsx@0a4252b — рефакторинг не изменил ни одного видимого текста; рантайм-маппинг .tsx покрывает все 10 id.

### Оракулы аудитора на своих данных (30/30, scripts/progr2cert_oracles.py)
Своя кодировка, seed 20260924, свои probe-реестры: G — reference-фаззинг свёртки (независимый ref_fold по докстрингу, 3000 случайных наборов, 0 расхождений; порядок-инвариантность и детерминизм по 500; только 3 визуальных состояния на всех комбинациях алфавита 0–4); H — полная негативная матрица узла (46 узлов × чужие статусы, замороженность всех 7 полей, eq/hash, границы summary_count, mode-гейты стадии И значения, валидация прямого конструирования — 6 кейсов); I — граф (8 своих негативных пар, 46 пар известны, кросс-стадийные дубликаты ровно regularity/stationarity, 46=1+10+10+10+11+4, passport отсутствует); J — загрузчик JSON на своих probe-файлах (7 узлов с unicode дословно; битый/отсутствующий JSON, nodes-не-список, пустой label/id из пробелов, stage=upload — каждый fail-closed); K — §12 п.10 на реальных стадиях (warning/error на любой позиции всех 6 стадий ×2 типа; метаданные не влияют на fold).

### Мутационный прогон аудитора (scripts/progr2cert_mutations.py)
Дизъюнктный набор к 11 мутантам исполнителя: 12 реальных мутантов × 3 детектора (сьют исполнителя, его оракулы, мои оракулы). Итог: 12/12 KILLED — все независимые мутации ловятся сьютом ИСПОЛНИТЕЛЯ, детекционная сила подтверждена извне. CERT-E01 (удаление import-гейта STAGE_NODES vs STAGES) — ожидаемый эквивалентный survivor: защитная ветка недостижима через публичный API (pragma: no cover честна). Границы собственных оракулов: CERT-M06 не пойман моими оракулами (покрыт сьютом/оракулами исполнителя); CERT-M02/M03/M11 не ловились оракулами исполнителя (ловились его сьютом).

### Находки (полный акт: docs/cert_progr2_pipeline_graph_2026-09-24.md)
F-1 (Средняя, интеграция): packages/ui/eda-checks-json.test.ts ОТСУТСТВУЕТ на main@4467fae — заявлен в deliverable и «4/4» в записи PROGR-2, в коммит не вошёл, в дереве нет; согласуется с расхождением счётчиков jest (заявлено 136/1563, фактически 135/1565). Защитная сеть не пуста: бэкенд-тесты test_eda_tsx_imports_shared_json / test_eda_tsx_maps_every_json_id и мои F1–F4 покрывают те же маркеры; тем не менее 4 фронтенд-теста утрачены при интеграции — включить файл из ZIP cisstat-progr2-pipeline-graph.zip ближайшим коммитом.
F-2 (Инфо): jest.tsconfig.json (+resolveJsonModule) тоже не интегрирован и эмпирически не нужен (moduleResolution: bundler допускает JSON-импорт; EDA 41/41, jest весь зелёный, typecheck:all чисто). Действий нет.
R-2 (Инфо): счётчики jest записи PROGR-2 арифметически не восстанавливаются (1563 ≠ 1565+4); вероятен подсчёт на промежуточном дереве; на вердикт не влияет.
R-3 (Инфо, среда): чек-лист R5 подтверждён и дополнен признаком «без API-манифеста — 54 ошибки коллекции tests/api».
Вердикт
PASSED WITH REMARKS. Реализация PROGR-2 соответствует канону spec_progress.md §2/§3/§12 п.2/§12 п.10 и плану; все заявления исполнителя воспроизведены; код задачи замечаний не имеет. Замечания — интеграционные/книгопроводные (F-1, F-2, R-2), кода не касаются. Блокеров для PROGR-3 нет.

---

## Task ID: PROGR-3 (2026-09-24) — Внутрисессионный слой трассы (§5 слой 1) + хук записи событий (§4.2)

Синхронизация: main@b83120a (PROGR-2-CERT PASSED WITH REMARKS; commit/push запрещены AGENTS.md).

### Среда (откат контейнера и восстановление)

Контейнер между сессиями откатился к снапшоту: HEAD съехал с 0a4252b на 29d84a8, все
незакоммиченные артефакты (включая deliverable предыдущей сессии и node_modules/python-зависимости)
утрачены. Восстановлено до начала PROGR-3: переключение на b83120a (PROGR-2 интегрирован
тимлидом: 4467fae реализация, 30b5cca FIX, b83120a сертификация); python-среда по чек-листу
R5 (pandera, fakeredis, syrupy, httpx, PyWavelets, ruptures, prophet 1.4.0, statsforecast
2.1.1, xgboost 2.1.3, lightgbm 4.5.0, catboost 1.2.8, statsmodels>=0.15.0); npm install.
Реконструкция затронутых откатом файлов PROGR-2 (shared/pipeline_nodes/eda_checks.json —
дословно по сохранённому содержимому; packages/ui/eda-checks-json.test.ts — по контракту
«4/4» записи PROGR-2) подтверждена сертификацией F-1/F-2: файл вошёл в b83120a, тесты зелёные.

### Постановка

Третья задача plan_progress.md: слой 1 персистентности (§5) — AnalysisSession.pipeline_trace
(внутрисессионный буфер, TTL = TTL сессии, без изменений архитектуры) + run_id (§5, не
session_id); хук записи событий (§4.2) — таблица маршрутов путь→(stage, node_id, event_type),
события на успешных ответах, profile_viewed троттлится (дефолт 5 мин, env-переменная);
граница чтения трассы нормализует stored-события (риск-таблица: Redis-сессии со старыми
3-польными записями). Приёмка: correction_applied/mode_changed/... на успешных ответах;
profile_viewed троттлится; run_id фиксируется при первой загрузке. Адресуются замечания
PROGR-1-CERT R1–R4.

### Проектирование

Интеграция — из двух вариантов §4.2 («FastAPI Depends или dispatch-middleware») выбран чистый
ASGI-middleware: только он видит финальный response.status_code И тело ответа, а §4.1 требует
payload из формы ответа (applied/strategy/total_changed — факты результата, не запроса).
«Точечные включения в роутеры» из плана реализованы как точечный список маршрутов в таблице
TRACE_ROUTES (40 записей): роутер-файлы не правятся вовсе, что дословно соответствует §4.2
«не требует правки каждого из уже существующих роутов вручную»; отклонение от буквального
прочтения плана зафиксировано здесь. Таблица fail-closed на импорте (_validate_table): невалидная
пара (stage, event_type), неизвестный узел графа, дубликат маршрута, трассируемый forecasting
или throttled не-profile_viewed — ImportError (паттерн pipeline_graph). Прогнозирование
исключено: 4 call-site make_trace_event (PROGR-1) уже пишут канонические события в
ForecastRun.trace — дубли в слой 1 не создаются, унификация — PROGR-5. Разбиение
preview/apply — по applied В ОТВЕТЕ (все 20 correction-эндпоинтов возвращают applied: bool,
проверено по схемам) — тело запроса хук не читает вовсе. payload — белый список ключей ответа
(§4.1: факты, не сырой ответ; тяжёлые columns/profile отсечены). Throttle — per (event_type,
node_id), окно из PROGRESS_PROFILE_VIEWED_THROTTLE_SECONDS на вызов, битое → 300, ≤0 → выключен.
run_id — "RUN-XXXXXXXX" (uuid4.hex[:8].upper(), человекопроизносимый §5.3), ensure_run_id()
идемпотентен, вызывается хуком при записи при активном датасете; set_dataset() сбрасывает
run_id и pipeline_trace (новый датасет = новое исследование §3.1); первая трассируемая
успешная загрузка и есть фиксация (Set-Cookie fallback в middleware — cookie ещё нет в запросе).
Cap буфера MAX_PIPELINE_TRACE_EVENTS=1000, вытеснение старейших (§5 «короткий буфер» + защита
Redis-документа). Рантайм-политика двухконтурная: контракт таблицы — fail-closed на импорте,
IO-сбои хранилища — warning без поломки ответа (трасса вспомогательна). SESSION_SCHEMA_VERSION
1→2 (+run_id, +pipeline_trace), чтение полнo совместимо. R1: глубокая копия payload в
append_trace_event. R2: legacy-маркер приоритетнее явной stage — поведение зафиксировано
тестом как осознанное решение. R3: event_type на чтении не валидируется (аудит), тестом.
R4: живые дефолты TraceEvent покрыты тестом прямого конструирования.

### TDD

RED: tests/api/test_progress_trace_hook.py — ImportError подтверждён. GREEN:
apps/api/trace_hook.py (TraceRouteSpec, TRACE_ROUTES 40, resolve_trace_route по сегментам,
throttle_seconds_from_env, record_trace_event, TraceHookMiddleware, _validate_table),
apps/api/session_store.py (+run_id, +pipeline_trace, ensure_run_id, append_trace_event,
read_pipeline_trace, сериализация, сброс в set_dataset), apps/api/main.py (регистрация
middleware ДО CORS — CORS остаётся внешним слоем). Итерации по своим падениям: (1) target-column
живёт на /v1/session/target-column (роутер объявляет "/target-column" без /dataset) — таблица
и тесты исправлены; (2) коллизия ключа payload с именованными параметрами фабрики (ответ
паспорта содержит "stage") — **payload дал TypeError; payload присоединяется dataclasses.replace
к базовому событию make_trace_event (гейт сохранён, факты не теряются); (3) ответ check-modes —
ЭФФЕКТИВНЫЕ режимы, не частичная правка — тест проверяет факт ranges=enabled в эффективном
словаре; (4) monkeypatch класса save требует self. Сьют: 40 тестов (таблица 6, резолвер 5,
session_store 8, граница чтения 5, R4 1, интеграция 10, троттлинг 5).

### Верификация (свои данные)

- Оракулы (scripts/progr3_oracles.py, независимая перекодировка §4.1/§4.2/§5): 12/12 —
  таблица против собственного справочника 40 маршрутов, валидность пар по реестру, свой
  матчер шаблонов, белый список payload, preview/apply-семантика, фиксация run_id
  (без датасета/первая загрузка/новый датасет), арифметика окна 5:00 + пер-узловость,
  env-семантика, модель вытеснения cap, нормализация legacy→канон 8+1, порог успеха <400,
  JSON-раундтрип stored-формы.
- Мутационный прогон (scripts/progr3_mutations.py): 13/13 KILLED, 0 survived (потеря гейта
  успеха, перевёрнутое окно, инверсия preview/apply, отказ фиксации run_id, потеря
  Set-Cookie fallback, матчер без метода, payload-весь-ответ, подмена узла, невалидная пара
  → ImportError import-гейта, R1-копия, вытеснение новых, падение на битой записи,
  неидемпотентность run_id); sha256 обоих файлов после прогона совпадает.
- Полный tests/api: 923 passed / 3 failed — три падения дословно повторяют средовой baseline
  PROGR-2-CERT (modeling_workflow catalog-only, neural_capacity память хоста, models_candidates
  unsupported-гейт); новых падений нет. Якорь схемы test_session_store сознательно переведён
  на SESSION_SCHEMA_VERSION == 2 (с_comment PROGR-3); связка session_store + trace_events +
  forecasting_session + pipeline_graph: 272 passed.
- Потребители графов: test_pipeline_graph.py в связке зелёный — направление зависимостей
  trace_hook → pipeline_graph → реестры циклов не создало (session_store импортирует
  trace_events — безопасно: KNOWN_STAGES локальна, PROGR-1).

### Deliverable

ZIP: cisstat-progr3-trace-hook.zip — пути репозитория сохранены. НОВЫЕ:
apps/api/trace_hook.py, tests/api/test_progress_trace_hook.py, scripts/progr3_oracles.py,
scripts/progr3_mutations.py. ИЗМЕНЁННЫЕ: apps/api/session_store.py (слой 1: run_id,
pipeline_trace, ensure/append/read, сериализация, сброс set_dataset, схема 1→2),
apps/api/main.py (регистрация TraceHookMiddleware), tests/api/test_session_store.py (якорь
схемы 2), plan_progress.md (статус §5), worklog/worklog8.md (эта запись). Роутеры не правились
(§4.2, единая точка интеграции). Без commit/push (AGENTS.md).

Границы задачи: чтение трассы наружу (эндпоинт панели) — PROGR-4; долговременный слой
research_runs/trace_events, чекпоинты/пауза/restore и перенос run_id в Postgres — PROGR-5;
трасса слоя 1 не содержит forecasting-событий (живут в ForecastRun.trace до унификации PROGR-5);
passport_captured пишется хуком, но узлом графа паспорт не является (§2).

---

## Task ID: PROGR-3-CERT (2026-09-24) — Независимая сертификация Task PROGR-3 (слой 1 трассы §5 + хук записи событий §4.2)

Синхронизация: main@38f1cb9 (ff-pull с 4467fae; по указанию тимлида). Акт: scripts/audit_scripts/cert_progr3_trace_hook_2026-09-24.md.

### Постановка

Честная независимая сертификация задачи PROGR-3 из plan_progress.md, выполненной коллегой (commit 38f1cb9): воспроизведение заявлений исполнителя, кросс-верификация по живым роутерам/схемам/main.py, независимые оракул- и мутационные тесты на СВОИХ данных аудитора (свой мини-ASGI-стенд, свой FakeStore, свой сид). Методика — по прецедентам PROGR-1-CERT / PROGR-2-CERT; правила AGENTS.md (commit/push запрещены).

### Воспроизведение заявлений исполнителя (8/8 ПОДТВЕРЖДЕНО)

40/40 test_progress_trace_hook.py; с session_store 122/122; оракулы исполнителя 12/12; мутации исполнителя 13/13 KILLED (повторный прогон, файлы восстановлены); связка store+events+forecasting+graph 272 (=312 с хук-сьютом минус 40 — арифметика сходится); полный tests/api 923 passed / 3 failed — те же три средовых baseline PROGR-2-CERT (modeling_workflow catalog-only, neural_capacity память хоста, models_candidates unsupported-гейт), новых падений нет; якорь SESSION_SCHEMA_VERSION == 2 (test_session_store.py:726); F-1/F-2 сертификации PROGR-2-CERT интегрированы на main — eda-checks-json.test.ts + resolveJsonModule, EDA-сьюты jest 45/45. Среда по чек-листу R5 (statsmodels 0.15.0).

### Кросс-верификация по живым исходникам (21/21, scripts/audit_scripts/progr3cert_crossverify.py)

Ожидания читаются из живых файлов, не из хука: все 40 шаблонов таблицы разрешаются ровно в один живой маршрут с тем же методом (включая target-column БЕЗ /dataset и {stage} паспорта); пары (stage, event_type) валидны по живому STAGE_EVENT_TYPES+RUN_LEVEL; узлы известны графу; forecasting вне таблицы (все 4 изменяющих forecasting-эндпоинта); throttled только у profile_viewed и все GET-строки троттлируются; env-имя/дефолт 300 с §4.2; заявление «все 20 correction-эндпоинтов возвращают applied: bool» верифицировано по живым pydantic-схемам; §3.1 — хук не трогает session.stages; ни один роутер не изменён коммитом 38f1cb9; схема v2/cap 1000/STAGES-инвариант; TraceHookMiddleware в main.py ДО CORS; set_dataset сбрасывает run_id+trace; сериализация/чтение с фильтром мусора.

### Оракулы аудитора на своих данных (12/12, scripts/audit_scripts/progr3cert_oracles.py)

Своя кодировка, свой мини-ASGI-стенд с FakeStore, свои метки времени: A — статус-гейт через ЖИВОЙ middleware (200/204/399 пишутся, 400..503 нет — граница 399/400 на реальном ASGI-стеке); B — preview/apply identity-семантика `is False` (False→previewed; True/None/0/"false"/нет ключа→applied); C — payload-белый список (тяжёлое отсечено, отсутствующее опущено) + коллизия payload["stage"] паспорта снята replace-ом (TypeError невозможен, факты тела сохранены, event.stage="eda"); D — окно 299.5/300/300.5 (строгое <), naive-ts→UTC, битый ts→write, пер-узловость/пер-типовость; E — env 9 кейсов (нет→300, 0/-5→выкл, abc/5.5→300, " 600 "→600); F — run_id lifecycle (без датасета не фиксируется; RUN-[0-9A-F]{8}; идемпотентен; set_dataset→сброс, новый≠старый); G — cap (свои 8 событий при cap=5 → хвост [3..7]) + R1-копия глубока (мутация источника после append не меняет stored); H — свой legacy-корпус (маркер>stage R2, чужой event_type сохранён R3, skip-деградация, чтение не мутирует stored, run_id-фоллбек); I — документы v1→дефолты, v2 раундтрип точен, мусор фильтруется, v3-вперёд не падает; J — интеграция: первая загрузка через Set-Cookie fallback фиксирует run_id, троттлинг сквозь стенд, ответ клиенту не искажается, не-матчящий запрос молчит, неизвестная сессия — тихий пропуск; J2 — исключение хендлера пробивается наружу, трасса не засорена; K — матчер ({stage} непустой, метод строг, трейлинг-слэш/лишний сегмент→None, параллельные ветки regularity не путаются).

### Мутационный прогон аудитора (scripts/audit_scripts/progr3cert_mutations.py)

Дизъюнктный набор к 13 мутантам исполнителя: 12 мутантов × 3 детектора (сьют исполнителя, его оракулы, мои оракулы). Итог: 11/12 KILLED. Пять мутантов убиты всеми тремя детекторами (env-гейт, payload-присоединение, run_id set_dataset/сериализация, KeyError-обработка). Дыры сьюта исполнителя, закрытые только оракулами: CERT-M1 (граница ровно 400 — их неуспешные кейсы 404/409/422) и CERT-M5 (пустой сегмент {param}); дыры оракулов исполнителя, закрытые сьютом/моими: CERT-M2/M6/M7/M10. CERT-M12 (удаление import-гейта запрета forecasting) — SURVIVED 0/3, охарактеризован: на текущей таблице поведение не меняется (эквивалент), но защитная ветка контракта лишена теста-нарушения (аналог CERT-E01 PROGR-2-CERT); рекомендация — тест с пробной forecasting-строкой → ImportError.

### Находки (полный акт: scripts/audit_scripts/cert_progr3_trace_hook_2026-09-24.md)

- **F-1 (Low, тест-контур): import-гейт запрета forecasting не покрыт тестом-нарушением** (CERT-M12 survivor 0/3). Защитная ветка жива и корректна на текущей таблице; не покрыт сам гейт. Рекомендация: 5-строчный тест с пробной таблицей → ImportError. Не блокер.
- **R-1 (Info):** общий payload-кортеж `_CORRECTION_PAYLOAD_KEYS` содержит «мёртвые» ключи для каждой из 20 correction-строк (convert-types 7/11, feature-generations 9/11) — опускаются рантаймом, §4.1 не нарушено, но таблица завышает ожидания о составе payload.
- **R-2 (Info):** 19 изменяющих сессионных эндпоинтов без канонического типа §4.1 не трассируются (date-column, validation-rules, type-schema, stage/{stage}; modeling: compare, selection/evaluate, candidates, baselines, backtest/exclude, tuning/skip×2, jobs×3, diagnostics×2, feature-regressors) — по букве §4.1 (закрытый реестр); «решенческие» факты этих шагов в трассу слоя 1 не попадают; расширение реестра STAGE_EVENT_TYPES — задел PROGR-5+.
- **R-3 (Info):** граница гейта (статус ровно 400) не покрыта сьютом исполнителя — ловится оракулами (их O11 + мой OR-A через живой middleware).
- **R-4 (Info):** legacy-записи без event_id регенерируют id при каждом чтении (from_dict-дефолт); семантика стабильна, stored не мутируется; учесть при экспорте/чекпоинтах (PROGR-5): backfill id при записи либо детерминированный id.

### Вердикт

**PASSED WITH REMARKS.** Реализация PROGR-3 соответствует канону spec_progress.md §4.1/§4.2/§5 и плану: единая точка интеграции (ASGI-middleware, роутеры не тронуты), события только на успешных ответах, payload — факты ответа, preview/apply по applied в ответе, троттлинг profile_viewed (env, 300 с), run_id фиксируется при первой загрузке (Set-Cookie fallback), буфер 1000 с вытеснением старейших, глубокая копия payload (R1), нормализующая граница чтения (R2/R3 зафиксированы), схема 1→2 с обратной совместимостью, session.stages не тронут, forecasting не дублируется. Все заявления исполнителя воспроизведены; 21/21 кросс-верификация; 12/12 оракулов аудитора; мутации 11/12 (+1 охарактеризованный survivor). Находки F-1, R-1–R-4 не блокируют; блокеров для PROGR-4/PROGR-5 нет.

### Deliverable

ZIP: cisstat-progr3-cert-trace-hook.zip — пути репозитория сохранены. НОВЫЕ: scripts/audit_scripts/cert_progr3_trace_hook_2026-09-24.md (акт), scripts/audit_scripts/progr3cert_crossverify.py, scripts/audit_scripts/progr3cert_oracles.py, scripts/audit_scripts/progr3cert_mutations.py. ИЗМЕНЁННЫЕ: worklog/worklog8.md (эта запись). Без commit/push (AGENTS.md).

---

## Task ID: PROGR-4 (2026-09-25) — UI-панель «Прогресс» + кнопка-триггер (аддендум §4.1–4.2)

Синхронизация: main@47a33eb (ff-pull с 38f1cb9; в 47a33eb вошла интеграция PROGR-3-CERT — аудиторские скрипты и запись worklog8, локальные копии удалены как идентичные). Правила AGENTS.md: TDD RED→GREEN, без commit/push, ZIP в download.

### Постановка

Реализация Task PROGR-4 из plan_progress.md: правая выдвижная панель «Прогресс» (§6.1–6.2 spec_progress.md) + pill-кнопка-триггер по контракту аддендума §4.1–4.2; атомарное удаление EventsLogDrawer/AppShellContext.log (§6.1, риск-таблица плана); jest-сьюты зелёные, typecheck/build чисто.

### Ключевые решения

- **Чтение трассы слоя 1 (новый минимальный бэкенд).** PROGR-3 дала только запись, а шапке §6.1 нужен run_id («новое, см. §5») и «Начат N мин назад», §6.2 — хронологический список событий. Добавлен ровно один читающий эндпоинт GET /v1/progress/trace (namespace /v1/progress/* — канон §5; apps/api/routers/progress.py + регистрация в main.py): run_id (честный null без датасета), started_at (ts первого события — аналог created_at слоя 1), events (канон §4.1 через read_pipeline_trace — нормализация legacy на границе, решения R2/R3). Эндпоинт вне TRACE_ROUTES — ридер трассы сам не трассируется.
- **Статусы узлов из фактов трассы (§4.1).** Слоя профильных опросов 46 узлов панель не делает (§4.2 разрешает опрашивать только видимые, но маппинг ~30 гетерогенных ответов — отдельная работа). Честный источник MVP: трасса. Терминальные события (upload_completed/correction_applied/backtest_run/tuning_trial_completed/model_selected/model_card_generated/forecast_*) → done; correction_previewed → warning («найдены проблемы»: preview показывается только при найденных нарушениях, решение не принято); profile_viewed → running. Последнее событие узла выигрывает. События уровня стадии (node_id=null) и неизвестные типы — мимо узлов (фантомов нет).
- **Прогнозирование — из ForecastRun.trace (§3 дословно: статус «по факту наличия ForecastRun/конкретных trace_events»).** Слой 1 forecasting-событий не содержит (решение PROGR-3, унификация PROGR-5), поэтому панель досчитывает их из живого GET /v1/session/modeling/forecast (ForecastTraceEventSchema: legacy event_type/timestamp/payload → ts/stage/node_id=event_type).
- **Свёртка §12 п.10** — точный TS-порт fold_status_values (pipeline_graph.py), застрахован зеркальной таблицей кейсов; карточка: bg-green-50 / bg-amber-50 / нейтральная, иконка StatusIcon как есть, текст «N/total, найдены проблемы | в работе | пройдено | не начато».
- **Реестр узлов фронтенда** (packages/ui/lib/progress.ts, 46 узлов): 5 стадий текстовой копией, EDA — из общего JSON §12 п.2 (без дубля); sync-тест tests/api/test_progress_panel.py читает живой .ts (паттерн test_eda_tsx_imports_shared_json): 5 стадий дословно с STAGE_NODES, для eda — маркер импорта общего JSON (паритет JSON↔граф уже страхует сюит PROGR-2). Метки узлов — из CHECK_META/мета-степперов/PIPELINE_STAGES/общего JSON.
- **Кнопка-триггер** — построчно по аддендуму §4.1: BADGE_BASE-геометрия (rounded-full, h-9, px-3/[13px] → lg:px-4/sm), неактивная bg-white+border border-brand (тонкая, без border-2)+text-brand; активная bg-brand+text-white+**font-semibold** (не font-medium — осознанное отличие §4.1); aria-expanded/aria-controls="progress-drawer", focus-visible ring, иконка Workflow в слоте ScrollText. Toggle-поведение (повторный клик закрывает).
- **Атомарное удаление лога (§6.1):** EventsLogDrawer.tsx удалён; из AppShellContext удалены log/addLogEntry/clearLog (+LogEntry), добавлен targetColumn из GET /current (шапка §6.1: «поле есть — новых данных не требуется», optional в контракте для частичных моков); вызовы addLogEntry в TsAnalysisUpload (2) и TsAnalysisForecasting (5) убраны: факты решений — в бэкенд-трассе (§4.2/PROGR-1), ошибки — инлайн/тосты вкладок. Кнопки «Пауза»/«Сохранить точку»/«Наставник» — не в объёме PROGR-4 (PROGR-5/6; без бэкенда были бы мёртвыми).
- **Контент панели монтируется с первого открытия** (hasOpened): закрытая панель не дублирует тексты стадий рядом с бейджами меню (и не гоняет fetch).

### TDD и верификация

- RED: 8 бэкенд-тестов падали (404/нет progress.ts), 29 фронтовых (TS2307/новый контракт) — все по правильным причинам.
- GREEN: tests/api/test_progress_panel.py 9/9 (эндпоинт: пустая сессия, demo→upload_completed+run_id RUN-XXXXXXXX, нормализация legacy на чтении (R2: stage=forecasting; R3: event_type не валидируется), run_id=null без датасета, хронология, эндпоинт вне таблицы хука; sync реестра узлов ×3).
- Jest полный: **140 сюит / 1637 тестов — зелёные** (было 135/1565 в PROGR-2-CERT; +4 новых сюиты, +eda-checks-json.test.ts из F-1 интеграции; обновлены guard-тесты ModuleNav и моки forecasting-тестов).
- tests/api полный: **932 passed / 3 failed** — ровно средовой baseline PROGR-2/3-CERT (modeling_workflow catalog-only, neural_capacity память хоста, models_candidates unsupported-гейт), новых падений нет.
- typecheck:all чисто (embedded+standalone), npm run build:all зелёный.

### Находки/заметки (не блокеры)

- N-1 (Info): краткая подпись карточки считает doneCount строго по done-узлам (образец §6.2 «3/10, найдены проблемы» воспроизводится при done+warning-сочетании; при только-previewed — честное «0/10, найдены проблемы»).
- N-2 (Info): stage-level решения (mode_changed, target_column_changed) не влияют на свёртку стадии (§12 п.10 определён по узлам) — карточка стадии с такими событиями остаётся «не начато», события видны в трассе. Обсудить с тимлидом, нужен ли stage-уровень активности в своде.
- N-3 (Info): в трассе слоя 1 passport_captured пишется на узел None (§2: паспорт — не узел); в трассе панели отображается без узла — корректно, но узловых статусов EDA паспорт не даёт.
- N-4 (Info): переход по deep-link узла не закрывает панель (состояние в ModuleNav живёт поверх смены маршрутов); поведение совпадает с прежним EventsLogDrawer, вопрос UX — на будущее.

### Deliverable

ZIP: cisstat-progr4-progress-ui.zip — пути репозитория сохранены. НОВЫЕ: apps/api/routers/progress.py; packages/ui/lib/progress.ts (+progress.test.ts); packages/ui/components/ProgressDrawer.tsx, ProgressStageFlow.tsx, ProgressTraceLog.tsx (+*.test.tsx); tests/api/test_progress_panel.py. ИЗМЕНЁННЫЕ: apps/api/main.py; packages/ui/components/ModuleNav.tsx, TsAnalysisUpload.tsx, TsAnalysisForecasting.tsx (+forecasting.test.tsx), packages/ui/context/AppShellContext.tsx, packages/ui/index.ts, packages/ui/lib/apiClient.ts, apps/standalone/app/forecasting/page.test.tsx, packages/ui/components/ModuleNav.test.tsx. УДАЛЁННЫЕ: packages/ui/components/EventsLogDrawer.tsx. ИЗМЕНЁННЫЙ: worklog/worklog8.md (эта запись). Без commit/push (AGENTS.md).
