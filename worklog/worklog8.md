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

