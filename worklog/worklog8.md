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

---

## Task ID: PROGR-7-CERT (2026-09-27) — Независимая сертификация Task PROGR-7 (отчёт §5.4) — PASSED
Синхронизация: main@0c7ec6b (коммит PROGR-7). Сертификатор независим от исполнителя: продукт-файлы задачи не менялись, commit/push не выполнялись (AGENTS.md), рабочее дерево чистое после всех прогонов.

### Методика
Изучены spec_progress.md §5.4/§4.1/§5, аддендум v4 (Часть 5), plan_progress.md (строка PROGR-7), дифф 0c7ec6b (app/core/run_report.py 670 строк — движок без HTTP; apps/api/routers/progress.py +эндпоинт; apps/api/knowledge/registry.py +7 строк аддитивно; tests/api/test_run_report.py 61 тест). Контроль на СОБСТВЕННЫХ данных сертификатора — сценарии не копировались из коллегиального тест-файла.

### Верификация
- Базлайн воспроизведён ТОЧНО: tests/api/test_run_report.py 61/61; полный tests/api/ 1110 passed / 1 skipped (после установки полного requirements: statsmodels 0.15.0, pandera, PyWavelets, ruptures, prophet, statsforecast, arch, torch-cpu + neuralforecast 3.2.2; и изоляции DATABASE_URL песочницы через CISSTAT_RUNS_BACKEND=memory). До установки — 22 средовых падения смежных сьютов (нейро-гейты/симуляция/структурные сдвиги), подтверждает находки PROGR-2/3-CERT, к PROGR-7 отношения не имеет.
- Oracle-тесты (scripts/cert7_oracles.py): 70/70 PASSED на своих данных — метео-ряд 120 точек (сид 20260926), свои XSS-инъекции (<script>alert("cert7"), инъекция в run_id/forecast_id/label), свои нечитаемые ts, своя неизвестная стадия, E2E живого сеанса (upload→паспорта→бэктесты naive/ets→compare→selection→Model Card→прогноз→реальный GET export.json→отчёт md/html). Ключевые оракулы: методология == body_md реестра байт-в-байт; метка == заголовок без префикса; хронология внутри узла с нечитаемыми в конец (стабильность, зеркально фронтенду); N-2 без фантомных узлов; forecasting-узел из типа; ссылка export.json == реальному forecast_id сеанса (GET 200); счётчики коррекций только из payload; честные строки аудита; канонический порядок STAGES + защитный хвост; 404/422 pdf/503-гейт/media-type/Content-Disposition; ридер не трассируется; изоляция слоя 2 (событие только слоя 1 в отчёт не попадает); пустой запуск честен. В ходе калибровки оракулов три первичных «падения» — ошибки самих оракулов (хронология гарантирована внутри узла, run_id 12 символов, подстрока «train 100 / test 20»), не дефекты реализации; после исправления — все 70 зелёные.
- Мутационные тесты (scripts/cert7_mutations.py): 16/16 KILLED, kill-rate 100%, каждый мутант убит ОБОИМИ контролями (коллегиальный сьют + оракулы сертификатора). Мутанты: reversed(STAGES); нечитаемые ts→0.0; sort reverse; body_md[:80]; префикс метки не срезан; href→export.csv; escape(fact.text) убран (XSS); node_id or STAGES[0] (фантомные узлы N-2); вывод forecasting-узла из типа убран; счётчики коррекций отключены; пометка предпросмотра убрана; строка аудита→пустая; events_total−1; pattern допускает pdf (fail-open 422); md→text/plain; хвостовая секция отброшена. Тестовый контур задач не имеет заметных дыр на периметре §5.4.

### Находки (не блокеры)
- R-1 (Info, средовое): базлайн требует полного requirements + нейро-группы и изоляции DATABASE_URL среды; воспроизводит observation исполнителя.
- R-2 (Info): фронтенд-базлайн jest в этой сессии не гонялся (node_modules отсутствуют); компенсирующий контроль — дифф коммита без фронтенд-файлов, аддитивность registry.py, бэкенд-сьюты слоя знаний зелёные (58 passed/1 skipped), паритет-тесты help.test.ts/promote_knowledge_registry.test.ts существуют в репозитории.
- R-3 (Info): подтверждена R-1 исполнителя — отчёт без пагинации, приемлемо для §12 п.1.
- R-4 (Info): events_total — число событий слоя 2 (не строк факта), консистентно md/html/мета — зафиксировано оракулами.

### Вердикт
PASSED. Артефакты: scripts/cert7_oracles.py (70 оракулов, standalone), scripts/cert7_mutations.py (16 мутантов, автооткат), CERT_REPORT_PROGR-7.md (полный отчёт), ZIP в download. Без commit/push (AGENTS.md).

---

## Task ID: PROGR-8 (2026-09-27) — Admin-панель (§10) + офлайн-потребители (§9), категория D | backend+frontend

Синхронизация: main@5b7c1cd (коммит PROGR-7-CERT). Правила AGENTS.md: TDD RED→GREEN, без commit/push, ZIP изменённых/новых файлов в download.

### Постановка

Задача PROGR-8 из plan_progress.md: Admin-панель мониторинга (spec_progress.md §10) + офлайн-потребители (§9) — категория D (ось времени/данных). Ожидаемые файлы: `AdminProgressDashboard.tsx`, `GET /v1/progress/admin/*` (API-ключ, `Role.ADMIN`). Приёмка: агрегаты по корпусу; частота sanity-предупреждений по правилу/узлу; старт — по накоплении данных (не гейтится кодом). Зависимости: PROGR-1…7 готовы.

### Ключевые решения

- **Журнал наблюдений Наставника (новая сущность долговременного слоя).** Частоты §7.1/§7.2 нигде не персистились: sanity-check — чистое вычисление над телом запроса, next-step — вычисление над трассой. Почему НЕ trace_events: трасса — канон §4.1 (события РЕШЕНИЙ аналитика); служебная телеметрия не имеет шаблона в отчёте §5.4 (стала бы «строкой аудита») и узлового факта — загрязнение пользовательских артефактов. Решение: `MentorObservation` (замороженный датакласс, fail-closed: неизвестный obs_kind/пустые run_id|rule_id — ValueError), таблица `mentor_observations` (append-only, BIGSERIAL seq, БЕЗ FK — телеметрия переживает удаление запуска, агрегаты частот корпусные), DDL синхронно в MIGRATION_STATEMENTS и ops-файле migrations/0001. Контракт ResearchRunStore +2 метода (append/list — список ВЕСЬ: объёмы одной платформы §12 п.1, паттерн «журнал целиком» R-1 PROGR-7), реализации Memory (lock) и Postgres (ON CONFLICT DO NOTHING).
- **Точки записи — best-effort, ответы не меняются.** (1) `POST /mentor/sanity-check`: run-контекст из cookie-сессии (фронтенд шлёт credentials: include — ТЕЛО ЗАПРОСА НЕ меняется, обратная совместимость §7.2; нет cookie/сессии/run_id — записей нет, «предупреждение вне исследования не существует для корпуса»); по одному наблюдению на КАЖДОЕ сработавшее правило (их список §7.2). (2) `GET /runs/{run_id}/mentor/next-step`: запись ВЫДАННОЙ рекомендации (частота выдач — «какие рекомендации даются чаще всего», §10 дословно; повторные вызовы накапливаются). Обе — try/except с warning (паттерн record_run_event/_mirror_to_layer1): сбой журнала не ломает ответ (предупреждения вспомогательны, §12 п.8). Троттлинг не нужен — вызовы человеко-масштаба (клик preview / открытие Наставника), в отличие от рендер-поллинга profile_viewed.
- **Движок агрегатов — app/core/admin_analytics.py (чистый, без HTTP, паттерн run_report.py PROGR-7).** Вход — словари канонических форм (to_dict), выход — иммутабельные модели; сериализация — роутер. Состав §10 дословно: запуски по статусам за период (period_days по читаемому created_at; нечитаемый — в all-time, вне периода — честно; окно включительно); время по стадиям (span first→last читаемого ts внутри запуска, измеримо при ≥2 событиях; нечитаемые ts пропускаются — деградация, паттерн _parse_event_ts; сортировка по mean desc — «где застревают»); топ warning/error-узлов (статусы derive_node_statuses — зеркало PROGR-6; счёт ПО ЗАПУСКАМ, фантомов нет); частота правил §7.1 (по журналу next_step); sanity по правилу И по узлу (две проекции журнала; наблюдение без node_id — по правилу да, по узлу нет); предпочтения Прогнозирования §9 (model_id/horizon/alpha из payload forecast_generated, spec_forecasting2 §9.3 п.5). Период применяется ТОЛЬКО к счётчикам запусков (§10: «запуски за период»), остальные агрегаты — по накопленному корпусу. Пустой корпус — честные нули, не заглушка (не гейтится кодом ✓).
- **Банк кейсов (§9) — алгоритмическая эвристика отбора.** Кандидат: status=completed + финальный бэктест-скор + малое число warning-узлов + малое число sanity-предупреждений («чистые» прохождения). Финальный бэктест = ПОСЛЕДНИЙ backtest_run запуска; его payload `mape` — доказательство скора; MAPE lower-is-better → порог-максимум (честная инверсия формулировки §9 «скор выше порога» для lower-is-better метрики, зафиксировано в докстринге). Без mape у финального бэктеста — доказательства нет, кандидат не отбирается (no fabricated results). Отобранные run_id + evidence — для офлайн-суммаризации (LLM-джоба ВНЕ сервиса, §9 дословно); RAGFlow индексирует кейсы, дообучение — вне спеки, поэтому экспорта сырого корпуса нет (дисциплина объёма).
- **Авторизация §10 дословно — не новая система прав.** `require_admin_role` в apps/api/auth.py: фабрика зависимостей (паттерн require_capability) над тем же get_current_principal; проверяется РОЛЬ, не capability — доступ определяется ИДЕНТИЧНОСТЬЮ, полные capabilities internal_analyst админку не открывают (403). 401 — неверный ключ, 500 — CISSTAT_API_KEYS не настроены (существующее поведение).
- **REST: два эндпоинта в progress.py** (namespace /v1/progress/admin/*): GET /admin/overview?days=1..730&top=1..50; GET /admin/case-bank/candidates?max_backtest_mape=&max_warning_nodes=&max_sanity_warnings= (+эхо критериев и total_completed для прозрачности панели). Оба @_durable_ops (503 — слой недоступен: агрегаты по неполному корпусу выдали бы неполную картину за полную, паттерн PROGR-5/6/7), оба НЕ в TRACE_ROUTES (ридеры не трассируются), pydantic-схемы — зеркало моделей движка.
- **Дополнение хука (единственная правка PROGR-3-области, аддитивная):** dotted-ключи whitelist — "metrics.mape" в backtest_run; `_extract_payload` проходит по сегментам, хранит под ПОСЛЕДНИМ сегментом (корпус — плоские ключи §4.1); промежуточный уровень отсутствует/не dict — ключ честно опускается. Плоские ключи работают как прежде. Мотивация: скор финального бэктеста в корпусе — доказательство эвристики §9 (mape жил в BacktestResponse.metrics, белый список был плоским).
- **Frontend: AdminProgressDashboard.tsx (самостоятельный, без AppShellProvider) + lib/admin.ts + страница apps/embedded/app/admin/progress.** §6.3 «(только Role.ADMIN)»: панель НЕ часть cookie-оболочки аналитика — ключ вводится в панели (type=password, aria-label), живёт ТОЛЬКО в стеё вкладки (не localStorage/sessionStorage), уходит только в заголовок X-API-Key. credentials НЕ включаются. Состав — все блоки §10 + §9; пустой корпус — честное пояснение; 401/403 — различимые сообщения. Метки — переиспользованы runStatusLabel/stageLabel/nodeLabel lib/progress (единый источник, не новая копия). Страница в embedded (внутренний контур CISStat), экспорт из index.ts.

### TDD и верификация

- RED: backend — ImportError: MentorObservation / ModuleNotFoundError: admin_analytics; frontend — TS2307: Cannot find module './AdminProgressDashboard'. Зафиксированы до реализации.
- GREEN: tests/api/test_admin_analytics.py 28/28 (движок на собственных данных: период/границы, нечитаемые created_at/ts, неизмеримые стадии, агрегаты mean/median, топ-узлы с фантом-гейтом и done-исключением, частоты правил/узлов, наблюдение без node_id, предпочтения прогнозирования с пропусками, банк кейсов — 10 сценариев включая «последний backtest финален» и нечитаемый mape, пустой корпус, события-призраки); tests/api/test_admin_progress_api.py 23/23 (авторизация 401/403/500/200, изоляция internal_analyst, агрегаты, 422-валидация, 503-гейт, не трассируются, запись наблюдений sanity/next-step включая без-cookie/без-warnings/best-effort-сбой/накопление, dotted-path хука ×4).
- Полный pytest tests/api: **1145 passed / 1 skipped / 16 failed — все 16 падений в test_forecasting_session.py воспроизведены на ЧИСТОМ baseline (git stash) бит-в-байт** — средовой drift (torch 2.14/pydantic vs эпоха сертификации), к задаче отношения не имеет; 1145 = 1110 baseline + 51 новый, регрессий ноль. Среда дотянута до полного requirements в ходе задачи (PyWavelets, ruptures, pandera, arch, statsforecast 2.1.1, prophet, cmdstanpy, torch-cpu, neuralforecast 3.2.2, psycopg[binary]).
- Полный jest: **146 сюитов / 1785 тестов — зелёные** (baseline RCH-3 1777 + 8 новых). typecheck:all чисто; npm run build:all — оба приложения ✓ Compiled successfully.
- Находка среды TS: jest.tsconfig strict=false → TS 6.0.3 НЕ сужает дискриминированные объединения по булеву дискриминанту (подтверждено минимальным репро) → AdminResult спроектирован плоским {ok, status, data}, не union.

### Находки/заметки (не блокеры)

- N-1 (Info): наблюдения next-step/sanity не имеют ретеншена — объёмы человеко-масштабных вызовов малы; TTL/ротация — решение при появлении PROGR-агрегатов в проде (тот же класс, что калибровка троттлинга §12 п.6).
- N-2 (Info): частоты §7.1/§7.2 честно = «выданные/сработавшие с момента запуска журнала»; исторические события до PROGR-8 не заполняются задним числом (mape в backtest_run — только у новых событий) — категория D («старт — по накоплении данных») это прямо допускает.
- N-3 (Info): период (days) применяется только к счётчикам запусков; периодизация остальных агрегатов — при росте корпуса (SQL-агрегации §12 п.1 — зрелая оптимизация).
- N-4 (Info): ключ админа в панели — в стеё вкладки (перезагрузка = повторный ввод); sessionStorage отклонён осознанно (XSS-поверхность > удобство для админ-контура).
- R-1 (Low, средовое): 16 средовых падений test_forecasting_session (baseline) — вне задачи; воспроизводятся без изменений задачи.

### Deliverable

ZIP: cisstat-progr8-admin-offline.zip — пути репозитория сохранены. НОВЫЕ: app/core/admin_analytics.py; packages/ui/lib/admin.ts; packages/ui/components/AdminProgressDashboard.tsx (+.test.tsx); apps/embedded/app/admin/progress/page.tsx; tests/api/test_admin_analytics.py; tests/api/test_admin_progress_api.py. ИЗМЕНЁННЫЕ: apps/api/research_runs.py (+MentorObservation, +DDL, +2 метода store); apps/api/migrations/0001_research_runs.sql (дубль DDL); apps/api/auth.py (+require_admin_role); apps/api/trace_hook.py (dotted-path, +metrics.mape); apps/api/routers/progress.py (+/admin/*, запись наблюдений); packages/ui/index.ts (+экспорт); worklog/worklog8.md (эта запись). Без commit/push (AGENTS.md).

---

## Task ID: PROGR-8-CERT (2026-09-27) — Независимая сертификация Task PROGR-8 (Admin-панель §10 + офлайн-потребители §9) — PASSED WITH REMARKS

Синхронизация: main@326fc21 (коммит PROGR-8 исполнителя). Сертификатор независим
от исполнителя: продукт-файлы задачи не менялись, commit/push не выполнялись
(AGENTS.md), рабочее дерево чистое после всех прогонов (только артефакты
сертификатора). Полный отчёт — CERT_REPORT_PROGR-8.md.

### Методология

Честная независимая сертификация по прецедентам PROGR-1…7-CERT: воспроизведение
заявлений исполнителя, кросс-верификация §9/§10/§5/§4.1/§12 п.8 по живым исходникам,
независимые оракул- и мутационные тесты на СВОИХ данных сертификатора (свой
детерминированный корпус с инъекцией now; свой E2E через демо-сеанс по HTTP;
фикстуры исполнителя не использовались).

### Воспроизведение заявлений

- test_admin_analytics.py + test_admin_progress_api.py — 51/51.
- Полный tests/api: 3 средовых baseline (modeling_workflow/neural_capacity/
  models_candidates — известный набор с PROGR-1) + 16 в test_forecasting_session,
  воспроизведённые бит-в-байт на родителе 5b7c1cd (worktree) — средовой дрейф,
  регрессий ноль.
- Полный jest: 147 сюит / 1785 тестов — все зелёные; typecheck:all чисто.

### Независимые оракулы — 89/89 PASSED (scripts/cert8_oracles.py, scripts/cert8_oracles_store_api.py)

O1–O6 движок (35): границы/окно периода §10 (обе границы включительны, будущий
created_at вне, нечитаемый — all-time); время по стадиям с асимметрией
mean(12.33)≠median(10) как анти-мутационный контроль; счёт problem-узлов ПО
ЗАПУСКАМ + last-event-wins + фантом-гейт; точные проекции журнала §7.1/§7.2
(чужой obs_kind не смешивается; без node_id — по правилу да, по узлу нет);
частоты Прогнозирования §9 со строкованием чисел; банк кейсов §9 — последний
backtest финален (40→8 кандидат, 5→50 нет), без/нечитаемый mape — нет
доказательства, границы == включительны, sanity чужих run_id не текут,
сортировка mape asc + run_id.
O7–O12 слой 2/хук/REST/E2E (54): fail-closed MentorObservation (3 ValueError);
roundtrip 8 полей; DDL-синхронность MIGRATION_STATEMENTS ↔ migrations/0001
(9 колонок, типы дословно, UNIQUE — разбором обоих источников); dotted-хук
(metrics.mape→плоский mape, пропуски честные, mape=null сохраняется, РЕАЛЬНАЯ
строка backtest несёт metrics.mape — сверено с BacktestResponse.metrics
schemas.py); REST 401/403×2/422(нет заголовка)/500/200, границы days/top,
gt=0 mape, админ-ридеры не трассируются, пустой корпус — честные нули;
E2E: демо-сеанс → run_id → sanity-наблюдение с cookie-контекстом → best-effort
(сбой журнала — 200) → next-step по подсеянному model_selected (реальный
record_run_event) → admin/overview + case-bank по HTTP с полной evidence.

### Мутационный прогон — 25/25 KILLED, 0 SURVIVED (scripts/cert8_mutations.py)

Два независимых контроля на мутант: коллегиальный сьют (51) + оракулы
сертификатора (89). Убиты обоими: 18; ТОЛЬКО оракулами сертификатора: 7
(M4 mean≠медиана на асимметрии; M12 граница mape; M14 атрибуция sanity
своему run_id; M16 сортировка кандидатов; M17 fail-closed obs_kind;
M18 roundtrip node_id; M19 копийность списка журнала) — собственный контроль
добавил реальную убийственную силу. Покрыты: окно/границы периода, измеримость
стадий, mean/median, сортировки, warning-статусы, top_limit, чистота проекций,
пропуск пустых payload, финальный backtest, пороги, коэрция mape, fail-closed
слоя 2, dotted-хук и whitelist backtest, запись наблюдений обоих видов,
инверсия роли ADMIN (M24), честный total_completed.

### Находки

- F-1 (Low, не блокирует): select_case_bank_candidates принимает mape=NaN как
  доказательство (float('nan') > порога == False) → кандидат с NaN и
  нестабильная сортировка на уровне движка (O6.12 — фиксация фактического
  поведения). В проде недостижимо: HTTP отсекает NaN (Starlette JSONResponse
  allow_nan=False), JSONB NaN не хранит. Риск — для будущих офлайн-потребителей
  §9 с произвольными экспортами. Рекомендация: math.isfinite(mape) у
  float(raw_mape) — однострочно, в любую следующую задачу.
- R-1 (Info): без X-API-Key админ-эндпоинты дают 422 (контракт FastAPI
  Header(...)), панель показывает «Сервис недоступен», а не «неверный ключ» —
  косметика UX.
- R-2 (Info): runs_by_status при прямом dict-входе с не-каноническим статусом
  добавит лишний ключ (через слой 2 невозможно — ResearchRun валидирует);
  канонические 4 ключа присутствуют всегда.
- R-3 (Info): criteria эхо отдаёт целые пороги как float (Dict[str, float]);
  панель не рендерит. Нит.

### Вердикт

PASSED WITH REMARKS. Реализация соответствует spec_progress.md §9/§10 дословно
(авторизация по идентичности — роль, не capability; период только к счётчикам
запусков; суммаризация LLM вне сервиса; «no fabricated results»; best-effort
§12 п.8; N-2 фантом-гейт; телеметрия НЕ в trace_events). Все заявления
исполнителя воспроизведены. F-1/R-1–R-3 не блокируют. PROGR-8 — последняя
задача декомпозиции plan_progress.md: план работ «Прогресс» выполнен полностью.

### Deliverable

ZIP: cisstat-progr8-cert-audit.zip — пути репозитория сохранены. НОВЫЕ:
scripts/cert8_oracles.py (35 оракулов), scripts/cert8_oracles_store_api.py
(54 оракула), scripts/cert8_mutations.py (25 мутантов, автооткат),
CERT_REPORT_PROGR-8.md (полный отчёт), worklog/worklog8.md (эта запись).
Без commit/push (AGENTS.md).

---

## Task ID: PROGR-9-FIX (2026-09-27) — Удаление 6 мёртвых кнопок пересчёта Панели управления («Предобработка»); подтверждение автопересчёта на 4 живых остановках

Синхронизация: main@9ae6b5c. Постановка тимлида по итогам PROGR-9-ANALYSIS:
«6 кнопок удаляем — 4 оставляем; возможен ли автоматический пересчёт на 4
рабочих кнопках после внесения аналитиком изменений?» TDD-цикл, commit/push
НЕ выполнялись (AGENTS.md).

### Дизайн решения

Точка изменения — единственная: TsAnalysisPreprocessing.tsx, рендер кнопки в
карточке остановки Панели управления (ранее строка 1478). Кнопка обёрнута
условием по «живому» множеству остановок (stationarity, spectral,
feature_eng, scaling); для остальных шести (missing, outliers, regularity,
decomposition, variance_stab, smoothing) кнопка больше не рендерится.
Риски: низкие — существующие тесты не ссылались на «Пересчитать…»;
refreshKey-механика шести остановок сохранена (используется сменой режима —
handleCheckModeChange, и Обзорами через сумму ключей PREPR-4).

### Ответ на вопрос постановки (автопересчёт)

Автоматический пересчёт после изменений аналитика на 4 живых остановках
УЖЕ РЕАЛИЗОВАН и работает единообразно для всех 10 остановок:
- apply любого из 10 мастеров → handleApplied → datasetVersion+1 →
  перезапрос ВСЕХ профилей (+ инвалидация кэша раскрытия RCH-2);
- сохранение периода («Зафиксировать периоды») и рецепта масштабирования
  НЕ мутируют dataframe, но тоже вызывают onApplied (SpectralPipeline:61,
  ScalingPipeline:62) — профиль обновляется сразу;
- смена «Режима проверки» → PUT check-modes → бамп собственного ключа;
- смена исследуемого признака (activeFeature) и параметров спектра
  (spectralParameters) — в deps соответствующих эффектов.
Осталось ровно два сценария, где автоматика бессильна и кнопка оправдана:
чужая мутация датасета при открытой вкладке (вторая вкладка браузера —
общая cookie-сессия) и ручной ретрай после сбоя GET. Поэтому 4 кнопки
оставлены как явный ручной fallback. Опциональное развитие (вне мандата):
автоперезапрос по window focus/visibilitychange — закроет и первый сценарий.

### TDD

RED: новый describe «кнопки пересчёта Панели управления (PROGR-9)» —
3 теста. Тест 1 падал (мёртвые кнопки рендерились) — ожидаемо.
GREEN после правки: 68/68 по сьюту. Полный jest: 147 сюит / 1788 тестов —
все зелёные (+3 новых). typecheck:all чисто (embedded+standalone).

### Новые тесты (3)

1) «не рендерит мёртвые кнопки пересчёта у шести остановок без обработчика
(однородность UX)» — фиксация удаления;
2) «рабочая кнопка пересчёта остаётся ручным fallback: клик перезапрашивает
профиль своей остановки» — счётчиками fetch по stationarity/scaling;
3) «после внесения изменений аналитиком (apply мастера) профили четырёх
живых остановок пересчитываются автоматически — кнопка не требуется» —
документирует автопаттерн (ответ на вопрос постановки).

### Deliverable

ZIP: cisstat-prepr-recalc-buttons-fix.zip — пути репозитория сохранены.
ИЗМЕНЕНЫ: packages/ui/components/TsAnalysisPreprocessing.tsx (условный рендер
кнопки + комментарий PROGR-9), packages/ui/components/TsAnalysisPreprocessing.test.tsx
(+3 теста, describe PROGR-9), worklog/worklog8.md (эта запись).
Без commit/push (AGENTS.md).

---

## Task ID: PROGR-10 — Расхождение №1: единый движок статусов из фактов решений (панель, Наставник, admin-аналитика); /trace отдаёт панели готовое состояние
Синхронизация: main@4a83bf8 (PROGR-9-FOCUS), рабочее дерево с незакоммиченными правками текущей задачи (commit/push запрещены AGENTS.md). Среда: дотянута до полного requirements (PyWavelets, ruptures, pandera, arch, statsforecast, prophet, cmdstanpy, torch, neuralforecast, psycopg) + npm install; найдено и подавлено средовое «DATABASE_URL=file:...» из окружения контейнера (прогон с DATABASE_URL= пустым).

### Постановка
При реализации микросервиса «Прогресс» между progress_ts_analysis.md (2026-08-31) и реализованным кодом по spec_progress.md обнаружены расхождения. Задача — Расхождение №1: вывод статуса из фактов решений консистентен по всем трём потребителям (панель, Наставник, admin-аналитика — один движок), убирает N опросов и гонку «профиль vs трасса». Цена (принята тимлидом): статус — с точностью до последнего засеянного события (узел, просмотренный и оставленный без коррекции, останется running) — для навигационной панели приемлемо. §3/§4.2 «живой опрос profile-эндпоинтов» сознательно НЕ реализуется.

### Проектирование (что нашла верификация по коду @4a83bf8)
Заявленное улучшение было реализовано не до конца: движков было ДВА.

Бэкенд — app/core/mentor_rules.py::derive_node_statuses + приватные _EVENT_STATUS_MAP/_FORECASTING_NODES/_event_dict («зеркало фронтенда PROGR-4»); использовали Наставник (next-step по слою 2) и admin_analytics, причём admin_analytics импортировал приватное _event_dict из модуля-потребителя (нарушение владения).
Фронтенд — packages/ui/lib/progress.ts::deriveNodeStatuses + PROGRESS_EVENT_STATUS + порт свёртки foldNodeStatuses (панель); связь с бэкендом — только зеркальные тесты, расползание тихое по построению.
Третье зеркало — app/core/run_report.py::_forecasting_node_of (вывод forecasting-узла для группировки отчёта §5.4).
Панель делала 2 запроса ради состояния (GET /v1/progress/trace + GET /v1/session/modeling/forecast), сливала трассы и выводила статусы/свёртку на клиенте.
Гонки «профиль vs трасса» нет (профили не опрашиваются); цель — довести «один движок» до истины.

### Ключевые решения
Канонический владелец — app/core/node_status.py (новый чистый модуль, паттерн pipeline_graph/admin_analytics: без HTTP и хранилищ). Состав: EVENT_NODE_STATUS — каноническая карта 12 узловых типов событий §4.1 (перенос дословно); event_to_dict — публичная нормализация (бывший приватный _event_dict); resolve_node_id — вывод узла (контракт PROGR-1: forecasting node_id=None → event_type; явный node_id приоритетен; фантом-гейт остаётся в деривации); derive_node_statuses — сам движок (last-event-wins по хронологии входа, ключ "stage/node_id", is_known_node-гейт); derive_stage_states — панельная надстройка: ВСЕ 6 стадий в порядке §2 {stage, fold §12 п.10 (канонический fold_status_values), done_count, warning_nodes, total_nodes}; пустая трасса — честные «не начато». Докстринг фиксирует решение расхождения: живой опрос профилей §3/§4.2 не реализован; цена — точность до последнего засеянного факта.
Потребители переключены, дубликаты удалены (проверяется тестом владения). mentor_rules: движок и приватные хелперы вырезаны, внутренние правила читают event_to_dict из node_status (публичный API вместо приватного импорта); stage_node_summary остался (форма ответа Наставника §7.1 не менялась). admin_analytics: импорт из node_status. run_report: _forecasting_node_of → resolve_node_id. progress.py (next-step): импорт из node_status. Реэкспорт совместимости в mentor_rules сознательно не оставлен (чистое владение; все импорты обновлены).
Панель — потребитель ГОТОВОГО состояния: GET /v1/progress/trace расширен (additive). events = слой 1 + ForecastRun.trace (артефакты сессии session.modeling_artifacts["forecasts"], тот же источник, что /v1/session/modeling/forecast), слитые сервером и отсортированные хронологически (нечитаемые ts — в конец, stable); 3-польная запись ForecastRun.trace канонизируется (ts=timestamp, stage="forecasting", node_id=event_type, чужие типы fail-safe пропуск); run_id/event_id НЕ выдумываются — события артефакта не становятся якорями чекпоинтов (семантика §5.1 прежняя). node_statuses — вывод единым движком; stages — свёртки §12 п.10 + счётчики. Панель теряет второй опрос (минус один запрос) и клиентское слияние; best-effort жив: ридер не зависит от слоя 2 (503 durable-слоя панель не ломает, кнопки disabled — прежняя семантика PROGR-5.1). started_at — по-прежнему ts первого события слоя 1 (§6.1 без изменений).
Фронтенд рендерит, не вычисляет. progress.ts: удалены PROGRESS_EVENT_STATUS, deriveNodeStatuses, foldNodeStatuses, collectForecastTraceEvents, stageSummary; добавлены StageStateInfo (зеркало StageStateOut) и stageStateText (текст карточки §6.2 из ГОТОВЫХ счётчиков; текст — UI-ответственность, вычисление — бэкенд). FOLD_*-константы и FoldVisualState остались как контракт значений fold ответа. ProgressStageFlow: props {statuses, stages} вместо events; стадии, отсутствующие в ответе (сеть/старый бэкенд), честно «не начато» из реестра узлов. ProgressDrawer: один запрос /trace (+ независимый /runs/{run_id} для полосы действий). Реестр PROGRESS_STAGE_NODES и sync-тест (Контур 2 test_progress_panel.py) не тронуты — лейблы и deep-link рендер по-прежнему нужны, sync-маркер жив.
Источник деривации панели — слой 1 + ForecastRun.trace (как у панели и было), не слой 2. Осознанно: /trace — сессионный ридер без durable-зависимости (503 слоя 2 не должен гасить статусы). Консистентность трёх потребителей обеспечивается одним движком; журналы — зеркала по построению (§5 «в дополнение, не вместо»; хук зеркалирует слой 1 → слой 2, forecasting — record_run_event). Полное совмещение источника с Наставником/admin (слой 2) — отдельное решение при переносе панели на durable-слой.

### TDD и верификация
RED: tests/api/test_node_status_engine.py — ImportError (модуля нет); Контур 1.1 test_progress_panel.py — 5 падений (KeyError node_statuses). Два падения ловили ошибки в самих тестах (regularity — узел validation+preprocessing, не eda; missing — узел preprocessing, не validation) — исправлены по живому графу, не по коду.
GREEN: test_node_status_engine.py 28/28 (карта 12 типов и семантика статусов; event_to_dict на объекте/dict/мусоре; resolve_node_id ×5; движок: last-event-wins, N-2, forecasting-вывод, фантомы, смешанные представления, коллизия regularity; derive_stage_states: пусто/порядок §2/тоталы, warning→attention при done-большинстве §12 п.10, running→attention, счётчики=деривация; владение: нет копий в mentor_rules/progress.ts/run_report).
Полный pytest tests/api: 1185 passed / 1 skipped / 3 failed — все 3 (modeling_workflow / neural_capacity / models_candidates) воспроизведены на чистом baseline @4a83bf8 (git stash) бит-в-байт — средовой дрейф, известный набор с PROGR-1, к задаче отношения не имеет.
Полный jest: 148 сюит / 1767 тестов — все зелёные; typecheck:all чисто; build:all — оба приложения ✓ Compiled successfully.
Миграция оракулов PROGR-4-CERT (scripts/audit_scripts/progr4cert_oracles.test.ts): оракулы удалённого фронтенд-движка сняты (OR-H/I/J/K1/K4 — поведение теперь на бэкенде, кейсы-эквиваленты в test_node_status_engine.py и Контуре 1.1 test_progress_panel.py); живые сохранены (OR-K2/K3 sort, OR-L stageLabel); fixture ln.json и генератор оставлены как артефакт сертификации, шапка файла фиксирует пересмотр.
Находки/заметки (не блокеры)
N-1 (Info): тесты Контур 1.1 сеют прогнозные события прямой инъекцией в modeling_artifacts (артефакт сессии) — через живой forecasting-роут не идут: слияние/канонизация/деривация проверяются на детерминированных данных, запись прогнозов — зона сертификации forecasting-задач.
N-2 (Info): при рестарте бэкенда in-memory слой 1 пустеет — статусы панели честно «не начато» до новых фактов (слоя 1 касается и прежнее поведение); слой 2 (Наставник/admin) этой деградации не имеет.
N-3 (Info): response /trace расширен аддитивно — старые потребители (только шапка/трасса) совместимы; e2e Vercel-standalone не гейтится кодом.
R-1 (Low, средовое): DATABASE_URL окружения контейнера (file:...) ломает импорт psycopg в тестах с durable-слоем — прогон с DATABASE_URL= (пусто); вне задачи.
Deliverable
ZIP: cisstat-progr10-node-status-engine.zip — пути репозитория сохранены (16 файлов).

### НОВЫЕ: app/core/node_status.py; tests/api/test_node_status_engine.py.
ИЗМЕНЁННЫЕ: app/core/mentor_rules.py (−движок, +импорт event_to_dict); app/core/admin_analytics.py (публичный импорт движка); app/core/run_report.py (resolve_node_id вместо зеркала); apps/api/routers/progress.py (/trace: node_statuses/stages/серверное слияние); tests/api/test_mentor_rules.py (Контур 5 переехал); tests/api/test_progress_panel.py (+Контур 1.1); packages/ui/lib/progress.ts (−движок, +StageStateInfo/stageStateText); packages/ui/lib/progress.test.ts (пересборка сюит); packages/ui/components/ProgressStageFlow.tsx (+.test.tsx: props statuses/stages); packages/ui/components/ProgressDrawer.tsx (+.test.tsx: один запрос); scripts/audit_scripts/progr4cert_oracles.test.ts (пересмотр оракулов); worklog/worklog8.md (эта запись). Без commit/push (AGENTS.md).

---

## Task ID: PROGR-11 — Расхождение №2 (§3): mode/summary_count/status_reason объявлены в PipelineNodeState, но до UI не доезжают; /trace отдаёт полные состояния узлов, панель рендерит бейджи/режимы/причины
Синхронизация: main@a25bfbf (PROGR-10), рабочее дерево с незакоммиченными правками текущей задачи (commit/push запрещены AGENTS.md). Среда: venv пересобран (.venv: requirements.txt + apps/api/requirements.txt + requirements-dev.txt), npm install свежий.

### Постановка и верификация гипотезы
Анализ progress_ts_analysis.md + plan_progress.md выявил расхождение: поля §3 mode/summary_count/status_reason объявлены в PipelineNodeState, но в рендер панели попадает только статус, выведенный из событий; бейджи-числа и mode до UI не доезжают. Верификация по живому коду @a25bfbf ГИПОТЕЗУ ПОДТВЕРДИЛА:
  * PipelineNodeState (app/core/pipeline_graph.py: 7 полей §3) в рантайме НИГДЕ не конструируется -- только упоминания в докстрингах; /trace строит node_statuses: Dict[str, str] каноническим derive_node_statuses (PROGR-10) и всё;
  * NodeStateOut в ответе нет; фронт (ProgressStageFlow) рендерит только StatusIcon+метку узла из карты статусов; packages/ui/lib/progress.ts не знает полных состояний узлов.
Итог: навигационная панель не показывает число проблем узла (то же число, что в правом бейдже степпера -- §3), режим проверки (auto/enabled/disabled) и причину статуса -- функциональность §3 не доведена до потребителя.

### Ключевые решения
Принцип PROGR-10 сохранён ДОСЛОВНО: живой опрос profile-эндпоинтов не появляется; бейдж/причина -- с точностью до последнего засеянного факта (та же принятая цена, что у статуса). Единый движок дополняется, а не дублируется:
  * app/core/node_status.py (канонический владелец): EVENT_NODE_REASON -- шаблоны фактов последнего события решения, ключи == EVENT_NODE_STATUS (тест страхует: reason и статус всегда об одном событии; текст -- факт, не совет -- советы у Наставника §7); NODE_SUMMARY_COUNT_KEYS -- приоритет ключей бейджа из payload (total_missing/total_outliers/total_violations/total_invalid старше rows_removed/total_changed; список согласован с _CORRECTION_PAYLOAD_KEYS хука -- новых ключей не изобретается); EFFECTIVE_NODE_MODE_DEFAULT="auto". derive_pipeline_node_states(events, check_modes=None) -- чистая функция: ВСЕ 46 узлов графа в порядке §2, словарь ровно 7 полей датакласса; статус -- ТОТ ЖЕ derive_node_statuses (вторая реализация статуса запрещена), reason/count/ts -- по последнему событию узла (last-event-wins, те же гейты N-2/фантомы/мусор), mode -- эффективный из сессионных check-modes (отсутствующее/битое значение -- fail-safe "auto", контракт _effective_*_check_modes степперов; check_modes не передан -- None: движок не выдумывает данные). _clean_summary_count: только неотрицательный int, bool исключён.
  * app/core/pipeline_graph.py: _MODE_STAGES -> публичный MODE_STAGES (владение классификацией стадий -- у графа; потребитель импортирует, не копирует; мутирующий скрипт PROGR-2 синхронизирован).
  * apps/api/routers/progress.py: NodeStateOut (зеркало датакласса §3); ProgressTraceResponse + nodes: List[NodeStateOut] -- АДДИТИВНО (N-3), node_statuses/stages не тронуты; /trace передаёт движку сессионные validation_check_modes/preprocessing_check_modes (прямое чтение полей сессии -- не опрос профилей).
  * packages/ui/lib/progress.ts: NodeStateInfo (зеркало NodeStateOut), nodeStateMap (карта "stage/node_id" -> состояние; пустой ответ -- пустая карта), nodeModeLabel (авто/вкл/выкл; неизвестное -- как есть), nodeStateKey.
  * ProgressStageFlow: props.nodes опционален; в раскрытой стадии -- бейдж-число справа (tabular-nums, title=reason), чип режима (только когда mode != null), причина статуса второй строкой (11px, нейтральная); узлы без фактов и ответ старого бэкенда -- рендер как прежде.
  * ProgressDrawer: nodes парсятся из /trace (?? []) и прокидываются в блок-схему; best-effort/N-3 сохранены.

### TDD и верификация
RED: tests/api/test_node_status_engine.py -- ImportError derive_pipeline_node_states; ProgressStageFlow.test.tsx/progress.test.ts -- TS2724/TS2305 (нет экспортов); ProgressDrawer.test.tsx -- TS2353 (nodes нет в типе mock-ответа). GREEN: код выше.
Тесты новые: бэкенд +20 (Контур 7 движка -- 16: карта reason==карта статусов, пустая трасса=46 узлов порядок §2, ровно 7 полей, факты коррекции -> reason/count/ts, приоритет проблемных счётчиков, last-event-wins, profile_viewed running+причина, upload без бейджа, mode только validation/preprocessing + fail-safe "auto" + None без check_modes, N-2/фантомы не трогают детали, мусор в счётчике пропускается, нечитаемый ts не затирает, смешанные представления, статусы == каноническому движку на всех узлах; Контур 1.2 /trace -- 4: пустая сессия=все поля §3 + mode auto/None по стадиям, demo -> reason/ts, факты коррекции слоя 1 -> summary_count=12 + N-3, сессионные check-modes -> mode disabled/enabled). Фронт +11 (progress.test.ts: nodeStateMap x2, nodeModeLabel x2; ProgressStageFlow.test.tsx: бейдж числа, отсутствие бейджа без факта, чип авто/выкл, null-mode без чипа, reason второй строкой, старый бэкенд рендер как прежде; ProgressDrawer.test.tsx: сквозной nodes -> бейдж/чип/причина).
Прогоны: pytest tests/api: 1208 passed / 1 skipped / 3 failed -- те же 3 (modeling_workflow / neural_capacity / models_candidates) воспроизведены в PROGR-10 на чистом baseline как средовой дрейф, к задаче отношения не имеют. Полный jest: 148 сюит / 1781 тест -- все зелёные. typecheck:all чисто; build:all -- оба приложения ✓ Compiled successfully.
Находки/заметки (не блокеры):
N-1 (Info): summary_count -- число из payload последнего корректировочного события (проблемные счётчики preview/apply -- факты §4.1); между коррекциями профиль узла мог измениться мимо трассы -- бейдж панели с точностью до последнего факта, как и статус (цена расхождения №1).
N-2 (Info): mode отдаётся ЭФФЕКТИВНЫМ (auto-дефолт) для всех узлов Валидации/Предобработки; UI рендерит чип всегда для этих стадий (то же состояние, что селекторы степперов) -- скрытие дефолта сознательно не делалось (честность данных выше плотности).
N-3 (Info): ответ /trace расширен аддитивно (nodes); старые потребители (шапка/трасса/node_statuses/stages) совместимы; e2e Vercel-standalone не гейтится кодом.

### Deliverable
ZIP: cisstat-progr11-node-states-to-ui.zip -- пути репозитория сохранены.
ИЗМЕНЁННЫЕ: app/core/node_status.py (+EVENT_NODE_REASON/NODE_SUMMARY_COUNT_KEYS/EFFECTIVE_NODE_MODE_DEFAULT/derive_pipeline_node_states); app/core/pipeline_graph.py (_MODE_STAGES -> публичный MODE_STAGES); apps/api/routers/progress.py (+NodeStateOut, +nodes в /trace); packages/ui/lib/progress.ts (+NodeStateInfo/nodeStateKey/nodeStateMap/nodeModeLabel); packages/ui/components/ProgressStageFlow.tsx (+props.nodes, бейдж/чип/reason); packages/ui/components/ProgressDrawer.tsx (+nodes в state и прокидка); tests/api/test_node_status_engine.py (+Контур 7); tests/api/test_progress_panel.py (+Контур 1.2); packages/ui/lib/progress.test.ts (+4); packages/ui/components/ProgressStageFlow.test.tsx (+6); packages/ui/components/ProgressDrawer.test.tsx (+1, тип mockFetch); scripts/progr2_mutations.py (синхронизация имени MODE_STAGES в MUT-07); worklog/worklog8.md (эта запись). Без commit/push (AGENTS.md).

---

## Task ID: PROGR-12 — Расхождение №3 (§8): MentorTextRenderer не зафиксирован в коде как Protocol (только упоминание в докстринге mentor_rules.py); контракт бумажный, подключение LLM позже потребовало бы ввода интерфейса. Фиксация контракта в коде: Protocol + дефолтный .format()-рендер + рендер ЧЕРЕЗ renderer ПОСЛЕ факта
Синхронизация: main@73f8467 (PROGR-11 применён тимлидом; diff рабочего пакета PROGR-11 против коммита пуст), рабочее дерево с незакоммиченными правками текущей задачи (commit/push запрещены AGENTS.md).

### Постановка и верификация гипотезы
Анализ progress_ts_analysis.md + plan_progress.md: §8 фиксирует контракт MentorTextRenderer(Protocol).render(rule, context) -> str («дефолтная реализация -- просто .format() шаблона, без сети/модели; применимо одинаково к §7.1 и §7.2»). Верификация по живому коду @73f8467 ГИПОТЕЗУ ПОДТВЕРДИЛА:
  * MentorTextRenderer в app/ НЕ определён нигде -- только упоминание в докстринге mentor_rules.py («единственная точка расширения (§8, не реализуется)»);
  * тексты производились ИНЛАЙН: §7.1 -- message=rule.explanation_template как есть (evaluate_next_step); §7.2 -- f-строки внутри условий правил (_over_aggressive_text(factor), f"Стратегия удалит {removed_share:.0%}..."), статичные константы (_NO_EFFECT_TEXT/_THRASHING_TEXT);
  * следствие: подключение LLM позже = сначала ВЕСТИ интерфейс + рефакторить все точки производства текста, только потом добавлять реализацию -- нарушение замысла §8 («контракт зафиксирован заранее, чтобы включение LLM не потребовало переписывать §7»).

### Ключевые решения
Канон §7 сохранён дословно (поля MentorRule -- 7 полей спеки, без расширений; §7.1-условия -- bool; сортировка (priority, rule_id); §7.2 -- весь список; пороги -- из rules/mentor.yaml на вызов). Единая точка рендера:
  * MentorTextRenderer -- @runtime_checkable Protocol в app/core/mentor_rules.py, сигнатура §8 ДОСЛОВНО: render(self, rule: MentorRule, context: dict[str, Any]) -> str. Структурный: duck-typed реализация без наследования удовлетворяет контракту (тест страхует -- «подключение LLM = добавление реализации»).
  * FormatMentorTextRenderer -- дефолт §8: rule.explanation_template.format(**context), без сети/модели. Богатый контекст (лишние ключи -- агрегированные факты для будущего LLM) .format() игнорирует; пропущенный параметр -- KeyError (строгий: пары шаблон/контекст страхуют тесты + валидация на импорте).
  * DEFAULT_TEXT_RENDERER: MentorTextRenderer = FormatMentorTextRenderer() -- дефолт процесса; evaluate_* принимают keyword-only renderer (внедрение без правки движка: LLM-рендер за фиче-флагом передаётся точкой вызова, §8 «вызывается ПОСЛЕ того, как правило-движок уже определил rule_id/recommended_action/severity»).
  * MentorRuleFact (frozen dataclass: context + severity + suggested_action) -- ФАКТ срабатывания, возвращаемый условиями §7.2/on_demand_with_history ВМЕСТО SanityWarning: текст больше не производится в условиях; severity/suggested_action -- постоянные правила, переносятся движком в SanityWarning. Контекст несёт параметры шаблона + агрегированные факты, виденные условием ({times}, {removed_share}, список стратегий окна, исход коррекции; сырые данные ряда -- НЕ попадают, принцип «LLM -- рендерер, не источник истины»). §7.1: контекст строит движок ({"statuses": dict(statuses)}).
  * Шаблоны с подстановками переехали в explanation_template правил (канон §7 «параметризованный текст»): over_aggressive -- «...более чем в {times} раз...», excessive_data_loss -- «Стратегия удалит {removed_share:.0%} строк датасета.»; no_effect/thrashing -- статичные (уже были). Тексты ПОБАЙТОВО те же (тест блокирует: «в 5 раз», «70%», «STL-декомпозиция», «чекпоинтом»).
  * evaluate_next_step/evaluate_sanity/evaluate_history_warnings: рендер ТОЛЬКО через renderer.render(rule, context) ПОСЛЕ факта; renderer НЕ вызывается, если ни одно правило не сработало (регресс-тест границы «сначала правило, потом текст», спека education §4.2). Сигнатуры evaluate_* обратно совместимы (renderer -- keyword-only, default None) -- роутер progress.py НЕ тронут.
  * validate_explanation_template: fail-closed валидация шаблонов РАСШИРЕНА на ВСЕ триггеры (раньше on_correction_result был исключён с пустым шаблоном): пустой шаблон ИЛИ битая подстановка (незакрытая "{") -- ImportError на импорте реестра (паттерн TRACE_ROUTES PROGR-3, опечатка не доходит до рантайма).

### TDD и верификация
RED: ImportError cannot import name 'FormatMentorTextRenderer' (контракт действительно бумажный). GREEN: код выше.
Тесты новые (tests/api/test_mentor_rules.py, Контур 7 -- 13): Protocol runtime_checkable + дефолт структурно conforms; duck-typed реализация без наследования удовлетворяет Protocol; семантика дефолта (.format с параметрами {removed_share:.0%}; статичный шаблон игнорирует лишний контекст; пропущенный параметр -- KeyError); §7.1/§7.2/on_demand_with_history рендерятся ЧЕРЕЗ renderer (стаб фиксирует вызовы: rule_id + контекст; message == возврат стаба; severity/suggested_action -- из факта, не от рендерера); renderer не вызывается при не сработавших правилах; побайтовое совпадение дефолтных текстов с прежними инлайн-формулировками; отсутствие остаточных подстановок {name} во всех отрендеренных сообщениях всех триггеров; fail-closed: битый шаблон -- ImportError; у всех правил всех реестров непустой валидируемый шаблон; условия §7.2 возвращают факт без текста.
Прогоны: pytest tests/api/test_mentor_rules.py -- 54 passed (было 41). Полный pytest tests/api: 1222 passed / 1 skipped / 3 failed -- те же 3 средовых (modeling_workflow / neural_capacity / models_candidates), воспроизведены на чистом baseline в PROGR-10/PROGR-11, к задаче отношения не имеют. Полный jest: 148 сюит / 1781 тест -- все зелёные (фронтенд не менялся). typecheck:all чисто; build:all -- оба приложения ✓ Compiled successfully.
Сертификационные оракулы PROGR-6 (scripts/audit_scripts/progr6cert_oracles.py): секции по моей зоне OR-2 (500 рандомных sanity-проб), OR-3 (300 потоков thrashing), OR-5 (живая проба API), OR-6 (конфиг §12 п.7) -- проходят через новый путь факт->рендер; OR-1/OR-4 падают с AttributeError на mentor_rules._EVENT_STATUS_MAP / derive_node_statuses -- СТАРОЕ, предсуществующее на чистом 73f8467 падение (движок переехал в app/core/node_status.py ещё в PROGR-10, офлайн-скрипт не обновлялся; к задаче не относится -- воспроизведено на чистом HEAD git-скрытием правок).

Находки/заметки (не блокеры):
N-1 (Info): phase_text/PHASE_TEXT_TEMPLATES сознательно НЕ заведены в Protocol -- это пояснение фазы ответа next-step без правила (нет факта, нет rule_id), контракт §8 определён для render(rule, context); заведение фазовых текстов в рендер -- отдельное решение при реальном LLM-тике.
N-2 (Info): строгий KeyError дефолтного рендера при пропуске параметра -- сознательно: пары шаблон/контекст одного модуля и страхуются тестами (Контур 7) + валидацией на импорте; тихая деградация подставила бы пользователю сырой шаблон с "{times}".
N-3 (Info): прогресс-оракулы PROGR-6 OR-1/OR-4 устарели с PROGR-10 (ссылаются на прежнее размещение движка статусов в mentor_rules) -- чинить отдельным тикетом по оракулам, не в рамках Расхождения №3.
N-4 (Info): роутер/фронтенд/оракулы не тронуты -- ответ API побайтово тот же (message собирается теми же формулировками); подключение LLM позже = реализация LLMMentorTextRenderer(MentorTextRenderer) + передача renderer= в точках вызова (или подмена DEFAULT_TEXT_RENDERER) за фиче-флагом, без правки app/core/mentor_rules.py.

### Deliverable
ZIP: cisstat-progr12-mentor-text-renderer-protocol.zip -- пути репозитория сохранены.
ИЗМЕНЁННЫЕ: app/core/mentor_rules.py (+MentorTextRenderer Protocol §8, +FormatMentorTextRenderer, +DEFAULT_TEXT_RENDERER, +MentorRuleFact, +validate_explanation_template; условия §7.2/истории -> факты без текста; шаблоны {times}/{removed_share:.0%} -- в реестр правил; evaluate_* -- рендер через renderer после факта; fail-closed валидация шаблонов на все триггеры; докстринги модуля/MentorRule); tests/api/test_mentor_rules.py (+Контур 7 -- 13 тестов, шапка Контуров); worklog/worklog8.md (эта запись). Без commit/push (AGENTS.md).

---

## Task ID: PROGR-13-B (2026-10-02) — Компактное backend-исправление дефекта 2 «Прогресса» + исключение главного риска плана (нормализация legacy node_id корпуса слоя 2)

База: main@2d2d05c. Правила AGENTS.md соблюдены: commit/push НЕ выполнялись; TDD RED→GREEN→миграции контрактов; сборка проверена.

Постановка (тимлид): Реализовать в коде PROGR-13-B (компактная). Исключить главный риск: без нормализации старого node_id в Postgres-корпусе панель и admin-аналитика теряют историю запусков. Выложить ZIP в открытый контейнер сессии.

### B1 (фаза Наставника по УЗЛОВЫМ фактам):

app/core/node_status.py: НОВАЯ чистая функция derive_last_active_stage(events, default="upload") — стадия последнего узлового факта решения (event_type in EVENT_NODE_STATUS + resolve_node_id + is_known_node, тот же гейт, что у derive_node_statuses). Stage-level события (node_id=None: target_column_changed/passport_captured/mode_changed/run_*) фазу НЕ двигают (target_column_changed мульти-страничен: сеется авто-POST хука useTargetColumn на вкладке «Загрузка»; паспорт — фиксация снимка, не переход на вкладку).
apps/api/routers/progress.py::get_mentor_next_step: вместо events[-1].stage — derive_last_active_stage(events). Дефект 2 закрыт: «Идёт этап "Валидация"» без захода на Валидацию воспроизводится больше нельзя (скрипт scripts/progr13_repro_defects.py: last_active_stage='upload' в ОБОИХ вариантах сценария, phase_text — «Загрузка»).
apps/api/routers/progress.py::restore (§5.3): session.last_active_stage и стадия run_resumed — тоже derive_last_active_stage(seeded) (тот же корень дефекта: хвост трассы из stage-level событий делал «Валидацию» текущим этапом после восстановления на другом устройстве).
B2 (мисаттрибуция паспортов):

apps/api/trace_hook.py: динамическая строка passport/{stage} (всё — eda) развёрнута в 4 ЛИТЕРАЛЬНЫХ: start→upload (точка фиксируется на вкладке «Загрузка»), validation→validation, exit→eda, modeling_entry→modeling; payload_keys прежние (stage/snapshot_id/fingerprint — точка остаётся фактом payload). Неизвестная точка — ни одной строки таблицы → событие не пишется (fail-closed; эндпоинт сам 404 по PASSPORT_STAGES). Таблица 40 → 43 строк (контракт-тест обновлён).
apps/api/trace_events.py: реестр STAGE_EVENT_TYPES расширен passport_captured на upload/validation/modeling (паттерн модуля «сторонние этапы — расширением реестра, а не обходом гейта»); eda — без изменений. _validate_table (fail-closed на импорте) проходит.
B3 (ГЛАВНЫЙ РИСК ПЛАНА — корпус слоя 2):

app/core/pipeline_graph.py: UPLOAD_STAGE_IDS = ("structure",) — канонический id узла Загрузки выровнен с id остановки «Структура» реестра модуля TsAnalysisUpload.tsx::STOPS (прежний structure_confirmed становится legacy-идентификатором).
app/core/node_status.py: LEGACY_NODE_IDS = {"upload": {"structure_confirmed": "structure"}} + normalize_legacy_node_id(stage, node_id) (идемпотентность, ограничение своей стадией, unknown — как есть, фантомов нет — дальше гейт is_known_node); нормализация вшита в resolve_node_id — ЕДИНСТВЕННУЮ точку вывода узла, поэтому все потребители наследуют её: панель /trace (node_statuses/stages/nodes), Наставник (статусы+фаза), admin-аналитика (top_problem_nodes/банк кейсов), отчёт §5.4 (run_report импортирует resolve_node_id). Трасса — журнал (R3 PROGR-1-CERT): записи Postgres-корпуса НЕ переписываются, нормализация только на чтении; без неё is_known_node-гейт молча отбрасывал бы узловые факты старых запусков (панель — «Загрузка: не начато», потеря истории у Наставника/admin).
app/core/run_report.py: FALLBACK_NODE_LABELS["upload","structure"]="Структура данных" (метка старых запусков — та же через нормализацию в модели отчёта; прямая метка по legacy id — честный сырой фоллбек, зафиксировано тестом).
packages/ui/lib/progress.ts: зеркало PROGRESS_STAGE_NODES["upload"]=["structure"] + NODE_LABELS.upload.structure (sync-структура jest-теста сохранена: счётчики [1,10,10,10,11,4]).

### TDD:
RED: tests/api/test_progress_progr13b.py (НОВЫЙ, 19 тестов): B1 — stage-level события не двигают фазу, последний узловой факт выигрывает, forecasting-вывод из event_type, fallback upload, legacy-строка корпуса считается узловым фактом; B3 — контракт normalize_legacy_node_id (идемпотентность/стадия/unknown/None), derive_node_statuses нормализует legacy-строку БЕЗ фантомного ключа, admin-аналитика (build_admin_overview) видит legacy-корпус без фантомов; B2 — параметризованная таблица точка→стадия (4) + fail-closed на неизвестной точке + регистрация типа на новых стадиях; API — фаза Наставника на legacy-корпусе (upload, затем modeling после нового факта), панель на legacy-слое-1 (upload/structure done, карточка passed, фантома нет), restore — фаза по узловым фактам. Все 16 содержательных падали на @2d2d05c с диагностичными сообщениями (2 — совпадения по стадии exit/validation, 1 — регрессионный guard mentor-legacy).
GREEN: реализация выше; 19/19.
Миграции контрактов (структурный переезд фиксур, не ослабление): test_pipeline_graph (3), test_node_status_engine (4), test_trace_events (1), test_progress_trace_hook (6), test_run_report (2), test_progress_panel (4).
Итог pytest tests/api/: 1228 passed; падения — ТОЛЬКО (а) 19 предсуществующих средовых (forecasting_session/modeling_workflow/models_*; воспроизводятся 1:1 на чистом 2d2d05c через git worktree — к задаче не относятся), (б) 5 RED-контрактов PROGR-13-A в test_progress_defects_progr13.py — оставлены RED сознательно, их GREEN = задача A. Три B-контракта того файла — GREEN (дефект 2 закрыт полностью).
Jest: 148 сюит / 1781 теста — все зелёные (фикстуры с raw node_id="structure_confirmed" — легальные legacy-события журнала). typecheck:all (embedded+standalone) — чисто.
Скрипт live-репродукции scripts/progr13_repro_defects.py: ДЕФЕКТ 2 ИСПРАВЛЕН (оба варианта сценария — этап «Загрузка»); дефект 1 ожидаемо остаётся (1/5 остановок — зона PROGR-13-A).

### Осознанные границы (не входящие в компактную B):

stage_for_run_level_event (research_runs.py:1091) всё ещё stamps run_paused/resumed/checkpoint по хвосту трассы; правка требует импорта движка в research_runs → цикл. Кандидат на отдельную задачу.
upload_completed по-прежнему красит узел structure в done (дефект 1б) и граф Загрузки — 1 остановка (дефект 1а): это PROGR-13-A (A1–A5).
Спек-документы (spec_progress.md §2/§4.1, progress_ts_analysis.md) не переписывались — документационная часть A; код самодокументирован комментариями PROGR-13-B.
Исторические оракулы/сертификаты не трогались — датированные свидетельства приёмок.

---

## Task ID: PROGR-13-A (2026-10-02) — Полнота Загрузки: общий реестр 5 остановок, разведение фактов upload_completed/structure_confirmed, контракт POST /v1/progress/upload-stops (дефект 1 закрыт полностью)
База: main@7cb4535 (PROGR-13-B принят в main; синхронизация: git stash -u -> reset --hard origin/main -> извлечение незакоммиченных артефактов PROGR-13-REPRO из stash^3: scripts/progr13_repro_defects.py, tests/api/test_progress_defects_progr13.py -- их в 7cb4535 нет, RED-контракты задачи A живут там). Правила AGENTS.md соблюдены: commit/push НЕ выполнялись; TDD RED->GREEN->миграции контрактов; сборка проверена.

### Постановка (тимлид)

Реализовать PROGR-13-A (полнота): A1 -- общий JSON upload_stops.json (паттерн eda_checks.json §12 п.2); A2 -- узел structure_confirmed->structure + нормализация legacy в корпусе слоя 2; A3 -- upload_completed->Превью; POST /date-column->Структура; A4 -- контракт POST /v1/progress/upload-stops (фронт отчитывает stopStatus -- прецедент §7.2); A5 -- постинг из TsAnalysisUpload, зеркало progress.ts, run_report. ZIP в открытый контейнер сессии.

Примечание о базе: A2 (канонический id structure + LEGACY_NODE_IDS/normalize_legacy_node_id в resolve_node_id) уже реализована в PROGR-13-B3 -- задача A проверила контракт на ПОЛНОМ реестре (тесты test_legacy_node_id_normalized_with_full_registry, test_is_known_node_accepts_all_five_stops) и ничего не меняла: нормализация ортогональна числу узлов, история корпуса слоя 2 сохраняется.

### Что сделано

A1 (общий реестр остановок):
- shared/pipeline_nodes/upload_stops.json (НОВЫЙ): 5 остановок (overview/chart/distribution/structure/quality) с id/label/description ДОСЛОВНО из прежнего STOPS модуля TsAnalysisUpload.tsx; порядок = порядок степпера; comment фиксирует двух потребителей и синхронный маппинг stopStatus.
- app/core/pipeline_graph.py: общее ядро _load_pipeline_node_defs(path, expected_stage=, registry_name=) -- контракт ошибок прежнего EDA-загрузчика (fail-closed на импорте: отсутствие/битый JSON/чужая stage/пустой nodes/пропуск ключей/дубликат id = ImportError); _load_eda_check_defs сохранена как обёртка (сигнатура и сообщения тестов нетронуты); НОВЫЙ _load_upload_stop_defs + UPLOAD_STOP_DEFS + UPLOAD_STAGE_IDS из JSON (вшитой копии кортежа в Python больше нет; STAGE_NODES["upload"] == 5 id == RED-контракт дефекта 1а).

A3 (разведение фактов загрузки):
- apps/api/trace_hook.py: 3 строки upload (internal/public/demo) -- node_id "structure" -> "overview" (upload_completed -- факт ЧТЕНИЯ ФАЙЛА; дефект 1б: зелёная «Структура» противоречила жёлтому модулю при confidence<70); НОВАЯ строка POST /v1/session/date-column -> upload/structure, event structure_confirmed, payload_keys=("date_column",) -- форма ТЕЛА ОТВЕТА DateColumnResponse (§4.1: факты из payload; колонка -- решение аналитика). Таблица 43 -> 44 строк.
- apps/api/trace_events.py: STAGE_EVENT_TYPES["upload"] += {structure_confirmed, upload_stop_status} (паттерн «сторонние этапы -- расширением реестра, не обходом гейта»).
- app/core/node_status.py: EVENT_NODE_STATUS += {"structure_confirmed": "done"}; EVENT_NODE_REASON["upload_completed"] -- честный факт «Датасет загружен, превью доступно» (прежний «структура подтверждена» -- ложь дефекта 1б), + reason для structure_confirmed («Временная колонка подтверждена аналитиком»).

A4 (контракт отчёта остановок + payload-статусы в движке):
- app/core/node_status.py: НОВЫЙ публичный реестр PAYLOAD_STATUS_EVENT_TYPES = {"upload_stop_status"} + чистая resolve_event_status(data) -- статус типа из карты EVENT_NODE_STATUS, ЛИБО из payload["status"] с whitelist CHECK_STATUS_VALUES (мусор -- None: событие хранится, фантомного статуса не создаёт, R3 PROGR-1-CERT); derive_node_statuses и derive_last_active_stage переведены на resolve_event_status (ЕДИНСТВЕННАЯ точка решения «узловой ли это факт»); derive_pipeline_node_states -- reason для payload-статусных типов тоже (EVENT_NODE_REASON["upload_stop_status"] = «Статус остановки отчитан модулем "Загрузка"»); инвариант «reason == карта статусов» расширен тестом до объединения с payload-реестром.
- apps/api/routers/progress.py: НОВЫЙ POST /v1/progress/upload-stops (UploadStopsReportIn{stops}, UploadStopsReportResponse{run_id, reported}): валидация fail-closed ДО первой записи -- 422 на пустую карту, неизвестный узел, недопустимый статус, НЕПОЛНУЮ карту (отчёт -- снапшот ВСЕХ остановок реестра, не дельта: чёрных дыр в фактах стадии нет); 400 без датасета (паттерн /date-column); ensure_run_id при активном датасете; 5 событий make_trace_event("upload_stop_status", stage="upload", node_id=..., status=...) в каноническом порядке реестра -> append_trace_event (слой 1) + record_run_event (зеркало слоя 2 -- тот же механизм, что у хука §5; admin-аналитика и Наставник видят факты).

A5 (потребители):
- packages/ui/lib/progress.ts: PROGRESS_STAGE_NODES["upload"] = ["overview","chart","distribution","structure","quality"] (литеральный массив -- формат страхован regex-sync-тестом и RED-контрактом дефекта 1а); NODE_LABELS.upload -- из ОБЩЕГО JSON (метки -- тот же источник, что у модуля и отчёта; вшитой метки «Структура данных» больше нет); шапка -- 50 узлов.
- packages/ui/components/TsAnalysisUpload.tsx: STOPS -- из общего JSON (вшитый список удалён; импорт в блоке импортов); ПРОГР-13-A5-отчёт: postStops (POST /v1/progress/upload-stops, credentials: include) + stopsSnapshot (JSON.stringify useMemo) + useEffect -- отчёт только при РЕАЛЬНОМ изменении статусов и только после загрузки (все-pending не отчитывается); сбой сети -- молча сбрасывает маркер (вспомогательный контур §12 п.8, следующее изменение повторит); reportUploadStopsNow -- принудительный ре-пост.
- packages/ui/components/DatasetPassportPanel.tsx: опциональный проп onDateColumnConfirmed (N-3), вызывается после УСПЕШНОГО POST /date-column до паспорта (порядок фактов трассы честный); TsAnalysisUpload передаёт reportUploadStopsNow -- панель «Прогресс» остаётся зеркалом модуля и после confirmation: structure_confirmed (done) + ре-пост (warning при confidence<70) -- хронология решает, последнее событие узла выигрывает в едином движке.
- app/core/run_report.py: FALLBACK_NODE_LABELS upload -- из UPLOAD_STOP_DEFS (единый источник меток; прямая метка по legacy id -- честный сырой фоллбек, как в B3); НОВЫЕ строки фактов: structure_confirmed -> «Подтверждена временная колонка "..."» (колонка из payload, отсутствующая -- без выдуманных фактов), upload_stop_status -> «Статус остановки "..." отчитан модулем: ...» (метка узла из реестра, RU-метки CheckStatus, неизвестное значение -- как есть).
- spec_progress.md (документационная часть A, отложенная B): §2 -- строка реестра Загрузки (5 остановок из общего JSON, формулировка «нет CHECKS-массива» устарела) + код-блок графа; §4.1 -- строка upload (upload_completed/structure_confirmed/upload_stop_status/passport_captured-start) + modeling дополнен modeling_entry (B2) + абзац о доверенных фактах с фронтенда (валидация fail-closed).

### TDD

RED: на @7cb4535 падали ровно 5 A-контрактов test_progress_defects_progr13.py (граф == 5 id модуля; зеркало progress.ts == 5 id; upload_completed не красит structure в done; upload_completed красит overview в done; POST /upload-stops -- панель == stopStatus модуля, карточка attention при warning-остановках); 3 B-контракта того файла и 19 тестов PROGR-13-B -- зелёные.
GREEN: НОВЫЙ tests/api/test_progress_progr13a.py (25 тестов): A1 -- JSON/граф/tsx/ts-метки из одного источника + fail-closed загрузчика (4 параметризованных отказа); A2 -- legacy-нормализация на полном реестре без фантомов; A3 -- карта статусов (overview done / structure только по structure_confirmed), API /date-column сеет structure_confirmed с payload date_column, 422 -- события нет; A4 -- resolve_event_status whitelist (валидный/мусор/не-строка/нет payload), last-wins (отчёт -> structure_confirmed -> ре-пост = warning), фаза Наставника от отчёта, полный контракт эндпоинта (слой 1: 5 событий с payload+run_id; слой 2: зеркало видна), fail-closed 422x4 all-or-nothing, 400 без датасета, фиксация run_id первым отчётом; A5 -- отчёт §5.4 (метки из реестра, строки фактов, без выдуманных чисел) + FALLBACK покрывает весь реестр + структурные проверки progress.ts.
Миграции контрактов (структурный переезд, не ослабление): test_pipeline_graph (5-узловой upload, счётчики 46->50, iter_all_nodes/parametrize 50); test_node_status_engine (карта 12->13 типов + payload-реестр, терминальные 10->11, reason-инвариант = карта | payload-реестр, all-done fold на 5 узлах, фикстура upload_completed -> overview); test_trace_events (реестр upload +2 типа); test_progress_trace_hook (таблица 43->44, узел overview, +позитив /date-column, из «не трассируются» убран /date-column, stored node overview); test_progress_panel (demo -> overview, карточка attention 1/5 -- честная семантика полной Загрузки, reason «превью доступно»); test_progress_progr13b (легенда-корпус: факт сохранён, карточка 1/5 attention -- суть теста «история не потеряна» не менялась); test_run_report (метки из общего реестра: «Структура» вместо «Структура данных», +overview/quality); packages/ui/lib/progress.test.ts (счётчики [5,10,10,10,11,4], 50 узлов).
Итог pytest tests/api/: 1263 passed; падения -- ТОЛЬКО 19 предсуществующих средовых (forecasting_session x16, modeling_workflow, models_candidates, models_backtest_neural_capacity: statsmodels 0.14.5/psycopg -- воспроизводятся 1:1 на чистом 7cb4535, к задаче не относятся).
Jest: 148 сюит / 1781 тестов -- все зелёные. typecheck:all (embedded+standalone) -- чисто.
Скрипт live-репродукции scripts/progr13_repro_defects.py (дополнен шагом 2b -- POST /upload-stops как А5-фронтенд, и ре-постом после /date-column как reportUploadStopsNow): ДЕФЕКТ 1 ИСПРАВЛЕН -- панель показывает 5 остановок, статусы == модулю (overview/chart/distribution done, structure/quality warning, карточка attention 3/5, «Панель == модулю: True»); ДЕФЕКТ 2 остаётся закрытым (оба варианта -- этап «Загрузка»).

### Осознанные границы

- Полная карта «панель == модуль» гарантируется связкой «отчёт на изменение + ре-пост после подтверждения структуры»; серверный факт structure_confirmed намеренно остаётся узловым фактом done (отчёт §5.4 и admin-аналитика обязаны видеть РЕШЕНИЕ аналитика), конфликт с жёлтым модулем решает хронология -- контракт зафиксирован тестом last-wins.
- progress_ts_analysis.md не переписывался (исторический дизайн-документ; его «живой опрос profile-эндпоинтов» уже отвергнут решением расхождения №1 PROGR-10) -- актуализирован только spec_progress.md.
- stage_for_run_level_event (research_runs.py) -- прежний кандидат на отдельную задачу (граница PROGR-13-B), не входил в A.
- Исторические оракулы/сертификаты (scripts/progr*_oracles.py, cert*, audit_scripts) не трогались -- датированные свидетельства приёмок.

### Deliverable

ZIP: cisstat-progr13-a-upload-stops-full-registry.zip -- пути репозитория сохранены.
НОВЫЕ: shared/pipeline_nodes/upload_stops.json; tests/api/test_progress_progr13a.py (25 тестов).
ИЗМЕНЕНЫ: app/core/pipeline_graph.py, app/core/node_status.py, app/core/run_report.py, apps/api/trace_hook.py, apps/api/trace_events.py, apps/api/routers/progress.py, packages/ui/lib/progress.ts, packages/ui/components/TsAnalysisUpload.tsx, packages/ui/components/DatasetPassportPanel.tsx, spec_progress.md, scripts/progr13_repro_defects.py (из PROGR-13-REPRO -- дополнен шагами A5), tests/api/test_pipeline_graph.py, tests/api/test_node_status_engine.py, tests/api/test_trace_events.py, tests/api/test_progress_trace_hook.py, tests/api/test_progress_panel.py, tests/api/test_run_report.py, tests/api/test_progress_progr13b.py (1 фикстура карточки), packages/ui/lib/progress.test.ts, worklog/worklog8.md (эта запись; восстановлена запись PROGR-13-REPRO, отсутствовавшая в каноническом файле после коммита 7cb4535).
Без commit/push (AGENTS.md).

---

## Task ID: PROGR-13-C (2026-10-02) — Граница PROGR-13-B: стадия run-level событий (run_paused/run_resumed/checkpoint_saved) -- из фактов решения единого движка, не из хвоста трассы
База: main@f607ccc (PROGR-13-A принят в main; синхронизация: все рабочие изменения A в f607ccc совпали байт-в-байт; локальный worklog8.md -- суперсет, сохранена запись PROGR-13-REPRO, отсутствующая в каноническом файле upstream). Правила AGENTS.md соблюдены: commit/push НЕ выполнялись; TDD RED->GREEN; сборка проверена.

### Постановка (тимлид)

Граница stage_for_run_level_event (research_runs.py) -- осознанная граница PROGR-13-B («всё ещё stamps run_paused/resumed/checkpoint по хвосту трассы; правка требует импорта движка в research_runs -> цикл»). Реализовать.

### Корень (проверка по коду @f607ccc)

stage_for_run_level_event (research_runs.py:1085) брала events[-1].stage: последними событиями трассы регулярно становятся события УРОВНЯ СТАДИИ (node_id=None) -- target_column_changed сеется авто-POST хука useTargetColumn на вкладке «Загрузка» со stage="validation", passport_captured -- фиксация снимка, mode_changed/run_* -- служебные. «Пауза» после загрузки датасета попадала в корпус слоя 2 как пауза НА СТАДИИ ВАЛИДАЦИИ -- ложь о маршруте аналитика; тот же корень, что у дефекта 2 Наставника (исправлен B1 derive_last_active_stage), но у атрибуции run-событий. Расхождение видно и в тесте: после B1 фаза Наставника -- "upload", а штамп run_paused -- "validation" (два вывода стадии расходились).

ЦИКЛ (подтверждён эмпирически): research_runs -> node_status -> pipeline_graph -> routers.session -> research_runs (routers.session импортирует get_dataset_file_store). Верхнеуровневый импорт движка в research_runs при порядке «research_runs первым» валит импорт. Разрыв -- ЛЕНИВЫЙ импорт внутри функции: прецедент модуля modeling_session.py:697/forecasting_session.py:620; на момент вызова (обработка запроса) граф уже загружен.

### Реализация

app/core/node_status.py: НОВАЯ чистая функция derive_last_decision_stage(events, *, default="upload") рядом с derive_last_active_stage: стадия последнего ФАКТА РЕШЕНИЯ по ТИПУ события. Гейт -- resolve_event_status (ЕДИНСТВЕННАЯ точка решения «узловой ли это факт»: карта EVENT_NODE_STATUS либо payload-статус из PAYLOAD_STATUS_EVENT_TYPES, PROGR-13-A4); известность стадии -- ключи STAGE_NODES графа (import-инвариант test_pipeline_graph страхует равенство с KNOWN_STAGES -- НОВОГО импорта apps.api в app.core не заводится). Отличие от гейта Наставника СОЗНАТЕЛЬНОЕ: атрибутируется СТАДИЯ, узел не требуется -- фантомного узла тут возникнуть не может; certified контракт E6 (PROGR-5-CERT) сохранён дословно: backtest_run с node_id=None -> "modeling" (на реальных корпусах факты хука всегда несут узлы -- гейты совпадают; расходятся только на синтетике «факт без узла», где E6 требует считать факт). Хронология дописывания: позднее событие выигрывает; пустая трасса / только stage-level -- честный fallback "upload"; факт с неизвестной стадией штамп не уводит (журнал R3: мусор хранится, но стадию атрибутировать не может); run_* -- не факты, серию пауза/возобновление/чекпоинт стадия «не держит».

apps/api/research_runs.py: stage_for_run_level_event -- публичный контракт и сигнатура НЕ изменены (оракул E6 зовёт rr.stage_for_run_level_event(store, run_id)); хвостовая эвристика заменена выводом движка: derive_last_decision_stage(store.list_events(run_id)) с ленивым импортом (докстринг фиксирует корень, цикл и прецедент разрыва). Импорт KNOWN_STAGES из trace_events стал ненужным (гейт стадии переехал в движок к ключам STAGE_NODES) -- убран из строки импорта (TraceEvent остаётся; перепроверено: ре-экспорта KNOWN_STAGES из research_runs никто не читает).

Потребители (apps/api/routers/progress.py) не менялись: pause/resume/checkpoints продолжают зоввать stage_for_run_level_event -- штампы исправлены на границе. run_report не менялся: строки run-событий §5.4 рендерятся БЕЗ стадии события (проверено), расхождений нет. restore (§5.3) не менялся: B1-контракт derive_last_active_stage для session.last_active_stage И run_resumed сохранён (на реальных корпусах совпадает с новым гейтом; расхождение только на «факте без узла» -- задокументировано в докстринге движка).

### TDD

RED: tests/api/test_progress_progr13c.py (НОВЫЙ, 18 тестов). На @f607ccc падали 15 с диагностированными сообщениями: чистый движок -- 10 через ожидаемый ImportError (derive_last_decision_stage ещё нет); публичный контракт -- «assert 'validation' == 'upload'» (хвост stage-level target_column_changed уводит штамп); HTTP-интеграция -- run_paused/run_resumed/checkpoint_saved штампуются "validation" в сценарии demo -> авто-POST /target-column -> действие (корпус слоя 2 хранит паузу на Валидации, куда аналитик не заходил); консистентность -- «assert 'upload' == 'validation'» (фаза Наставника и штамп run-события расходились). 3 теста предсуществующе ЗЕЛЁНЫЕ и остаются guard-контрактами GREEN: обе половины certified E6 (пустая трасса -> upload; backtest_run без узла -> modeling) и last-fact-wins (факт, дописанный между паузой и возобновлением, двигает штамп).
GREEN: 18/18. Контракты: fallback upload (пустая/только stage-level/только мусорные стадии); хвост stage-level не двигает штамп (канонический сценарий дефекта); последний факт выигрывает (в т.ч. forecasting node_id=None слоя 2 и payload-статусный upload_stop_status); факт с неизвестной стадией пропускается; run_* не держат стадию; legacy node_id корпуса не блокирует атрибуцию (гейт по типу -- нормализация ортогональна); E6 дословно на новой реализации; HTTP run_paused/run_resumed/checkpoint_saved -- по последнему факту; единство с фазой Наставника на реальном корпусе.

### Верификация

pytest tests/api/: 1281 passed (ровно 1263 базы A + 18 новых), 1 skipped; падения -- ТОЛЬКО 19 предсуществующих средовых (test_forecasting_session x16, test_modeling_workflow, test_models_backtest_neural_capacity, test_models_candidates: statsmodels 0.14.5/psycopg) -- воспроизведены 1:1 на ЧИСТОМ f607ccc через git stash -u (оба прогона 19 failed на тех же файлах). Миграций контрактов не потребовалось: ни один тест сьюта не пинил хвостовую семантику stage_for_run_level_event (проверено grep'ом: стадийных assert на run-события в tests/api нет, прямой зов функции только в оракуле).
Jest (packages/ui): 148 сюит / 1781 тестов -- все зелёные (фронтенд задачей не затронут; запуск из КОРНЯ репо -- из packages/ui jest подхватывает не тот конфиг и падает на парсинге TS, fixturная ошибка окружения).
typecheck:all (embedded+standalone) -- чисто.
Сертификат PROGR-5-CERT (датированное свидетельство, не трогалось): полный прогон оракулов 39/40 PASS; E6 (контракт ИЗМЕНЁННОЙ функции) -- PASS на новой реализации. E1 (MIGRATION_STATEMENTS == 0001_research_runs.sql текст в текст) -- FAIL, предсуществующий: воспроизведён 1:1 на чистом f607ccc (докстринговый/комментарийный дрейф файла миграции; pytest-инвариант того же равенства в test_research_runs.py -- зелёный, в сьют-базу оракул не входит; к задаче не относится).
Мутационный скрипт M8 (progr5cert_mutations.py) -- якорь на СТАРЫЙ текст хвостовой эвристики ("events = store.list_events... if events: stage = events[-1].stage"): после C якорь устарел, полный мутационный прогон stopped assert'ом "old-фрагмент не найден". Скрипт -- датированное свидетельство приёмки PROGR-5 (2026-09-25), не трогался; свежая мутационная защита контракта -- RED-тесты C (ImportError/текстовые диагностики) + guard-половины E6.

### Осознанные границы

- Гейт атрибуции run-событий -- по ТИПУ факта (без is_known_node): синтетический «факт без узла» двигает штамп (E6), но не фазу Наставника. На реальных корпусах (факты хука всегда с узлами, forecasting выводит узел из типа) гейты совпадают -- контракт единства зафиксирован тестом test_run_level_stamp_agrees_with_mentor_phase. Дальнейшая унификация (одна функция) возможна только вместе с пересмотром сертифицированного E6 -- сознательно не делалась.
- restore (§5.3) продолжает B1-гейт (derive_last_active_stage) для session.last_active_stage И run_resumed: основная роль restore -- фаза восстановленной сессии; расхождение с новым гейтом -- та же синтетика «факт без узла».
- Спецификация: spec_progress.md §5.2 дополнен абзацем об атрибуции стадии run-level событий (последний факт решения, не хвост; fallback upload). progress_ts_analysis.md не трогался (исторический дизайн-документ).
- Исторические оракулы/сертификаты (scripts/audit_scripts/*) не трогались -- датированные свидетельства приёмок (E1-дрейф и устаревший якорь M8 зафиксированы здесь).

### Deliverable

ZIP: cisstat-progr13-c-run-level-stage-facts.zip -- пути репозитория сохранены.
НОВЫЕ: tests/api/test_progress_progr13c.py (18 тестов).
ИЗМЕНЕНЫ: app/core/node_status.py (derive_last_decision_stage), apps/api/research_runs.py (stage_for_run_level_event через движок, ленивый импорт; убран неиспользуемый KNOWN_STAGES), spec_progress.md (§5.2), worklog/worklog8.md (эта запись).
Без commit/push (AGENTS.md).

---

## Task ID: PROGR-13-CERT (2026-10-02) — Независимая сертификация PROGR-13-A + PROGR-13-B — PASSED WITH REMARKS
База: main@f607ccc (7cb4535 = B, f607ccc = A). Правила AGENTS.md соблюдены: commit/push НЕ выполнялись; рабочее дерево после сертификации чистое (мутационная сеть с бэкапом/восстановлением). Сертификатор вне цепочки реализации; проверка БЕЗ опоры на тесты разработчика.

### Постановка (тимлид)
Синхронизироваться до f607ccc. Изучить постановки PROGR-13-A/B в worklog8.md и их реализацию в коде. Провести честную сертификацию, в том числе мутационные и оракул-тесты на своих данных. ZIP новых/изменённых файлов -- в открытый контейнер сессии.

### Контуры проверки и результаты

1. Код vs постановки: A1--A5 и B1--B3 подтверждены по живому коду (детали -- docs/progr13cert_certification_report.md §2): derive_last_active_stage с гейтом узловых фактов (B1), 4 литеральные паспортные точки (B2), LEGACY_NODE_IDS в resolve_node_id (B3), общий JSON 5 остановок + fail-closed ядро загрузчика (A1), upload_completed->overview / POST /date-column->structure (A3), PAYLOAD_STATUS_EVENT_TYPES + POST /v1/progress/upload-stops all-or-nothing с зеркалом слоя 2 (A4), метки отчёта §5.4 из общего реестра (A5).
2. Целевые сьюты: test_progress_progr13a (25) + test_progress_progr13b (19) + test_progress_defects_progr13 (8) -- 52 passed.
3. Полный pytest tests/api/: 1282 passed / 1 skipped / 0 failed (единственный skip -- PG-интеграция без CISSTAT_TEST_PG_DSN). В полной среде (arch, prophet, tbats, statsforecast, torch+neuralforecast, statsmodels 0.15.0, psycopg, sqlalchemy) «19 средовых» из записи A -- зелёные; счётчики 1263+19=1282 сходятся.
4. RED-верификация TDD (git worktree на базах): на 7cb4535 A-контракты падают РОВНО 5/8, 3 B-контракта зелёные -- дословное совпадение с claim; на 2d2d05c B-файл (коммитнутая версия) -- 17 failed / 2 passed ([exit-eda] -- совпадение со старой строкой, test_mentor_phase_for_legacy_corpus_run -- guard; см. R-3 об учёте «16+2+1»).
5. Оракулы на СВОИХ данных (scripts/progr13cert_oracles.py, NEW): 64/64 PASS. Property-based нормализация legacy (идемпотентность 500, fuzz 500 без фантомов, все 50 id насквозь, история слоя 2 сохранена), движок (whitelist 11 видов мусора, last-wins 200 хронологий, «панель == модулю» 200 снапшотов, фантом-фри 120 шумовых), фаза Наставника (инвариант 150 хронологий), HTTP-контракт /upload-stops (all-or-nothing с проверкой НУЛЯ записей, зеркало слоя 2, run_id pinning, 400 без датасета, last-wins с /date-column), отчёт §5.4 (30 комбинаций остановка x статус, без выдуманных фактов), таблица хука, fail-closed загрузчика (5 видов порчи).
6. Мутационный прогон (scripts/progr13cert_mutations.py, NEW): 23 мутанта -- 20 KILLED / 2 SURVIVED / 1 контроль SURVIVED (по ожиданию). Все рецидивы дефектов 1 и 2, снятая нормализация legacy (функция и вызов-сайт), cross-stage перезапись, снятый whitelist payload, выпавшие structure_confirmed/payload-типы, лживая причина, 5 снятых fail-closed проверок /upload-stops, мисаттрибуция паспортов, /date-column->overview, обрезка реестра, снятый fail-closed дубликатов, сырые id в отчёте -- УБИТЫ тестами.
7. Live-репродукция scripts/progr13_repro_defects.py: ДЕФЕКТ 1 ИСПРАВЛЕН (5 остановок, «Панель == модулю: True», fold=attention 3/5), ДЕФЕКТ 2 закрыт (оба варианта -- этап «Загрузка»).
8. Jest: 148 сюит / 1781 тестов -- все зелёные (совпадает с claim). typecheck:all -- exit 0; build:all -- оба приложения Compiled successfully.

### Находки (не блокеры)
R-1 (Minor, покрытие): мутант M-B1-2 выжил -- снятие гейта resolve_event_status в derive_last_active_stage (узловое событие с НЕразрешимым статусом -- неизвестный тип при известном node_id / мусорный payload -- двигает фазу) не ловится pytest. Не эквивалентный мутант; прод-риск мал (статусы валидируются сервером). Рекомендация: прямой кейс в test_progress_progr13b отдельным тикетом.
R-2 (Minor, покрытие): мутант M-A5-2 выжил -- подмена честной строки _structure_confirmed_line при отсутствующей date_column на выдуманный unknown_column не ловится pytest (контракт покрыт только оракулом E3 сертификатора, вне сьюта). Рекомендация: тест в test_run_report.py.
R-3 (Info, учёт): на 2d2d05c коммитнутый B-файл даёт 17 failed / 2 passed против claim «16 содержательных + 2 совпадения + 1 guard»; расхождение в 1 тест объяснимо миграцией фикстуры карточки в A (RED-версия файла не коммитилась). Суть RED-claim подтверждена; на 7cb4535 -- дословные 5/5.
R-4 (Info, среда): «19 средовых» -- артефакт неполной среды (без arch/prophet/tbats/statsforecast/neural; statsmodels 0.14.5); в полной среде 0 failed, счётчики сходятся.
R-5 (Info, граница, перенесена из B): stage_for_run_level_event (research_runs.py) штампует run-level стадии по хвосту трассы -- осознанная граница компактной B, кандидат на отдельную задачу.

ВЕРДИКТ: PROGR-13-A -- PASSED; PROGR-13-B -- PASSED; совместный вердикт -- PASSED WITH REMARKS (R-1, R-2 -- малые дыры pytest-покрытия, найденные мутационно; код и контракты соответствуют постановкам).

### Deliverable
ZIP: cisstat-progr13cert-certification.zip -- пути репозитория сохранены.
НОВЫЕ: scripts/progr13cert_oracles.py (64 оракула); scripts/progr13cert_mutations.py (23 мутанта); docs/progr13cert_certification_report.md (полный отчёт).
ИЗМЕНЕНЫ: worklog/worklog8.md (эта запись).
Без commit/push (AGENTS.md).

---

## Task ID: PROGR-14-A (2026-10-02) — Формула остановки «Структура» (модуль «Загрузка»): явные выборы «(нет)»/«(не использовать)» = confident -- статус из факта решения, не из raw confidence
База: main@bdc4b27 (PROGR-13-CERT принят в main; рабочее дерево до задачи чистое). Правила AGENTS.md соблюдены: commit/push НЕ выполнялись; TDD RED->GREEN; сборка проверена.

### Постановка (тимлид)

Модуль «Загрузка», остановка «Структура» -- реальный дефект формулы: entity confidence = 0% для легитимного «(нет)» группирующей колонки у однорядного датасета -- зелёным остановке не быть никогда. Реализовать PROGR-14-A: формула «Структуры» -- явные выборы «(нет)»/«(не использовать)» = confident, либо статус из факта решения, а не raw confidence. По результатам -- открытый контейнер сессии, ZIP новых/изменённых файлов.

### Корень (проверка по коду @bdc4b27)

Формула stopStatus.structure (TsAnalysisUpload.tsx): `dateCol.confidence < 70 || entityCol.confidence < 70 ? "warning" : "done"`. Raw confidence -- статическая оценка АВТО-детекта бэкенда (get_structure_detection): когда колонки такого рода в датасете НЕТ (однорядный/односерийный датасет -- легитимный случай «нет группирующей колонки»), бэкенд отдаёт selected="(нет)"/"(не использовать)" с confidence=0% -- нечего скорить. Категориальная ошибка формулы: 0% читается как «система не уверена», тогда как факт -- «колонки нет» (решающее состояние, альтернативы, между которыми можно сомневаться, отсутствуют). Ручной onChange селектора confidence НЕ пересчитывает (задокументированный баг 2026-08-14) -- пользователь не мог «позеленить» остановку никаким действием. Дефект 1б PROGR-13-A (upload_completed красил «Структуру») уже закрыт разведением фактов; здесь -- оставшаяся «вечная жёлтость» СМОЙ формулы модуля. Симптом был виден и в тестах: стандартный мок TsAnalysisUpload.test.tsx (однорядный "a,b\n1,2", entity "(нет)" conf 0) -- комментарий фиксации прямо говорил «Структура -- warning (entity confidence 0 < 70)».

### Реализация

packages/ui/components/TsAnalysisUpload.tsx:
- КОНСТАНТА EXPLICIT_NONE_CHOICES = {"(нет)", "(не использовать)"} + isExplicitNoneChoice() -- явные выборы-маркеры отсутствия колонки; комментарий фиксирует семантику «решающее состояние выбора, не сомнительная догадка» и источник 0% (бэкенд).
- isStructureDecisionConfident(col) -- решение по ОДНОЙ колонке уверенное <=> явный маркер отсутствия ЛИБО raw confidence >= 70 (порог прежний). Прецедент в коде -- гейт confidentDateCol 2026-08-14: «доверяем осознанному выбору, confidence -- только для предупреждения о низком авто-детекте».
- Формула structure: done <=> ОБА решения confident (per-column гейт: дата «(не использовать)» + сомнительная конкретная entity -- всё ещё warning); pending/warning без изменений. Комментарий у формулы -- корень дефекта и ссылка на замечание тимлида.
- Бейдж «0%» на самой остановке НЕ тронут -- честный показ оценки авто-детекта (факт), дефект был именно в статусе остановки.
- chart-stop (confidence даты < 70 -> warning) сознательно НЕ тронут: без даты график реально недоступен (confidentDateCol=null) -- предупреждение честное, вне постановки.

Потребители без изменений: панель «Прогресс» остаётся зеркалом модуля через POST /v1/progress/upload-stops (PROGR-13-A5: отчёт на изменение + ре-пост после structure_confirmed) -- с фиксом модуль отчитывает done, конфликт «structure_confirmed vs warning» из записи PROGR-13-A исчезает в обе стороны хронологии; doneCount/progressPct -- «Структура» стала засчитываться. Бэкенд не менялся (факты structure_confirmed/upload_stop_status -- из PROGR-13-A/B/C, не пересматривались).

### TDD

RED: НОВЫЙ describe PROGR-14-A в TsAnalysisUpload.test.tsx (5 тестов) + расширение mockFetchSequence 3-м параметром detectionOverride (detectionPayload/defaultStructureDetection -- без дублирования мока). На @bdc4b27 падали РОВНО 3 контракта с одной диагностикой (Структура: bg-white-warning вместо bg-green-50-done): (1) однорядный датасет, легитимное «(нет)» conf 0% -- дефект тимлида; (2) «(не использовать)»+«(нет)», оба 0% -- оба решения явные; (3) ручной выбор «(нет)» на остановке при сомнительном авто-детекте (Country conf 25) -- статус из факта решения. 2 guard-теста зелёНЫ ДО кода и остаются контрактами: сомнительное угадывание КОНКРЕТНОЙ колонки (Year conf 40) -- честный warning; уверенные конкретные выборы (95/85) -- done.
Миграции контрактов (следствие фикс-а, не ослабление): шапка describe «зелёной подсветки» (Структура -- done) + 2 теста матрицы статус x активность: warning-пример «Структура» -> «Качество» (единственный warning стандартного мока), клик-деактивация «Качество» -> «Структура» (теперь done). Обе миграции нейтральны к RED (зелёны и на старом коде) -- матрица перекодирована под новую реальность.
GREEN: файл 37/37 (5 новых + 32 предсуществующих). Полный Jest: 148 сюит / 1786 тестов -- все зелёные (1781 база + 5 новых). typecheck:all (embedded+standalone) -- чисто; build:all -- оба приложения Compiled successfully.

### Осознанные границы

- «(нет)»/«(не использовать)» как АВТО-выбор бэкенда (колонки действительно нет) и как РУЧНОЙ выбор пользователя уравнены: оба -- решающий факт «колонки нет»; различить их по локальному состоянию модуля невозможно и не требуется (в обоих случаях сомнения в выборе нет). Качество самого авто-детекта конкретных колонок по-прежнему видно бейджем и списком кандидатов на остановке.
- Сомнительное угадывание КОНКРЕТНОЙ колонки (confidence<70) остаётся warning даже при ручном выборе другой конкретной колонки (confidence не пересчитывается, 2026-08-14) -- вне постановки; возможное продолжение («любой ручной выбор = confident» из прецедента confidentDateCol) требует трекинга факта ручного вмешательства и не заказано.
- chart-stop не тронут (см. Реализация); freq в формуле «Структуры» не участвует -- как и прежде.
- scripts/progr13_repro_defects.py и оракулы PROGR-13-CERT -- датированные свидетельства приёмок, не трогались (сценарий «панель == модулю» в них не зависит от формулы модуля: статусы подаются на вход).

### Deliverable

ZIP: cisstat-progr14-a-structure-decision-status.zip -- пути репозитория сохранены.
ИЗМЕНЕНЫ: packages/ui/components/TsAnalysisUpload.tsx (EXPLICIT_NONE_CHOICES/isExplicitNoneChoice/isStructureDecisionConfident + формула structure), packages/ui/components/TsAnalysisUpload.test.tsx (describe PROGR-14-A: 5 тестов; mockFetchSequence +detectionOverride; миграции матрицы подсветки), worklog/worklog8.md (эта запись).
Без commit/push (AGENTS.md).

---

## Task ID: PROGR-15-A (2026-10-06) — Отчёт остановок «Загрузки» доходит до бэкенда: URL через progressApiUrl + проверка res.ok (причина Г-1 расследования PROGR-15-REPRO)
База: main@aff4d81 (PROGR-14-A принят в main; рабочее дерево до задачи чистое). Правила AGENTS.md соблюдены: commit/push НЕ выполнялись; TDD RED->GREEN; сборка проверена. Расследование сценария тимлида (демо forecast_monitor_synthetic_n150: модуль 4 зелёных + жёлтое «Качество», панель «Прогресс» -- только «Превью»+«Структура», Наставник требует «подтвердить структуру») -- предыдущей read-only задачей; причины Г-1/Г-2 подтверждены тимлидом, настоящая задача закрывает Г-1.

### Корень (подтверждён по коду @aff4d81, симптом A расследования)
postStops (TsAnalysisUpload.tsx:785) строил URL через sessionApiUrl("/v1/progress/upload-stops"), но sessionApiUrl добавляет префикс /v1/session САМ (apiClient.ts:56-58) -- фактический путь /v1/session/v1/progress/upload-stops, гарантированный 404 на любом окружении (бэкенд-маршрут: apps/api/main.py:89 prefix="/v1/progress" + routers/progress.py:373 @router.post("/upload-stops")). fetch резолвится и с HTTP-ошибкой: res.ok не проверялся, .catch ловил только сеть -- отчёт «успешно» не доходил до единого движка НИ РАЗУ. Панель «Прогресс» жила на одних бэкенд-фактах (upload_completed -> «Превью», structure_confirmed -> «Структура»); модульные статусы 5 остановок терялись молча -- наблюдаемое расхождение «модуль 4 зелёных + жёлтый, панель 2 зелёных». Правильный хелпер progressApiUrl существовал (apiClient.ts:65-67) и НЕ использовался ни одним вызовом. Аудит grep по packages/: дефект изолирован одной строкой; по apps/ -- нарушений нет. Почему тесты не ловили: ноль URL-ассертов на upload-stops; мок-помощник TsAnalysisUpload.test.tsx матчит fetch по подстроке "/upload", под которую попадает и "upload-stops" -- мусорный URL обслуживался моком как легитимный; live-repro PROGR-13-A постит прямой URL бэкенда, минуя фронт.

### Реализация
packages/ui/components/TsAnalysisUpload.tsx:

postStops: fetch(progressApiUrl("/upload-stops")) -- единственный содержательный фикс; импорт хелпера добавлен (строка 98).
Харденинг res.ok: при !ok маркер lastReportedStopsRef сбрасывается -- HTTP-неудача проходит тем же контуром повтора, что и сетевая (.catch), семантика «вспомогательного контура §12 п.8» сохранена (без алертов и таймеров).
Комментарий блока PROGR-13-A5 дополнен фиксацией URL-контракта и корня дефекта.
Панель, бэкенд, формула stopStatus (PROGR-14-A), контракт POST /v1/progress/upload-stops (PROGR-13-A4 корректен) -- НЕ тронуты.

### TDD
RED: describe «PROGR-15-A: URL-контракт отчёта остановок в „Прогресс“» в TsAnalysisUpload.test.tsx (2 теста) + НОВЫЙ packages/ui/lib/apiUrlPrefixGuard.test.ts (скан-инвариант класса: ни один вызов apiUrl/sessionApiUrl/progressApiUrl во всём фронтенд-коде packages/+apps/ не содержит "/v1" в аргументе -- двойной префикс ловится на CI, паттерн TRACE_ROUTES PROGR-3 «опечатка не доходит до рантайма»). Дискриминирующий диагностикул RED: Expected "http://localhost:8000/v1/progress/upload-stops", Received "http://localhost:8000/v1/session/v1/progress/upload-stops" -- дефект воспроизведён литерально в обоих URL-ассертах; guard падал с единственным нарушителем TsAnalysisUpload.tsx. Честная квалификация: тест 2 («HTTP-неудача не блокирует последующие отчёты») -- КОНТРАКТ, не дискриминатор: повтор при изменении снапшота работает и на старом коде (ref выставляется до поста, следующий снапшот отличается строкой) -- RED-часть у него только URL-ассерт. Сброс ref при !ok в текущей архитектуре эффектов наблюдаемо инертен (эффект перезапускается только сменой снапшота, которая сама инвалидирует сравнение) -- принят как симметрия с .catch и документирование контракта, без ложного claim «фикс ретраев».
Дизамбигуация мока: mockFetchSequence -- 4-й параметр stopsOkSequence (сценарии приёма отчёта: каждый вызов берёт следующее значение, последнее повторяется) + ветка "upload-stops" ДО ветки "/upload" (коллизия подстрок, маскировавшая дефект, снята и закомментирована).
GREEN: файл 40/40 (37 предсуществующих + 2 новых + guard-файл отдельной сюитой). Полный Jest: 149 сюит / 1789 тестов -- все зелёные (1786 базы + 3 новых: 2 контракта + guard). typecheck:all -- чисто; build:all -- оба приложения Compiled successfully.

### Осознанные границы
Г-2 (Наставник) -- ОТДЕЛЬНАЯ задача PROGR-15-B: статический шаблон PHASE_TEXT_TEMPLATES["upload"] (app/core/mentor_rules.py:762-766, phase_text(stage) без фактов) противоречит summary того же ответа next-step (structure=done); план согласован (phase_text(stage, statuses=None), ветвление по узлу upload/structure), в эту задачу не входил.
Повтор неудачного отчёта -- по следующему изменению stopStatus / reportUploadStopsNow (как и до фикса): периодический таймер ретраев сознательно не вводился (вспомогательный контур, §12 п.8).
Guard-скан -- статический (regex по исходникам): ловит вложение "/v1" в АРГУМЕНТ хелперов; конкатенации обходными путями не ловит (риск принят: единственный прецедент класса -- именно буквальный аргумент).
scripts/progr13_repro_defects.py и оракулы PROGR-13-CERT -- датированные свидетельства, не трогались.

---

## Task ID: PROGR-15-B (2026-10-06) — Текст фазы «Загрузки» Наставника -- из фактов решения, не статический шаблон (причина Г-2 расследования PROGR-15-REPRO); упоминание целевого признака обусловлено фактом target_column_changed
База: main@f3bfad4 (PROGR-15-A принят в main; клон в свежем контейнере, рабочее дерево до задачи чистое). Правила AGENTS.md соблюдены: commit/push НЕ выполнялись; TDD RED->GREEN; сборка проверена. Постановка тимлида: факт-обусловленный текст фазы по согласованному плану + РАСШИРЕНИЕ -- обусловить и упоминание целевого признака фактом target_column_changed (проброс событий в phase_text).

### Корень (подтверждён по коду @f3bfad4, симптом B расследования)
PHASE_TEXT_TEMPLATES["upload"] (app/core/mentor_rules.py) -- жёсткая строка «подтвердите структуру данных и целевой признак…»; phase_text(stage) фактов не читает. В сценарии тимлида Наставник требовал подтвердить УЖЕ подтверждённую структуру: факт upload/structure=done лежит в той же трассе, а summary ТОГО ЖЕ ответа next-step показывает structure=done (JSON противоречит сам себе в одном payload). Потребители без изменений: панель/фронт читают phase_text как строку.

### Реализация
app/core/mentor_rules.py:

Сигнатура phase_text(stage, statuses=None, events=None) -- РАСШИРЕНИЕ контракта (не ломающее): вызов по-старому возвращает дословно статический шаблон; неизвестная стадия -- прежний fail-safe fallback.
Ветвление ТОЛЬКО для стадии upload, по фактам решения: узел upload/structure -- из статусов единого движка (те же derive_node_statuses, что читает summary ответа); выбор целевого признака -- _target_confirmed(events): target_column_changed с НЕПУСТЫМ payload.target_column. Семантика факта цели -- та же, что у метаданных ResearchRun.target_column (research_runs.py:869-871): пустой payload -- сброс выбора, не факт; мусор/чужие типы -- пропуск через event_to_dict (деградация «событие мимо фактов», не 500).
Четыре консистентных варианта текста: оба факта -- «структура подтверждена, целевой признак выбран»; только структура -- просьба про цель; только цель -- просьба про структуру; ни одного -- прежний статический шаблон. Консервативные трактовки неполного контекста: события без статусов -- структура считается неподтверждённой; статусы без событий -- цель невыбранной: НЕИЗВЕСТНЫЙ факт не превращается в утверждение.apps/api/routers/progress.py (next-step): phase_text(last_stage, statuses=statuses, events=events) -- статусы и события уже вычислены выше, ноль дополнительного I/O; контракт MentorNextStepResponse прежний (phase_text: str), фронт не тронут.

### TDD
RED: tests/api/test_mentor_rules.py -- НОВЫЕ TestPhaseTextUploadFacts (10 unit) + TestMentorNextStepPhaseFacts (4 REST; сидирование _seed_run/_seed_event по образцу существующих REST-тестов). Падения РОВНО 13 (контракты): unit -- TypeError «phase_text() takes 1 positional argument but 2 were given» (контракт не расширен); REST -- AssertionError «'подтвердите структуру' is contained here: …» при факте upload/structure=done в сидированной трассе (дефект воспроизведён литерально). 2 guard-теста зелёны ДО кода и остаются контрактами: вызов по-старому == статический шаблон (обратная совместимость); run без фактов == статический шаблон. Два источника одного факта структуры покрыты раздельно: upload_stop_status (отчёт модуля, PROGR-13-A4) и structure_confirmed (POST /date-column, PROGR-13-A3).GREEN: сьют 68/68 (55 предсуществующих + 13 новых). Связанные потребители движка/трассы (node_status_engine, progr13a/b/c, defects, panel, trace_hook, research_runs, admin_progress_api, run_report, trace_events, pipeline_graph): 560 passed.Верификация: полный tests/api -- 1278 passed / 1 skipped / 3 failed (test_modeling_workflow catalog-only, test_models_backtest_neural_capacity память, test_models_candidates unsupported-model) -- 1:1 воспроизведены на ЧИСТОМ f3bfad4 через git stash (предсущественные средовые, известны со времён PROGR-1/PROGR-13-B). Jest (фронт не тронут, страховка): 149 сюит / 1789 тестов -- все зелёные. typecheck:all -- чисто; build:all -- оба приложения Compiled successfully.

### Осознанные границы
Факт цели -- НАЛИЧИЕ target_column_changed с непустой колонкой в истории запуска: тип события не несёт различения «авто-выбор хука vs ручной выбор» (auto-POST useTargetColumn сеет тот же тип; задокументированный баг raw confidence 2026-08-14 -- другой контур). Уточнение семантики «осознанного выбора цели» требует нового факт-типа -- вне постановки.
Ветвление только для upload: остальные шаблоны описательные («Идёт этап…») и фактам не противоречат; обусловливать их -- расширение без заказа.
«upload/structure» -- канонический ключ; legacy «structure_confirmed» нормализуется на границе чтения движка (PROGR-13-B3) -- копии ключей в phase_text не заводились (владение: единственный движок).
Мутационная защита: RED-ассерты целевые (просьба «подтвердите структуру»/«подтвердите целевой» как подстроки case-insensitive) -- подмена вариантов текста или снятие ветвления ловится сьютом; отдельный мутационный прогон не заказывался.
scripts/progr13_repro_defects.py и оракулы PROGR-13-CERT -- датированные свидетельства, не трогались.

---

## Task ID: PROGR-16-A (2026-10-06) — Отчёт фактов проверок модулем «Валидация»: POST /v1/progress/validation-checks + тип validation_check_status (закрытие дефекта PROGR-16-REPRO «Валидация. Не начато»); граница задачи -- только validation
База: main@c164e95 (PROGR-15-B принят в main; рабочее дерево до задачи чистое). Правила AGENTS.md соблюдены: commit/push НЕ выполнялись; TDD RED->GREEN->миграции контрактов; typecheck+build проверены. Квалификация тимлида: класс дефекта подтверждён («отсутствующий носитель факта»), инвариант «панель == модулю» применим, трасса -- дополнительный слой; граница -- validation, preprocessing, РЕАЛИЗАЦИЯ -- только для Валидации (Предобработка -- родственная зона, отдельная задача).

### Корень (подтверждён расследованием PROGR-16-REPRO @c164e95)
«Запустить валидацию» (TsAnalysisValidation.tsx -> GET /dataset/validate) вычисляла статусы 10 проверок, но факт-контур стадии validation не имел носителя результатов запуска: (1) GET /dataset/validate не в TRACE_ROUTES; (2) клиентский отчёт не существовал; (3) типа события не было в реестре §4.1. Панель /trace (единственный источник -- факты трассы, решение Расхождения №1) честно выводила все узлы validation/* pending -> fold not_started -> «Валидация. не начато» при цветном модуле.

### Реализация
apps/api/trace_events.py: тип validation_check_status в _STAGE_EVENT_TYPES["validation"] (гейт make_trace_event; комментарий -- корень дефекта и паттерн).
app/core/node_status.py: validation_check_status в PAYLOAD_STATUS_EVENT_TYPES (статус из payload["status"], whitelist CHECK_STATUS_VALUES -- тот же механизм, что upload_stop_status) + EVENT_NODE_REASON («Статус проверки отчитан модулем «Валидация»»).
apps/api/routers/progress.py: POST /v1/progress/validation-checks (ValidationChecksReportIn.checks: Dict[str,str] -> ValidationChecksReportResponse{run_id, reported}) -- зеркало report_upload_stops: fail-closed 422 (пустая карта / неизвестная проверка вне STAGE_NODES["validation"] / статус вне CHECK_STATUS_VALUES / неполная карта -- ДО первой записи, all-or-nothing), 400 без датасета, ensure_run_id, события stage="validation" по узлам CHECK_IDS в слой 1 (append_trace_event) + зеркало слоя 2 (record_run_event, best-effort), save.
app/core/run_report.py: _validation_check_status_line -- человекочитаемая строка факта отчёта §5.4, метка проверки из реестра справки (node_label("validation", ...)), статус словами CheckStatus; ветка в fact_line (та же гранулярность, что у панели).
packages/ui/components/TsAnalysisValidation.tsx: postChecks (fetch(progressApiUrl("/validation-checks"), POST, credentials) -- URL-контракт PROGR-15-A: хелпер progressApiUrl, НЕ sessionApiUrl; res.ok проверяется, при !ok маркер сбрасывается -- симметрия .catch, повтор по следующему снапшоту, §12 п.8); checksReportSnapshot -- JSON снапшот статусов РОВНО как показывает степпер (displayedStatus: pending+needs_rule -> warning), только при validationHasRun && checksData (до первого запуска отчёта НЕТ -- модуль не существует как источник фактов); эффект отчёта по смене снапшота (идентичность -- строка, последний wins); сброс маркера при смене датасета (новая вселенная фактов -- повторный запуск с идентичной картиной обязан репортиться).
spec_progress.md: §4.1 строка validation/preprocessing + примечание PROGR-16-A (носитель факта, контракт эндпоинта, граница задачи).

### TDD
RED: НОВЫЙ tests/api/test_progress_progr16.py (8 тестов: движок -- payload-статус с whitelist-мусором None, узловой факт + фаза Наставника -> validation; эндпоинт -- полный контракт end-to-end слой1+слой2+/trace+fold attention, fail-closed all-or-nothing 4 вида x 422, 400 без датасета, посев run_id на первом отчёте, last-wins при повторном отчёте; отчёт §5.4 -- метки из реестра). На @c164e95 падали РОВНО 8: движок -- resolve_event_status None (типа нет), эндпоинт -- 404, отчёт -- нет строки. НОВЫЙ describe PROGR-16-A в TsAnalysisValidation.test.tsx (3 теста) + хелпер mockProgressReportValidation (маршрут /validation-checks с записью URL+body): URL-дискриминатор «Expected http://localhost:8000/v1/progress/validation-checks» -- на старом коде ноль вызовов; guard «до запуска не отчитывать» зелёный ДО кода (контракт-инвариант). Падение 2/2 дискриминаторов подтверждено прогоном.
GREEN: test_progress_progr16 8/8; связанный контур (node_status_engine, progress_panel, trace_hook, progr13a/b/c, defects_progr13, mentor_rules, run_report, admin_progress_api, pipeline_graph, research_runs) -- 544 passed.
Миграции контрактов (следствие расширения реестров, не ослабление): test_node_status_engine (PAYLOAD_STATUS_EVENT_TYPES == {upload_stop_status, validation_check_status}) + test_trace_events::test_registry_per_spec_table (строка validation + validation_check_status).
Верификация: полный tests/api -- 1303 passed / 1 skipped / 19 failed; ВСЕ 19 воспроизведены 1:1 на ЧИСТОМ c164e95 через git stash (средовые, свежий контейнер: forecasting_session x16, modeling_workflow, models_backtest_neural_capacity память, models_candidates; известны по PROGR-15-B, там же зафиксирован их средовый характер; дополнительно установлен ruptures -- его отсутствие давало средовый провал eda_structural_breaks, на базе -- тот же). Jest полный: 149 сюит / 1792 теста -- все зелёные (1789 базы + 3 новых). typecheck:all -- чисто; build:all -- оба приложения Compiled successfully.

### Осознанные границы
Предобработка: та же дыра класса (запуск preprocess-вычислений не является фактом), СОЗНАТЕЛЬНО вне границы -- отдельная задача.
Семантика повтора: сброс маркера при !ok симметричен .catch; сам по себе он НЕ инициирует повтор -- эффект перезапускается сменой снапшота (задокументированная семантика PROGR-15-A; тест «повтор» построен на смене картины статусов, без таймеров).
До первого запуска отчёта нет: модуль без вычислений -- не источник фактов (не путать с «все pending после запуска» -- такой снапшот отчитывается честно).
Отчёт -- снапшот displayedStatus (вид пользователя), не сырых статусов ответа: инвариант «панель == модулю» определён по НАБЛЮДАЕМОМУ.
Фаза Наставника после запуска валидации -- «validation» (validation_check_status -- узловой факт): ожидаемое следствие контракта B1, тестом закреплено.
Панель/Наставник/admin-аналитика/отчёт -- потребители БЕЗ изменений кода (единый движок); trace_hook не тронут (клиентский отчёт, не маршруты сессии).
Установка зависимостей в контейнер (pywt/pandera/arch/statsforecast/tbats/prophet/psycopg2-binary/sqlalchemy/ruptures) -- средовое, код репозитория не касается.

### Deliverable
ZIP: cisstat-progr16-a-validation-checks-report.zip -- пути репозитория сохранены.
НОВЫЕ: tests/api/test_progress_progr16.py.
ИЗМЕНЕНЫ: apps/api/trace_events.py, app/core/node_status.py, apps/api/routers/progress.py, app/core/run_report.py, packages/ui/components/TsAnalysisValidation.tsx, packages/ui/components/TsAnalysisValidation.test.tsx, tests/api/test_node_status_engine.py (миграция контракта), tests/api/test_trace_events.py (миграция контракта), spec_progress.md (§4.1), worklog/worklog8.md (эта запись).
Без commit/push (AGENTS.md).

---

## Task ID: PROGR-17 (2026-10-06) — Отчёт фактов этапов модулем «Предобработка»: POST /v1/progress/preprocessing-checks + тип preprocessing_check_status (зеркало PROGR-16-A; spec_progress_v1.1.md §2, категория B)
База: main@3ace7d2 (spec_progress_v1.1.md принят в main; рабочее дерево до задачи чистое, HEAD detached на 3ace7d2). Правила AGENTS.md соблюдены: commit/push НЕ выполнялись; TDD RED→GREEN; мутационные пробы; typecheck+build проверены. Постановка — сводный план задач spec_progress_v1.1.md §6: «PROGR-17, категория B: preprocessing_check_status, backend+frontend, по образцу PROGR-16-A».

### Корень (зафиксирован v1.1 §2)
PROGR-16-A закрыл класс «нет носителя факта прохождения» только для Валидации. Для Предобработки та же дыра: степпер автозаполняется профилями 10 остановок (missing/outliers/regularity/decomposition/variance_stab/smoothing/stationarity/spectral/feature_eng/scaling == PREPROCESSING_CHECK_IDS), но факт-контур стадии preprocessing не имел носителя результатов — панель показывала «не начато» при цветном модуле (тот же класс «отсутствующего носителя факта», родственная зона PROGR-16-REPRO).

### Реализация
apps/api/trace_events.py: тип preprocessing_check_status в _STAGE_EVENT_TYPES["preprocessing"] (гейт make_trace_event; комментарий — корень и паттерн).
app/core/node_status.py: preprocessing_check_status в PAYLOAD_STATUS_EVENT_TYPES (статус из payload["status"], whitelist CHECK_STATUS_VALUES — тот же механизм, что upload_stop_status/validation_check_status) + EVENT_NODE_REASON («Статус проверки отчитан модулем «Предобработка»»).
apps/api/routers/progress.py: POST /v1/progress/preprocessing-checks (PreprocessingChecksReportIn.checks: Dict[str,str] → PreprocessingChecksReportResponse{run_id, reported}) — зеркало report_validation_checks буквально: fail-closed 422 (пустая карта / неизвестная остановка вне STAGE_NODES["preprocessing"] / статус вне CHECK_STATUS_VALUES / неполная карта — ДО первой записи, all-or-nothing), 400 без датасета, ensure_run_id, события stage="preprocessing" по узлам PREPROCESSING_CHECK_IDS в слой 1 (append_trace_event) + зеркало слоя 2 (record_run_event, best-effort), save.
app/core/run_report.py: _preprocessing_check_status_line — человекочитаемая строка факта отчёта §5.4, метка остановки из реестра справки (node_label("preprocessing", ...); все 10 остановок имеют статьи «Метрики и алгоритм» — проверено по registry_data.json), статус словами CheckStatus; ветка в fact_line. Модуль назван ЯВНО («отчитан модулем «Предобработка»»): строка Валидации не тронута (существующий контракт не сужается), в журнале отчёта строки однозначно различимы.
packages/ui/components/TsAnalysisPreprocessing.tsx: useAppShell() (activeDataset; оба приложения рендерят модуль под AppShellProvider — embedded/standalone layout, проверено); postChecks (fetch(progressApiUrl("/preprocessing-checks"), POST, credentials) — URL-контракт PROGR-15-A; res.ok проверяется, при !ok маркер сбрасывается — симметрия .catch, повтор по следующему снапшоту, §12 п.8); checksReportSnapshot — JSON снапшот статусов РОВНО как показывает степпер; гейт = activeDataset && ни одной «running» && ни одной «pending»; эффект отчёта по смене снапшота (строковая идентичность, последний wins); сброс маркера по activeDataset?.name (новая вселенная фактов).
ГЕЙТЫ ОТЧЁТА (отличие от Валидации — автозаполнение степпера вместо явного «Запустить»): (а) activeDataset — факты этапов без исследования не существуют (зеркало 400-гейта; 404-контур профилей даёт осевшие «skipped» БЕЗ исследования — не отчёт); (б) только ПОЛНОСТЬЮ осевший снапшот (ни running, ни pending): транзит авто-перезапросов PROGR-9-FOCUS (фокус окна/вкладки) и стартовый pending 7 целевых остановок (не начинают вычисления без activeFeature) — не факты; (в) строковая идентичность дедуплицирует фокус-рефетчи с неизменной картиной; (г) порядок эффектов ВАЖЕН: сброс маркера объявлен ДО эффекта отчёта — в коммите гидратации activeDataset сброс выполняется первым и не затирает маркер уже сделанного отчёта (иначе дедупликация слепа навсегда).

### TDD
RED: НОВЫЙ tests/api/test_progress_progr17.py (8 тестов, зеркало test_progress_progr16: движок — payload-статус с whitelist-мусором None, узловой факт + фаза Наставника → preprocessing; эндпоинт — полный контракт end-to-end слой1+слой2+/trace+fold attention (6 done/3 warning/1 skipped), fail-closed all-or-nothing 4 вида x 422, 400 без датасета, посев run_id на первом отчёте, last-wins при повторном отчёте; отчёт §5.4 — метки «Пропуски»/«Выбросы» из реестра). На @3ace7d2 падали РОВНО 8: движок — resolve_event_status None (типа нет), эндпоинт — 404, отчёт — строка-фоллбек «Событие трассы».

RED frontend: НОВЫЙ describe PROGR-17 в TsAnalysisPreprocessing.test.tsx (3 теста) + хелпер mockProgressReportPreprocessing (маршрутизация 10 профилей + /session/current + /progress/preprocessing-checks с записью URL+body; все 68 прежних render(...) переведены на модульный renderPreprocessing() c AppShellProvider — компонент теперь читает useAppShell). Дискриминаторы URL («Expected http://localhost:8000/v1/progress/preprocessing-checks») — на старом коде ноль вызовов (2 упавших); guard «без датасета не отчитывать» зелёный ДО кода (контракт-инвариант).

Итерация GREEN (находка теста, зафиксированная в коде): первый вариант гейта «!anyRunning» ловил промежуточный снапшот (3 dataset-wide остановки осели, 7 целевых ещё «pending» — их эффекты ждут activeFeature) и репортил его; тест «ровно 1 POST с полным снапшотом» это поймал ДО попадания в трассу — гейт усилен до полного оседания (ни running, ни pending).

GREEN: test_progress_progr17 8/8; TsAnalysisPreprocessing.test.tsx 73/73 (68 прежних + 3 новых + 1 guard); связанный контур (node_status_engine, progress_panel, trace_hook, progr13a/b/c, defects_progr13, mentor_rules, run_report, admin_progress_api, pipeline_graph, research_runs, progr16, progr17) — 552 passed.

Миграции контрактов (следствие расширения реестров, не ослабление): test_node_status_engine (PAYLOAD_STATUS_EVENT_TYPES == {upload_stop_status, validation_check_status, preprocessing_check_status}) + test_trace_events::test_registry_per_spec_table (строка preprocessing + preprocessing_check_status).

### Верификация
Полный tests/api — 1311 passed / 1 skipped / 19 failed; ВСЕ 19 воспроизведены 1:1 на ЧИСТОМ 3ace7d2 (git stash — упреждающе при отладке jest-конфига) и совпадают со средовым набором PROGR-16-A: forecasting_session x16, modeling_workflow (catalog-only-гейт), models_backtest_neural_capacity (память хоста), models_candidates (unsupported-model гейт) — к задаче не относятся.

Jest полный: 149 сюит / 1795 тестов — все зелёные (1792 базы + 3 новых). typecheck:all — чисто; build:all — оба приложения Compiled successfully.

Мутационные пробы (каждая — правка → прогон → откат): M-1 снят гейт неполной карты (all-or-nothing) — пойман test_...fail_closed_all_or_nothing (KeyError на партиальной карте в assert слоя 1); M-2 удалено зеркало record_run_event — пойман test..._full_contract (слой 2 пуст); M-4 URL через sessionApiUrl (двойной префикс) — пойманы 2 дискриминатора describe PROGR-17; M-5 снят гейт activeDataset — НЕ пойман (замаскирован pending-гейтом: без датасета activeFeature не приходит, целевые остановки остаются «pending», снапшот не оседает). Вывод по M-5: гейт activeDataset — оборонительный слой (зеркало 400-гейта бэкенда, защита экзотического stale-target-края), первичный контур — оседание снапшота, финальный арбитр — 400; осознанная избыточность, оставлен намеренно.

### Осознанные границы
Датасет БЕЗ единой числовой колонки (вырожденный для платформы): целевые остановки остаются «pending» навсегда — отчёта нет (useTargetColumn авто-фиксирует рекомендацию при наличии хоть одной числовой колонки). Зафиксировано в коде и spec_progress.md §4.1.

Транзитные состояния («running»/стартовый «pending») в трассу не попадают — панель показывает последний ОСЕВШИЙ снапшот (та же семантика, что у Валидации во время перезапуска).

EDA (eda_check_status) — следующая задача PROGR-18 по v1.1 §2 (переиспользование этого паттерна); методологический вопрос семантики статуса EDA поставлен в v1.1 и не решается здесь.

Панель/Наставник/admin-аналитика/отчёт — потребители БЕЗ изменений кода (единый движок); trace_hook не тронут (клиентский отчёт, не маршруты сессии).

---

## Task ID: PROGR-18 (2026-10-06) — Отчёт фактов просмотров исследований модулем «EDA»: POST /v1/progress/eda-checks + тип eda_check_status (зеркало PROGR-16-A/17; spec_progress_v1.1.md §2, категория B)
База: main@0fc5293 (рабочее дерево до задачи чистое). Правила AGENTS.md соблюдены: commit/push НЕ выполнялись; TDD RED→GREEN; мутационные пробы; typecheck+build проверены. Постановка — сводный план задач spec_progress_v1.1.md §6: «PROGR-18, категория B: eda_check_status, backend+frontend, тот же паттерн + решение по семантике статуса EDA». РЕШЕНИЕ ТИМЛИДА (фиксация): статус `done`/`pending` по факту «аналитик открыл и просмотрел результат», `warning` НЕ вводить (ложная тревога там, где нет критерия ошибки — EDA не проверка качества, а анализ).

### Корень (зафиксирован v1.1 §2)
PROGR-16-A/17 закрыли класс «нет носителя факта прохождения» для Валидации и Предобработки. Для EDA аналогичного отчётного контура не было никогда: узлы eda/* не достигали done от самого модуля (profile_viewed → running, троттлинг §4.2) — панель показывала «не начато»/«в работе» при просмотренных аналитиком исследованиях; критерии «проверки пройдена/есть замечания» к EDA неприменимы по определению (анализ, не проверка качества).

### Семантика статуса (реализация решения тимлида)
Словарь отчёта EDA — ровно ("done", "pending"), константа EDA_CHECK_STATUS_VALUES в routers/progress.py, ENFORCED эндпоинтом fail-closed: легальный CheckStatus «warning» в отчёте EDA — 422 с пояснением решения (движок node_status при этом остаётся общим — whitelist CHECK_STATUS_VALUES, трасса журнал; граница слоёв задокументирована тестом Э-1). «Просмотрено» = исследование АКТИВНО (activeCheckId) И его результат ПОКАЗАН модулем (статус исследования done/warning: найденные особенности результата — нестационарность, сдвиги, блокировки матрицы моделей — НЕ мешают факту просмотра, они остаются в модуле; running/error/skipped результата не показывают — факта просмотра нет). Множество просмотренных МОНОТОННО в пределах датасета (увиденный результат не «развидеть», в т.ч. при пересчётах/смене признака); смена датасета — новая вселенная фактов (ключ datasetKey = datasetId ?? name — точнее name PROGR-17: datasetId меняется даже при повторной загрузке файла с тем же именем). До первого показанного результата отчёта НЕТ (модуль без просмотренных результатов — не источник фактов).

### Реализация
apps/api/trace_events.py: тип eda_check_status в _STAGE_EVENT_TYPES["eda"] (гейт make_trace_event; комментарий — корень и паттерн).
app/core/node_status.py: eda_check_status в PAYLOAD_STATUS_EVENT_TYPES (статус из payload["status"]) + EVENT_NODE_REASON («Статус исследования отчитан модулем «EDA»» — терминология ИССЛЕДОВАНИЕ, не проверка).
apps/api/routers/progress.py: POST /v1/progress/eda-checks (EdaChecksReportIn.checks: Dict[str,str] → EdaChecksReportResponse{run_id, reported}) — зеркало report_preprocessing_checks буквально: fail-closed 422 (пустая карта / неизвестное исследование вне STAGE_NODES["eda"] / статус вне EDA_CHECK_STATUS_VALUES / неполная карта — ДО первой записи, all-or-nothing), 400 без датасета, ensure_run_id, события stage="eda" по узлам EDA_STAGE_IDS (общий JSON eda_checks.json §12 п.2) в слой 1 (append_trace_event) + зеркало слоя 2 (record_run_event, best-effort), save.
app/core/run_report.py: _eda_check_status_line + _EDA_STATUS_LABELS — человекочитаемая строка факта §5.4 с формулировками факта ПРОСМОТРА («результат просмотрен аналитиком»/«ещё не просмотрен аналитиком» — не «выполнена»: pass/fail-семантики нет), метка исследования из реестра справки (node_label("eda", ...); все 10 исследований имеют статьи «Метрики и алгоритм» — проверено по registry_data.json), модуль назван ЯВНО («отчитан модулем «EDA»» — строка однозначно отличается от строк «Валидации»/«Предобработки»); ветка в fact_line.
packages/ui/components/TsAnalysisEDA.tsx: отчётный контур (блок после checks-memo, порядок эффектов — урок PROGR-17: сброс → seed → postEdaChecks → факт просмотра → снапшот → отчёт). Факт просмотра: эффект по [checks, activeCheckId, edaSeedReady] — активное исследование с статусом done/warning → идемпотентное добавление в edaViewedIds (Set). Снапшот: JSON всех 10 исследований реестра в порядке JSON (viewed → done, остальные pending) — тот же сериализатор buildEdaChecksSnapshot для маркера и для отчёта (строковая идентичность). postEdaChecks: fetch(progressApiUrl("/eda-checks"), POST, credentials) — URL-контракт PROGR-15-A; res.ok проверяется, при !ok маркер сбрасывается — симметрия .catch, повтор по следующему снапшоту (§12 п.8, без таймеров); гейт activeDataset — зеркало 400-гейта.
ЯКОРЬ В ЖУРНАЛЕ (осознанное отличие от зеркала, главная находка проектирования): вкладки платформы — роуты Next.js, модуль РАЗМОНТИРУЕТСЯ при каждом переключении; кумулятивное множество просмотренных, в отличие от детерминированно выводимых статусов Валидации/Предобработки, из ответов НЕ восстанавливается — первый снапшот после перемонтирования/перезагрузки (descriptive-only) ПЕРЕЗАПИСАЛ бы факты назад (last-wins): панель/Наставник занижали бы прогресс, журнал регрессировал. Решение: при монтировании одноразовый GET /v1/progress/trace (§7.2-прецедент «клиент строит сводку из уже полученных данных» — читаются уже ПОСЧИТАННЫЕ движком node_statuses, НЕ опрос profile-эндпоинтов, решение Расхождения №1 не трогается) → seed done-узлов eda/* (фильтр по известным id реестра) → слияние с текущим множеством, маркер инициализируется seed-снапшотом → отчёт происходит ТОЛЬКО по новому просмотру, дедупликация переживает перемонтирование. Seed best-effort (§12 п.8): сбой/старый бэкенд — пустой якорь, отчёт с чистого листа. edaSeedReadyRef-гейт в эффекте факта просмотра отсекает устаревшие статусы предыдущей вселенной в коммите смены датасета (ref опускается синхронно сброс-эффектом раньше — фантомного факта в мёртвой вселенной не возникает; state edaSeedReady дублирует ref для рендер-гейта снапшота).

### TDD
RED: НОВЫЙ tests/api/test_progress_progr18.py (9 тестов, зеркало test_progress_progr17 + специфика EDA: движок — payload-статус с whitelist-мусором None + граница слоёв «движок общий / словарь отчёта enforced эндпоинтом», узловой факт + составной ключ eda/stationarity ≠ preprocessing/stationarity + фаза Наставника → eda; эндпоинт — полный контракт end-to-end слой1+слой2+/trace+fold attention при 6 done/4 pending и warning_nodes=0, fold passed при 10/10, fail-closed all-or-nothing 5 видов x 422 ВКЛЮЧАЯ легальный «warning» (решение тимлида), 400 без датасета, посев run_id, last-wins; отчёт §5.4 — метки реестра + формулировки просмотра). На @0fc5293 падали РОВНО 9: движок — resolve_event_status None, эндпоинт — 404, отчёт — строка-фоллбек «Событие трассы».
RED frontend: НОВЫЙ describe PROGR-18 в TsAnalysisEDA.test.tsx (6 тестов) + хелпер mockProgressReportEda (маршрутизация /progress/trace-seed + /progress/eda-checks с записью URL+body поверх routeFetch): URL-дискриминатор «Expected http://localhost:8000/v1/progress/eda-checks» — на старом коде ноль вызовов; guard «без датасета не отчитывать» зелёный ДО кода (контракт-инвариант, как в PROGR-16-A/17). Падение 5/6 подтверждено прогоном.
GREEN: test_progress_progr18 9/9; TsAnalysisEDA.test.tsx 47/47 (41 прежних + 6 новых); связанный контур test_trace_events + test_node_status_engine — зелёные.
Миграции контрактов (следствие расширения реестров, не ослабление): test_node_status_engine (PAYLOAD_STATUS_EVENT_TYPES == {upload_stop_status, validation_check_status, preprocessing_check_status, eda_check_status}) + test_trace_events::test_registry_per_spec_table (строка eda + eda_check_status).

### Верификация
Полный tests/api — 1320 passed / 1 skipped / 19 failed; ВСЕ 19 воспроизведены 1:1 на ЧИСТОМ 0fc5293 (git stash) и совпадают со средовым набором PROGR-16-A/17: forecasting_session x16, modeling_workflow (catalog-only-гейт), models_backtest_neural_capacity (память хоста), models_candidates (unsupported-model гейт) — к задаче не относятся (свежий контейнер: зависимости доустановлены — PyWavelets/pandera/arch/statsforecast/tbats/prophet/psycopg2-binary/sqlalchemy/ruptures, средовое, код репозитория не касается).
Jest полный: 149 сюит / 1802 теста — все зелёные. typecheck:all — чисто; build:all — оба приложения Compiled successfully.
Мутационные пробы (каждая — правка → прогон → откат): M-1 снят гейт неполной карты — пойман fail_closed_all_or_nothing; M-2 удалено зеркало record_run_event — пойман full_contract (слой 2 пуст); M-3 словарь EDA расширен до CHECK_STATUS_VALUES (гейт тимлида снят) — пойман fail_closed (warning прошёл бы); M-4 URL через sessionApiUrl (двойной префикс) — пойманы 5 дискриминаторов describe PROGR-18; M-5 снят seed-якорь — пойман тест «anchors the viewed set from /trace» (перезапись фактов назад); M-6 ослаблен критерий просмотра до «открыл» (без показанного результата) — пойман тест «does not count a study with a failed fetch as viewed». Итог 6/6.

### Осознанные границы
Seed-якорь — ОДНОРАЗОВЫЙ GET /trace на монтирование модуля (не полинг): между отчётами панель может отстать от живого модуля не более чем на один просмотр — та же принятая цена «точность до последнего засеянного факта», что у всего факт-контура (Расхождение №1).
Мульти-вкладочность: два таба браузера с одной cookie-сессией могут разойтись в локальных множествах просмотренных; финальный арбитр — last-wins журнала, seed следующего монтирования якорит состояние журнала. Расширение контракта (merge на бэкенде) — новый механизм, сознательно не вводился (v1.1: «не изобретая новый механизм»).
«Панель == модулю» для EDA определена ПО ФАКТУ ПРОСМОТРА (решение тимлида), не по сырым статусам степпера модуля: аналитические warning/error/skipped остаются в модуле, панель отражает прохождение. Это зафиксированное семантическое отличие от Валидации/Предобработки (там снапшот = displayedStatus степпера).
Датасет БЕЗ числового признака: исследования с гейтом activeFeature остаются skipped (результата нет — просмотра нет) в pending навсегда; descriptive (без гейта) показывается и отчитывается. Зеркало границы PROGR-17.
Фаза Наставника после отчёта EDA — «eda» (eda_check_status — узловой факт): ожидаемое следствие контракта B1. Текст фазы «EDA: N/10 исследований просмотрено» — задача PROGR-19 (категория C), вне границы.
Прогнозирующие вызовы, trace_hook, панель, Наставник, admin-аналитика — потребители БЕЗ изменений кода (единый движок).

### Deliverable
ZIP: cisstat-progr18-eda-checks-report.zip — пути репозитория сохранены.
НОВЫЕ: tests/api/test_progress_progr18.py.
ИЗМЕНЕНЫ: apps/api/trace_events.py, app/core/node_status.py, apps/api/routers/progress.py, app/core/run_report.py, packages/ui/components/TsAnalysisEDA.tsx, packages/ui/components/TsAnalysisEDA.test.tsx, tests/api/test_node_status_engine.py (миграция контракта), tests/api/test_trace_events.py (миграция контракта), spec_progress.md (§4.1), worklog/worklog8.md (эта запись).
Без commit/push (AGENTS.md).

---

## Task ID: PROGR-17-CERT (2026-10-06) — Независимая сертификация Task PROGR-17 (оракулы на своих данных + мутанты аудитора)

### Постановка
Честная сертификация PROGR-17 по практике проекта (прецеденты TASK-144-CERT, PROGR-1-CERT): изучение spec_progress_v1.1.md и живого кода, НЕЗАВИСИМЫЕ мутационные пробы на СВОИХ мутантах (не копия M-1..M-5 записи PROGR-17), оракулы на СВОИХ данных, сверка всех заявлений worklog8.md. База аудита: main@0fc5293 (HEAD; PROGR-17 — коммит 2b9ae24). AGENTS.md: commit/push НЕ выполнялись; код платформы НЕ менялся (аудит + артефакты).

### Верификация приёмки (своё окружение, восстановлено с нуля)
Среда контейнера собрана заново: PyWavelets/pandera/arch/statsforecast/tbats/psycopg2-binary/sqlalchemy/ruptures + prophet (без prophet import-гейт models.py честно падает: prophet входит в PRODUCTION_BACKTEST_MODEL_IDS через runtime_available(); нейро-группа опциональна — гейт симметричен). test_progress_progr17 8/8; TsAnalysisPreprocessing.test.tsx 73/73; полный tests/api 1311 passed / 1 skipped / 19 failed — все 19 совпадают 1:1 с задокументированным средовым базлайном (forecasting_session ×16, modeling_workflow, neural_capacity, models_candidates); Jest полный 149 сьютов / 1796 зелёных (1795 worklog + 1 от последующего 0fc5293); typecheck:all чисто; build:all — оба приложения Compiled successfully. Все заявления записи PROGR-17 воспроизведены 1:1 (включая честное «M-5 НЕ пойман»); замечание: нумерация проб M-1..M-5 имеет дыру M-3 (не описан).

### Оракулы аудитора (свои данные) — scripts/progr17cert_oracles.py: 15/15 GREEN
Данные не пересекаются с fixtures коллеги: недельный cert17_weekly_sales_n120.csv (dt/sales/promo/store, 120 точек, ровно 7 инжектированных пропусков, 10x-выброс), снапшот выводится из РЕАЛЬНЫХ ответов 10 profile-эндпоинтов по семантике модуля (осел → status, 404 → skipped), признак — suggested_column из /target-column (как useTargetColumn). Группы: A — отпечатки своих данных (total_missing == 7 ровно; total_outliers ≥ 1; total_violations == 0); B — снапшот 10/10 осевший; C — контракт end-to-end (200/reported 10/run_id; слой 1 payload.status == снапшоту; зеркало слоя 2; панель == модулю все 10; свёртка warning → attention §12 п.10; last-wins; fail-closed ×4 с нулём записей; 400 без датасета; посев run_id); D — потребители (отчёт §5.4 для ВСЕХ 10 остановок с метками реестра без сырых id/фоллбеков; фаза Наставника B1 → preprocessing).

### Мутационный прогон аудитора — 22 СВОИХ мутанта: 15 KILLED / 7 SURVIVED (68.2%)
Протокол: scripts/progr17cert_mutations.py (backend), ..._fe.py (frontend), ..._fe FM-V отдельно (порядок эффектов), полный журнал scripts/progr17cert_mutation_results.txt. Backend 12/14: убиты все гейты fail-closed по-отдельности (фантом/мусор/неполнота), 400-гейт, зеркало слоя 2, stage-подмена, оба реестра движка, реестр трассы, 3 порчи строки отчёта. Выжившие: BM-A — ЭКВИВАЛЕНТНЫЙ (пустая карта отклоняется гейтом полноты тем же 422 до записи — empty-map gate избыточная оборона, дыры нет); BM-H — снятие store.save() незаметно в memory-режиме (дыра персистентности, общая с upload-stops/validation-checks). Frontend 3/8: убиты URL-дискриминаторы (sessionApiUrl — 2 теста), pending/running-гейты; выжившие: FM-S — маскировка pending-гейтом (НЕЗАВИСИМОЕ подтверждение вывода M-5); FM-T/FM-U/FM-W/FM-V — реальные дыры покрытия ВСПОМОГАТЕЛЬНЫХ контуров: повтор после HTTP-неудачи при неизменном снапшоте, дедупликация строковой идентичностью (дубликаты фактов при фокус-волнах не поймались бы), незакреплённый порядок эффектов. Ядро контракта (полный снапшот → трасса/панель/зеркало/отчёт) убой-консистентно.

### Находки (акт: docs/cert_progr17_preprocessing_checks_2026-10-06.md)
R1 (средняя): контур «неудача → повтор при НЕизменённом снапшоте» не покрыт (FM-T) — тест 3 покрывает только изменённый снапшот; R2 (средняя): дедупликация не покрыта (FM-U/FM-W) — регресс «дубликаты фактов на фокус-волну» прошёл бы незамеченно; R3 (низкая): порядок эффектов (сброс ДО отчёта) не закреплён тестом (FM-V), обоснование реально; R4 (низкая): персистентность store.save() не покрыта (BM-H); R5 (информационная): empty-map gate — избыточная оборона, контракт держит гейт полноты; R6 (документационная): дыра нумерации M-3 в записи PROGR-17; R7 (средовая): в чек-лист развёртывания добавить prophet (import-гейт среды). Рекомендация: R1–R4 закрыть тестами в PROGR-18 (переиспользует паттерн) отдельной тестовой задачей.

### Вердикт
**PASSED WITH REMARKS.** Критерии приёмки выполнены и подтверждены независимо; все заявления worklog8.md подтверждены 1:1; находки R1–R4 не блокируют (вспомогательные контуры, ядро не затронуто). Deliverable: ZIP cisstat-progr17-certification.zip (docs/cert_progr17_preprocessing_checks_2026-10-06.md, scripts/progr17cert_oracles.py, scripts/progr17cert_mutations.py, scripts/progr17cert_mutations_fe.py, scripts/progr17cert_mutant_fmv.py, scripts/progr17cert_mutation_results.txt, worklog/worklog8.md). Без commit/push (AGENTS.md).

---

## Task ID: PROGR-17-CERT-R1R4 (2026-10-06) — Закрытие находок R1–R4 сертификации тестами (TDD, мутационная верификация)

### Постановка
По рекомендации акта PROGR-17-CERT (§7): закрыть находки R1–R4 тестами — дыры покрытия ВСПОМОГАТЕЛЬНЫХ контуров отчёта фактов (мутанты FM-T, FM-U/FM-W, FM-V, BM-H выжили). Код платформы НЕ менялся — только тесты (контур уже корректен; дыры именно в покрытии). TDD-инверсия задачи: RED проверяется на СВОИХ мутантах сертификации (каждый новый тест обязан убить своего мутанта), GREEN — на чистом коде. База: main@0fc5293 + тестовые артефакты сертификации. AGENTS.md: commit/push НЕ выполнялись.

### Проектирование (точки изменения, риски)
Механика контура отчёта (TsAnalysisPreprocessing.tsx): снапшот — СТРОКА (JSON статусов 10 остановок), эффект отчёта с deps [checksReportSnapshot, postChecks] перезапускается только при смене строки; транзит «running» фокус-волны обнуляет снапшот (гейты) — при оседании той же картины строка восстанавливается и эффект перезапускается, дедупликацию держит ref-маркер (сброс при !ok/.catch/смене датасета). Риски дизайна тестов: (1) sleep-угадайка «осел ли фокус» — устранён счётчиком GET профилей (profileCounts, +1 по каждой остановке; missing +2 — self-fetch Обзор активной остановки), тест ждёт волну детерминированно; (2) гонка R3 может быть замаскирована, если гидратация бампит datasetVersion — проверено: datasetVersion локальный useState(0), бампится только apply мастеров; useTargetColumn(undefined) — datasetKey константен, фетч признака не гейтится датасетом (7 профильных эффектов оседают до гидратации); AppShellProvider батчит гидратацию в ОДИН коммит (reset+report стартуют вместе) — гонка воспроизводима детерминированно; (3) наивная сплайс-инверсия эффектов FM-V даёт невалидный мутант (см. ниже).

### Реализация (только тесты)
packages/ui/components/TsAnalysisPreprocessing.test.tsx: хелпер mockProgressReportPreprocessing расширен ОБРАТНО-СОВМЕСТИМО — возврат { postCalls, profileCounts } (bump в 10 профильных ветках) + опция deferSession (управляемый момент гидратации /session/current). НОВЫЙ describe «PROGR-17-CERT: закрытие находок R1–R3», 3 теста: R1 (FM-T) — POST → 500 → фокус-волна → ТА ЖЕ картина → 2-й POST (сброс маркера при !ok наблюдается БЕЗ изменения снапшота — контур «HTTP-неудача → повтор» честнее теста 3, где картина меняется); R2 (FM-U/FM-W) — фокус-волна → осели та же картина → POST по-прежнему 1 (дедупликация строковой идентичностью; регресс «10 дублей фактов на волну» ловится); R3 (FM-V) — поведенческий тест гонки «быстрые профили / медленный /session/current»: профили осели ДО гидратации (отчёта нет — activeDataset-гейт наблюдаем), releaseSession → коммит гидратации (оба эффекта в одном проходе), фокус-волна с неизменной картиной → отчёт по-прежнему 1 (порядок «сброс ДО отчёта» закреплён ПОВЕДЕНЧЕСКИ, не source-guard'ом — строгое закрытие по акту).

tests/api/test_progress_progr17.py (Пр-4): R4 (BM-H) — персистентность отчёта через НАСТОЯЩУЮ границу сериализации: RedisSessionStore на fakeredis (FakeServer/FakeStrictRedis, паттерн test_session_store.py; в memory-бэкенде save() ненаблюдаем — алиасинг ссылок, потому BM-H и выжил). monkeypatch singleton _store → upload (handle_upload сам save'ит — иначе 400) → POST отчёта → ПЕРЕзачитать store.get: 10 событий preprocessing_check_status в сериализованном документе + seeded run_id; снятие store.save оставляет документ в состоянии НА момент upload (RED на мутанте честный — json.dumps→redis→json.loads, не та ссылка).

### Верификация мутантами — scripts/progr17cert_r1r4_mutation_check.py, протокол scripts/progr17cert_r1r4_mutation_results.txt
9 мутантов (8 FE + BM-H backend), каждая проба — правка → прогон → откат (git checkout, верифицирован). Итог: ВСЕ ОЖИДАНИЯ СХОДЯТСЯ. FM-T KILLED ровно тестом R1; FM-U/FM-W KILLED тестом R2; FM-V KILLED ровно тестом R3; BM-H KILLED тестом Пр-4 (FAILED на сериализованной границе); FM-P/FM-Q/FM-R остаются KILLED (регрессии нет). БОНУС закрытия R3: FM-S («маскировка» из акта) теперь KILLED — в гонке R3 «профили осели / сессия не гидратирована» activeDataset-гейт становится наблюдаемым (фаза «отчёта нет»), маскировка pending-гейтом снята — оборонительный слой покрыт тоже. Честные примечания к протоколу: (1) оригинальная FM-V проба сертификации (конкатенация RESET+REPORT) в текущем компоненте НЕ применяется (эффекты не смежные — между ними postChecks/checksReportSnapshot), т.е. исходный вердикт «FM-V SURVIVED» был APPLY-FAIL — в этой задаче проба пересобрана честной инверсией (объявления остаются перед обоими эффектами; первый вариант сплайса ставил отчёт-эффект до объявлений — TS2448/TDZ, 0 тестов выполнено, невалидный мутант — обнаружен ручной верификацией «0 total», исправлен); (2) итоговые прогоны: 76 тестов, падает ровно R3.

### GREEN (полный прогон)
TsAnalysisPreprocessing.test.tsx — 76/76 (73 + 3 новых). Jest полный — 149 сьютов / 1799 тестов, все зелёные (1796 + 3 — сходится). tests/api полный — 1312 passed / 1 skipped / 19 failed; состав 19 совпадает со средовым базлайном 1:1 (forecasting_session ×16, modeling_workflow, neural_capacity, models_candidates) — ноль новых регрессий, 1311+1 новый Пр-4. typecheck:all — чисто; build:all — оба приложения Compiled successfully.

### Осознанные границы
R5–R7 акта не в объёме: R5 (empty-map gate — избыточная оборона) действий не требует; R6 (нумерация M-3) — документационная, учтена примечанием выше; R7 (prophet в чек-листе развёртывания) — средовая. BM-A остаётся эквивалентным мутантом (дыры нет). Sleep-буферы (30/50 мс) после детерминированных ожиданий — страховка от микрозадачных хвостов (паттерн теста 1 PROGR-17); вся синхронизация волн — по счётчикам GET, не по таймерам.

Deliverable: ZIP cisstat-progr17-certification-r1r4.zip — packages/ui/components/TsAnalysisPreprocessing.test.tsx, tests/api/test_progress_progr17.py, scripts/progr17cert_r1r4_mutation_check.py, scripts/progr17cert_r1r4_mutation_results.txt, scripts/progr17cert_fmv_manual_check.py, worklog/worklog8.md. Без commit/push (AGENTS.md).

---

## Task ID: PROGR-19 (2026-10-06) — Обобщение phase_text на 6 стадий: декларативный реестр STAGE_PHASE_TEXT_RULES + перенос upload-логики + документационная фиксация §3.2 (spec_progress_v1.1.md §3–§4, категории C и D)
База: main@9ce93c2 (HEAD; рабочее дерево до задачи чистое). Правила AGENTS.md соблюдены: commit/push НЕ выполнялись; TDD RED→GREEN; мутационные пробы; полный tests/api — средовой базлайн без новых регрессий. Постановка — сводный план задач v1.1 §6: «PROGR-19, категория C: обобщение phase_text на 6 стадий (декларативный реестр правил) + перенос upload-логики; категория D: документационная фиксация §3.2 (советы Наставника — не факты)». Рекомендованный порядок PROGR-17 → PROGR-18 → PROGR-19 соблюдён (факты всех стадий уже в контуре — правила содержательны).

### Корень (зафиксирован v1.1 §3, категория C)
PROGR-15-B сделал phase_text факт-обусловленным ТОЛЬКО для upload — ручным if/elif («узкий фикс одной находки», не рассчитан на тиражирование). Остальные пять стадий получали статический шаблон, хотя summary того же ответа next-step уже содержит посчитанные цифры по узлам той же стадии — то же «самопротиворечие одного JSON», не найденное вживую (PROGR-15-REPRO тестировал именно Загрузку). Решение v1.1: НЕ копировать ветвление пять раз, а обобщить контракт декларативным реестром.

### Проектирование (точки изменения, риски)
Реестр STAGE_PHASE_TEXT_RULES в app/core/mentor_rules.py; PhaseTextRule — frozen dataclass (condition: Callable[[stage_node_summary, events], bool], template: str); порядок правил — приоритет, первое совпавшее — текст, ни одно — статический PHASE_TEXT_TEMPLATES[stage] (fallback). Источник условий — уже посчитанный stage_node_summary (тот же объект, что summary ответа next-step: ноль нового I/O, «пересказ уже вычисленного»); события — только для фактов уровня стадии без узла (target_column_changed у upload, унаследовано из PROGR-15-B). Кортежи вместо list из формулировки v1.1 — паттерн иммутабельных реестров кодовой базы (STAGE_NODES/TRACE_ROUTES). Риски: (1) деградация условий до чтения сырых statuses — снята сводкой (фильтрует по stage: чужие факты не протекают); (2) дрейф сигнатуры условий — fail-closed валидатор на импорте; (3) подстановка непроектируемых структур ({nodes} — список) в человекочитаемый текст — гейт полей шаблона в том же валидаторе; (4) генератор событий иссяк бы после первого условия — материализация tuple() ОДИН раз в phase_text; (5) по ходу задачи: git checkout как restore мутаций стёр незакоммиченную реализацию — протокол пересобран на backup-копию.

### Реализация
app/core/mentor_rules.py: (а) импорт STAGES расширен; (б) секция PROGR-15-B заменена секцией PROGR-19 — тексты UPLOAD_STRUCTURE_DONE* сохранены ДОСЛОВНО, добавлены 6 новых шаблонов (_VALIDATION_DONE_WITH_PROBLEMS/_VALIDATION_DONE_COUNT/_PREPROCESSING_DONE_COUNT/_EDA_VIEWED_COUNT/_MODELING_BACKTEST_RAN/_MODELING_NO_BACKTEST/_FORECASTING_GENERATED/_FORECASTING_NOT_GENERATED), PhaseTextRule, хелпер _summary_node_status (мусор — «pending»: неизвестный факт не превращается в утверждение), 7 чистых условий, реестр (upload — 3 правила-перенос; validation — 2; preprocessing/eda — по 1; modeling/forecasting — по 2), валидатор _validate_stage_phase_text_rules + вызов на импорте (паттерн TRACE_ROUTES PROGR-3: ключи == STAGES в каноническом порядке; стадия без правил — ImportError — критерий приёмки v1.1 «хотя бы один факт-обусловленный вариант на каждую стадию» закреплён СТРУКТУРНО; шаблон подставляет только поля сводки {stage,total_nodes,done_count,warning_nodes}; дрейф сигнатуры ловится на импорте); (в) phase_text переписана на реестр: сводка через тот же stage_node_summary, события материализуются один раз, первое совпавшее правило — template.format(**summary), иначе статический шаблон. Вызов без аргументов — дословно прежний статический шаблон (ранний возврат, требование v1.1 §7). Upload — частный случай реестра: НЕ два параллельных механизма.

apps/api/routers/progress.py: ТОЛЬКО комментарий вызова (контракт ответа прежний: phase_text: str; статусы/события уже вычислены выше — ноль I/O).

spec_progress.md: НОВЫЙ §3.2 «Советы Наставника — не факты» (категория D, дословное обоснование PROGR-8: советы не меняют состояние исследования, идемпотентны, не детерминированы частотой открытия панели; смешение обесценило бы трассу и телеметрию; решение зафиксировано как ФИНАЛЬНОЕ — новые виды советов наследуют разведение по умолчанию) + фиксация реестра в §7.1 (контракт, источник условий, перенос upload, минимальный набор v1.1, fail-closed валидатор, отсылка «кандидаты сформированы» → PROGR-20).

Фронтенд — БЕЗ изменений (MentorPanel.tsx рендерит строку phase_text; контракт ответа не менялся).

Содержательные решения текстов (в границах примеров v1.1 §3)
Валидация — два правила: «выполнено N из 10 проверок, найдены проблемы» (приоритет) и счётчик без проблем (warning_nodes==0 — формулировка «найдены проблемы» исчезает, факты не противоречат). Предобработка — счётчик «обработано этапов N из 10» (пример v1.1). EDA — «просмотрено исследований N из 10»: семантика ПРОСМОТРА решения тимлида PROGR-18 (done/pending, warning не вводить), не pass/fail. Моделирование — «бэктест кандидатов запускался; шагов контура с фактами: N из 11» / «backtest не запускался; в трассе есть факты других шагов контура»: пример v1.1 «кандидаты сформированы» НЕ воплощён текстом — факта в трассе пока нет (candidates не трассируется, P0 категории A — PROGR-20); текст утверждает только то, что факты подтверждают. Прогнозирование — «прогноз построен; шагов контура с фактами: N из 4» / «прогноз не строился; в трассе есть факты других шагов» (пример v1.1). Тексты — факты, не советы (граница §3.2/§7); консервативные трактовки PROGR-15-B сохранены.

### TDD
RED: НОВЫЕ 30 тестов в tests/api/test_mentor_rules.py (TestStagePhaseTextRulesRegistry — структура/порядок/минимум правил/рендер/legacy-verbatim всех 6 стадий; TestPhaseTextFactsAllStages — 16 юнит-тестов фактов каждой стадии, приоритета, переноса upload, непротекания чужих фактов, мусора, неизвестной стадии; TestMentorNextStepPhaseFactsAllStages — 5 REST-тестов end-to-end + регресс-guard «пустая трасса — статический текст», зелёный ДО кода — контракт-инвариант) + МИГРАЦИЯ КОНТРАКТА: test_other_stages_ignore_statuses_and_events (PROGR-15-B) → test_other_stages_condition_on_facts_not_static. На 9ce93c2+тестах падали РОВНО новые. Находка RED-этапа: дискриминатор «построен» — не дискриминатор (подстрока статического «построение») — усилен до «прогноз построен».
GREEN: test_mentor_rules 96/96 (68 + 28), после усиления валидатора 98/98; связанный контур — 435 passed. Миграции контрактов: игнор-тест заменён; остальные 67 базовых — без правок.

Мутационные пробы — scripts/progr19_mutation_check.sh + scripts/progr19_mutation_results.txt: 8/8 KILLED
M-1 перестановка правил validation — 3 failed (приоритет); M-2 опечатка {done_cout} — ImportError; M-3 ключ "forecast" — ImportError инварианта STAGES; M-4 стадия без правил — ImportError критерия v1.1; M-5 инверсия _some_done — 8 failed; M-6 подмена сводки statuses — 22 failed; M-7 fallback "" — 14 failed; M-8 снятый гейт полей + шаблон {nodes} — ПЕРВОНАЧАЛЬНО SURVIVED (гейт был несущей защитой без тестовой страховки: мусор-подстановка доходила бы до панели) — закрыт В ХОДЕ задачи тестом валидатора test_validator_rejects_template_outside_summary_fields (+ сопутствующий test_validator_rejects_signature_drift), повторный прогон — KILLED (паттерн TDD-инверсии PROGR-17-CERT-R1R4).
НАХОДКА ПРОТОКОЛА (честная фиксация): v1 скрипта использовала git checkout как restore — реализация НЕ закоммичена (AGENTS.md), откат стёр её; пробы v1 невалидны, протокол пересобран на restore через backup-копию с контролем diff. Урок: для незакоммиченного рабочего дерева единственный корректный restore — копия, не git.

### Верификация
Полный tests/api — 1351 passed / 1 skipped / 19 failed; ВСЕ 19 совпадают со средовым базлайном 1:1 (forecasting_session ×16, modeling_workflow — catalog-only гейт, models_backtest_neural_capacity — память хоста, models_candidates — unsupported-model гейт), ноль новых регрессий. Свежий контейнер: доустановлены pywavelets/pandera/arch/statsforecast/tbats/psycopg2-binary/sqlalchemy/ruptures/prophet (средовое, код не касается). Jest/typecheck/build не запускались СОЗНАТЕЛЬНО: фронтенд не менялся (ни одного .ts/.tsx в изменениях).

### Осознанные границы
«Кандидаты сформированы» — не в тексте (факта в трассе нет до PROGR-20; пример v1.1 — индикативный); после PROGR-20 правило Моделирования расширяется тем же TDD-циклом. Расширение NEXT_STEP_RULES (§7.1 «8 правил») — вне границы (отдельная растущая работа категории B). Кортежи вместо list в сигнатуре реестра — паттерн кодовой базы (иммутабельность), отступление от буквы v1.1 зафиксировано. Повторный вызов stage_node_summary внутри phase_text — чистая функция над 10 узлами, цена нулевая. Материализация событий — защита будущих условий, тестом не закреплена (честно указано в докстринге). §3.2 фиксирует решение категорией D БЕЗ переноса MentorObservation в трассу (v1.1 §4: принять как осознанный компромисс).

---

## Task ID: PROGR-18-CERT (2026-10-06) — Независимая сертификация Task PROGR-18 (оракулы на своих данных + мутанты аудитора)
База: main@9ce93c2 (HEAD; PROGR-18 — коммит 5f034e8). Правила AGENTS.md соблюдены: commit/push НЕ выполнялись; код платформы НЕ менялся (мутационные пробы — правка → прогон → git checkout). Метод — прецеденты PROGR-1/13/17-CERT: spec_progress_v1.1.md + живой код, СВОИ мутанты, оракулы на СВОИХ данных, воспроизведение RED, сверка worklog8 с кодовой базой.

### Среда и базлайн
Среда восстановлена (PyWavelets/pandera/arch/statsforecast/tbats/psycopg2-binary/sqlalchemy/ruptures/prophet — средовое). Базлайн аудита: test_progress_progr18 9/9; TsAnalysisEDA.test.tsx 47/47; полный tests/api 1321 passed / 1 skipped / 19 failed (все 19 == средовой набор 1:1: forecasting_session ×16, modeling_workflow catalog-only, neural_capacity память хоста, models_candidates unsupported-гейт); Jest полный 149 сьютов / 1805 тестов — зелёные (1802 записи + 3 от R1R4-коммита — сходится); typecheck:all чисто.

### Оракулы на СВОИХ данных — 21/21 GREEN (scripts/progr18cert_oracles.py)
Датасет аудита: cert18_daily_traffic_n210.csv — СУТОЧНЫЙ ряд 210 точек (30 недель), day/visits/channel, недельная сезонность (период 7), инжектированный сдвиг уровня +250 с i=150, выброс 5x в i=30. Не пересекается ни с fixtures коллеги (месячный monitor 150 строк), ни с оракулами PROGR-17-CERT (недельные продажи 120 строк). Группы: A — отпечатки своих данных на реальных EDA-профилях (сезонность: confirmed_periods≥1, dominant=7, кандидат 7 confirmed; структурные сдвиги: supported_count≥1 РОВНО в i=150; stats: mean>median, skew>3); B — семантика модуля (профили осели: seasonality=done, stationarity=warning — результат ПОКАЗАН, факт просмотра возможен; реестр един: backend == shared JSON == клиентский импорт); C — контракт end-to-end (200/reported=10/run_id; слой 1 ×10; зеркало слоя 2 ×10; панель == модулю; свёртка 6/4 → attention, warning_nodes==0; 10/10 → passed; fail-closed ×5 С ДЕТАЛЯМИ включая легальный «warning» — all-or-nothing; 400 без датасета; посев run_id; last-wins; составной ключ eda/stationarity ≠ preprocessing/stationarity; персистентность через fakeredis-границу — эквивалент Пр-4); D — потребители (отчёт §5.4: 6×«просмотрен» + 4×«не просмотрен», ВСЕ 10 меток реестра, модуль «EDA» назван, без сырых id; фаза Наставника → eda; терминология status_reason на /trace nodes[]; критерий приёмки v1.1 §7 — 6/6 стадий с узловым факт-источником: PROGR-18 закрывает eda).

### Мутационный прогон — 23 СВОИХ мутанта, 17 KILLED (73.9%), 6 SURVIVED
Каналы (репозиторий / оракулы) фиксировались раздельно — убитый только оракулами = находка покрытия (прецедент R4 PROGR-17-CERT). BE 13/15 (scripts/progr18cert_mutations.py): гейты фантом/чужой статус, 400-гейт + инверсия, зеркало слоя 2, stage-подмена eda→preprocessing (двойная оборона: fail-closed реестра стадии), PAYLOAD_STATUS_EVENT_TYPES, EVENT_NODE_REASON, _STAGE_EVENT_TYPES, инверсия _EDA_STATUS_LABELS, ветка fact_line, усечение EDA_STAGE_IDS (ImportError fail-closed на импорте) — KILLED. FE 4/8 (scripts/progr18cert_mutations_fe.py): инверсия снапшота, ослабление критерия просмотра, снятие дедупликации против seed-якоря (гонка seed-перезаписи маркера ПОКРЫТА набором — сильнее гипотезы), снятие activeDataset-гейта — KILLED. Протоколы: scripts/progr18cert_mutation_results.txt, scripts/progr18cert_fe_mutation_results.txt. Выжившие: BM-A (порядок валидаций), BM-I (ЭКВИВАЛЕНТНЫЙ: len(checks)==len(known_ids) после fail-closed), FM-C/FM-D/FM-E/FM-G.

### Воспроизведение RED (сверка worklog8 1:1)
git checkout 0fc5293 — 4 backend-файла + TsAnalysisEDA.tsx: pytest test_progress_progr18 — РОВНО 9 failed (Э-1 ×2, Э-2 ×6, Э-3 ×1); Jest TsAnalysisEDA — 5 failed / 42 passed, guard «без датасета не отчитывать» зелёный ДО кода. Все проверяемые заявления записи PROGR-18 подтверждены, включая независимое подтверждение M-1..M-6 своими мутантами (BM-F≈M-2, BM-C≈M-3, FM-B≈M-6 — KILLED; M-1/M-4/M-5 — каналы репозитория).

### Находки (R1–R9, не блокируют)
R1 (средняя): «HTTP-неудача → повтор при НЕизменённом снапшоте» для EDA не покрыт (FM-D выжил) — зеркало R1 PROGR-17-CERT, закрытого для Предобработки; для EDA аналога нет. R2 (средняя): смена датасета (сброс вселенной) не покрыта вообще (FM-E выжил) — зеркало R3 PROGR-17-CERT. R3 (низкая): персистентность отчёта EDA не покрыта репозиторием (BM-H убит только C12) — Пр-4 есть только у preprocessing. R4 (низкая): деталь 422 пустой карты не покрыта (BM-D убит только C7). R5 (низкая): терминология reason узла не покрыта (BM-K убит только D3). R6 (низкая): порядок валидаций 422/400 не зафиксирован (BM-A; комбинированное условие, записи фактов нет ни при каком порядке). R7–R8 (информационные): seed-фильтр warning/error недостижим легально, но не застрахован (FM-C); credentials POST не застрахован (FM-G). R9 (информационная): BM-I эквивалентный.

### Вердикт
PASSED WITH REMARKS. Критерии приёмки PROGR-18 подтверждены независимо: 21/21 оракулов, ядро контракта убой-консистентно, RED 1:1, критерий v1.1 §7 «6/6 стадий» закрыт. Находки R1–R2 — зеркала уже закрытых для Предобработки дыр (симметрия требует переноса на молодой EDA-контур); R3–R6 — низкие; R7–R9 — информационные. Ядро не затронуто.

Deliverable: ZIP cisstat-progr18-certification.zip — docs/cert_progr18_eda_checks_2026-10-06.md, scripts/progr18cert_oracles.py, scripts/progr18cert_mutations.py, scripts/progr18cert_mutations_fe.py, scripts/progr18cert_mutation_results.txt, scripts/progr18cert_fe_mutation_results.txt, worklog/worklog8.md. Без commit/push (AGENTS.md).

---

## Task ID: PROGR-16-A-R2 (2026-10-06) — Реализация R-2 (Minor из сертификации PROGR-16-A-CERT): jest-покрытие повтора при ИДЕНТИЧНОМ снапшоте после HTTP-неудачи
База: main@3ace7d2. Изменение ТОЛЬКО тестовое: реализация не тронута (дефекта нет — была дыра jest-покрытия; мутант M-F2 ловился только статическим оракулом E3 сертификатора). Правила AGENTS.md соблюдены: commit/push НЕ выполнялись.

### Постановка
R-2 отчёта сертификации: тест разработчика «re-reports after HTTP failure» строит повтор через ИЗМЕНЁННЫЙ снапшот (formats: done → warning), поэтому мутант M-F2 (снятие if (!res.ok) сброса маркера) в jest-канале ВЫЖИВАЛ — повтор обеспечивало изменение статусов, а не сброс маркера. Рекомендация: jest-кейс, в котором повтор происходит при ИДЕНТИЧНОЙ картине статусов и ЕДИНСТВЕННОЙ причиной повтора является сброс маркера.

### Проектирование кейса (почему контур из трёх запусков)
Эффект отчёта [checksReportSnapshot, postChecks] перезапускается только при смене dep-строки; при идентичных статусах двух успешных запусков строка совпадает и эффект НЕ перезапускается (дедуп честно отсекает). Реалистичный путь «идентичного повтора»: запуск 1 — POST 500 (ветка !ok сбрасывает маркер в ""); запуск 2 — неудача самого /dataset/validate (catch → checksData null → снапшот → null); запуск 3 — успех с ТОЙ ЖЕ картиной статусов: dep снапшота меняется null → строка, эффект перезапускается, и POST происходит тогда и только тогда, когда маркер был сброшен при !ok. Между POST не было ни одного изменения статусов (ассерт тела: тело повтора равно телу первой попытки, все 10 проверок done). В мутанте маркер остаётся равным снапшоту — отчёт молча теряется, кейс падает.

### TDD
GREEN (реальный код 3ace7d2): новый кейс «re-reports the IDENTICAL snapshot after an HTTP failure (marker reset is the only cause of the retry)» — зелёный (375 ms).
RED (мутация): M-F2 применён ТОЧНО по определению scripts/progr16cert_mutations.py (.then((res) => { void res; }) вместо сброса) — кейс падает (waitFor второго POST → таймаут); файл реализации восстановлен байт-в-байт, git diff по TsAnalysisValidation.tsx пуст.
Промежуточные инварианты кейса: после неудачного запуска 2 отчёта НЕТ (снапшот null — отправлять нечего, контур не «спамит»), postCalls == 1.

### Регрессия и сборка
Сьют TsAnalysisValidation.test.tsx: 51/51 (было 50, +1 новый).
Jest полный: 149 сюит / 1793 теста — все зелёные (было 1792, +1).
typecheck:all — чисто (tsc --noEmit, оба приложения); build:all — оба «Compiled successfully» (тест не входит в сборку, проверка для полноты контура AGENTS.md).

---

## Task ID: PROGR-20 (2026-10-07) — Расширение TRACE_ROUTES: P0 (candidates, selection/evaluate) обязательно, P1/P2 — решение тимлида (spec_progress_v1.1.md §1, категория A)
База: main@7e800c6 (origin/main, PROGR-16-A-R2; рабочее дерево до задачи — только запись онбординга в worklog8.md). Правила AGENTS.md соблюдены: commit/push НЕ выполнялись; TDD RED→GREEN; мутационные пробы 6/6 KILLED; полный tests/api — средовой базлайн 1:1 без новых регрессий. Постановка: v1.1 §1/§6 — «PROGR-20: расширение STAGE_EVENT_TYPES + TRACE_ROUTES по таблице §1 (P0 обязательно, P1/P2 — по решению тимлида)»; критерий приёмки §7 «TRACE_ROUTES включает как минимум оба P0» — ЗАКРЫТ.

### Корень (зафиксирован v1.1 §1, категория A)
Allowlist TRACE_ROUTES (44 строки, PROGR-3..13) не покрывал мутирующие эндпоинты Моделирования; candidates — ключевой случай: факт системного правила (applicability-движок modeling.yaml, прямой пример контрольной формулировки «факт, который система формирует автоматически») не оставлял следа в трассе вовсе. Архитектура allowlist ОСТАЁТСЯ (осознанный выбор платформы: fail-closed, не fail-open — не всякий мутирующий вызов содержательный факт); задача — плановое расширение по таблице приоритетов.

### Решение тимлида по P1/P2 (делегировано, зафиксировано в тестах и спецификации)
P1 — ВКЛЮЧИТЬ: compare (сравнение моделей — содержательное решение аналитика) и diagnostics ×2 (факт запуска/обеспечения диагностики — пара к трассируемому backtest_run). P2 — skip-пара и job-старт/отмена ВКЛЮЧИТЬ, jobs/{id}/step — НЕТ: tuning/skip/skip-pending — осознанный аудируемый выбор «оставить defaults» (докстринг эндпоинта: «Record an auditable choice»), НЕ дублирует tuning_trial_completed (тот пишется только реальным тюнингом /tune; на job-пути не возникает никогда — потому jobs/start единственный носитель факта тюнинг-запуска в job-контуре); jobs/{id}/cancel — явное решение остановить тюнинг (класс run_paused); jobs/{id}/step — механические единицы работы: прогресс-лог, не журнал решений (§1, §4.2) — поток step-событий обесценил бы трассу. Осознанные исключения по v1.1 «Не включать»: validation-rules, type-schema (конфигурационные правки до проверки) — зафиксированы тестом test_progr20_conscious_exclusions_stay_untraced (инвариант зелёный ДО кода). Вне таблицы v1.1 (наблюдение, не зона задачи): baselines, backtest/exclude, feature-regressors, tuning/start, tuning/step — остаются вне allowlist до отдельного решения, кандидаты следующего расширения.

### Проектирование (точки изменения, риски)
Точки: apps/api/trace_events.py (реестр), apps/api/trace_hook.py (таблица), spec_progress.md (§4.1). Риски: (1) подмена факта сырым ответом — payload_keys ТОЛЬКО форма ответа (статистика пула/идентификаторы/вердикт ансамбля), тяжёлые массивы (candidates/catalog/ranking/diagnostics) отсечены, тест test_progr20_payload_dotted_keys_flatten фиксирует точный состав; (2) подмена узла известным чужим (import-гейт is_known_node не различает узлы одной стадии) — явные ассерты (stage, node_id, event_type) на каждую строку; (3) сужение контрактов — инвариант «ровно 7 новых типов, существующие не сужены» в тесте реестра + миграция контракт-теста sets 1:1 с комментарием; (4) путь P0 из формулировки v1.1 «POST /v1/models/candidates» — stateless-зеркало (API-key auth, без cookie-сессии атрибутировать событие некуда); сессионный носитель факта — /v1/session/modeling/candidates (именно он в перечне сертификации PROGR-3-CERT под группой «Моделирование»); расхождение зафиксировано в spec_progress.md §4.1; (5) node_id с параметром пути {job_id} — механизм шаблонов resolve_trace_route уже поддержан (паспортные точки были развёрнуты в литералы по другой причине), тест resolve + e2e покрывают.

### Реализация
trace_events.py: +7 типов в _STAGE_EVENT_TYPES["modeling"] (candidates_generated, selection_evaluated, models_compared, diagnostics_run, tuning_skipped, tuning_job_started, tuning_job_cancelled) с обоснованием каждого. trace_hook.py: +9 строк (P0: candidates→candidate_generation, selection/evaluate→selection; P1: compare→comparison, diagnostics и diagnostics/ensure→diagnostics; P2: tuning/skip и skip-pending→tuning, jobs/start→tuning, jobs/{job_id}/cancel→tuning); dotted-ключи (паттерн metrics.mape PROGR-8): statistics.runnable_candidates/catalog_only_candidates/blocked_candidates → плоские ключи, recommended_single.model_id → model_id, ensemble.status → status, progress.total_steps → total_steps, cancellation.reason → reason; один тип на два эндпоинта для diagnostics (прямой запуск vs ensure: payload различает calculated/reused) и для skip-пары. fail-closed валидатор таблицы (дубликаты/невалидные пары/неизвестные узлы/throttled-гейт/forecasting-гейт) — без изменений, расширенная таблица проходит на импорте. Фронтенд — БЕЗ изменений (ProgressTraceLog рендерит event_type как есть; статусы узлов Моделирования — из session.modeling_pipeline, новые типы в EVENT_NODE_STATUS/PAYLOAD_STATUS_EVENT_TYPES не вводились, свод панели не меняется; только честный last_touched_at узла). spec_progress.md: §4.1 modeling-строка + полный абзац PROGR-20 (решения P1/P2, исключения, замечание о путях, потребители).

### TDD
RED: 9 новых тестов в tests/api/test_progress_trace_hook.py (секция 9-10: таблица P0/P1/P2 с payload_keys/preview/throttled, счётчик 53, исключения-инвариант, реестр, payload dotted, e2e candidates; e2e diagnostics+ensure+compare+selection/evaluate; e2e tuning/skip; e2e jobs start/cancel) — на 7e800c6+тестах падали РОВНО 8 новых, инвариант исключений зелёный ДО кода (контракт-инвариант, паттерн PROGR-19); причины падений проверены (последним событием остаётся passport_captured/backtest_run — события не пишутся). GREEN: 73/73 (trace_hook 49 + trace_events 24). МИГРАЦИИ КОНТРАКТОВ: test_route_table_covers_documented_endpoints (44→53 с комментарием арифметики), test_trace_events.py::test_registry_per_spec_table (modeling set +7). Остальные тесты обоих файлов — без правок.

Мутационные пробы — scripts/progr20_mutation_check.sh + scripts/progr20_mutation_results.txt: 6/6 KILLED. M-1 rename пути candidates — 3 failed; M-2 подмена узла candidate_generation→selection (оба известны графу — ловит ТОЛЬКО явный ассерт) — 2 failed; M-3 опечатка event_type — ImportError валидатора; M-4 снятие dotted-ключа payload — 3 failed; M-5 снятие типа из реестра — ImportError; M-6 добавление запрещённого step-маршрута — 3 failed (исключения + счётчик). Протокол — backup-копия с побайтовым cmp-контролем после restore (урок PROGR-19: git checkout для незакоммиченного дерева запрещён); финальный контроль — 73 passed.

### Верификация
Полный tests/api: 1360 passed / 1 skipped / 19 failed — ВСЕ 19 == средовой базлайн 1:1 (forecasting_session ×16, modeling_workflow catalog-only гейт, models_backtest_neural_capacity память хоста, models_candidates unsupported-model гейт); +9 passed к базлайну 1351 = ровно новые тесты. Свежая среда: установлены pywavelets/pandera/arch/statsforecast/tbats/psycopg2-binary/sqlalchemy/ruptures/prophet/psycopg (средовое, код не касается). Jest/typecheck/build не запускались СОЗНАТЕЛЬНО: фронтенд не менялся (ни одного .ts/.tsx в изменениях — паттерн PROGR-19).

### Осознанные границы
§5.4-отчёт рендерит новые типы честной fallback-строкой «Событие трассы: {event_type}» (специализация строк — отдельная работа, в границу PROGR-20 «расширение таблицы» не входит). idempotent_replay-ответы jobs/start и cancel пишутся как события (успешный вызов — факт вызова; repeated-вызовы коррекций ведут себя так же). tuning/skip-pending со статусом "unchanged" (нечего пропускать) пишет событие с payload status="unchanged" — вызов состоялся, факт честный. skip-pending e2e не прогонялся (таблица+payload-тесты покрывают контракт; тяжёлый 3-модельный контур уже покрыт тестами test_modeling_workflow). События не двигают фазу Наставника/штамп стадии (не в EVENT_NODE_STATUS — согласовано с гейтом derive_last_decision_stage PROGR-13-C). baselines/backtest/exclude/feature-regressors/tuning/start/tuning/step — вне таблицы v1.1, сознательно не включены (зафиксировано).

---

## Task ID: PROGR-21 (2026-10-07) — mode_changed/target_column_changed как источник reason (не status) в derive_pipeline_node_states (spec_progress_v1.1.md §5, категория E)
База: main@18e4871 (origin/main, PROGR-20; синхронизация по прямому указанию тимлида: код-файлы рабочего дерева PROGR-20 сверены с 18e4871 байт-в-байт до merge, untracked-скрипты мутационных проб совпали с закоммиченными (results.txt — только хвостовой перевод строки), локальная запись онбординга worklog8 сохранена бэкапом вне репо и в дерево не возвращалась — версия main канонична). Правила AGENTS.md соблюдены: commit/push НЕ выполнялись; TDD RED→GREEN; мутационные пробы 6/6 KILLED; полный tests/api — средовой базлайн 1:1 без новых регрессий. Постановка: v1.1 §5/§6 — «PROGR-21: добавить mode_changed и target_column_changed как источник reason (не status) в derive_pipeline_node_states — узел не меняет цвет статуса, но получает актуальный status_reason («Режим: включена вручную», «Целевой признак: Price») — минимальное, не ломающее текущий контракт расширение (поле reason уже существует в PipelineNodeState, PROGR-11)».

### Корень (зафиксирован v1.1 §5, категория E; находка N-2/N-3 PROGR-10)
Stage-level факты (mode_changed, target_column_changed, checkpoint_saved, run_*) не влияли на свод узла/стадии — видны только в плоском логе «Развернуть трассу». Решение v1.1 — трёхчастное: run_* принять (факты уровня запуска, §2), а mode_changed/target_column_changed закрыть — это узловые ПО СМЫСЛУ решения аналитика, не подсвечивающиеся на карточке. До задачи: details-цикл derive_pipeline_node_states пропускал все события без node_id целиком (гейт N-2) — reason с них не выводился.

### Проектирование (точки изменения, ключевые развилки)
Точка изменения ОДНА: app/core/node_status.py (единый движок — вторая реализация запрещена; потребители derive_pipeline_node_states: только GET /v1/progress/trace, routers/progress.py:329; Наставник и admin-аналитика потребляют derive_node_statuses — статусы, не зацеплены). Развилка 1 — НЕ расширять EVENT_NODE_REASON: карта reason ровно для узловых типов статуса (ключи == EVENT_NODE_STATUS | PAYLOAD_STATUS_EVENT_TYPES, тест инварианта страхует: reason и статус всегда про одно событие узла); stage-level событие статуса не даёт (гейты движка прежние) — нужен ОТДЕЛЬНЫЙ payload-атрибутированный источник reason. Развилка 2 — mode_changed несёт ПОЛНУЮ карту эффективных режимов (payload из тела ОТВЕТА PUT, whitelist payload_keys=("modes",), _effective_*_check_modes возвращает все CHECK_IDS с auto-дефолтами): атрибуция всем узлам карты забрызгала бы reason-канал на каждый PUT (принцип PROGR-20 P2: шум обесценивает канал) — reason получают ТОЛЬКО узлы с активным override (enabled/disabled), auto — сигнал СНЯТИЯ. Развилка 3 — снятие: возврат в auto / сброс цели делают прежний «Режим: …»/«Целевой признак: …» ложью (mode-поле карточки живёт в состоянии сессии); снятие через внутренний тег происхождения (_reason_tag в книжке деталей, в выход §3 не утекает): снимается ТОЛЬКО reason своего класса; reason последнего узлового решения (correction_applied и др.) неснимаем stage-level событием никогда — тег сбрасывается любым решением; last-wins хронологии прежний. Развилка 4 — носитель target-reason (см. решение реализации ниже). Риски: (1) подмена статуса — карты EVENT_NODE_STATUS/PAYLOAD_STATUS_EVENT_TYPES не расширялись, инвариантные тесты (map-coverage, N-2 details, status==canonical engine, фазы B1/C) остались зелёными; (2) утечка внутреннего тега в 7-польный контракт §3 — тест «ровно 7 полей» на трассе с reason; (3) фантомная атрибуция по мусорному payload (modes не словарь/чужие ключи/target не строка) — fail-safe пропуски, тесты на каждый класс мусора.

### Решение реализации — на утверждении тимлида (носитель target-reason)
Постановка v1.1 («выбор целевого признака конкретно для Загрузки») читается как атрибуция стадии Загрузки, но: (а) событие мульти-странично — авто-POST хука useTargetColumn возможен с любой вкладки (канон B1/C node_status.py: «сам хук — часть вкладки "Загрузка"» — лишь исходное размещение; компоненты Validation/EDA/Preprocessing используют тот же хук), атрибуция карточке Загрузки была бы ЛОЖЬЮ при срабатывании с другой вкладки; (б) узла «целевой признак» в реестре остановок Загрузки нет (upload_stops.json: overview/chart/distribution/structure/quality) — атрибуция любой из них была бы выдумкой. Носитель — TARGET_REASON_STAGE_NODE = ("validation", "sufficiency"): единственная проверка Валидации, чья семантика определена целью («достаточность по смыслу относится к активному прогнозируемому ряду», routers/session.py::sufficiency_target; КБ: «достаточность — достаточно ли наблюдений для моделирования» исследуемого ряда), текст «Целевой признак: {column}» — пример v1.1 дословно; атрибуция tab-независима и честна. Зафиксировано комментарием в коде, тестом и spec_progress.md §4.1 — при несогласии тимлида правка сводится к одной константе.

### Реализация
node_status.py: STAGE_LEVEL_REASON_EVENT_TYPES (frozenset mode_changed/target_column_changed); NODE_MODE_REASON_LABELS (enabled → «включена вручную», disabled → «отключена»; auto — НЕ текст, а снятие); TARGET_REASON_STAGE_NODE; _reason_tag-книжка (_empty_detail: 3 публичных поля + внутренний тег); чистая функция _stage_level_reason_updates(stage, data) → (reasons {node_id: текст}, resets {node_id}) — payload-атрибуция с гейтами is_known_node/NODE_MODE_VALUES-класса; derive_pipeline_node_states: ветка ДО гейта N-2 (node_id is None И тип в реестре reason-источников → set/clear по тегу → continue), decision-ветка сбрасывает тег (decision-reason неснимаем); выход — ровно 7 полей (тег не утекает). Докстринги модуля/функции + NodeStateOut (routers/progress.py) дополнены PROGR-21. Фронтенд — БЕЗ изменений (ProgressStageFlow рендерит status_reason как есть — вторая строка карточки; ни одного .ts/.tsx в изменениях — паттерн PROGR-19). spec_progress.md: §4.1-строка validation/preprocessing + полный абзац PROGR-21 (механизм, решения, развилка носителя — на утверждении).

### TDD
RED: 14 unit-тестов TestProgr21StageLevelReasons (test_node_status_engine.py: reason без статуса/ts/бейджа; тексты примеров v1.1 дословно; атрибуция своей стадии; фантомы/мусорные значения/не-словарь modes — пропуски; снятие auto с сохранением decision-reason; last-wins в обе стороны; target: выбор/sброс/мусор/чужая стадия; 7 полей; инвариант «не status» + фазы B1/C на stage-only трассе) + 3 e2e (test_progress_trace_hook.py секция 11: PUT check-modes → /trace reason «Режим: отключена» на formats при незатронутых data_types/ranges; POST target-column → «Целевой признак: Price» на sufficiency; auto-возврат снимает reason в живой панели) — на 18e4871+тестах падали РОВНО 9 (7 unit + 2 e2e; 5 contract-инвариантов зелёные ДО кода — absence/invariant-ассерты, паттерн PROGR-19/20), причины падений проверены (reason None — атрибуции не существовало). GREEN: 113/113 (engine 60 + hook 52... суммарно оба файла; см. финальный контроль мутаций — 113 passed). МИГРАЦИЙ КОНТРАКТОВ НЕ ТРЕБУЕТСЯ: прежние тесты (map-coverage reason, N-2 details без status_reason-ассерта, 7 полей, status==canonical) зелёны без правок — расширение аддитивно.

Мутационные пробы — scripts/progr21_mutation_check.sh + scripts/progr21_mutation_results.txt: 6/6 KILLED. M-1 искажение текста «включена вручную» — 4 failed (точные тексты v1.1); M-2 снятие auto отключено — 2 failed (unit снятия + e2e панели); M-3 auto как reason (шум карты) — 6 failed (авто-узлы без reason); M-4 носитель target-reason → formats (оба известны графу — ловит ТОЛЬКО явный ассерт) — 3 failed; M-5 mode_changed в EVENT_NODE_STATUS («не status» нарушен) — 4 failed (инвариант map-coverage); M-6 утечка тега в выход — 2 failed (7 полей). Протокол — backup-копия node_status.py с побайтовым cmp-контролем после restore (урок PROGR-19/20); финальный контроль — 113 passed.

### Верификация
Полный tests/api: 1377 passed / 1 skipped / 19 failed — ВСЕ 19 == средовой базлайн 1:1 (forecasting_session ×16, modeling_workflow catalog-only гейт, models_backtest_neural_capacity память хоста, models_candidates unsupported-model гейт); +17 passed к базлайну 1360 = ровно новые тесты (14 unit + 3 e2e). Средовой шум зафиксирован: DATABASE_URL=file:... в окружении песочницы логирует ProgrammingError psycopg в best-effort пути слоя 2 — на выбранные тесты не влияет (зеркало слоя 2 деградирует по контракту). Jest/typecheck/build не запускались СОЗНАТЕЛЬНО: фронтенд не менялся (ни одного .ts/.tsx в изменениях).

### Осознанные границы
Reason stage-level источника НЕ двигает last_touched_at/summary_count (толкование «подсветка причины», не «касание узла»; прежний тест N-2 сохранён дословно). Снятие mode-reason охватывает только auto из той же карты события: stale-reason при УДАЛЕНИИ узла из реестра (переименование) не снимается — LEGACY_NODE_IDS-нормализация на границе чтения покрывает канонические переименования, новый класс не вводился. «Режим: авто» как текст НЕ вводится (auto — снятие; текст дублировал бы mode-поле карточки и зашумлял канал). Прогон skip-pending-аналогов не требуется: задача не добавляет эндпоинтов/типов — только потребление существующих событий движком. Пустой target_column (сброс) текущей таблицей хука не порождается (ответ POST всегда непустая строка) — ветка снятия защитная, канон PROGR-15-B зафиксирован тестом на случай корпуса слоя 2. События не двигают фазу Наставника/штамп стадии/свод стадии — гейты resolve_event_status не расширены (тест инварианта).

Deliverable: ZIP cisstat-progr21-stage-level-reasons.zip — app/core/node_status.py, apps/api/routers/progress.py, tests/api/test_node_status_engine.py, tests/api/test_progress_trace_hook.py, spec_progress.md, scripts/progr21_mutation_check.sh, scripts/progr21_mutation_results.txt, worklog/worklog8.md. Без commit/push (AGENTS.md).

---

## Task ID: PROGR-20-CERT (2026-10-07) — Независимая сертификация Task PROGR-20 (оракулы на своих данных + мутанты аудитора)
База: main@ed26476 (HEAD; PROGR-20 — коммит 18e4871, поверх — фикс R3_R7 ed26476). Правила AGENTS.md соблюдены: commit/push НЕ выполнялись; код платформы НЕ менялся (мутационные пробы — правка → прогон → откат по backup-копии с байт-контролем cmp; урок PROGR-19 соблюдён). Метод — прецеденты PROGR-1/13/17/18-CERT: spec_progress_v1.1.md + живой код, СВОИ мутанты AM-1..AM-8 (НЕ копия M-1..M-6 реализатора), оракулы на СВОИХ данных, воспроизведение RED, сверка worklog8 с кодовой базой. Акт: docs/cert_progr20_trace_routes_2026-10-07.md.

### Верификация приёмки (своё окружение)
Целевые файлы: test_progress_trace_hook + test_trace_events — 73/73 GREEN. RED воспроизведён 1:1: реализация 7e800c6 при текущих тестах — РОВНО 8 failed / 1 passed (инвариант исключений test_progr20_conscious_exclusions_stay_untraced зелёный ДО кода, паттерн PROGR-19); восстановление — backup-копия + cmp, контроль 73/73. Полный tests/api: 1363 passed / 1 skipped / 19 failed — все 19 == средовой базлайн 1:1 (forecasting_session ×16, modeling_workflow catalog-only, neural_capacity память, models_candidates unsupported-гейт); 1363 = 1351 (запись PROGR-20) + 12 от тестовых коммитов 0fc5293/ed26476. Jest/typecheck/build не запускались СОЗНАТЕЛЬНО: коммит 18e4871 без единого .ts/.tsx (подтверждено составом коммита, паттерн PROGR-19). Критерий приёмки v1.1 §7 «минимум оба P0» — подтверждён структурно (B5) и e2e на своих данных (D1).

### Оракулы аудитора (свои данные) — 16/16 GREEN (scripts/progr20cert_oracles.py)
Датасет: cert20_weekly_demand_n156.csv — НЕДЕЛЬНЫЙ спрос, 156 точек (2022-01-02..2024-12-29), тренд 0.8/нед + треугольная годовая сезонность (ампл. 30) + детерминированный псевдошум; не пересекается с fixtures коллеги (месячный monitor-150), оракулами PROGR-17-CERT (недельные продажи-120), PROGR-18-CERT (суточный трафик-210) и месячным MS-96 реализатора. Группы: A — отпечатки applicability-движка на своих данных (spec v1.3.1: каталог 24 == len(catalog); пул 10 RECOMMENDED, catalog_only 5, blocked 4, сумма 19 < 24 — семантика честная; naive/ets/theta в пуле; payload события == статистике СВОЕГО ответа); B — механика allowlist на своих пробах (9 строк → точная тройка на живых path-пробах с uuid; метод-гейт GET/PUT/DELETE; шаблон {job_id}: uuid-матч, пустой/лишний сегмент — нет; 8 негативных проб исключений/вне-таблицы; §7 структурно + счётчик 53); C — форма payload на своих телах (dotted — под последним сегментом; тяжёлые массивы отсечены; отсутствующий промежуточный уровень — честное опущение; total_steps от своего max_trials); D — e2e (D1 полный контур: candidates ×2 → ровно 2 события — моделирование НЕ троттлится; diagnostics прямые ×2 с payload backtest_run_id == своему ответу; ensure-union == своему ответу; compare/evaluate — ID и вердикты своих ответов; skip-pending «unchanged» после закрытия scope; jobs start/cancel — total_steps==3 от своего max_trials=3, своя причина отмены; D1b — ДОБАВЛЕНИЕ аудитора: e2e skip-pending реализатора не было — «skipped» со списком СВОИХ pending-tuning → повтор «unchanged», единственная причина второго события — пустой pending; D2 зеркало слоя 2 research_runs; D3 422/405/409 — ни одного события; D4 панель: last_touched_at обновлён, status_reason None, статус не покрашен — свод не меняется; D5 регресс-страж backtest_run+metrics.mape «существующие не сужены»). Честное примечание протокола: первые итерации D1 падали на ОРАКУЛЕ — compare/evaluate требуют полного закрытия runnable-scope (честные 409-детейлы pending_backtests+pending_tuning), scope в /state — устаревший артефакт; контур перестроен на управление от 409-детейлов (наблюдение R4 акта).

### Мутационный прогон аудитора — 8 СВОИХ мутантов: 7 KILLED / 1 SURVIVED (87.5%), все 8 ожиданий сошлись
Протокол scripts/progr20cert_mutations.py + журнал scripts/progr20cert_mutation_results.txt; каналы раздельно (T — репозиторий 73; O — оракулы 16); каждый мутант — ровно одна замена (скрипт падает громко при 0/≥2 вхождениях); откат backup + cmp; финальный контроль — оба канала зелёные. AM-1 метод-гейт POST→GET на P0-строке (KILLED T+O: метод не специфицирован v1.1 — таблица единственный носитель); AM-2 flatten по ПЕРВОМУ сегменту rsplit→split (KILLED T+O: семантика хранения dotted, паттерн metrics.mape); AM-3 подмена на ВАЛИДНЫЙ тип models_compared→backtest_run — гейт проходит БЕЗ ImportError (KILLED T+O: различают только точные ассерты таблицы — сильнее гипотезы); AM-4 дегенерация шаблона /jobs/{job_id}/cancel→/jobs/cancel (KILLED T+O: механизм {param} на живом параметризованном пути); AM-5 superset-дрейф реестра +phantom_modeling_type — локальный тест ассертит >= при комментарии «ровно 7» (KILLED только T-контракт-тестом test_registry_per_spec_table — вторая линия обороны; канал O не ловит); AM-6 ослабление гейта статуса >=400→>=500 (KILLED T+O: единственный gate middleware застрахован с обеих сторон); AM-7 потеря атрибуции run_id='' (KILLED T+O: §5-привязка факта к исследованию); AM-8 снятие store.save(session) в _record — ОЖИДАЕМО SURVIVED в обоих каналах: MemorySessionStore.get возвращает объект по ссылке (алиасинг), граница сериализации Redis на hook-пути тестом не застрахована — класс BM-H/R4 PROGR-17-CERT, общий для ВСЕХ hook-маршрутов с PROGR-3, PROGR-20 не затронут (для отчётных контуров закрыто Пр-4 PROGR-17-CERT-R1R4).

### Находки (R1–R5, не блокируют; акт §6)
R1 (низкая, покрытие): персистентность слоя 1 hook-пути через настоящую границу сериализации не покрыта (AM-8) — рекомендация fakeredis-тест в духе Пр-4, общая задача контура PROGR-3..20. R2 (информационная): локальный реестр-тест — superset-ассерт при комментарии «ровно 7»; дрейф вверх ловит только контракт-тест (двойная оборона сработала; можно усилить до ==). R3 (информационная, закрыта аудитом): e2e skip-pending — D1b на своих данных. R4 (информационная, представительность e2e): у реализатора compare/evaluate шли в сессии БЕЗ candidates — гейт закрытия scope проходил тривиально; на пуле 10 моделей полный контур подтверждён оракулами. R5 (информационная, задокументировано реализатором и проверено независимо): путевое расхождение v1.1 «POST /v1/models/candidates» → сессионный носитель /v1/session/modeling/candidates; stateless-зеркало сессии не имеет — атрибутировать факт некуда.

### Вердикт
**PASSED WITH REMARKS.** Все заявления worklog8.md задачи PROGR-20 подтверждены 1:1; критерий приёмки v1.1 §7 закрыт; ядро контракта (таблица → middleware → слой 1 → зеркало слоя 2 → панель/отчёт) убой-консистентно (7/8 своих мутантов убиты, выживший — известный класс персистентной границы вне зоны задачи). Находки R1–R5 не блокируют; R1 — кандидат в общую тестовую задачу контура трассы.

Deliverable: ZIP cisstat-progr20-certification.zip — docs/cert_progr20_trace_routes_2026-10-07.md, scripts/progr20cert_oracles.py, scripts/progr20cert_mutations.py, scripts/progr20cert_mutation_results.txt, worklog/worklog8.md. Без commit/push (AGENTS.md).

---

## Task ID: PROGR-21-CERT (2026-10-07) — Независимая сертификация Task PROGR-21 (оракулы на своих данных + мутанты аудитора)
База: main@09674e1 (HEAD; сам коммит PROGR-21). Правила AGENTS.md соблюдены: commit/push НЕ выполнялись. Постановка: честная сертификация по прецедентам PROGR-1/13/17/18-CERT — изучение spec_progress_v1.1.md §5 и живого кода, НЕЗАВИСИМЫЕ мутационные пробы на СВОИХ мутантах, оракулы на СВОИХ данных, RED-воспроизведение, сверка заявлений worklog8 с кодом.

### Сверка реализации (все точки на месте)
STAGE_LEVEL_REASON_EVENT_TYPES (frozenset mode_changed/target_column_changed) — ОТДЕЛЬНЫЙ механизм, не EVENT_NODE_REASON (карта reason == ровно узловые типы статуса); NODE_MODE_REASON_LABELS enabled/disabled (auto — снятие, не текст); TARGET_REASON_STAGE_NODE ("validation","sufficiency") — решение реализации на утверждении тимлида (обоснованно: событие мульти-странично, узла «целевой признак» в upload_stops нет); _stage_level_reason_updates — чистая, fail-safe; ветка движка ДО гейта N-2, тег _reason_tag не утекает (выход ровно 7 полей); единственный потребитель — GET /v1/progress/trace (mentor_rules/admin_analytics потребляют derive_node_statuses — не зацеплены); фронтенд без изменений (0 .ts/.tsx в коммите; ProgressStageFlow уже рендерит status_reason второй строкой).

### Верификация аудитора
GREEN 113/113 (engine+hook). RED-воспроизведение: код откачен к 18e4871 (backup + побайтовый cmp, git-объекты напрямую) — РОВНО 9 failed (7 unit + 2 e2e), состав поимённо совпадает с записью PROGR-21; инварианты зелёные ДО кода. Полный tests/api: 1380 passed / 1 skipped / 19 failed — все 19 == средовой базлайн 1:1 (forecasting_session ×16, modeling_workflow catalog-only, neural_capacity, models_candidates), skip — Postgres-интеграция; счётчик passed +3 к записи worklog (1380 vs 1377) при идентичном failed/skip и коде 1:1 — свежесть зависимостей сред (находка R2, действий не требует). Jest/typecheck/build сознательно не запускались (фронтенд не менялся).

### Оракулы на СВОИХ данных — scripts/progr21cert_oracles.py: 23/23 PASS
Датасет аудита: ПОЧАСОВОЙ ряд энергопотребления 168 точек (7 суток, hour/Load/Reserve: суточная сезонность с двойным пиком, пониженные выходные, инжектированный вечерний пик воскресенья; цель Load → Reserve) — не пересекается ни с fixtures коллеги (Price-ряд 80 точек), ни с оракулами PROGR-17/18-CERT. Группа A (10, движок): смешанная карта 4/10 узлов Валидации; атрибуция своей стадии preprocessing; НЕЗАВИСИМОСТЬ ТЕГОВ mode/target (у коллеги отсутствует); last-wins decision/mode обе стороны; смена цели Load→Reserve; ISO-ts не протекает в last_touched_at; инвариант «не статус» + фазы B1/C; fail-safe 7 классов мусора; пустая карта {} — ни reason, ни снятия; чистота функции. Группа B (8, живой API на своих данных): тексты v1.1 дословно; кросс-стадийная изоляция validation/preprocessing; выбор цели + смена Reserve; возврат auto снимает (нетронутый uniqueness жив); хронология disabled→enabled→auto пошагово; /trace — 26 узлов, ровно 7 полей; неудачный POST target-column (422) НЕ сеет событие; полный контур аналитика. Группа C (5, инварианты реестров): EVENT_NODE_REASON == EVENT_NODE_STATUS | PAYLOAD_STATUS_EVENT_TYPES (PROGR-21-типы НЕ входят); пересечение с статусными картами пусто («не status» на уровне реестров); носитель target-reason; метки только enabled/disabled; пример v1.1 дословно. В RED-фазе оракулов 3 ожидания аудитора были СКОРРЕКТИРОВАНЫ (не платформы): upload/overview законно несёт reason/статус done от upload_completed; пробельная цель — следование канону PROGR-15-B (находка R1, зафиксирована регресс-якорем).

### Мутационный прогон аудитора — scripts/progr21cert_mutations.py: 10/10 KILLED (100%), каждый — ОБОИМИ каналами (repo + oracle)
СВОИ мутанты (не копия M-1..M-6): CM-1 target-тип выброшен из реестра; CM-2 метки swapped; CM-3 auto стал текстом «Режим: авто»; CM-4 decision не сбрасывает тег (неснимаемость нарушена); CM-5 reset без проверки тега; CM-6 пустая цель стала фактом; CM-7 двойное развёртывание payload; CM-8 сырое значение вместо метки; CM-9 ts протекает в last_touched_at; CM-10 mode-карта красит чужую стадию. Классы M-1..M-6 коллеги независимо подтверждены дублями (M-1≈CM-2/8, M-2≈CM-4/5, M-3≈CM-3, M-4≈CM-10, M-5≈оракулы C1/C2, M-6≈B6). Протокол: scripts/progr21cert_mutation_results.txt; restore — backup с побайтовым cmp (урок PROGR-19).

### Находки (не блокируют)
R1 (информационная): пробельная строка цели "   " каноном PROGR-15-B трактуется как выбор — «Целевой признак:    »; через живой API недостижима (404 несуществующей колонки), риск только для ручного слоя 2; зафиксирована регресс-якорем оракула, изменение на strip — решение тимлида. R2 (информационная): расхождение счётчика passed между средами (+3) — рекомендуется фиксировать pip freeze рядом с протоколом. R3 (низкая, вне границы): детальный whitelist payload mode_changed не фиксирован отдельным тестом состава (аналог PROGR-20 dotted-теста) — заметил бы только e2e-ассерт конкретной карты. R4 (решение на утверждении): носитель target-reason — ожидает формального подтверждения тимлида.

### Вердикт: PASSED
Критерии приёмки v1.1 §5 выполнены и подтверждены независимо (reason-не-статус на уровнях реестров/движка/живой панели; тексты дословно; снятие/неснимаемость/last-wins; 7 полей; fail-safe); все проверяемые заявления worklog8 воспроизведены 1:1; дыр покрытия классов задачи не обнаружено. Акт: docs/cert_progr21_stage_level_reasons_2026-10-07.md. Deliverable: ZIP cisstat-progr21-certification.zip (акт, оракулы, мутации, протокол, worklog8) — выложен в download. Без commit/push (AGENTS.md).

---

## Task ID: PROGR-22-REPRO (2026-10-07) — Воспроизведение пользовательского дефекта: остановка «Выбросы» жёлтая в степпере при зелёном узле в «Прогрессе» (исследование, БЕЗ fix)

База: main@b117f39 (HEAD, PROGR-21-CERT; синхронизация по прямому указанию тимлида, локальное дерево == b117f39 байт-в-байт). Правила AGENTS.md соблюдены: commit/push НЕ выполнялись; правок КОДА НЕТ — только read-only измерения (TestClient-паттерн tests/api, штатные эндпоинты) и чтение кода. Постановка тимлида: демо-датасет forecast_monitor_synthetic_n150.csv (FC-MON-2: 3 пропуска t={45,87,122} + 4 выброса t={25,70,105,130}, генератор scripts/dataset_forecast_monitor.py); аналитик проходит Загрузку и Валидацию, в Предобработке чинит Пропуски и Выбросы, на остановке «Стационарность ряда» добавляет колонки по рекомендации стратегии, выбросы появляются повторно, повторно чинит (мастер пишет «Изменения применены, профиль пересчитан») — при этом остановка «Выбросы» остаётся жёлтой, а узел «outliers» в «Прогрессе» зелёный. Воспроизвести; хронология; факты vs гипотезы; минимальные read-only проверки; НЕ предлагать fix до подтверждения причины.

### Хронология наблюдаемого поведения (измерено, дефолтный поток: cap + iqr 1.5)

| Шаг | Действие | КАРТОЧКА «Выбросы» (живой IQR-профиль, method=iqr фиксирован) | TRACE узел outliers (события, last-wins) |
|---|---|---|---|
| 1 | Upload n150 + подтверждение date | warning, 4 выброса в value @ [25,70,105,130] | pending |
| 2 | Пропуски → interpolate (apply) | warning, 4 | pending |
| 3 | Выбросы №1 (мастер cap/iqr 1.5): found=4 changed=4 still=0 | done, 0 | done «Коррекция применена» count=4 |
| 4 | Стационарность: рекомендация linear_detrend → +колонка value_detrended (rows 150→150) | warning, 4 в value_detrended @ [25,70,105,130] (bounds [-51.83, 50.61]) — «опять появляются выбросы» | ПО-ПРЕЖНЕМУ done — события НЕТ |
| 5а | Выбросы №2, strategy=cap: found=4 changed=4 still=0 | done, 0 | done count=4 — расхождения в КОНЦЕ нет |
| 5б | Выбросы №2, strategy=flag («Добавить флаг выброса»): found=4 changed=0 still=4 + колонка value_detrended_outlier_flag | warning, 8 (value_detrended 4 + value_detrended_outlier_flag 4, bounds флаг-колонки [0.0, 0.0]) | done count=4 — РАСХОЖДЕНИЕ ВОСПРОИЗВЕДЕНО == наблюдение тимлида |

### Факты (код, все сверены на b117f39)

Ф1. Карточка — ЖИВОЙ профиль: GET /dataset/outlier-profile?method=iqr (метод ЖЁСТКО iqr, TsAnalysisPreprocessing.tsx:289); статус из _preprocessing_outliers_status: warning ⇔ total_outliers > 0, done ⇔ 0 (routers/session.py:357–371). Перезапрос после apply привязан к datasetVersion (deps [outliersRefreshKey, datasetVersion], :310), handleApplied бампит его (:211–214) — фронт после apply ПЕРЕзапрашивает бэкенд.
Ф2. «Прогресс» — журнал событий, last-wins: correction_applied → done БЕЗУСЛОВНО (app/core/node_status.py:67), опроса profile-эндпоинтов НЕТ по проектному решению (комментарий в node_status.py); событие пишет хук на POST apply безотносительно результата (trace_hook.py:224–228), payload — факты ответа (total_outliers = НАЙДЕНО в этой фиксации, не «осталось»). GET-пересчёты профиля выбросов НЕ трассируются (в TRACE_ROUTES GET только у EDA — profile_viewed).
Ф3. Мастер: setSuccess(«Изменения применены, профиль пересчитан») БЕЗУСЛОВНО при HTTP 200 (PreprocessingOutliersPipeline.tsx:190) — в flag-потоке баннер успеха показан при changed=0/still=4; ответ apply при этом пишется и в preview-бокс («Осталось выбросов: 4»).
Ф4. Стратегия flag: значения НЕ трогаются by design — still_outliers = outlier_count, changed_count = 0 (apps/api/outliers_correction.py:200–203); добавляемая 0/1-колонка числовая → входит в IQR-профиль, у почти-нулевой колонки IQR=0 → забор [0,0] → КАЖДАЯ единица = «выброс» (измерено: +4 «выброса» от самой флаг-колонки).
Ф5. Механизм «опять появляются выбросы»: cap ставит значения РОВНО НА забор исходной колонки; производная колонка (detrended/разности) живёт в ДРУГОЙ шкале → закэпированные точки снова вне её забора (измерено: спайки ~+110 при заборе detrended +50.6). Для first_difference дополнительно: удаление неопределённого префикса сдвигает квантили — даже «вылеченный» value ре-флагается (офлайн-проба, 4 @ [24,69,104,129]).
Ф6. Рекомендация стационарности на этом датасете — linear_detrend (не разности); станция-apply не удаляет строк (150→150), при first_difference удаляет префикс.

### Гипотезы → минимальные read-only проверки → вердикты (все проверки ВЫПОЛНЕНЫ)

Г1 «Карточка устарела (фронт не перезапросил профиль)». Проверка: deps useEffect (Ф1) + GET outlier-profile сразу после apply в API. Результат: ОПРОВЕРГНУТА — фронт перезапрашивает; бэкенд после cap-apply честно возвращает done. Жёлтая карточка = ответ бэкенда, не стагнация.
Г2 «Зелёный trace = в данных нет выбросов („честно зеленая")». Проверка: одновременные GET profile vs GET trace в одной сессии. Результат: ОПРОВЕРГНУТА как общее правило — trace=done при 4–8 выбросах в данных: в ОКНЕ после добавления колонки (шаг 4) у ВСЕХ потоков и в ФИНАЛЕ flag-потока. Trace честен о решениях, НЕ о состоянии данных; интерпретация «в Прогрессе честно зеленая» — неверна: при воспроизведённом расхождении в данных 8 IQR-выбросов.
Г3 «Повторная фиксация при некоторых настройках мастера не устраняет IQR-выбросы». Проверка: матрица 8 конфигураций мастера на полном сценарии (scripts/progr_repro_variations.py). Результат: ПОДТВЕРЖДЕНА — детерминированный воспроизводитель: strategy=flag (by design, Ф4); cap/drop_rows/median чистят; percentile(1/99)/zscore(3.0)/use_residual(STL)+cap на этом датасете чистят. Тривиальный дополнительный класс: частичный выбор колонок (снятие галочек) — любая нефиксируемая колонка остаётся жёлтой.
Г4 «Мастер сообщает успех безусловно». Проверка: код (:190, Ф3) + измерение flag-apply. ПОДТВЕРЖДЕНА.
Г5 «Trace не видит появления выбросов (окно лжи)». Проверка: card vs trace после станция-apply до повторной фиксации. ПОДТВЕРЖДЕНА у всех потоков: карточка warning, trace done; причина — Ф2 (GET-пересчёты не трассируются).

### Корневая причина (установлена, fix НЕ предлагается — по требованию тимлида)

Два источника истины с РАЗНОЙ семантикой: карточка = «в данных ЕСТЬ выбросы по IQR(iqr 1.5) сейчас» (живой пересчёт), «Прогресс» = «последнее событие-решение узла — correction_applied → done» (журнал, last-wins, безусловный). Наблюдаемое тимлидом расхождение воспроизводится тогда, когда apply не устраняет IQR-выбросы из данных: детерминированно — strategy=flag (значения сохранены + флаг-колонка сама генерирует новые «выбросы»); системно — окно «выбросы появились → apply» у ЛЮБОГО потока (trace зелёный, карточка жёлтая). Дополнительные слагаемые: безусловный баннер успеха мастера (Ф3) и разница «метод мастера vs фиксированный iqr степпера» (маскирует still>0 при percentil/zscore/остатке — на этом датасете чисто, класс потенциально широкий).

### Артефакты (без правок кода репозитория)

scripts-копии: progr_repro_api_scenario.py (полный сценарий с измерениями на каждом шаге), progr_repro_variations.py (матрица 8 конфигураций), progr_repro_chronology.py (детальная хронология дефолт/flag), progr_repro_offline_probe.py (офлайн-проба механизма ре-флага). Датасет: scripts/repro_data/forecast_monitor_synthetic_n150.csv (генерация scripts/dataset_forecast_monitor.py). Deliverable: ZIP cisstat-progr22-repro-outliers-trace.zip — выложен в download. Без commit/push (AGENTS.md). Fix-предложения — ПОСЛЕ подтверждения причины тимлидом.
