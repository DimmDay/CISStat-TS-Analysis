# Акт независимой сертификации PROGR-AUDIT-5B-CERT (2026-10-12)

**Задача:** plan_progress_audit.md §8, AUDIT-5B — единая полная согласованная
проекция и watermark контура «Прогресс» (коммит 09e312f поверх a2dcbee).
**Аудитор:** независимая сессия (PROGR-AUDIT-5B-CERT). Правила AGENTS.md
соблюдены: commit/push НЕ выполнялись; продуктовый код и тесты репозитория
не изменялись — только артефакты аудита (все новые файлы аудита untracked;
продуктовые файлы после мутационных проб md5 == HEAD, побайтово — §8).
**Постановка тимлида:** «честно сертифицируй PROGR-AUDIT-5B. Спроектируй и
реализуй данную Сертификацию. Используй мутантов на своих мутантах, оракулов
на своих данных».
**Окружение:** Python 3.12.15, pandas 2.2.3, statsmodels, prophet,
statsforecast, torch-CPU + neuralforecast, PyWavelets/pandera/arch/ruptures
(полный контур доведён в сессии; средовой класс базлайна снят);
pgserver 0.1.4 + psycopg 3.3.6 — живой PostgreSQL-контур (тот же рецепт,
что AUDIT-6A-CERT; пакеты установлены в сессии с pypi.org).
**База аудита:** main@09e312f (HEAD = коммит задачи; предыдущий a2dcbee —
принятая AUDIT-6A-CERT; синхронизация по прямому указанию тимлида).

---

## 1. Сверка реализации с кодовой базой (09e312f)

Периметр коммита — 14 файлов. Все точки карточки §8 и контракта v0.6-5B §16
на месте:

- `app/core/node_status.py` — **NodeStateFold**, инкрементальная форма
  ЕДИНОГО редьюсера: `apply()` — точная копия тел двух батч-проходов
  (PROGR-11/13-A4/21/H1) в один проход; `derive_node_statuses`/
  `derive_pipeline_node_states` — делегирование той же свёртки (вторая
  реализация семантики не заведена); checkpoint-состояние
  `export_state`/`restore_state` (JSON-безопасно, мусор — честные дефолты);
  книжка деталей несёт происхождение КАЖДОГО поля (`_status_src`/
  `_status_ctx`/`_status_level`/`_reason_src`/`_count_src`);
  `node_states_with_evidence` — 7 полей §3 + 6 полей доказательств (I10);
  ЕДИНСТВЕННОЕ семантическое изменение против базы — I10: payload-статусный
  тип с невалидным payload больше не ставит reason/счётчик — диагностическая
  аномалия (`anomaly_count`), `last_touched_at` остаётся фактом касания.
- `app/core/pipeline_graph.py` — `event_context_validity(event_ctx, run_ctx)`:
  централизованная применимость факта на уровне context_id (нет контекста
  события/запуска — unknown, совпал — current, иначе stale; те же константы
  VALIDITY_*; I4 — исторические факты не стираются).
- `apps/api/progress_projection.py` (НОВЫЙ) — `canonical_corpus(*sources)`
  (нормализация канона §4.1 + merge_canonical_events AUDIT-S: дедуп строго
  по event_id, первый источник приоритетен, канонический порядок §3.3);
  `ProjectionSnapshot` (run_id/watermark/last_sequence/started_at/context_id/
  состояния/полный корпус/anomalies/complete/last_event_id/fold_state;
  `display_events(cap)` — I9; `to_dict`/`from_dict` — checkpoint);
  `build_projection` (полный replay — контрольный эталон плана §8 «Риск»);
  `advance_projection(base, tail)` (checkpoint + tail БЕЗ повторного прогона
  префикса; выравнивание run-метаданных свежими run_meta);
  `ProjectionPendingError` + `min_watermark` в build/advance (PR-7).
- `apps/api/routers/progress.py` — /trace переведён на ПОЛНУЮ проекцию:
  ledger слоя 2 приоритетен, слой 1 и артефакты Прогнозирования с дедупом;
  честная деградация `projection_source="session_tail"`/
  `projection_complete=false`/`started_at=null` при недоступности слоя 2
  (PR-8; 503 не вводится — панель advisory-потребитель §3.6);
  `after_watermark` → 409 projection_pending (PR-7);
  `started_at = run.created_at` (P11); события ответа — последние
  MAX_PIPELINE_TRACE_EVENTS канонического корпуса (I9); аддитивно
  watermark/events_total/anomalies/context_id; NodeStateOut + 6 полей
  доказательств (13-полевой контракт). Наставник (next-step) — статусы из
  ТОЙ ЖЕ проекции полного ledger + watermark/events_total аддитивно. Отчёт —
  canonical_corpus + build_report_model(canonical_order=True).
- `app/core/run_report.py` — `canonical_order` kwarg: вход в каноническом
  порядке НЕ пересортируется ts-сортировкой (P12/F08); default False —
  прежнее поведение прямых вызовов (легаси-ветка сохранена).
- UI: `packages/ui/lib/progress.ts` (NodeStateInfo + аддитивные Optional
  поля доказательств — N-3), `packages/ui/components/ProgressDrawer.tsx`
  (watermark/projectionSource/projectionComplete + честное предупреждение
  «история неполна» при projection_complete=false; undefined — старый
  бэкенд, прежний рендер). Фронтенд-файлы задачей затронуты, мутационная
  кампания сертификации — серверное ядро (мутанты UI не заводились;
  jest/typecheck — верификация базлайна, §2/§8).

Versioned-обновления тестов репозитория подтверждены в коде: пин «ровно 7
полей» /trace-узлов расширен до 13-полевого контракта с фиксацией
аддитивности N-3 (test_progress_panel.py); legacy-корпус PROGR-13-B3
моделируется в ОБОИХ слоях, нормализация legacy id проверяется на новом
ledger-пути чтения (test_progress_progr13b.py).

## 2. Независимая верификация базлайнов (1:1 с журналом)

- Оракул исполнителя `tests/api/test_progress_audit_5b.py` на HEAD,
  Memory: **20/20 passed** (= заявление «20/20 на Memory»).
- Тот же оракул на живом PostgreSQL: **20/20 passed** (pgserver;
  CISSTAT_TEST_PG_DSN + DATABASE_URL направлены на pgserver-инстанс —
  средовой file:-DSN песочницы нейтрализован; изоляция уникальными run_id —
  урок F-6A2) (= заявление «20/20 на живом PostgreSQL»); postgres-сюита 6A
  `test_research_runs_postgres.py`: **17/17**; сюита 6A на живом PG:
  **38/38** (= «17/17 без регресса» и базлайн 6A).
- RED-протокол исполнителя воспроизведён на worktree a2dcbee (копия скрипта
  в базу; sys.path → база): **5/5 RED-CONFIRMED, EXIT=0** — 1:1 с
  `scripts/prograudit5b_red_repro.txt`. ЗАМЕЧАНИЕ сертификации (находка
  F-5B1, §7): вердикт-логика артефакта недискриминирующая — все ветки
  харнесса печатают RED-CONFIRMED, exit 1 недостижим; прогон артефакта на
  HEAD даёт байт-в-байт тот же вывод «5/5». Различающая сила RED
  обеспечивается pytest-оракулом (ниже) — заявительная строка журнала
  честна именно в паре с ним.
- pytest-оракул исполнителя на базе a2dcbee (копия тест-файла в базу):
  **20/20 FAILED** = 11 ImportError контрактных API
  (TestProjectionModuleContract: apps.api.progress_projection и
  NodeStateFold отсутствуют целиком) + 9 поведенческих (панель/watermark/
  деградация/потребители) — расщепление 11+9 подтверждено 1:1 с журналом.
  Ложно-зелёных нет: ни один тест не проходит на базе.
- Полный регресс среды (после доведения контура): см. §8.

## 3. RED-воспроизведение СВОИХ оракулов на a2dcbee

git-worktree a2dcbee, копия scripts/prograudit5bcert_oracles.py в базу
(sys.path → база): **ImportError: cannot import name 'NodeStateFold' from
'app.core.node_status'** — контрактные API задачи (NodeStateFold,
apps/api/progress_projection целиком, event_context_validity,
canonical_order) на базе отсутствуют; все группы оракулов честно
RED-как-коллекция, EXIT=1 (протокол scripts/prograudit5bcert_red_repro.txt).
Ложно-зелёных нет: ни один из 51 оракула не проходит на базе.

## 4. Оракулы на СВОИХ данных — scripts/prograudit5bcert_oracles.py: 51/51 PASS (+ EXIT=0)

Свои данные сертификатора: тема — речная гидрология; run_id
RUN-C5B-H01…-API7/PG1-3, event_id c5b-*, контексты c5b-ctx-a1/b2/c3, ts и
payload пиннуты детерминированно (урок 6A-CERT: фабрика с новым event_id на
вызов делает «тот же корпус» неопределимым), кириллические payload
(«расход», «уровень», «дырка», «мусор»), свой нагрузочный корпус 1050 и
1500 событий, свои расщепления [3, 177, 512, 1024, 1499] и [1, 999, 1499]
(JSON-restart), живой pgserver-PostgreSQL с чистой схемой на каждый
PG-оракул.

- **CC (6)**: дедуп строго по event_id (зеркало P17 — один факт; независимые
  события с байт-совпадающим payload живы); приоритет первого источника при
  любом порядке слияния; канонический порядок — sequence побеждает обратный
  ts; частичный sequence корпус НЕ переупорядочивает (P12-механика);
  не-события (None/str/int) честно пропущены, словарь без event_id —
  легальный id-less факт (дедуп только по идентичности); watermark == число
  фактов, не строк.
- **UR (4)**: инкрементальный NodeStateFold == батч-развёрткам на СМЕШАННОМ
  корпусе (TraceEvent слоя 1 + stored-dict ledger + stage-level reason +
  невалидный payload): статусы, детали, аномалии, доказательства;
  derive-функции делегируют fold (нет второй реализации); last-wins +
  H1-монотонность (повторный GET не понижает done — P25); стадийный fold:
  6 стадий канонического порядка, done+pending → «в работе» (правило 5
  §12.10), пустой корпус — честное not_started.
- **SN (5)**: форма снапшота (все 13 носителей + events_total == watermark);
  display_events: последние cap, cap≠состояния, 0/отрицательный — пусто
  (I9); to_dict JSON-безопасен, from_dict восстанавливает всё (включая
  fold_state и доказательства узлов); restart через JSON-checkpoint не
  теряет ранние статусы (RED-критерий плана §8); контейнерный мусор
  from_dict — честные дефолты (скалярный мусор — находка F-5B2); 
  last_sequence: max int, bool НЕ позиция (корпус [0, True] → 0, не 1),
  legacy — честное None.
- **EQ (5)**: replay полного ledger == snapshot + tail на своих расщеплениях
  (3/177/512/1024/1499 корпуса 1500 > 2 капов) — равенство состояний
  (статусы/узлы с доказательствами/стадии/watermark/anomalies/last_sequence/
  last_event_id/started_at/context_id); эквивалентность через
  JSON-checkpoint restart (1/999/1499); advance выравнивает сместившийся
  run-контекст свежими run_meta (current → stale); tail из TraceEvent ==
  tail из stored-dict (два представления канона §4.1); watermark advance —
  позиция base + хвост (дедуп хвоста против префикса — ошибка вызывающего,
  ВИДНАЯ по watermark: документированный контракт запинен).
- **WM (4)**: build/advance с min_watermark — ProjectionPendingError при
  недостижимой позиции, OK на позиции и ниже; отказ advance не портит
  checkpoint (retry тем же base честен); текст pending называет обе позиции
  и projection_pending; HTTP-форма /trace?after_watermark: 200 на позиции,
  409 projection_pending при недостижимой, 0 — валидная позиция (PR-7).
- **ST (4)**: started_at == run.created_at при ts хвоста на часы позже
  (P11/PR-3); run-less — честное None (хвост начало не выдумывает); мусор
  run_meta — честные None (числовой created_at не станет строкой);
  session_tail: started_at None + complete False.
- **VAL (4)**: таблица истинности event_context_validity (unknown×4,
  current, stale; пустые строки — unknown); узловая validity: current /
  stale / unknown (легаси без контекста — НЕ current, PR-4) / None (узел
  без статусного факта — не unknown!); I4 — исторический факт не стёрт,
  помечен stale; смещение контекста запуска пересчитывает validity против
  того же корпуса.
- **EV (6)**: source-ссылки status/reason/count — РАЗНЫЕ решения
  (count_source_event_id от своего счётчика; stage-level target-reason
  ссылается на свой источник и не порождает статусного факта — N-2);
  невалидный payload («дырка»/None/1337/True) НЕ меняет детали, счётчик
  аномалий +4, last_touched_at обновлён (касание — факт журнала);
  evidence_level из envelope v2 доезжает до узла, легаси — честное None;
  mode_source="session" против event-derived (PR-6; узел без mode —
  mode_source None); контракт 13 полей узла (батч-версия — прежние 7).
- **RP (4)**: отчёт canonical_order=True НЕ пересортирует корпус с sequence
  против обратного ts (P12); default False хранит прежнюю ts-сортировку
  прямых вызовов; равные ts — стабильный порядок входа; API-отчёт
  (markdown) читает корпус в каноническом порядке — потребитель согласован
  с панелью.
- **API (7)**, живой API + Memory: P11 на корпусе 1050 (ранний
  upload/overview=done жив; watermark/events_total=1050; отображаемый
  список ровно 1000 — I9; started_at=run.created_at; ledger-пометки;
  13-полевые узлы); after_watermark 200/409/0; session_tail — честная
  деградация без 503 (complete=false, started_at=None, watermark>0);
  пустая сессия — честные «не начато» (§6.1); Наставник на той же проекции
  (watermark панели == watermark Наставника == 20; last_active_stage);
  зеркала слоя 1 не удваивают факты (P17); anomalies=1 в /trace с
  нетронутыми доказательствами.
- **PG (3)**, живой PostgreSQL (pgserver, чистая схема на оракул):
  committed история через атомарный батч 6A (commit_event_batch + receipt)
  даёт ТЕ ЖЕ состояния проекции, что те же факты из памяти
  (store-независимость приёмки §8; last_sequence=25, started_at/context из
  run-строки); /trace на PG-бэкенде (CISSTAT_RUNS_BACKEND=postgres) —
  ledger-путь, watermark=30, те же состояния, что на Memory; на живом store
  с запуском session_tail не срабатывает ложно.

## 5. Мутационная кампания СВОИХ мутантов — scripts/prograudit5bcert_mutations.py: 14/14 KILLED, 0 выживших; контроль выжил

Набор покрывает ядро контракта v0.6-5B и дизъюнктен задачам реализации
(исполнитель 5B мутационную кампанию не вёл — артефакты задачи: RED-repro +
pytest-оракул; мутации редьюсера/проекции/отчёта/маршрута ранее не
выполнялись). Дисциплина: байтовый backup, побайтовое восстановление + md5
после КАЖДОГО мутанта и в finally (урок PROGR-19); аварийный останов при
неединичном якоре (все 14 якорей проверены на единственность до прогона).
Каналы: oracle (51 свой оракул, сами поднимают pgserver) + repo (сюита
исполнителя tests/api/test_progress_audit_5b.py, Memory).

| Мутант | Класс атаки | Вердикт |
|---|---|---|
| CM-0 | no-op контроль | SURVIVED (харнесс достоверен, оба канала зелёные) |
| CM-1 | canonical_corpus: слияние/дедуп сняты (конкатенация источников — дубликаты фактов и второй порядок) | KILLED-BOTH |
| CM-2 | canonical_corpus: приоритет идентичности инвертирован (слой 1 перезаписывает ledger) | KILLED-ORACLE-ONLY |
| CM-3 | build_projection: read-after-watermark снят (min_watermark игнорируется) | KILLED-BOTH |
| CM-4 | advance_projection: хвост НЕ применяется к состоянию fold (checkpoint без достройки) | KILLED-BOTH |
| CM-5 | advance_projection: min-проверка по позиции base (хвост не учтён — ложный pending) | KILLED-ORACLE-ONLY |
| CM-6 | _max_sequence: bool принят за позицию ledger | KILLED-ORACLE-ONLY |
| CM-7 | started_at из ts первого события хвоста (P11 возвращён на run-less путях) | KILLED-ORACLE-ONLY |
| CM-8 | fold.apply: I10 снят (невалидный payload снова меняет детали, аномалия не считается) | KILLED-BOTH |
| CM-9 | evidence: validity всегда current (PR-4 снят, исторические факты неотличимы) | KILLED-BOTH |
| CM-10 | fold.restore_state: статусы checkpoint не восстанавливаются (restart теряет раннее) | KILLED-BOTH |
| CM-11 | build_report_model: canonical_order игнорируется (P12 — ts-сортировка канонического корпуса) | KILLED-BOTH |
| CM-12 | /trace: after_watermark 409 снят (PR-7) | KILLED-BOTH |
| CM-13 | /trace: session_tail помечен полной историей (PR-8 снят) | KILLED-BOTH |
| CM-14 | display_events: cap не ограничивает список (I9 снят — список 1050 вместо 1000) | KILLED-BOTH |

Ноль выживших; 9/14 убиты ОБОИМИ каналами; 5 KILLED-ORACLE-ONLY —
сюита исполнителя не пинит: приоритет идентичности источников (CC-2),
учёт хвоста в min-проверке advance (WM-2), bool как позиция ledger (SN-5),
started_at на run-less путях при непустом корпусе (ST-2/API-3),
видимость ошибки дедупа хвоста по watermark (EQ-5). Все 5 прикрыты
оракулами сертификации; перенос пинов в repo-сюиты рекомендован следующей
тестовой задачей (прецедент F-6A1 → перенос 6A-пинов).

## 6. Эволюция оракулов (открытая фиксация, прецедент PROGR-24-C-CERT R4)

Первая редакция сюиты (51 оракул) дала 39/51: 11 падений — ошибки САМОГО
сертификатора (гейт фабрики: profile_viewed вне Валидации; структура
check_modes — плоская карта {node: mode}, не {node: {mode}}; асимметрия
envelope в EQ-4 — сравнивались v2-TraceEvent и v1-dict; seeding без строки
run (session_tail вместо ledger-пути) в API/PG-группах; фиксированный id
сессии мимо cookie; JSON-парсинг markdown-отчёта; тафтологическое сравнение
SN-3 с replay хвоста вместо полного корпуса; fold-вердикты not_started).
Исправлены до 2-й редакции (48/51), 3-й (50/51 — поправка вердикта
«не начато»: not_started, не pending) и финальной (51/51). Параллельно
усилен SN-5 (корпус [0, True] — bool не позиция даже как максимум) под
killability CM-6. Единственное непокрытое первой редакцией продуктовое
поведение — граница мусора from_dict: вынесено в находку F-5B2 (§7) вместо
подгонки оракула под дефект.

## 7. Находки (акт §7)

- **F-5B1 (МЕТОДОЛОГИЧЕСКАЯ, артефакт исполнителя, не продукт)**:
  scripts/prograudit5b_red_repro.py — вердикт-логика недискриминирующая:
  все три ветки харнесса (_check) печатают «RED-CONFIRMED» (в т.ч. ветка
  AssertionError), обещанный докстрингом exit 1 («хотя бы одна уже
  исправлена») недостижим; прогон на HEAD даёт байт-в-байт тот же вывод
  «5/5», что и на базе. Четыре из пяти проверок к тому же щупают легально
  сохранившиеся старые пути чтения (слой 1 с капом, canonical_order=False
  по умолчанию) и не различают базы и HEAD по построению. РЕКОМЕНДАЦИЯ:
  починить вердикт-логику (ветка FIXED-ALREADY) и перецелить проверки на
  новые API проекции — прецедент F-CERTC1 (эволюция оракулов с открытой
  фиксацией). Заявленная честность RED при этом подтверждена парой
  «pytest-оракул 20/20 FAILED на базе ↔ 20/20 PASSED на HEAD» (§2) —
  продуктовых сомнений не остаётся.
- **F-5B2 (РЕКОМЕНДАЦИЯ, робастность границы, не блокер)**:
  ProjectionSnapshot.from_dict на скалярном нечисловом мусоре
  (watermark="мусор") поднимает ValueError, на нечисловом мусоре
  контейнерных полей (node_statuses="мусор") — AttributeError, вопреки
  докстрингу модуля («мусор при чтении — честные дефолты») и дисциплине
  fold.restore_state (который мусор честно дефолтит). Контейнерный мусор
  корректных типов (None/не-Mapping) обработан честно. Риск отложен до
  владельца формата хранения: персистентный кэш снапшотов — AUDIT-6B;
  рекомендовано согласовать (try/except как в restore_state либо явный
  контракт «checkpoint хранится как сформирован to_dict»).
- **R1 (Info)**: приёмка «одинаковые состояния независимо от выбранного
  store» подтверждена независимо на своих данных в обе стороны
  (PG committed-батч → те же состояния, что из памяти; /trace на PG-бэкенде
  == Memory); выбор store для проекции действительно не материен — корпус
  канонизируется до состояний.
- **R2 (Info)**: границы совпадают с заявленными (§16.5): персистентный
  кэш снапшотов — AUDIT-6B; scope-уровень validity — AUDIT-8; Наставник не
  читает артефакты сессии (run-scoped) — честная граница доставки,
  наблюдаемая watermark'ами; UI-мутанты не заводились (серверное ядро —
  носитель контракта; UI-базлайны верифицированы §2/§8).
- **R3 (Info)**: документированный контракт advance «дедуп хвоста против
  префикса — ошибка вызывающего, видимая по watermark» запинен оракулом
  EQ-5 как есть; альтернатива (тихий дедуп) контрактом отвергнута —
  согласовано с журналом задачи.

## 8. Регрессионный контур и границы сертификации

Все продуктовые файлы после мутационных проб побайтово идентичны HEAD
(git diff пуст по apps/api/progress_projection.py, app/core/node_status.py,
app/core/run_report.py, app/core/pipeline_graph.py,
apps/api/routers/progress.py; восстановление контролировалось md5 после
КАЖДОГО мутанта и в finally). Независимые прогоны сертификации:

- Адресный прогресс-контур (25 адресных сюит плана: панель/движок/трасса/
  хук/Наставник/отчёт/audit S,C,H1/6A-Memory-часть/progr13/16/17/18/23/25/
  session_store/target_column/admin): **807 passed / 0 failed** (Memory).
- tests/api + tests/integration: **1665 passed / 0 failed / 18 skipped** —
  1:1 с базлайном журнала (средовой класс снят: statsmodels поднят до
  0.15.0 — параметрическая симуляция прогнозирования была единственной
  причиной 16 падений до доведения среды, вне контура Прогресса).
- Полный tests/: **3549 passed / 3 errors / 18 skipped** — 1:1 с журналом
  (3 errors — документированный snapshot-fixture класс
  tests/unit/test_preprocessing.py, вне контура).
- Живой PostgreSQL (pgserver; DATABASE_URL нейтрализован — средовой
  file:-DSN песочницы направлен на pgserver-инстанс, паттерн
  prograudit6a_pg_runner.sh): оракул исполнителя 5B — **20/20**;
  сюита 6A — **38/38**; postgres-сюита 6A — **17/17** (суммарно 75/75).
- Jest: **163 suites / 1934 tests passed** — 1:1 с базлайном журнала;
  tsc standalone — единственная диагностика TS2882 globals.css —
  задокументированный средовой класс (1:1 с журналом).

- Сертифицируется реализация задачи AUDIT-5B на коммите 09e312f. Живой
  PostgreSQL — временный pgserver-инстанс (рецепт Донастройка_2 п.1 /
  AUDIT-6A-CERT); production PostgreSQL render.com, Vercel-деплой,
  браузерные потоки и персистентный кэш снапшотов (AUDIT-6B) — вне
  периметра.

## 9. Вердикт: PASSED

Ядро приёмки AUDIT-5B подтверждено независимо на своих данных: канонический
корпус един (дедуп строго по event_id, приоритет ledger → слой 1 →
артефакты, sequence-порядок без переупорядочивания частичным sequence) и
watermark — позиция истории в фактах, а не строках; редьюсер один —
инкрементальная свёртка байт-в-байт совпадает с батч-развёртками, второй
реализации нет; replay полного ledger == snapshot + tail на нагрузочном
корпусе 1500 > 2 капов и всех расщеплениях, включая restart через
JSON-checkpoint; read-after-watermark честен на всех уровнях (модуль,
advance, HTTP 409 projection_pending); started_at — run.created_at, хвост
начало не выдумывает; validity различает current/stale/unknown (легаси-факт
не current, узел без факта — None), исторические факты не стираются;
доказательства полей (I10) — свои source-ссылки status/reason/count,
evidence_level из envelope, mode_source="session" отдельно от event-derived;
невалидный payload не трогает детали и честно посчитан аномалией; cap
ограничивает только отображаемый список; отчёт и Наставник — потребители
той же проекции (P12/F08 закрыты); деградация session_tail честна и не
срабатывает ложно на живом store; одна и та же committed история даёт
одинаковые состояния на Memory и живом PostgreSQL (приёмка §8). Базлайны
исполнителя воспроизведены 1:1 (20/20 на обоих stores; RED 5/5;
20 FAILED = 11 ImportError + 9 поведенческих); свои оракулы 51/51 (RED на
базе — ImportError-коллекция, ложно-зелёных нет); 14/14 своих мутантов
убиты, контроль выжил; продуктовые файлы после мутаций md5 == HEAD.
Противоречий «код vs контракт v0.6-5B» не найдено; две находки (F-5B1 —
артефакт RED-протокола исполнителя, F-5B2 — робастность from_dict до
AUDIT-6B) рекомендательной силы, продуктовое ядро не затрагивают.

**Deliverable:** ZIP cisstat-prograudit5b-certification.zip → открытый
контейнер сессии (download): docs/cert_prograudit5b_2026-10-12.md,
scripts/prograudit5bcert_oracles.py (+ .txt), scripts/prograudit5bcert_red_repro.txt,
scripts/prograudit5bcert_mutations.py (+ _mutation_results.txt),
worklog/worklog9.md. Без commit/push (AGENTS.md).
