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

---

## Task ID: OUTL-1 (2026-09-25) — Остановка «Выбросы»: границы метода на «Линейном» графике (верифицируемость кэпирования) + ревизионный refresh графиков Обзора

Синхронизация: main@47a33eb (working tree с незакоммиченными правками текущей задачи; commit/push запрещены AGENTS.md).

### Постановка

Воспроизвести и прокомментировать дефект тимлида: демо-датасет forecast_monitor_synthetic_n150.csv → «Предобработка → Выбросы», линейный график показывает 4 выброса, счётчик под графиком «выбросов — 4»; мастер (IQR + кэпирование) → apply; возврат на линейный график — «сам график не изменился», счётчик «выбросов — 0». При необходимости исправить. ZIP в download, AGENTS.md.

### Воспроизведение и диагноз (контрольные замеры ДО правки)

1. **Бэкенд-проба** (scripts/probe_outliers_line_stale.py: TestClient + дословный порт генератора демо-датасета из demoDatasets.ts — mulberry32 + Box-Muller, seed 20260916; структурный контракт сошёлся — IQR находит ровно 4 выброса): POST /dataset/outlier-corrections (cap, apply=true) атомарно обновляет сессию; GET /dataset/outlier-line ПОСЛЕ apply отдаёт ИСПРАВЛЕННЫЙ ряд — 4 точки изменены (260.12→245.84, 261.77→245.84, 267.53→245.84, 58.45→76.56). Бэкенд корректен: stale-данные на сервере исключены.
2. **E2E в браузере** (прод-сборка standalone + локальный API; полный сценарий: загрузка демо → Выбросы → Линейный → мастер → предпросмотр → подтверждение → apply → «Метрики и алгоритм» → Линейный): график перерисовывается новыми данными (ось Y 0–280 → 0–260, путь ряда изменился), счётчик 0. Классический stale-график (не-рефетч/HTTP-кэш) стандартным потоком НЕ воспроизводится.
3. **Корень симптома**: кэпирование прижимает выбросы К границе IQR, а не удаляет их — 4 точки ложатся ровно на границу (245.84/76.56), которая сама далека от типичных значений ряда: шипы остаются визуально доминирующими, «на глаз» график неотличим от исходного, хотя данные изменились. Счётчик «0» честен (значения НА границе методом IQR не обнаруживаются). Дефект — **информативность визуализации**: «Линейный» — единственное из четырёх представлений Обзора, не показывающее границы метода (гистограмма показывает их с Task 65), поэтому результат исправления невозможно верифицировать глазами; ожидание «кэпировал — шипы ушли» против факта «кэпировал — шипы прижаты к границе» не получает визуального объяснения.

### Решение

1. Backend: GET /dataset/outlier-line принимает method (+param_low/param_high по образцу гистограммы, дефолт iqr, неизвестный метод — 422) и отдаёт bounds = method_bounds(series, method, param) — ЕДИНСТВЕННЫЙ источник формулы, переиспользование без дублирования; DatasetOutlierLineResponse +bounds (Optional).
2. Frontend: OutlierLineChart рисует границы горизонтальными ReferenceLine по оси значений (тот же пунктир var(--status-error), что у гистограммы) + подсказка с числами и семантикой «после кэпирования бывшие выбросы лежат на границе — за пунктиром точек нет»; Overview прокидывает method.
3. **Защитный инвариант согласованности** (класс дефекта из постановки): все 4 графика Обзора подписаны на ТЕМ же сигнал обновления, что профиль/счётчик (refreshKey = outliersRefreshKey + datasetVersion) — ревизия включена в query как cache-buster (revision). До правки свежесть графиков держалась на случайном побочном эффекте («loading-flash» профиля перемонтировал их); контракт теперь явный: «счётчик обновился ⟹ графики перезапросились», закрыто окно рассинхрона в любом потоке (медленный apply на проде, промежуточные HTTP-слои).

### TDD (RED → GREEN)

Backend (+4, tests/api/test_dataset_outlier_correction.py): bounds линейного графика == bounds гистограммы на том же ряде; дефолт iqr без явного метода; неизвестный метод 422; после cap нет точек за границами и max ряда == upper (прижатые НА границе). RED: KeyError 'bounds'. GREEN: 7/7 файла.
Frontend: PreprocessingOutliersVisualizations.test.tsx +7 (it.each по 4 графикам: изменение refreshKey при смонтированном графике → перезапрос с revision в URL; границы-пунктир: подсказка с числами; method в URL ряда; нет подсказки при bounds=null); PreprocessingOutliersOverview.test.tsx +1 интеграционный (смонтированный Обзор: bump refreshKey → профиль перезапросился И последний вызов ряда несёт новую ревизию; точное число вызовов ряда не фиксируется — существующий loading-flash даёт дополнительный, отбрасываемый active-guard-ом запрос). RED: TS2322 (method/refreshKey отсутствовали в пропсах) + падения контрактов. GREEN: 22/22 двух сьютов.

### Верификация

- Полная бэкенд-регрессия: 2602 passed / 9 failed — все 9 воспроизведены на чистом baseline 47a33eb прогоном через git stash (без правок задачи): 3 задокументированных средовых (modeling_workflow catalog-only, neural_capacity память хоста, models_candidates unsupported-гейт) + 6 отсутствия нейро-группы (torch/neuralforecast; дизайн допускает хосты без неё, чек-лист R5). Новых падений нет.
- Полный jest: 136 сьют / 1577 тестов — все зелёные (+8 к baseline 47a33eb: 1569 = 1565 PROGR-3-CERT + 4 eda-checks-json).
- typecheck:all (embedded + standalone) — чисто; next build standalone — успешно.
- E2E-верификация фикса (браузер, полный сценарий): до кэпирования — 2 пунктирные границы, шипы ЗА ними (267.53 > 245.84; 58.45 < 76.56); после apply — шипы лежат НА границах, за пунктиром точек нет; счётчики всех поверхностей (шапка Обзора, Metric-карточки под графиком, степпер, правая панель «Проверка пройдена») сходятся в 0.

### Deliverable

ZIP: cisstat-outl1-outlier-line-bounds-refresh.zip — пути репозитория сохранены. ИЗМЕНЁННЫЕ: apps/api/schemas.py, apps/api/routers/session.py, tests/api/test_dataset_outlier_correction.py, packages/ui/components/PreprocessingOutliersVisualizations.tsx, packages/ui/components/PreprocessingOutliersVisualizations.test.tsx, packages/ui/components/PreprocessingOutliersOverview.tsx, packages/ui/components/PreprocessingOutliersOverview.test.tsx, worklog/worklog8.md. НОВЫЕ: scripts/probe_outliers_line_stale.py (проба воспроизведения). Без commit/push (AGENTS.md).

### Границы задачи

- Тот же класс «графики Обзора без явной подписки на refresh» существует на других остановках (Пропуски: матрица/корреляция/boxplot, Регулярность, …) — ревизионный паттерн применён точечно к «Выбросам»; распространение на все Обзоры — отдельная постановка (механика идентична, тест-паттерн it.each готов к переносу).
- «Плотность» не получила границы метода (вне постановки; линейный график — поверхность из отчёта).
- Уточнение диагностики: «счётчик под графиком» — Metric-карточки под центральным блоком (TsAnalysisPreprocessing, «Строк/Числовых колонок/Выбросов/Затронуто колонок»); шапка Обзора «Выбросов всего — N» и степпер-бейдж читают тот же профиль.

---

## Task ID: PROGR-4-CERT (2026-09-25) — Независимая сертификация Task PROGR-4 (UI-панель «Прогресс» + кнопка-триггер, аддендум §4.1–4.2)

Синхронизация: main@8a20ba3 (PROGR-4 исполнителя; commit/push запрещены AGENTS.md).
Акт: scripts/audit_scripts/cert_progr4_progress_ui_2026-09-25.md.

### Постановка

Честная независимая сертификация PROGR-4 по прецедентам PROGR-1/2/3-CERT: воспроизведение
заявлений исполнителя, кросс-верификация по живым исходникам, независимые оракул- и
мутационные тесты на СВОИХ данных аудитора (свой TestClient-стенд, свои cookie-сессии,
свой корпус событий, свой сид 20260925, свои мутанты).

### Воспроизведение заявлений исполнителя (7/8 ПОДТВЕРЖДЕНО, 1 — НЕТ)

9/9 test_progress_panel.py; полный tests/api 932 passed / 3 failed — дословно средовой
baseline PROGR-2/3-CERT, новых падений нет; jest 140 сюит / 1637 тестов зелёные;
typecheck:all чисто; build:all зелёный; sync-реестра узлов подтверждён (46 узлов, eda из
общего JSON §12 п.2); **НЕ ПОДТВЕРЖДЕНО удаление EventsLogDrawer.tsx — см. F-1**.

### Кросс-верификация по живым исходникам (82/84, scripts/audit_scripts/progr4cert_crossverify.py)

84 ожидания из живых файлов: pill-контракт аддендума §4.1 построчно (BADGE_BASE-геометрия,
bg-white+тонкая border-brand+text-brand неактивная, bg-brand+text-white+font-semibold
активная — font-medium отсутствует, aria-expanded/aria-controls, focus ring, Workflow в
слоте, toggle повторным кликом); w-[40rem] + механика EventsLogDrawer (backdrop/крестик/
translate-x); шапка §6.1 (target_column уже отдавался /current — бэкенд не правился);
ридер: один GET /trace, started_at=ПЕРВЫЙ ts, run_id честный null, вне TRACE_ROUTES
(живой resolve → None), нормализация на границе чтения; реестр 46 узлов дословно графу
(5 стадий текстово, eda — общий JSON, паритет перепроверен); свёртка §12 п.10: множества
статусов/started-признаков идентичны бэкенду, fail-closed; статусы из трассы §4.1
(10 терминальных→done, previewed→warning, viewed→running, stage-level мимо, ключ
stage/node, фантомы отсечены); карточки/трасса §6.2; атомарность замены слота.

### Оракулы аудитора на своих данных (52/52)

Бэкенд (progr4cert_oracles.py, 35/35): OR-A пустая сессия (null/[]/cookie); OR-B канон
8+алиас на своём payload; OR-C started_at==первый ts (≠последнего); OR-D run_id null без
датасета при наличии событий; OR-E свой legacy-корпус (R2/R3, чтение не мутирует stored,
идемпотентно); OR-F ридер не трассируется и не растит трассу; OR-G сквозная связка хук→ридер.
Фронтенд (progr4cert_oracles.test.ts, 17/17): OR-H **кросс-языковой fixture свёртки — все
2800 комбинаций длины 1–4 над 7 статусами, размеченные живым fold_status_values
(progr4cert_fold_fixture.json), TS-порт совпал 2800/2800**; OR-I свой корпус
deriveNodeStatuses (деградация applied→previewed, коллизия regularity между стадиями,
чужая стадия/фантомы, node_id=null, unknown-типы); OR-J свои тексты §6.2 («0/10, найдены
проблемы» при только-preview — N-1 подтверждён); OR-K слияние+хронология (стабильность
равных ts, битые в конец, перемежение слоя 1 и ForecastRun.trace); OR-L stageLabel=STAGE_DEFS.

### Мутационный прогон аудитора (scripts/audit_scripts/progr4cert_mutations.py)

Дизъюнктный набор 17 мутантов (у исполнителя мутационного прогона PROGR-4 не было):
детекторы — сьют исполнителя + оракулы аудитора; каждая мутация с чистого оригинала,
восстановление побайтово (sha256 OK). **17/17 KILLED.** TS: M1 потеря warning/error-
приоритета, M2 done+skipped, M3 fail-open (убит только сьютом исполнителя — fixture
аудитора сознательно на известных статусах), M4 первое-выигрывает, M5 фантомы, M6
previewed→done, M7 doneCount+=warning, M8 перепутанные подписи, M9 чужие forecasting-типы,
M10 битые ts в начало, M11 ключ без стадии (коллизия regularity). PY: B1 started_at=
последний ts (**дыра сьюта исполнителя — убит только оракулами аудитора**, их тесты
проверяют только not-null; аналог CERT-M1/M5 PROGR-3-CERT), B2 started_at=null, B3
run_id=session_id, B4 run_id="", B5 raw-чтение без нормализации, B6 пустой ридер.

### Находки (полный акт: scripts/audit_scripts/cert_progr4_progress_ui_2026-09-25.md)

- **F-1 (Medium, целостность артефакта): EventsLogDrawer.tsx НЕ удалён.** DELETIONS.txt
  в самом коммите 8a20ba3 и запись PROGR-4 утверждают удаление; факт — файл в коммите и
  дереве (name-status коммита строки удаления не содержит). Экспорт снят, импортёров нет —
  недостижимый мёртвый код («второго параллельного лога» нет, §6.1 по сути соблюдён);
  реактивация громко ломает typecheck (проверено: TS2339 log/clearLog при прямом tsc) —
  fail-closed. Рекомендация: git rm однострочным коммитом интеграции либо корректировка
  DELETIONS.txt/worklog с пометкой причины. Блокером рантайма не является.
  PS: тимлид удалил EventsLogDrawer.tsx.
- R-1 (Info): дыра CERT4-B1 — покрыть started_at==events[0].ts в сьюте (или принять
  оракулы аудитора как покрытие).
- R-2 (Info): трасса грузится только при открытии панели; открытая панель не обновляется
  (§6.2 live-обновлений не требует) — зафиксировать как MVP-контур, кандидат в PROGR-5/6.
- R-3 (Info): «Начат N мин назад» не тикает при открытой панели — косметика.
- R-4 (Info): «Пауза»/«Сохранить точку»/«Наставник» отсутствуют — честно вне объёма
  (PROGR-5/6), плановая незавершённость §6.2.
- R-5 (Info): jest-артефакты аудита добавляют сьют в общий прогон: полный jest теперь
  141/1654 (140/1637 + 1/17 аудитора) — воспроизведено.

### Вердикт

**PASSED WITH REMARKS.** Реализация соответствует канону построчно; сьюты/сборки зелёные;
52/52 оракулов; 17/17 мутантов KILLED; свёртка портирована без расхождений (2800/2800).
Единственная содержательная находка F-1 — целостность артефакта доставки (заявленное
удаление не выполнено), закрывается однострочным git rm. Блокеров для PROGR-5/6 нет.

### Deliverable

ZIP: cisstat-progr4-cert-progress-ui.zip — пути репозитория сохранены. НОВЫЕ:
scripts/audit_scripts/cert_progr4_progress_ui_2026-09-25.md (акт),
scripts/audit_scripts/progr4cert_crossverify.py, scripts/audit_scripts/progr4cert_oracles.py,
scripts/audit_scripts/progr4cert_oracles.test.ts, scripts/audit_scripts/progr4cert_gen_fold_fixture.py,
scripts/audit_scripts/progr4cert_fold_fixture.json, scripts/audit_scripts/progr4cert_mutations.py.
ИЗМЕНЁННЫЕ: worklog/worklog8.md (эта запись). Без commit/push (AGENTS.md).

---

## Task ID: PROGR-5 (2026-09-25) — Долговременный слой: research_runs/trace_events (Postgres §12 п.1) + чекпоинты/пауза/restore

Синхронизация: main@4ed649f (ff-pull с 38f1cb9; в промежутке вошли PROGR-3-CERT e0c7350 — аудиторские скрипты и запись worklog8 интегрированы как идентичные, 47a33eb, PROGR-4 8a20ba3, OUTL-1 4ed649f). Правила AGENTS.md: TDD RED→GREEN, без commit/push, ZIP в download.

### Постановка

Реализация Task PROGR-5 из plan_progress.md: слой 2 персистентности spec_progress.md §5 (research_runs/trace_events, §12 п.1 — Postgres) + чекпоинты (§5.1, паттерн PassportCheckpoint) + пауза (§5.2) + restore (§5.3, GET /v1/progress/runs/{run_id}/restore). Отдельное внимание N-2 (stage-level события не влияют на свод стадии) и N-4 (deep-link не закрывает панель) — находки PROGR-4.

### Ключевые решения

- **apps/api/research_runs.py (новый, единый модуль слоя 2).** Модели: ResearchRun (run_id PK «RUN-XXXXXXXX», session_id «последний известный», dataset_fingerprint, dataset_name, target_column, created_at, last_active_at, status active/paused/completed/abandoned — §5 дословно) и ResearchCheckpoint (§5.1: именованная ССЫЛКА на событие — event_id + label, не копия; has_snapshot, created_at). Контракт ResearchRunStore (10 методов) + две реализации: MemoryResearchRunStore (default dev/tests; глубокие копии payload на записи И чтении — R1; backfill пустого event_id при записи — R4 PROGR-3-CERT) и PostgresResearchRunStore (ленивый коннект на первой операции, идемпотентный DDL из MIGRATION_STATEMENTS при первом коннекте, conn-per-op — объёмы одной платформы §12 п.1). Фабрика get_research_run_store по env (симметрично get_session_store): CISSTAT_RUNS_BACKEND=memory — приоритет; postgres/DATABASE_URL — Postgres; сбой конструктора — деградация в Memory с error-логом; синглтоны + reset для тестов.
- **Зеркало §5 («в дополнение, не вместо»).** record_run_event(session, event) — best-effort (свой warning, ответ эндпоинта не ломается): события без run_id пропускаются честно (запуска без датасета нет); при первом событии создаётся ResearchRun с fingerprint/именем из DatasetInfo и СВЕРХ заменой статусов: предыдущие активные запуски сессии → abandoned (новый датасет = новое исследование §3.1); при каждом событии — last_active_at + session_id. Вызов из TraceHookMiddleware._record (trace_hook.py, +3 строки) после store.save. УНИФИКАЦИЯ ПРОГНОЗИРОВАНИЯ, обещанная PROGR-3: _append_event forecasting_session.py дополнена тем же best-effort вызовом — ForecastRun.trace остаётся слоем 1 forecasting, слой 2 получает его события (run_id attach из сессии; event.payload не теряется; контракт PROGR-1 не тронут).
- **REST /v1/progress/runs/{run_id}[...] (progress.py, namespace канона §5).** GET /runs/{run_id} — мета + события (хронология; ?limit — последние N; events_total) + чекпоинты. POST /pause (§5.2: status=paused; не из active — 409; двойная пауза — ошибка клиента, не идемпотент) / POST /resume (только из paused — 409). POST /checkpoints {event_id, label?} — ссылка обязана указывать на событие ЭТОГО запуска (404 иначе, чужие/фантомные исключены — усиление PassportCheckpoint «Checkpoint должен ссылаться на снимок текущей сессии»); + checkpoint_saved (run-level §4.1) в слой 2 и слой 1 сессии запуска. Run-level события пишутся эндпоинтами ЯВНО через make_trace_event (fail-closed гейт реестра §4.1); namespace вне TRACE_ROUTES (паттерн PROGR-4: ридер не трассируется) — зафиксировано тестом по всем 5 маршрутам.
- **Restore (§5.3).** GET /runs/{run_id}/restore: 404 неизвестный; 409 completed («status != completed» дословно); датасет — из файлового слоя по dataset_fingerprint (§12 п.3), нет файла — честный 409 «повторная загрузка» (§5.3: промежуточные состояния DataFrame не восстанавливаются; чтение файла — по ИЗВЕСТНОМУ расширению regex-ом: display-имя «demo_sales.csv (демо-датасет)» ломает суффикс-детектор read_uploaded_file); создаётся НОВАЯ AnalysisSession + НОВЫЙ cookie (даже если cookie был; политика SameSite/Secure — как get_or_create_session_id); session.run_id = run запуска — run_id ПЕРЕЖИВАЕТ cookie (ключевая приёмка плана); трасса слоя 1 засеивается из слоя 2 (хвост ≤ cap 1000; полная история остаётся в слое 2 — события_total в ответе); target_column из метаданных запуска — только если колонка существует в перечитанном df; last_active_stage — стадия последнего события; session.stages не пишется (§3.1, только честный upload=done от set_dataset); run перелинковывается на новую сессию (§5: session_id — «последний известный») + run_resumed {restored: true} в обе трассы; активные запуски прежней сессии браузера — abandoned (симметрия новой загрузке). Продолжение работы пишет в ТОТ ЖЕ запуск — покрыто тестом.
- **Файловый слой DatasetFileStore (§12 п.3/п.4).** data/uploads/{sha256}{ext} + {sha256}.meta.json (имя/размерность/источник); демо — builtin_demo без копии (restore перечитывает встроенный файл); корень — env CISSTAT_DATA_DIR, default <repo>/data (в .gitignore добавлены data/uploads/, data/checkpoints/). Снимки чекпоинтов: CSV последних 5 на запуск (§12 п.4 «входит в MVP»), prune по списку из хранилища запусков (детерминированно, не по mtime). Отклонение от буквы §12 п.4: CSV вместо Parquet — pyarrow в среде недоступен; замена изолирована в save/load_checkpoint_snapshot (одна функция), ограничение dtype дат задокументировано. Отступление от «переиспользуй существующий хэш» §12 п.3: series_fingerprint определён на ряде с датой (target), которого при загрузке нет; dataset_fingerprint = SHA-256 байт файла — единственный честный ключ файла в этот момент; сверка когорт Моделирования не тронута.
- **Контракт сессии (аддитивно).** DatasetInfo + dataset_fingerprint: str = "" (конец списка полей, дефолт — старые Redis-документы совместимы, asdict/DatasetInfo(**d) работают в обе стороны — тест legacy-документа). handle_upload и /demo вычисляют fingerprint и регистрируют файл best-effort (сбой диска не роняет загрузку — restore потом ответит 409 честно).
- **503-контур:** сбой долговременного слоя в рантайме (Postgres-бэкенд недоступен/драйвера нет) — честный 503 «Долговременный слой недоступен» (декоратор _durable_ops; 404/409 проходят насквозь — факты, не сбои); деградировать читающие эндпоинты на слой 1 нельзя — ответ выдавал бы неполную историю за полную.
- **N-2 (PROGR-4):** сохранён инвариант — stage-level события (node_id=None: mode_changed/target_column_changed/passport_captured) нигде в слое 2 не превращаются в узловые факты; restore засевает трассу «как есть» (тест: mode_changed остаётся node_id=None, фантомных узлов нет); факт target фиксируется в метаданных запуска (target_column), не в сводах. **N-4 (PROGR-4):** ответы всех 5 эндпоинтов не содержат семантики управления панелью (запрещённый набор close_panel/open_panel/navigate/redirect проверен тестом) — deep-link узла не закрывает панель, состояние панели по-прежнему живёт во фронтенде (бэкенд не может и не должен его менять).

### TDD и верификация

- RED: 59 тестов нового файла падали по правильной причине (ImportError: cannot import name 'research_runs'), зафиксировано до реализации.
- GREEN: tests/api/test_research_runs.py 60/60 (модели/раундтрипы; Memory-хранилище: изоляция payload R1/R4, chекпоинты, supersede; DatasetFileStore: fingerprint=SHA-256, demo-перечитывание, снимки+prune; фабрика по env; зеркало хука: создание run, паритет слой1↔слой2, target_column, skip без run_id, переживание сбоя слоя, supersede, унификация forecasting; REST: детали/limit/404/503, пауза/resume 200/409/404, чекпоинт 201/404/снимок/чужая-сессия, restore: 404/409 completed/409 нет файла/новый cookie+тот же run_id/засев с cap/target/stages §3.1/N-2/N-4/paused→active).
- tests/api полный: **996 passed / 3 failed** — ровно средовой baseline PROGR-2/3-CERT (modeling_workflow catalog-only, neural_capacity память хоста, models_candidates unsupported-гейт); было 936 перед задачей (+60 новых, новых падений нет). Смежные сюиты точечно: хук+панель+session_store+forecasting+upload 158/158.
- Jest полный: **140 сюит / 1645 тестов — зелёные** (фронтенд задачей не трогался, baseline воспроизведён).
- typecheck:all чисто; npm run build:all зелёный.
- Среда: установлен PyWavelets+pandera+requirements (окружение сессии было без зависимостей проекта); Postgres-сервера/драйвера в среде нет — Postgres-реализация покрыта DDL-константами, ленивым импортом и выбором фабрики, поведенческие тесты на Memory (тот же контракт базового класса); интеграционный прогон — на on-prem Postgres (ops: apps/api/migrations/0001_research_runs.sql).

### Находки/заметки (не блокеры)

- N-5 (Info): run без события «completed» в MVP не достигается ни одним эндпоинтом (статус доступен хранилищу/тестам; правило терминальности — решение PROGR-8/статистики: §10.5 forecasting_exported — кандидат на триггер).
- N-6 (Info): зеркальный supersede помечает abandoned только при НОВОМ событии нового запуска; запуск, брошенный без новых событий (аналитик просто ушёл), остаётся active до политики PROGR-8 (TTL-правило статистики §5.2 «учитывается отдельно»).
- N-7 (Info): restore не перепроигрывает correction-события в состояние DataFrame (§5.3 дословно) — снимки чекпоинтов (§12 п.4) сохранены на запись, применение снимка при restore (откат к точке) — отдельный контракт следующей задачи вместе с кнопками панели (Пауза/Сохранить точку — фронтенд).
- N-8 (Info): env DATABASE_URL вне тестов выбирает Postgres-бэкенд при любом значении (стандартное соглашение); в этой среде переменная занята sandbox-инфраструктурой (file:-URL) — на тесты не влияет (fixture удаляет), на dev/ prod влияет только осознанно заданным DSN.
- R-1 (Low): events GET /runs/{run_id} без limit отдаёт весь журнал (на объёмах одной платформы — приемлемо; пагинация — по факту PROGR-8-агрегатов).

### Deliverable

ZIP: cisstat-progr5-research-runs.zip — пути репозитория сохранены. НОВЫЕ: apps/api/research_runs.py; apps/api/migrations/0001_research_runs.sql; tests/api/test_research_runs.py. ИЗМЕНЁННЫЕ: apps/api/routers/progress.py (5 эндпоинтов runs-namespace); apps/api/trace_hook.py (+зеркало слоя 2); apps/api/routers/forecasting_session.py (+унификация слоя 2); apps/api/session_store.py (DatasetInfo+dataset_fingerprint); apps/api/upload_common.py (+файловый слой загрузки); apps/api/routers/session.py (demo: fingerprint+регистрация файла); .gitignore (data/uploads/, data/checkpoints/). ИЗМЕНЁННЫЙ: worklog/worklog8.md (эта запись). Без commit/push (AGENTS.md).

---

## Task ID: DEPLOY-1 (2026-09-25) — Hotfix деплоя render.com: ImportError «Общий реестр EDA не найден» — каталог shared/ не попадал в Docker-образ apps/api (§12 п.2)

Синхронизация: main@4c5486a (ff-pull с 925aa1c; попутно из stash восстановлены артефакты и запись OUTL-1-CERT, выстроены хронологически перед PROGR-5). Правила AGENTS.md: TDD RED→GREEN, без commit/push, ZIP в download.

### Постановка

Передеплой render.com (следствие рекомендации OUTL-1-CERT: «Manual Deploy последнего main») падает: `ImportError: Общий реестр EDA не найден: /app/shared/pipeline_nodes/eda_checks.json (§12 п.2); файл обязателен для старта графа пайплайна` → `Exited with status 1` → «No open ports detected», сервис недоступен. Найти причину, исправить, дать контроль.

### Root cause (доказан симуляцией сборки образа)

apps/api/Dockerfile копирует в образ ТОЛЬКО каталоги, найденные статическим AST-разбором импортов бэкенда (app/, validation/, src/, apps/api/, rules/; комментарий в Dockerfile: «проверено статическим AST-разбором»). Общий реестр EDA — файл-ДАННЫЕ, а не импорт: app/core/pipeline_graph.py читает shared/pipeline_nodes/eda_checks.json НА ИМПОРТЕ модуля (fail-closed, `EDA_CHECK_DEFS = _load_eda_check_defs()` — строка 128, §12 п.2). AST-разбор data-файл не видит → каталога shared/ в образе НИКОГДА не было. Зависимость появилась в PROGR-2 (4467fae, 2026-09-24): любой образ, собранный из кода ≥ PROGR-2, умирает на старте; живой контейнер на render.com был собран из кода СТАРШЕ PROGR-2 (live-проба OUTL-1-CERT: OpenAPI без bounds, без /v1/progress), поэтому баг был латентным до передеплоя. Цепочка старта: CMD `uvicorn apps.api.main:app` → main.py:32 (TraceHookMiddleware) → trace_hook.py:61 (`from app.core.pipeline_graph import is_known_node`) → pipeline_graph.py:128 (module-level загрузка JSON) → FileNotFoundError → ImportError → exit 1.

Эмпирика (scripts/audit_scripts/deployfix_simulate_image.py): сборка образа имитируется без docker — парсинг COPY-строк Dockerfile, копирование в tmp (WORKDIR /app), слой `RUN touch apps/__init__.py`, стартовый контракт uvicorn `from apps.api.main import app` в subprocess с чистым PYTHONPATH: [A] образ ДО фикса (без shared/) — exit 1, stderr дословно содержит ошибку render.com (маркер «Общий реестр EDA не найден» + путь реестра); [B] +shared/ — exit 0, IMPORT_OK.

### TDD

- RED: tests/api/test_docker_image_layout.py (4 теста, НЕ требуют docker): (1) статический — «shared» обязан быть среди COPY-источников Dockerfile; (2) реестр существует/парсится/stage='eda'/nodes непусты/без дубликатов id; (3) динамический — имитация образа ПО исправленному Dockerfile стартует (импорт apps.api.main зелёный); (4) имитация БЕЗ shared/ воспроизводит инцидент дословно — защита fail-closed контракта §12 п.2 от ослабления загрузчика до тихой деградации (граф «Прогресса» не должен стартовать с частичной картиной стадий). RED подтверждён: (1) и (3) падали по правильной причине («shared» отсутствует в COPY), (4) проходил уже до фикса (документирует инцидент).
- GREEN: фикс apps/api/Dockerfile — `COPY shared/ ./shared/` с комментарием о классе бага (data-файлы невидимы AST-разбору) + build-гвард `RUN python -c "from app.core.pipeline_graph import EDA_STAGE_IDS; print(...)"`, поставленный ПОСЛЕ слоя `RUN touch apps/__init__.py` (гвард импортирует apps.api.*). Философия Dockerfile соблюдена: падать на СБОРКЕ с явной ошибкой, а не мёртвым контейнером в проде (прецедент rules/modeling.yaml в том же файле). 4/4 зелёные.
- Верификация гварда (scripts/audit_scripts/deployfix_verify_guard.py): код RUN-гварда парсится ИЗ Dockerfile (не дублируется); [A] без shared/ — сборка падает на гварде с искомой ошибкой (инцидент класса DEPLOY-1 отныне ловится на этапе docker build); [B] с shared/ — «pipeline graph OK, EDA nodes from shared JSON: 10».
- Смежные сюиты: tests/api/test_pipeline_graph.py + test_progress_panel.py + test_progress_trace_hook.py + test_research_runs.py + новый файл — 257 passed. Код продукта Python не менялся (только Dockerfile + новый тест), регресса быть не может по построению; прогон подтверждает.

### Латентные баги того же класса (проверены, ответ отрицательный)

- data/ для файлового слоя PROGR-5 (§12 п.3/п.4) в образ НЕ копируется — и НЕ НУЖНО: DatasetFileStore создаёт каталоги лениво `mkdir(parents=True, exist_ok=True)` (research_runs.py:778/815/873, neural_contract.py:710). Эфемерность /app/data в контейнере — честный 409 restore после редеплоя по §5.3 (дизайн MVP, persistence вне объёма).
- config/, docs/, packages/ бэкендом на импорте не читаются: полный стартовый импорт apps.api.main в имитации проходит на {app, validation, src, apps/api, rules, shared} — это исчерпывающий стартовый контракт.

### Операционная инструкция тимлиду

1. Применить ZIP (единственный изменённый файл — apps/api/Dockerfile) либо вручную добавить в него два блока (COPY shared/ + гвард) — они помечены «DEPLOY-1» в комментариях. 2. Manual Deploy на render.com. 3. Контроль сборки: в логе должна появиться строка «pipeline graph OK, EDA nodes from shared JSON: 10» — её отсутствие на сборке без падения означает, что деплоится не этот Dockerfile (dockerfilePath: ./apps/api/Dockerfile, dockerContext: . по render.yaml). 4. Контроль рантайма после деплоя: `python3 scripts/cert_outl1_live_probe.py` — шаг 3 обязан показать bounds в ответе /outlier-line (замыкает контроль OUTL-1-CERT: замечание «счётчик 0, график не меняется» было стейл-деплоем, код правилен; после успешного деплоя границы метода и ревизионный refresh станут видны пользователю).

### Находки

- N-1 (Info): корневой Dockerfile (Streamlit, порт 8501) — ДРУГОЙ деплой, не затронут: у него `COPY . .` и shared/ попадает в образ.
- N-2 (Info): .dockerignore корня репозитория (`*.md`, exports/, reports/, ...) shared/ не исключает — виноватых масок нет, зависимость просто не была перечислена.
- R-1 (Low, осознанно): парсер теста поддерживает только канонизированные строки `COPY <dir>/ ./<dir>/`; при расширении Dockerfile новым синтаксисом (COPY --from, одиночные файлы) тест (1) упадёт и заставит расширить парсер осознанно — цена защиты от «тихих» пропусков.
- R-2 (Info, рекомендация из OUTL-1-CERT остаётся в силе): маркер версии (git sha) в /health — drift деплоя и принадлежность образа коммиту проверялись бы одной командой; в объём данной задачи не входил.

### Deliverable

ZIP: cisstat-deploy1-render-shared-registry.zip — пути репозитория сохранены. ИЗМЕНЁННЫЙ: apps/api/Dockerfile (+COPY shared/ §12 п.2, +build-гвард pipeline_graph). НОВЫЕ: tests/api/test_docker_image_layout.py (регресс-инвариант состава образа, 4 теста), scripts/audit_scripts/deployfix_simulate_image.py (доказательство root cause), scripts/audit_scripts/deployfix_verify_guard.py (верификация гварда). Восстановлены из stash (OUTL-1-CERT, не изменялись): scripts/audit_scripts/cert_outl1_outlier_line_2026-09-25.md, outl1cert_oracles.py, outl1cert_oracles.test.tsx, outl1cert_mutations.py, outl1cert_crossverify.py, scripts/cert_outl1_live_probe.py. ИЗМЕНЁННЫЙ: worklog/worklog8.md (запись OUTL-1-CERT восстановлена + эта запись). Без commit/push (AGENTS.md).

---

## Task ID: PROGR-5-CERT (2026-09-25) — Независимая сертификация Task PROGR-5 (долговременный слой research_runs/trace_events §5 слой 2, Postgres §12 п.1 + чекпоинты/пауза/restore)

Синхронизация: main@b9a16ca (исполнение PROGR-5 — 4c5486a; b9a16ca — DEPLOY-1 тимлида, включён в проверку). Правила AGENTS.md: без commit/push, ZIP в download.
Акт: scripts/audit_scripts/cert_progr5_research_runs_2026-09-25.md.

### Постановка

Честная сертификация PROGR-5 по прецедентам PROGR-2/3/4-CERT, OUTL-1-CERT: воспроизведение заявлений исполнителя, кросс-верификация по живым исходникам, независимые оракул- и мутационные тесты на СВОИХ данных аудитора (корпус seed 20250925, progr5cert_revenue.csv 40×3 с NaN-зазором; фикстуры исполнителя не используются).

### Воспроизведение заявлений исполнителя (10/10 ПОДТВЕРЖДЕНО)

test_research_runs.py 60/60 (счётчик совпал); полный tests/api 1000/3 на b9a16ca = 996 (заявлено) + 4 DEPLOY-1, 3 падения — ровно средовой baseline, новых нет; jest 142/1674 = 140/1645 + OUTL-1 (хронология сходится); typecheck:all чисто; RED «59 по ImportError» правдоподобен (файл теста импортирует модуль, которого до реализации не было); модели/контракт хранилища/фабрика/зеркало — дословно §5/§5.1; унификация Прогнозирования подтверждена диффом; оба заявленных отклонения воспроизведены и изолированы (CSV вместо Parquet — pyarrow недоступен; file-SHA-256 вместо series_fingerprint — когортная сверка Моделирования цела: backtesting.py/modeling_workflow.py не тронуты).

### Оракулы аудитора на своих данных (40/40 PASS)

A (6): R1-изоляция payload; R4-backfill со стабильностью id; append-only порядок (12 событий); supersede (keep цел, paused/completed/чужие не тронуты); set_run_status ValueError+last_active_at; list_runs сортировка/фильтр. B (6): фантом без run_id НЕ создан; первый запуск с fingerprint/именем своего датасета; target_column_changed ставит/снимает; last_active_at+«последний известный»; forecasting attach run_id; best-effort при падающем store. C (6): fingerprint == независимый SHA-256 своих байт; round-trip; демо builtin_demo БЕЗ копии; CSV-снимок round-trip своего df; prune по keep-списку при подменённом mtime; битая мета → None. D (16, HTTP на реальном стеке): upload→запуск с SHA-256; detail events_total/?limit-последние-N; машина статусов 200/409/404 + run_paused стадии последнего события; чекпоинт 201+снимок/404 фантом/409 completed/чужая сессия без снимка; restore 404/409(completed)/409(нет файла)/happy path (новый cookie, ТОТ ЖЕ run_id, мой датасет, target, засев, run_resumed{restored:true} в обоих слоях, перелинковка); supersede старой сессии; run переживает cookie (D9); cap засева 1005→1000 (D10); N-2 (node_id=None, session.stages не тронут); N-4 (нет close_panel/open_panel/navigate/redirect); 503-контур+404 насквозь; demo-fingerprint; target не из колонок не применяется (D15); чужой сессии зеркала нет (D16). E (6, без сервера): MIGRATION_STATEMENTS == 0001_research_runs.sql текст в текст; DDL-структура (PK/FK CASCADE/UNIQUE(run_id,event_id)/индексы); фабрика по env + ленивость + RuntimeError; _ts round-trip/naive→UTC/битый ts; иммутабельность моделей; stage_for_run_level_event.

### Мутационный прогон аудитора (20/20 KILLED; у исполнителя мутационного прогона не было)

M1 supersede no-op; M2 supersede трогает keep; M3 target не фиксируется; M4 фантом; M5 R4 удалён; M6 md5 вместо sha256; M7 prune отключён; M8 стадия всегда upload; M9/M10 машина статусов; M11/M12 чекпоинт-гейты; M13 restore completed; M14 restore без файла; M15 target без колонки; M16 засев без cap; M17 restored=true снят; M18 без перелинковки; M19 503 проглочен; M20 зеркало в чужую сессию. Детекторы — ТОЛЬКО оракулы аудитора. Методология: побайтовое восстановление с верификацией, purge __pycache__, PYTHONDONTWRITEBYTECODE, сдвиг mtime (уроки OUTL-1-CERT применены сразу); два дефекта собственного раннера (потеря __name__ в декораторе; ложный «пустая база»-гард) пойманы ДО зачётного прогона; baseline 20/20 PASS на нетронутых исходниках.

### Находки (полный акт: scripts/audit_scripts/cert_progr5_research_runs_2026-09-25.md)

- CERT-N-1 (Info, следствие §5.3): run_id — bearer-возможность: знающий run_id может паузить/ресторить/чекпоинтить чужой запуск (аутентификации нет — §10; §5.3 дословно «если предъявленный run_id валиден»). Для MVP корректно; ownership-модель — к PROGR-8/auth; честность зеркала чужой сессии подтверждена (D16).
- CERT-N-2 (Info): Postgres get_event — O(n) полный список с фильтром в Python; на объёмах одной платформы приемлемо, при росте — WHERE event_id в SQL.
- CERT-N-3 (Info): при заполненном cap засева run_resumed вытесняет старейшее событие слоя 1 (контракт буфера PROGR-3; полная история в слое 2, events_total честен) — зафиксировано D10.
- CERT-N-4 (Info): двойной commit в Postgres-операциях (context-manager + явный) — безвреден, на сбой rollback; шум, не дефект.
- CERT-R-1 (Low): _ext_of сохраняет неизвестные расширения как .csv — для известных форматов корректно, для будущих (parquet) возможно расхождение суффикса и содержимого.
- Среда (не находка кода): Postgres-интеграционный прогон невозможен в обеих средах (нет сервера/драйвера); компенсации — текстовая сверка DDL (сошлась), структурные проверки, ленивый импорт, фабрика; поведенческий прогон — на on-prem (ops: apps/api/migrations/0001_research_runs.sql).

### Вердикт

**PASSED WITH REMARKS.** 40/40 оракулов, 20/20 KILLED, 10/10 воспроизведений, оба отклонения обоснованы и изолированы, приёмка плана «run_id переживает cookie» подтверждена независимо. Блокеров нет.

### Deliverable

ZIP: cisstat-progr5-cert-research-runs.zip — пути репозитория сохранены. НОВЫЕ: scripts/audit_scripts/cert_progr5_research_runs_2026-09-25.md (акт), scripts/audit_scripts/progr5cert_oracles.py, scripts/audit_scripts/progr5cert_mutations.py. ИЗМЕНЁННЫЕ: worklog/worklog8.md (восстановленная запись OUTL-1-CERT + эта запись). Код продукта не менялся. Без commit/push (AGENTS.md).

---

## Task ID: PROGR-5.1 (2026-09-25) — Подключение кнопок панели «Пауза»/«Сохранить точку» на фронтенде (бэкенд PROGR-5) + интеграционный прогон DDL на on-prem Postgres

Синхронизация: main@b9a16ca (ff-pull с 38f1cb9; в промежутке вошли PROGR-3-CERT e0c7350 — локальные копии аудиторских скриптов удалены как идентичные, 47a33eb, PROGR-4 8a20ba3, OUTL-1 4ed649f, PROGR-4-CERT 925aa1c, PROGR-5 4c5486a, DEPLOY-1 b9a16ca). Правила AGENTS.md: TDD RED→GREEN, без commit/push, ZIP в download.

### Постановка

Указание тимлида вслед за N-7 PROGR-5 («применение снимков/откат к точке + кнопки панели — фронтенд»): подключить кнопки панели «Пауза»/«Сохранить точку» к готовому бэкенд-контракту PROGR-5 (§5.1–§5.2) в правой панели «Прогресс» (§6.2–§6.3); выполнить интеграционный прогон DDL долговременного слоя (apps/api/migrations/0001_research_runs.sql, §12 п.1) на on-prem Postgres — в среде PROGR-5 Postgres-сервера/драйвера не было, прогон был явно отложен на ops-контур.

### Ключевые решения

- **ProgressCheckpointBar.tsx (новый, §6.3)** — полоса действий панели: бейдж статуса запуска («В работе»/«На паузе»/«Завершён»/«Брошен» — 4 канонических статуса §5, неизвестный статус возвращается как есть, без маскировки), кнопка «Пауза» → POST /v1/progress/runs/{run_id}/pause, в статусе paused — «Продолжить» → POST .../resume; кнопка «Сохранить точку» (§5.1) раскрывает inline-форму с опциональным комментарием и POST .../checkpoints {event_id, label}. Кнопка «Наставник» сознательно НЕ рендерится — её бэкенд отдельная задача PROGR-6 (решение PROGR-4 «мёртвых кнопок нет» продолжено).
- **Якорь чекпоинта — «текущий момент» исследования.** lastCheckpointableEvent(events) (lib/progress.ts) — последнее в хронологии событие с непустым event_id: события без идентификатора (слитые ForecastRun.trace — legacy 3-польный контракт без event_id) для якоря непригодны, бэкенд отклонил бы ссылку 404 — прогнозируемый отказ отсекается на фронтенде disabled-состоянием («Нечего фиксировать» — title честной причины).
- **Гейт действий по статусу.** runAcceptsActions: только active/paused; completed/abandoned — disabled (пауза не из active — гарантированный 409 §5.2, чекпоинт недоступен §5.1); неизвестный статус (деталь запуска недоступна: 503 слоя/404/сеть) — тоже disabled: бэкенд гарантированно откажет, «гарантированный отказ не кликается». Отказ любого действия — inline role="alert" с detail бэкенда (409/503/404/сеть), панель не роняется (best-effort, паттерн панели PROGR-4).
- **Данные полосы — из слоя 2, обновление — через refresh-цикл.** ProgressDrawer при известном run_id (из слоя 1) запрашивает GET /v1/progress/runs/{run_id} (status + checkpoints; best-effort: недоступно — кнопки disabled, панель жива). После успешного действия — перечитывание трассы слоя 1 (run_paused/run_resumed/checkpoint_saved зеркалятся в неё, PROGR-5) и детали запуска слоя 2 (refreshCounter). Без run_id полоса не рендерится вовсе — действиям запуска неоткуда взяться (панель честно показывает прочерки шапки).
- **N-2 (находка PROGR-4) сохранён:** run-level события (checkpoint_saved/run_paused/run_resumed, node_id=null) не попадают в deriveNodeStatuses — узловых статусов не создают, своды стадий не трогают (тесты: до/после — равенство). **N-4 сохранён:** компонент не содержит семантик закрытия/навигации (запрещённый набор проверен тестом по DOM); об успехе родитель узнаёт только через onChanged() — панель остаётся открытой, данные обновляются (тест сквозной: после «Паузы» aside с translate-x-0, onClose не вызван, refetch слоя 1 выполнен).
- **Интеграционный прогон DDL (scripts/audit_scripts/progr5fe_ddl_integration.py, 6 контуров).** [1] применение DDL-файла на живом сервере (psql -f-эквивалент: весь файл простым протоколом); [2] контроль объектов — 3 таблицы + 3 индекса §12 п.1; [3] идемпотентность — повторный прогон не меняет схему; [4] эквивалентность источников — MIGRATION_STATEMENTS (авто-миграция первого коннекта) дают то же множество объектов, что файл; [5] поведенческий контракт PostgresResearchRunStore на живой БД — раундтрип запуска, paused, события (JSONB/юникод/N-2 node_id=None), дубль отсечён, чекпоинт; [6] DDL-гарантии сервера — UNIQUE (run_id, event_id) (UniqueViolation на сырой дубль-вставке) и FK ON DELETE CASCADE. Цель — реальный PostgreSQL 16.2: в песочнице без root поднят эфемерный сервер pgserver (PyPI-бинари PostgreSQL, unix-сокет) — НЕ эмуляция, применяется и проверяется тот же DDL; на on-prem запуск: --dsn 'postgresql://user:pass@host:5432/db'.
- **Постоянный регресс on-prem (tests/api/test_research_runs_postgres.py, 12 тестов).** Затвор средой CISSTAT_TEST_PG_DSN: без него модуль skip (CI/базлайн без Postgres не меняются), с ним — полный интеграционный прогон: DDL-файл/идемпотентность/эквивалентность источников, поведенческий контракт хранилища, серверные гарантии UNIQUE/CASCADE и REST-смоук сквозь TestClient с CISSTAT_RUNS_BACKEND=postgres: demo-загрузка создаёт запуск в Postgres (проверка прямым SQL), «Пауза» → status=paused и run_paused в таблице, «Сохранить точку» → строка run_checkpoints с has_snapshot=true (снимок сессии запуска), «Продолжить» → active, чекпоинт виден в детали запуска; двойная пауза — 409 из живого статуса БД.

### TDD и верификация

- RED: 30 новых фронтовых тестов падали по правильным причинам — сьют бара не компилировался (TS2307: нет ProgressCheckpointBar; TS2305: нет runStatusLabel/CheckpointInfo в lib), 6 новых drawer-тестов — полоса/кнопки не рендерятся (компонента нет), lib-дополнения — отсутствующие экспорты.
- GREEN: три целевых сюита **69/69** (bar 14, lib 24+9, drawer 15+7). Находка GREEN-цикла: исходный вариант допускал клик при неизвестном статусе — исправлено на disabled с комментарием (см. выше).
- Jest полный: **142 сюиты / 1690 тестов — зелёные** (апстрим-базлайн b9a16ca 141/1660 воспроизведён + 30 новых).
- tests/api полный: **1012 passed / 3 failed** — ровно средовой baseline PROGR-2/3/4/5 (modeling_workflow catalog-only, neural_capacity память хоста, models_candidates unsupported-гейт); из 1012 — 4 теста docker-layout DEPLOY-1 (апстрим) и 12 новых Postgres-интеграционных (прогон с CISSTAT_TEST_PG_DSN на живом PostgreSQL 16.2; без DSN — skip, базлайн 1000/3 сохраняется).
- Интеграционный прогон DDL: **6/6 PASS** (PostgreSQL 16.2, pgserver-бинари; все контуры [1]–[6] PASS).
- typecheck:all чисто (embedded+standalone); npm run build:all зелёный.
- Среда: установлены requirements (корень + apps/api/requirements.txt — в свежем venv отсутствие prophet/statsforecast роняло import-гейт реестра моделей «Реестр готовности моделей расходится с production backtest dispatch»; вопрос среды, не кода), psycopg 3.3.6 + pgserver 0.1.4 (для Postgres-контура).

### Находки/заметки (не блокеры)

- N-1 (Info): размещение полосы — единым блоком под шапкой (бейдж + «Пауза»/«Продолжить» + «Сохранить точку»), а не [Пауза] в строке заголовка эскиза §6.2: единый компонент §6.3 («Кнопки „Пауза“/„Сохранить точку“/„Наставник“») cohesion-нее, деталь вёрстки; семантика §5.1–§5.2 и состав кнопок соблюдены.
- N-2 (Info): подтверждение чекпоинта и список сохранённых точек рендерятся в полосе (label + время + «снимок данных»); полная карта чекпоинтов на трассе (маркеры на событиях) — UX-задел beyond-MVP, не требовался планом.
- N-3 (Info): pgserver-сервер в песочнице живёт, пока жив процесс-холдер; для повторных прогонов тестов — фоновый холдер или --dsn на внешний сервер; ops-скрипт самодостаточен в обоих режимах.
- N-4-подтверждение: бэкенд-контракт PROGR-5 (ответы без семантик управления панелью) не потребовал НИ ОДНОЙ правки бэкенда — подключение чисто фронтовое, продакт-код Python не менялся.

### Deliverable

ZIP: cisstat-progr5-1-buttons-ddl.zip — пути репозитория сохранены. НОВЫЕ: packages/ui/components/ProgressCheckpointBar.tsx (+ProgressCheckpointBar.test.tsx), tests/api/test_research_runs_postgres.py (12 тестов, затвор CISSTAT_TEST_PG_DSN), scripts/audit_scripts/progr5fe_ddl_integration.py (ops-прогон DDL, 6 контуров). ИЗМЕНЁННЫЕ: packages/ui/components/ProgressDrawer.tsx (+полоса, +fetch детали запуска, +refresh-цикл), ProgressDrawer.test.tsx (+7), packages/ui/lib/progress.ts (+runStatusLabel/CheckpointInfo/lastCheckpointableEvent), packages/ui/lib/progress.test.ts (+9), packages/ui/index.ts (+экспорт бара). ИЗМЕНЁННЫЙ: worklog/worklog8.md (эта запись). Без commit/push (AGENTS.md).

---

## Task ID: PLAN-REVIEW-CHARTS (2026-09-26) — План устранения класса «графики Обзоров без явной подписки на refresh» во всех Обзорах и их остановках

Синхронизация: main@cfa1213 (ff-clone; working tree чистый, код продукта не менялся). Правила AGENTS.md: без commit/push, ZIP в download.

### Постановка

Указание тимлида вслед за границей задачи OUTL-1: класс «графики без явной подписки на refresh» существует на других остановках (Пропуски: матрица/корреляция) — тест-паттерн it.each готов к переносу, требуется отдельная постановка на все Обзоры. Составить план устранения недоработки во всех Обзорах и их остановках; упаковать в plan_review_charts.md.

### Работа (инвентаризация по живому коду @ cfa1213)

Полный обход семейства Обзоров (ExpandableChartPanel-пользователи, *Overview.tsx, *Visualizations.tsx, hooks/useChartDetailData, точки fetch контейнеров TsAnalysisEDA/Preprocessing/Validation/Modeling) с классификацией по трём механизмам доставки данных графика: (A) profile-prop — подписка обеспечена deps контейнера; (B) self-fetch чарта — паттерн OUTL-1 (refreshKey проп + revision= в query); (C) кэш раскрытия useChartDetailData — fingerprint обязан включать мутацию датасета. Ключевые факты: «Пропуски» — 3 графика без подписки (missing-matrix/missing-correlation — константные URL вовсе, missing-distribution — только выбор колонок; файл не менялся с Task 54); «Выбросы» — эталон OUTL-1 (revision=, 4 графика); «Регулярность» — корректна с Task 72 (_r=); Decomposition/Spectral — useChartDetailData БЕЗ fingerprint (комментарий «fingerprint не нужен» написан до эпохи datasetVersion/PREPR-4 — инвалидация по apply не покрыта, ключ кэша переживает мутацию); EdaStructuralBreaks — fingerprint=datasetKey не меняется при in-place мутации, а detailCache — модуль-глобальный Map, переживает переходы между модулями; EdaDescriptive — самофетч с requestKey-гвардом (подписан), без cache-buster; Валидация/Моделирование — чисты (профиль-проп/action-driven, recharts в Обзорах нет). Детали, постановки по волнам, TDD, риски — plan_review_charts.md (репозиторий, корень, по прецеденту plan_progress.md).

### Решение плана (кратко)

- Волна 1 (P0): «Пропуски» — MissingMatrixChart/MissingCorrelationChart/MissingBoxplotChart принимают refreshKey, URL получают revision= (дословный перенос паттерна OUTL-1); тест-паттерн it.each + интеграционный инвариант переносятся в оба существующих сюита. Бэкенд не меняется.
- Волна 2 (P1): слой C — invalidateChartDetailCache() из useChartDetailData + единый handleApplied контейнера «Предобработки» (bump datasetVersion + инвалидация кэша), fingerprint=String(refreshKey) для Decomposition/Spectral (контейнер передаёт сумму ключей); EdaStructuralBreaks закрывается глобальной инвалидацией без правки.
- Волна 3 (P2, опционально): унификация _r=→revision=, cache-buster для EdaDescriptive, TasksCauses — отдельная постановка.
- Статический гвард: ReviewChartsRefreshCoverage.test.ts по прецеденту ExpandableChartCoverage.test.ts — списки REVISION_SUBSCRIBED_CHART_SOURCES / PROFILE_PROP_OVERVIEWS / SELF_FETCH_GUARDED_OVERVIEWS, правило «новый Обзор классифицируется ровно в одном списке».
- Риски: тесты — на «последнюю ревизию», не на число вызовов (loading-flash); refreshKey — монотонная сумма (тип не менять); правки только frontend, Python-регрессия не требуется.

### Deliverable

ZIP: cisstat-plan-review-charts.zip — пути репозитория сохранены. НОВЫЙ: plan_review_charts.md (план-постановка: инвентаризация 30 остановок, контракт инварианта, 3 волны, TDD, гвард, риски, порядок и приёмка). ИЗМЕНЁННЫЙ: worklog/worklog8.md (эта запись). Код продукта не менялся. Без commit/push (AGENTS.md).

---

## Task ID: PROGR-6 (2026-09-26) — Наставник v1: §7.1 «Следующий шаг» + §7.2 sanity-правила (правило-движок без LLM, пороги rules/mentor.yaml §12 п.7)

Синхронизация: main@1e00ab1 (ff-merge; рабочее дерево чистое, локальные копии audit-скриптов PROGR-3-CERT идентичны upstream и сняты). Правила AGENTS.md: без commit/push, ZIP изменённых/новых файлов в download.

### Постановка

Задача PROGR-6 из plan_progress.md (spec_progress.md §7 + §12 п.7/п.8): Наставник v1 — правило-движок без LLM: §7.1 «Следующий шаг» (on_demand, ОДНА рекомендация по priority), §7.2 sanity-правила (on_correction_result, ВЕСЬ список; предупреждение в Предпросмотре ДО apply, кнопку не блокирует — §12 п.8), третье триггер-семейство on_demand_with_history («мечется» по истории trace_events). Пороги эвристик — не хардкод, а rules/mentor.yaml (§12 п.7). Кнопка «Наставник →» подключается в полосу действий панели «Прогресс» (слот зарезервирован PROGR-5.1 — кнопка сознательно не рендерилась до готовности бэкенда). Зависимости: PROGR-5 (слой 2) готова — бэкенд «уже готов» по постановке.

### Backend (TDD RED→GREEN: tests/api/test_mentor_rules.py, 46 тестов)

app/core/mentor_rules.py (новый): MentorRule/SanityWarning/CorrectionOutcomeSummary/MentorRecommendation; SANITY_RULES (no_effect, over_aggressive, excessive_data_loss — дословно §7.2), HISTORY_RULES (thrashing_detected: окно 10 мин, ≥3 разных стратегий preview без correction_applied — снятие применением; naive-ts→UTC, битый ts→вне окна, dеградация без 500), NEXT_STEP_RULES (8 on_demand-правил: каноническое regularity_before_decomposition + forecast_not_compared_before_export (категория C §11 — включено сразу, данные появятся с Прогнозированием), preprocessing_stationarity_before_modeling, modeling_selected_without_backtest, modeling_candidates_without_selection (Этап 2 §11), missing/outliers attention, validation_sufficiency_attention); evaluate_next_step — первое сработавшее по (priority, rule_id) (min priority = выше срочность), evaluate_sanity — весь список в порядке реестра, evaluate_history_warnings; derive_node_statuses — зеркало фронтенд-логики PROGR-4 (терминалы→done, previewed→warning, profile_viewed→running, последнее событие выигрывает; N-2: run-level с node_id=None не создают узловых фактов; forecasting-события слоя 2 хранят node_id=None (контракт PROGR-1) — узел выводится из типа; фантомов нет через is_known_node); stage_node_summary/phase_text (пересказ уже посчитанного §7.1); конфиг load_mentor_config — fail-closed ImportError (паттерн EDA-JSON §12 п.2), правила читают MENTOR_CONFIG на ВЫЗОВЕ (патч singleton меняет поведение — порог не захардкожен); fail-closed самопроверка реестра на импорте (дубликат rule_id, неизвестный trigger — паттерн TRACE_ROUTES PROGR-3).

rules/mentor.yaml (новый): sanity.over_aggressive.std_collapse_factor=0.2, sanity.excessive_data_loss.max_removed_share=0.3, history.thrashing.window_minutes=10/distinct_strategies=3 — стартовые дефолты §7.2/§12 п.7 с комментарием о калибровке. Находка TDD: float-граница 1−70/100=0.3000…04 рвала правило «ровно 30% — тишина»; доля считается как (before−after)/before.

apps/api/routers/progress.py (+эндпоинты): GET /v1/progress/runs/{run_id}/mentor/next-step (@_durable_ops: 404 неизвестный запуск, 503 слой недоступен — рекомендация по неполной истории выдавала бы уверенный совет на неполных данных; ответ: recommendation + phase_text + summary узлов стадии + history_warnings; N-4 — семантики закрытия/навигации нет); POST /v1/progress/mentor/sanity-check — чистое вычисление над телом (без store/_durable_ops; POST умышленно — тело несёт исход), fail-closed 422 на неизвестную пару (stage, node_id) (паттерн make_node_state). Эндпоинты вне TRACE_ROUTES (ридер трассы не трассируется — паттерн PROGR-4).

### Frontend (TDD: lib/mentor.test.ts, MentorInlineWarning.test.tsx, MentorPanel.test.tsx + расширения)

packages/ui/lib/mentor.ts (новый): типы-зеркала pydantic-схем; buildCorrectionOutcomeSummary — маппинг preview-ответа Мастера в общие имена §7.2 (дословно: «разный набор полей у Missing/Outliers/Regularity сводится к общим именам на клиенте»); worstStdStats — «худшая» колонка по падению std (для over_aggressive; нечисловые/нулевые std пропускаются); fetchSanityWarnings/fetchMentorNextStep — best-effort (сбой → []/null, Мастер и панель работают без Наставника — §12 п.8 сигнал, не принуждение).

packages/ui/components/MentorInlineWarning.tsx (новый): заметный amber-баннер role="alert" над кнопкой применения, весь список предупреждений с чипами severity, «Продолжить всё равно» скрывает до нового preview (дисмисс живёт в рамках одного preview-исхода); кнопку применения не трогает — блокировка физически невозможна (§12 п.8). MentorPanel.tsx (новый): секция внутри «Прогресса» (id=mentor-panel), next-step: ОДНА рекомендация с deep-link «stage.node_id» → href STAGE_DEFS (тот же механизм Link, что ProgressStageFlow §6.2), phase_text, сводка «N/M пройдено», history-замечания («мечется» — в панели, не инлайн, §7.2), «Обновить»; 503/сеть — честная «Наставник недоступен» (role=alert), не «рекомендаций нет»; N-4 — onClose нет по контракту.

Подключение кнопки: ProgressCheckpointBar — «Наставник →» справа (макет §6.2: «[Сохранить точку] … [Наставник →]», слот, зарезервированный комментарием PROGR-5.1), aria-expanded/aria-controls, активная — bg-brand/text-white (контракт pill §4.1); рендерится всегда (третий элемент триады §6.3 — мёртвых кнопок нет, бэкенд готов). ProgressDrawer — состояние mentorOpen, секция MentorPanel между полосой и блок-схемой; закрытия панели не инициирует (N-4). Мастера (§11 Этап 2.1 — Пропуски/Выбросы/Регулярность, мотивация §7.2): PreprocessingMissingPipeline (affected=total_missing, rows из профиля остановки, stats=worstStdStats), PreprocessingOutliersPipeline (+method), PreprocessingRegularityPipeline (violations/rows из preview, без статистик — over_aggressive честно молчит); запрос после preview ДО apply; сброс предупреждений на invalidatePreview/apply. packages/ui/index.ts — экспорты MentorPanel/MentorInlineWarning.

### Верификация

tests/api: 1046 passed / 3 failed — те же три средовых baseline (modeling_workflow catalog-only, neural_capacity память хоста, models_candidates unsupported-гейт), регрессий нет; test_mentor_rules.py 46/46. jest: 145 сьютов / 1726 тестов — все зелёные (новые: mentor 10, MentorInlineWarning 5, MentorPanel 7; bar +3, drawer +4, Мастера +8). typecheck:all — чисто. Тест-находки: в Мастерах PROGR-6-сьютам нужен свой beforeEach (общий jest.fn накапливал mock.calls между тестами — 3 вместо 1 sanity-вызова при счётчике).

### Deliverable

ZIP: cisstat-progr6-mentor-v1.zip — пути репозитория сохранены. НОВЫЕ: app/core/mentor_rules.py, rules/mentor.yaml, tests/api/test_mentor_rules.py, packages/ui/lib/mentor.ts, packages/ui/lib/mentor.test.ts, packages/ui/components/MentorPanel.tsx/.test.tsx, MentorInlineWarning.tsx/.test.tsx. ИЗМЕНЁННЫЕ: apps/api/routers/progress.py, packages/ui/index.ts, ProgressCheckpointBar.tsx/.test.tsx, ProgressDrawer.tsx/.test.tsx, PreprocessingMissingPipeline.tsx/.test.tsx, PreprocessingOutliersPipeline.tsx/.test.tsx, PreprocessingRegularityPipeline.tsx/.test.tsx, worklog/worklog8.md (эта запись). Без commit/push (AGENTS.md).

---

## Task ID: RCH-1 (2026-09-26) — Волна 1 plan_review_charts.md: остановка «Пропуски» — ревизионный refresh трёх графиков Обзора + статический гвард подписки

Синхронизация: main@564cd95 (ff-reset с cfa1213; в промежутке upstream вошли PLAN-REVIEW-CHARTS 1e00ab1 и PROGR-6 564cd95 — Наставник v1, на волну 1 не влияет: PROGR-6 трогает Мастеров остановок, не Обзоры). Правила AGENTS.md: TDD RED→GREEN, без commit/push, ZIP в download.

### Постановка

Реализовать волну 1 (P0) plan_review_charts.md: устранить класс OUTL-1 «графики без явной подписки на refresh» на остановке «Пропуски» — MissingMatrixChart/MissingCorrelationChart (константные URL без параметров вовсе) и MissingBoxplotChart (URL зависит только от ручного выбора колонок) не перезапрашиваются при смонтированном Обзоре после apply исправления/смены режима, тогда как профиль/счётчик перезапрашиваются (refreshKey = missingRefreshKey + datasetVersion). Плюс обязательная часть волны: статический гвард подписки (прецедент ExpandableChartCoverage.test.ts).

### TDD (RED → GREEN)

- RED подтверждён по правильным причинам, триада: (1) гвард ReviewChartsRefreshCoverage — «MissingMatrixChart: принимает refreshKey, включает ревизию (revision|_r)=${refreshKey} в query» (Outliers/Regularity списков — зелёные с первого прогона, дефект изолирован Missing); (2) PreprocessingMissingVisualizations.test.tsx — TS2322 «Property 'refreshKey' does not exist» (компиляционный RED, прецедент OUTL-1); (3) PreprocessingMissingOverview.test.tsx — интеграционный инвариант: профиль перезапросился (2 вызова), а /dataset/missing-matrix остался на 1 вызове (waitFor-timeout) — дефект воспроизведён на смонтированном Обзоре дословно как в отчёте OUTL-1.
- GREEN: PreprocessingMissingVisualizations.tsx — три сигнатуры принимают `refreshKey = 0`, ревизия в query: `/dataset/missing-matrix?revision=…`, `/dataset/missing-correlation?revision=…`, `/dataset/missing-distribution?…&revision=…` (в хвост существующих value_column/indicator_column); эпиграф-комментарий класса дефекта по образцу OUTL-1 (сценарий медленного apply, «неизвестный query-параметр FastAPI игнорирует»). PreprocessingMissingOverview.tsx — refreshKey прокинут во все три чарта. Бэкенд НЕ менялся.
- Тест-паттерн OUTL-1 перенесён дословно: it.each по трём чартам (render refreshKey=0 → fetch#1 с revision=0; rerender refreshKey=2 → fetch#2 с revision=2) + интеграционный инвариант «счётчик обновился ⟹ матрица перезапросилась» (контракт о последнем состоянии, не о числе попыток — loading-flash/active-guard).

### Статический гвард (новый файл, списки — единственный источник правды)

packages/ui/components/ReviewChartsRefreshCoverage.test.ts: REVISION_SUBSCRIBED_CHART_SOURCES (Missing 3 / Outliers 4 / Regularity 2 — каждый export function …Chart обязан принимать refreshKey и включать ревизию в query, число чартов зафиксировано), PROFILE_PROP_OVERVIEWS (18: 7 Preprocessing + 9 EDA вкл. StructuralBreaks + 2 Modeling — negative-guard: sessionApiUrl( запрещён, данные только с profile-пропом), SELF_FETCH_GUARDED_OVERVIEWS (EdaDescriptive: requestKey-гвард с refreshKey в ключе), PROFILE_SELF_FETCH_OVERVIEWS (11: Обзоры Пропусков/Выбросов/Регулярности + вся «Валидация» — самофетч СВОЕГО профиля с deps [refreshKey], собственных fetch-ей данных графиков нет). Инвентарная проверка: объединение списков == 33 файла семейства (Overview|Visualizations, без тестов), без дублей — новый Обзор обязан быть классифицирован ровно в одном списке.

### Верификация

- RED→GREEN целевых сюит: 3 сюита / 51 тест — зелёные (was: RED триада выше).
- Полный jest: **146 сюит / 1764 теста — все зелёные** (базлайн PROGR-6 145/1726 + 1 гвард-сюита + 38 тестов: it.each 3 + инвариант 1 + гвард 34).
- typecheck:all (embedded + standalone) — чисто; npm run build:all — оба приложения ✓ Compiled successfully.
- Бэкенд-проба (scripts/probe_missing_charts_revision.py, python3.13, PROBE OK 4/4): [1] /v1/session/dataset/missing-matrix и missing-correlation — 200 c ?revision=5, payload байт-в-байт совпадает с ответом без параметра; [1] missing-distribution — 200 c &revision=2 (ревизия в хвосте value_column/indicator_column), payload идентичен; [2] после apply (drop_rows) payload матрицы изменился — свежесть данных на сервере подтверждена (как в OUTL-1: источник симптома — только фронтенд). Датасет пробы — детерминированный CSV с зазорами в обеих колонках (mulberry32 seed 20260916, приём probe_outliers_line_stale.py; встроенный sales_demo.csv пропусков не содержит — проверено). Побочный traceback psycopg в пробе — best-effort слой 2 PROGR-5 честно деградирует без Postgres (дизайн), на результат не влияет.
- Расхождения с планом: нет по существу; уточнение классификации гварда против текста плана §3 — «Валидация» отнесена к PROFILE_SELF_FETCH_OVERVIEWS (Обзоры самофетчат СВОЙ профиль с deps [refreshKey] — честнее negative-guard'а «без fetch»), Modeling Traceability/Workflow — в PROFILE_PROP_OVERVIEWS (workflow POST-ы — не self-fetch данных графиков сессионного API); EdaStructuralBreaks — в PROFILE_PROP_OVERVIEWS с пометкой «слой C — волна 2».

### Находки/заметки (не блокеры)

- N-1 (Info): MissingBoxplotChart сохраняет ручной выбор колонок в state при смонтированной вкладке — после apply выбор не сбрасывается (R-1 плана, поведение выбора вне класса refresh, не трогалось).
- N-2 (Info): ревизия стандартизирована как `revision=`; `_r=` Регулярности остаётся (функционально эквивалентен, унификация — волна 3 по решению тимлида); гвард принимает оба.

### Deliverable

ZIP: cisstat-rch1-missing-charts-refresh.zip — пути репозитория сохранены. ИЗМЕНЁННЫЕ: packages/ui/components/PreprocessingMissingVisualizations.tsx (+refreshKey/revision, +эпиграф), packages/ui/components/PreprocessingMissingOverview.tsx (+прокидывание refreshKey), PreprocessingMissingVisualizations.test.tsx (+it.each×3), PreprocessingMissingOverview.test.tsx (+инвариант). НОВЫЕ: packages/ui/components/ReviewChartsRefreshCoverage.test.ts (гвард, 34 теста), scripts/probe_missing_charts_revision.py (бэкенд-проба). ИЗМЕНЁННЫЙ: worklog/worklog8.md (эта запись). Бэкенд/схемы не менялись. Без commit/push (AGENTS.md).

---

## Task ID: PROGR-6-CERT (2026-09-26) — Независимая сертификация Task PROGR-6 (Наставник v1: §7.1 + §7.2, пороги rules/mentor.yaml §12 п.7) — PASSED WITH REMARKS

Сертификатор: независимый аудитор (методология PROGR-1-CERT/PROGR-2/PROGR-3/OUTL-1-CERT). Синхронизация: клон main@564cd95, рабочее дерево чистое; commit/push запрещены (AGENTS.md). Изучены дословно: AGENTS.md, spec_progress.md (§7/§7.1/§7.2/§8/§11/§12 п.7-8), plan_progress.md (строка PROGR-6), вся реализация коммита 564cd95 (движок, роутер, YAML, фронтенд, тесты).

### Верификация заявлений коллеги (все подтверждены)
test_mentor_rules.py 46/46; tests/api 1046 passed / 3 failed — те же три средовых baseline, воспроизведены на родителе 1e00ab1 (не регрессии PROGR-6); jest 145 сьютов / 1726 тестов — зелёные. Поля клиентского маппинга §7.2 сверены со схемами apps/api/schemas.py (DatasetMissing/Outlier/RegularityCorrectionResponse, MissingColumnStatsOut, profile.total_rows) — все существуют, Optional-согласованы.

### Оракулы на своих данных (не копии assert-ов коллеги): 6/6 PASSED + фронтенд 9/9
OR-1 целостность реестров (детектор мёртвых правил: все (stage,node)-пары 8 on_demand-правил в графе; все 12 типов _EVENT_STATUS_MAP испускаются платформой; триггер-семейства дословно §7). OR-2 независимая реимплементация трёх sanity-правил на 500 рандомизированных preview-исходах (seed 260926) + границы: ровно 0.2 — тишина, std_after=0 — срабатывает, рост строк (fictitious_zero) — тишина; ноль расхождений. OR-3 независимая реимплементация окна «метаний» на 300 рандомизированных потоках (наивный/битый ts, дубли, TraceEvent-объекты) + границы apply/preview ровно на window_start; apply вне окна не снимает. OR-4 зеркало derive_node_statuses на фикстуре 12 событий (последнее событие выигрывает; N-2; фантомы; forecasting-узел из типа при node_id=None) — фикстура дублирована в TS-оракуле (кросс-слойная сверка). OR-5 живая проба API: 404/200/422, ОДНА рекомендация §7.1 c deep-link, thrashing в history_warnings, sanity-check с реальной формой preview-ответа Мастера (no_effect + over_aggressive одновременно; drop_rows 40%; ровно 30% — тишина). OR-6 конфиг §12 п.7: канон 0.2/0.3/10/3; fail-closed матрица (нет файла/битый YAML/нет секции/строка/bool — все ImportError). Фронтенд-оракул (packages/ui/lib/progr6cert_oracles.test.ts, 9 тестов): свойства worstStdStats (минимум отношения, пропуск нулевых/нечисловых std, null без валидных колонок), точная проекция buildCorrectionOutcomeSummary, best-effort (HTTP 503/404, сеть, битый JSON → []/null), кросс-слойное зеркало.

### Мутационный анализ: бэкенд 25 KILLED / 26 + фронтенд 4 KILLED / 5; оба SURVIVED охарактеризованы — дыр покрытия нет
Бэкенд (progr6cert_mutations.py, 26 мутантов mentor_rules.py + routers/progress.py + rules/mentor.yaml): инверсии границ (M2/M5/M11/M8), захардкоженный порог (M3), float-регрессия 1−after/before (M4 — убит ровно на кейсе «ровно 30%»: TDD-находка коллеги под защитой), подмена стратегии (M6), порог/окно «мечется» (M7/M9), наивный ts (M10), потеря last-wins/фантом-фильтра/forecasting-вывода (M12/M13/M14), default pending→done (M15), инверсия приоритета §7.1 (M16), обрыв списка §7.2 (M17), гейты 422 (M18/M18b/M19), last_stage (M20), подмена YAML (M21/M22), bool-порог (M23 — убит ТОЛЬКО оракулом), текст шаблона (M24), потеря дедупликации (M25). SURVIVED единственный M18: снятие гейта стадии удерживает контракт 422 гейтом пары (stage, node_id) — защита в глубину (характеризующий M18b с обоими гейтами убит). Фронтенд (progr6cert_front_mutations.py): инверсия минимума worstStdStats (F1), потеря guard нулевого std (F2), перепутанные changed/still (F3), потеря catch-all (F4b) — убиты; F4 (throw внутри try) поведенчески эквивалентен — catch-all перехватывает, best-effort §12 п.8 защищён дважды (характеризация). Восстановление файлов байт-в-байт (sha256, чистый git status); после мутационных прогонов контрольный полный повтор: 1046 passed / 3 baseline failed, jest 146 сьютов / 1735 тестов (1726 коллеги + 9 оракула), 46/46.

### Находки (не блокируют приёмку)
N-1: семантика «мечется» — реализация дословно следует канон-лямбде §7.2 (без фильтра по node_id; cross-node 3 стратегии срабатывают — OR-3; correction_applied в окне снимает), текст спеки же говорит «один и тот же узел» и упоминает паттерн «применение → повтор» — расхождение «текст vs лямбда» в самой спеке; рекомендация Mentor v2: либо node-фильтр, либо фиксация run-level выбора в спеке. N-2: загрузчик гарантирует «число, не bool», но не диапазон — distinct_strategies=1 тревожит с первой попытки, window_minutes=0 слепит правило (OR-6, демонстрация); рекомендована min/max-валидация при калибровке. N-3: round(1/factor) завышает формулировку для неканонических порогов (0.26 → «в 4 раза» при границе 3.85; канон 0.2 точен). N-4: отрицательный std_after (некорректный клиент) триггерит over_aggressive — для валидных данных недостижимо, можно усилить guard'ом. Позитивы: R-1 защита в глубину 422 (M18/M18b), R-2 двойной best-effort (F4/F4b), R-3 float-гвард доли под граничным тестом (M4).

### Вердикт
PASSED WITH REMARKS (N-1…N-4 не блокируют). Приёмка plan_progress.md подтверждена по всем четырём критериям: одно срабатывание §7.1 по priority; весь список §7.2; предупреждение в Предпросмотре ДО apply без блокировки кнопки (§12 п.8); пороги не хардкод (§12 п.7).

---

## Task ID: RCH-2 (2026-09-26) — Волна 2 plan_review_charts.md: слой C — кэш раскрытия, подписанный на мутацию датасета (invalidateChartDetailCache + fingerprint Декомпозиции/Спектрального)

Синхронизация: main@92407a4 (ff-reset с 564cd95; в промежутке upstream вошли RCH-1 84dc8e4 — Волна 1, применённая тимлидом, локальные правки совпали байт-в-байт, и PROGR-6-CERT 92407a4 — независимая сертификация Наставника v1, Обзоры не трогает). Правила AGENTS.md: TDD RED→GREEN, без commit/push, ZIP в download.

### Постановка

Реализовать волну 2 (P1) plan_review_charts.md — тот же класс OUTL-1 «график не подписан на сигнал обновления» в слое C (кэш раскрытия useChartDetailData, Task 97.3): Decomposition/Spectral передавали useChartDetailData БЕЗ fingerprint (комментарий «fingerprint не нужен» написан до эпохи datasetVersion/PREPR-4) — ключ кэша (profileKey, fingerprint, params) переживал apply (column/параметры раскрытия не меняются применением) → раскрытие после apply отдавало stale expanded-payload; EdaStructuralBreaks держит fingerprint=datasetKey, НЕ меняющийся при in-place мутации, а detailCache — модуль-глобальный Map, переживает переходы между модулями. Контракт волны: fingerprint Обзора обязан включать версию мутации датасета (refreshKey = собственный ключ остановки + datasetVersion), плюс ГЛОБАЛЬНАЯ инвалидация кэша в единственной точке истины — обработчике apply «Предобработки».

### TDD (RED → GREEN)

- RED подтверждён по правильным причинам, ровно критерии плана: (1) useChartDetailData.test.tsx — TS2305 «no exported member 'invalidateChartDetailCache'» (отсутствие экспорта — TS-ошибка); (2) TsAnalysisPreprocessing.test.tsx — TS2769 (jest.spyOn не может шпионить отсутствующий экспорт namespace-модуля); (3) PreprocessingDecompositionOverview.test.tsx + PreprocessingSpectralOverview.test.tsx — TS2322×4 «Property 'refreshKey' does not exist» (компиляционный RED, прецедент OUTL-1/RCH-1).
- GREEN: hook — публичный экспорт invalidateChartDetailCache() (detailCache.clear(); __clearChartDetailCacheForTests — делегат, эпиграф «единственная точка истины — обработчик apply»); контейнер — единый handleApplied (bump datasetVersion + invalidateChartDetailCache()), все 10 инлайн-строк onApplied={() => setDatasetVersion((v) => v + 1)} заменены (единственный оставшийся сеттер — внутри handleApplied); Decomposition/Spectral — проп refreshKey?: number, fingerprint: String(refreshKey) (в URL не попадает — только ключ кэша, §6.3.5), устаревшие комментарии «fingerprint не нужен…» заменены канонической формулировкой инварианта; контейнер передаёт суммы decompositionRefreshKey + datasetVersion / spectralRefreshKey + datasetVersion (та же формула, что у Пропусков/Выбросов/Регулярности). EdaStructuralBreaksOverview — БЕЗ функциональных правок, решение зафиксировано комментарием (fingerprint=datasetKey сохраняется, stale-кэш между модулями закрывает глобальная инвалидация). Бэкенд НЕ менялся (fingerprint в URL не входит).

### Тест-паттерн (5 новых тестов)

- useChartDetailData.test.tsx +2: (a) «тот же params, другой fingerprint между сеансами раскрытия — кэш не отдаёт старое» (механизм-лок межремоунтной смены fingerprint — сценарий возврата на остановку, ранее не покрытый; существующий тест «смена fingerprint» покрывал только rerender одного экземпляра); (b) «после invalidateChartDetailCache() следующее раскрытие уходит в сеть, а не в кэш».
- TsAnalysisPreprocessing.test.tsx +1: шпион на экспорте хука (namespace-import + jest.spyOn — вызовы контейнера поздне-связанные через module.exports): ДО apply — инвали­даций нет; apply мастера «Пропусков» (предпросмотр → подтверждение → применение) — ровно ОДНА инвалидация (единственная точка истины, apply мутирует датасет один раз).
- Обзорные интеграционные инварианты +1/+1 (Декомпозиция «Компоненты» / Спектральный CWT): первое раскрытие — expanded-дозапрос, stale-маркер в графике; схлопывание → rerender refreshKey 0→1 (params НЕ менялись) → второе раскрытие обязано уйти в сеть (новый fingerprint) и показать СВЕЖИЙ payload (43.5/44,25), а не stale-запись (40.5/42,75). Уточнение против буквы плана (зафиксировано в plan_review_charts.md): дефект «кэш отдал бы старое» воспроизводится на уровне ОБЗОРОВ (хук механизм поддерживал и так), поэтому (a) в hook-сюите — механизм-лок, а честный RED дефекта — TS2322 Обзоров.

### Верификация

- RED→GREEN целевых сюит: 4 сюита / 96 тестов — зелёные (was: RED-триада выше).
- Гвард и смежные (раскрытие не тронуто): ReviewChartsRefreshCoverage (списки не менялись — Decomposition/Spectral остаются в PROFILE_PROP_OVERVIEWS): прямого sessionApiUrl (в исходнике нет, fingerprint идёт через хук) + ExpandableChartCoverage + ExpandableChartsProvider + EdaStructuralBreaksOverview — 4 сюита / 102 теста зелёные.
- Полный jest: **146 сюит / 1769 тестов — все зелёные** (базлайн RCH-1 146/1764 + 5 новых).
- typecheck:all (embedded + standalone) — чисто; npm run build:all — оба приложения ✓ Compiled successfully.
- E2E-проба бэкенда не требуется (R-5 плана): fingerprint в URL не попадает, сеть/контракты не менялись; пользовательский сценарий «apply → раскрытие → свежий payload» покрыт интеграционными оракулами Обзоров и контейнерным шпионом.

### Находки/заметки (не блокеры)

- N-1 (Info): после волны 2 у Обзоров слоя C двойная защита (defense in depth): fingerprint=String(refreshKey) различает состояния датасета в ключе кэша даже при мимо-инвалидации (например, прямой прокидке refreshKey без handleApplied), глобальная инвалидация закрывает EdaStructuralBreaks и все будущие useChartDetailData-потребители без fingerprint.
- N-2 (Info): refreshKey Обзоров слоя C по умолчанию 0 (проп опционален) — прямые рендеры в тестах без пропа дают fingerprint "0" вместо прежнего "" (одноразовый промах кэша после деплоя — приемлемо, данные перезапросятся).
- N-3 (Info): шпион jest.spyOn(namespace, "invalidateChartDetailCache") перехватывает вызовы контейнера только из-за ts-jest/CommonJS позднего связывания (useChartDetailData_1.invalidateChartDetailCache(...)); при переходе проекта на чистый ESM шпион потребует jest.mock — зафиксировано в комментарии теста.

### Deliverable

ZIP: cisstat-rch2-detail-cache-invalidate.zip — пути репозитория сохранены. ИЗМЕНЁННЫЕ (product): packages/ui/hooks/useChartDetailData.ts (+invalidateChartDetailCache, делегат, эпиграф), packages/ui/components/TsAnalysisPreprocessing.tsx (+handleApplied, 10× onApplied, +refreshKey-суммы в Decomposition/Spectral), PreprocessingDecompositionOverview.tsx (+refreshKey, +fingerprint, канонический комментарий), PreprocessingSpectralOverview.tsx (аналогично), EdaStructuralBreaksOverview.tsx (только комментарий-решение). ИЗМЕНЁННЫЕ (тесты): useChartDetailData.test.tsx (+2), TsAnalysisPreprocessing.test.tsx (+1, шпион), PreprocessingDecompositionOverview.test.tsx (+1, инвариант), PreprocessingSpectralOverview.test.tsx (+1, инвариант). ИЗМЕНЁННЫЕ (док): plan_review_charts.md (статусы исполнения волн), worklog/worklog8.md (эта запись). Бэкенд/схемы не менялись. Без commit/push (AGENTS.md).

---

## Task ID: RCH-3 (2026-09-26) — Волна 3 plan_review_charts.md: hardening — канонический cache-buster revision= (унификация _r=→revision= Регулярности, cache-buster self-fetch EdaDescriptive, TasksCauses механикой B)
Синхронизация: main@befdfcf (ff-reset; в промежутке upstream вошли RCH-1 84dc8e4 — Волна 1, PROGR-6-CERT 92407a4, RCH-2 befdfcf — Волна 2; локальные артефакты прошлой сессии сброшены штатно). Правила AGENTS.md: TDD RED→GREEN, без commit/push, ZIP в download.

### Постановка
Реализовать волну 3 (P2 hardening) plan_review_charts.md по решению тимлида, с включением в волну TasksCauses (план предполагал отдельную постановку; тимлид объединил): (1) унификация cache-buster — Регулярность была единственным отклонением от канона OUTL-1 с legacy-параметром _r= (Task 72); (2) EdaDescriptive — единственный self-fetch графика в EDA имел requestKey-гвард эффекта, но URL не нёс ревизии (теоретический HTTP-кэш промежуточных слоёв); (3) TasksCauses — самофетч хаба «Задачи» ходил в сеть ОДИН раз по modelingDone (deps [modelingDone, sessionLoading]), сигнал обновления не входил ни в deps, ни в URL.

### TDD (RED → GREEN)
RED подтверждён по правильным причинам, ровно 7 падений: (1) TasksCauses.test.tsx — TS2322 «Property 'refreshKey' does not exist» (компиляционный RED, прецедент OUTL-1/RCH-1/RCH-2, сюит не компилируется); (2) PreprocessingRegularityVisualizations.test.tsx — behavioral ×2: в URL был _r=1, канонического revision=1 нет + негатив «не содержит _r=» падал; (3) EdaDescriptiveOverview.test.tsx — behavioral ×2: column=Price&revision=0:Price отсутствовал (URL без ревизии вовсе); (4) ReviewChartsRefreshCoverage.test.ts — ×3: Регулярность (канон-регэксп + legacy-бан), EdaDescriptive (обязанность revision=${requestKey}), TasksCauses (нет refreshKey — новый список 5).
GREEN: PreprocessingRegularityVisualizations.tsx — оба URL ?_r=→?revision=, эпиграф-комментарий дополнен (подписка с Task 72, канонизация волной 3, сценарий медленного apply, «FastAPI игнорирует неизвестный параметр»); EdaDescriptiveOverview.tsx — URL self-fetch дополнен &revision=${requestKey} (URL — чистая функция ключа эффекта: любое изменение refreshKey/фичи меняет и URL), комментарий по месту; TasksCauses.tsx — проп refreshKey?: number (дефолт 0), deps эффекта [modelingDone, sessionLoading, refreshKey], вызов fetchCauses(undefined, refreshKey), эпиграф-комментарий; lib/tasks.ts — fetchCauses(cardId?: string, revision?: number), query строится URLSearchParams: card_id (как прежде) + revision при переданном значении (канонический cache-buster, String(revision)). Гвард ужесточён: канон-регэксп revision=${refreshKey} вместо (revision|_r), явный негатив / _r=${refreshKey/ (запрет отката унификации), список 3 обязан revision=${requestKey}, новый список 5 REVISION_SUBSCRIBED_SELF_FETCH_SOURCES (TasksCauses.tsx + lib/tasks.ts; вне FAMILY_RE — в инвентарь 33 файлов семейства сознательно не входит, шапка гварда обновлена: пять списков).
Тест-паттерн (8 новых тестов)
PreprocessingRegularityVisualizations.test.tsx +1 (it.each ×2 графика): порт it.each-паттерна Волны 1 — render refreshKey=1 → первый fetch содержит путь + revision=1 + НЕ содержит _r=; rerender refreshKey=2 → второй fetch revision=2. Фикстура — надмножество полей обоих ответов (ранние return-ы на пустые bins/events — контракт о ПОВТОРНЫХ запросах, не об отрисовке).
EdaDescriptiveOverview.test.tsx +2: (a) первый запрос визуализации несёт revision=0:Price (requestKey = refreshKey:feature); (b) rerender refreshKey 0→1 при НЕИЗМЕННОЙ фиче — дозапрос (requestKey «1:Price» ≠ cacheKey «0:Price»), последний вызов несёт revision=1:Price (контракт о последнем вызове, R-2).
TasksCauses.test.tsx +3: (a) первый поход в сеть fetchCauses(undefined, 0) (дефолт refreshKey); (b) rerender refreshKey 0→2 БЕЗ смены стадии — повторный вызов (undefined, 2) (сигнал меняется ⟹ перезапрос — суть механики B); (c) rerender БЕЗ смены refreshKey — новых вызовов нет (дисциплина deps: derived-массивы methods/factors с новой ссылкой на каждый рендер не должны попасть в deps — гвард перерасхода запросов).

### Верификация
Целевые сюиты RED→GREEN: 4 сюита / 61 тест (базлайн до правок 4/53 — зелёный зафиксирован перед RED).
Смежные: PreprocessingRegularityOverview (прокидывание refreshKey не менялось), TsAnalysisEDA, TasksHub, heading-indigo-calibration, ExpandableChartCoverage — 6 сюитов / 118 тестов зелёные.
Полный jest: 146 сюитов / 1777 тестов — все зелёные (базлайн RCH-2 146/1769 + 8 новых).
typecheck:all (embedded + standalone) — чисто; npm run build:all — оба приложения ✓ Compiled successfully.
E2E-проба бэкенда не требуется (R-5 плана): ревизия — неизвестный query-параметр, FastAPI игнорирует (прецедент OUTL-1 в проде: outliers/missing/regularity-эндпоинты уже получали _r=/revision= без последствий); бэкенд и контракты схем не менялись.

### Находки/заметки (не блокеры)
N-1 (Граница, зафиксирована в плане): в приложении НЕТ счётчика мутаций сессии, видимого странице /tasks/causes (datasetVersion — локальный стейт контейнера Предобработки; updated_at сессии клиент не экспонирует и не опрашивает). Поэтому для TasksCauses реализована МЕХАНИКА B (точка подписки: проп + deps + ревизия в URL) — дословно «если решать — той же механикой B» из плана; прокидывание живого сигнала — одна строка страницы при появлении счётчика мутаций (отдельная архитектурная постановка). Сегодня поведение монтирования не изменилось, URL обрёл канонический cache-buster (revision=0).
N-2 (Info): унификация _r=→revision= меняет URL запросов Регулярности — браузерный HTTP-кэш одноразово промахнётся после деплоя (данные перезапросятся; тот же эффект был при введении revision= в OUTL-1).
N-3 (Info): revision EdaDescriptive = ${requestKey} (содержит двоеточие «1:Price») — валидный query-символ RFC 3986, FastAPI параметр игнорирует; значение покрывает BOTH refreshKey и фичу — URL идентифицирует попытку эффекта полностью.
N-4 (Info): fetchCauses переведён на URLSearchParams — card_id кодируется эквивалентно encodeURIComponent (семантика сохранена), revision добавляется только при переданном значении (explicit 0 включается: revision !== undefined).

---

## Task ID: PROGR-7 (2026-09-26) — Отчёт для пользователя (spec_progress.md §5.4): GET /v1/progress/runs/{run_id}/report?format=md|html — линейный отчёт из trace_events, терминология «Метрики и алгоритм», forecasting-экспорт по ссылке

Синхронизация: main@ef944f2 (ff-reset с befdfcf; в промежутке upstream вошла Волна 3 RCH-3 — канонический cache-buster revision=. Локальная запись синхронизации/онбординга прошлой сессии восстановлена append-ом — upstream её не содержал; случайные незакоммиченные удаления apps/{embedded,standalone}/app/upload/page.tsx отброшены — файлы существуют в upstream). Правила AGENTS.md: TDD RED→GREEN, без commit/push, ZIP изменённых/новых файлов в download.

### Постановка

Задача PROGR-7 из plan_progress.md (spec_progress.md §5.4): GET /v1/progress/runs/{run_id}/report?format=md|html — линейный отчёт из trace_events долговременного слоя: по каждому пройденному узлу — что нашли, что исправили, чем кончилось. Терминология отчёта НЕ изобретается заново — переиспользуются те же тексты «Метрики и алгоритм» остановок. Для Прогнозирования — ПО ССЫЛКЕ на GET .../forecast/{id}/export.json, сериализация не дублируется. Зависимости: PROGR-1…PROGR-6 готовы.

### Ключевые решения

- **app/core/run_report.py (новый, чистый движок без HTTP).** Модель: ReportFact (ts+текст+ссылки) → ReportNode (метка+методология+хронологические факты) → ReportStage (узлы в порядке ПЕРВОГО касания + блок «Решения уровня этапа») → RunReportModel (мета §5 + секции в каноническом порядке STAGES; этапы без событий опускаются). Сортировка хронологическая стабильная, нечитаемый ts — в конец (зеркало sortEventsChronologically packages/ui/lib/progress.ts). Защитный контур: событие неизвестной стадии (прямой TraceEvent мимо гейта make_trace_event) — в хвостовую секцию с id-меткой, отчёт не падает.
- **Терминология из ЕДИНОГО промотированного реестра знаний (EDU-API-1), не новая копия.** Ключевая находка постановки: backend-реестр УЖЕ существует — apps/api/knowledge (registry_data.json, паритет байт-в-байт с TS-источником застрахован jest-тестом при каждом прогоне; help-parity.fixture.json — оракул 77 записей). Отчёт читает его через find_article: методология узла — body_md facet=metrics (validation/preprocessing/eda) / facet=stage_overview (modeling); честный None на промахе (no fabricated results). Метки узлов — заголовки тех же текстов без префикса «Метрики и алгоритм: » (механический вывод, паттерн title реестра). Метки стадий — stage_labels_ru реестра: ДОБАВЛЕН публичный аксессор KnowledgeRegistry.stage_label (аддитивно, честный id на неизвестной стадии). Локальный fallback-словарь — только для узлов без статей (Загрузка; 4 типа событий Прогнозирования), значения синхронны NODE_LABELS packages/ui/lib/progress.ts; последний fallback — сам node_id. Файлы слоя знаний (help.ts/fixture) НЕ тронуты — фронтенд-регрессий ноль.
- **Строки фактов из payload (§4.1: факты результата, не сырой ответ).** 19 шаблонов event_type: upload_completed (демо-загрузка без payload_keys — честная строка без выдуманных чисел), correction_applied/previewed (стратегия/метод + счётчики total_changed/rows_removed/total_missing/total_outliers/total_violations/total_invalid/invalid_policy/target_column_reset — отсутствующие опускаются; предпросмотр честно помечен «Изменения не применены»), mode_changed/target_column_changed/profile_viewed/passport_captured, backtest_run/tuning_trial_completed/model_selected/model_card_generated, forecast_generated/compared/sensitivity_computed/exported, run-level run_paused/run_resumed (restored-вариант)/checkpoint_saved (метка + ссылка на событие). Неизвестный тип — строка аудита (R3 PROGR-1-CERT: такие события хранятся, отчёт не падает и не выдумывает фактов).
- **Forecasting — ссылкой (§5.4 дословно).** forecast_generated/forecast_exported несут [Полные данные прогноза (export.json)](/v1/session/modeling/forecast/{forecast_id}/export.json) — href из payload.forecast_id; сериализация не дублируется. Контракт PROGR-1: forecasting-события слоя 2 хранят node_id=None — узел выводится из типа (4 канонических типа == узлы графа §2, зеркало derive_node_statuses PROGR-6); N-2 соблюдён для остальных stage-level событий (блок «Решения уровня этапа», фантомных узлов нет).
- **Рендеры: md — канон; html — самодостаточный документ.** md: заголовок/мета-буллеты/## этапы/### узлы + методология вербатим + буллеты «ts — факт». html: полный документ lang=ru, встроенный стиль, методология white-space:pre-line, ВСЕ динамические значения через html.escape (payload несёт пользовательские данные — имя файла; тест с именем «prices <v2>.csv» + <script>-инъекция). Рендеры — чистые функции над моделью: формат и есть контракт ответа (Response, не pydantic-модель).
- **REST (progress.py): GET /runs/{run_id}/report** — @_durable_ops (паттерн PROGR-5/6): 404 неизвестный запуск, 503 слой недоступен (отчёт по неполной истории выдавал бы неполные факты за полные — та же логика, что next-step); format через Query(alias="format", pattern="^(md|html)$") — 422 на неизвестный формат (pdf — не контракт plan_progress.md, fail-closed); media_type text/markdown|text/html charset=utf-8 + Content-Disposition inline с именем report-{run_id}.md|html. Ридер трассы сам не трассируется — вне TRACE_ROUTES (паттерн PROGR-4/5, тестом).

### TDD и верификация

- RED: 48 failed + 9 errors по правильной причине (ModuleNotFoundError: run_report / AttributeError: stage_label) — зафиксировано до реализации. Тест-находка TDD: payload-ключ «stage» (passport_captured) коллизирует с параметром make_trace_event — тесты пишут payload через replace(), тот же паттерн, что PROGR-3/trace_hook (двойная проверка решения рантайма).
- GREEN: tests/api/test_run_report.py 61/61 — реестр (stage_label канон 6 стадий + честный id), терминология (метки из metrics/stage_overview + fallback upload/forecasting + методология вербатим + честные None), строки фактов (19 типов + варианты payload + неизвестный тип), сборка модели (канонический порядок стадий, узлы по первому касанию, N-2, forecasting-вывод узла из типа, хронология с нечитаемым ts в конец, статусы active/paused/completed/abandoned, защитная хвостовая секция), рендеры (md-структура + методология вербатим + export-ссылка + честный пустой отчёт; html-скелет + экранирование payload + escape-эквивалентность текстов реестра + ссылки), REST (200 md дефолт/200 html/404/422 pdf/503 сбой слоя/ссылка export.json/изоляция слоя 2 от чужих сессий/не трассируется/N-4 — нет семантики панели/пустой запуск честен).
- tests/api полный: **1110 passed / 1 skipped** (было 1049+1 перед задачей: +61 новых, падений ноль; три «средовых» падения baseline PROGR-2/3-CERT в этой среде НЕ воспроизводятся — при установке полного requirements + нейро-группы каталожные гейты зелёные).
- Jest полный: **146 сюитов / 1777 тестов — зелёные** (фронтенд задачей не тронут, baseline RCH-3 воспроизведён). typecheck:all чисто; npm run build:all зелёный.
- Смоук-просмотр md/html на полном сценарии (14 событий, 6 стадий, чекпоинт с меткой, паспорт, прогноз+экспорт): структура, методология вербатим, ссылки export.json — корректны; скрипт смоука после проверки удалён (покрыто тестами).

### Находки/заметки (не блокеры)

- N-1 (Info): методология в отчёте — вербатим-тексты реестра, они длинные (сотни знаков на узел); компактный режим (например, ?methodology=short или первые N абзацев) — решение при появлении UI-кнопки скачивания (вне backend-контракта PROGR-7).
- N-2 (Info): stage_overview-тексты Моделирования дают метки узлов графа; для Прогнозирования метки — fallback-словарь движка (4 значения, синхронны NODE_LABELS фронтенда). Если NODE_LABELS меняются — синхронизировать FALLBACK_NODE_LABELS (зафиксировано комментарием и тестом значений).
- N-3 (Info): Content-Disposition inline — отчёт открывается браузером по GET напрямую; при появлении «Скачать отчёт» на панели фронтенд может использовать download-атрибут ссылки, менять бэкенд не нужно.
- R-1 (Low): отчёт читает ВСЕ события запуска без пагинации (R-1 PROGR-5: журнал целиком; объёмы одной платформы §12 п.1 — приемлемо; пагинация — по факту PROGR-8-агрегатов).

### Deliverable

ZIP: cisstat-progr7-user-report.zip — пути репозитория сохранены. НОВЫЕ: app/core/run_report.py; tests/api/test_run_report.py. ИЗМЕНЁННЫЕ: apps/api/routers/progress.py (+эндпоинт report §5.4); apps/api/knowledge/registry.py (+публичный stage_label); worklog/worklog8.md (эта запись). Бэкенд-слой знаний/фронтенд/схемы не менялись. Без commit/push (AGENTS.md).
