# Акт независимой сертификации PROGR-AUDIT-6A-CERT (2026-10-11)

**Задача:** plan_progress_audit.md §7, AUDIT-6A — атомарный ledger «Прогресса»
и одинаковые хранилища (коммит 18bdac2 поверх 9a3ed2b).
**Аудитор:** независимая сессия (PROGR-AUDIT-6A-CERT). Правила AGENTS.md
соблюдены: commit/push НЕ выполнялись; продуктовый код и тесты репозитория
не изменялись — только артефакты аудита (все untracked; продуктовый файл
apps/api/research_runs.py после мутационных проб md5 == HEAD, побайтово).
**Постановка тимлида:** «честно сертифицируй PROGR-AUDIT-6A. Спроектируй и
реализуй данную Сертификацию. Используй мутантов на своих мутантах, оракулов
на своих данных».
**Окружение:** песочница доведена до рецепта R6 (Python 3.12.15, statsmodels
0.15.0, pandas 2.2.3, prophet, fakeredis, PyWavelets/pandera/arch/ruptures/
statsforecast, torch-CPU + neuralforecast — полный контур); pgserver 0.1.4 +
psycopg 3.3.6 установлены для живого PostgreSQL-контура (Донастройка_2 п.1).
**База аудита:** main@18bdac2 (HEAD = коммит задачи; предыдущий 9a3ed2b —
принятая AUDIT-C-CERT; синхронизация по прямому указанию тимлида).

---

## 1. Сверка реализации с кодовой базой (18bdac2)

Все точки карточки §7 и контракта v0.5-6A §15 на месте:

- `apps/api/research_runs.py` — контракт атомарного ledger: `CommitEventBatch`
  (frozen dataclass: run + events + expected_context_id + idempotency_key +
  body_fingerprint), `CommitReceipt` (to_dict/from_dict roundtrip), исключения
  `CommitConflictError`/`IdempotencyConflictError`, `batch_body_fingerprint`
  (sha256 канонического материала {v:1, run_id, context_id, события с
  payload sort_keys}, ensure_ascii=False — кириллица детерминированна).
- **Memory** `commit_event_batch`: тот же `threading.Lock` покрывает
  идемпотентность (повтор ключа → прежний receipt; другое тело → конфликт БЕЗ
  записи), CAS-контекст, дедуп (внутри батча первый occurrence + против
  корпуса), COALESCE-слияние run-метаданных (`_merge_run_additive`), запись
  событий + вода́ ledger (`_sequences`), регистрацию receipt — отказ на
  середине оставляет ноль событий и прежние метаданные (P08/P10).
  `append_event` — дедуп (run_id, event_id) + sequence per run (паритет I8).
- **Postgres** `commit_event_batch`: ОДНА транзакция (autocommit=False +
  контекст-менеджер): SELECT receipt FOR UPDATE → INSERT shell run + SELECT
  context FOR UPDATE (сериализация по run, непрерывный префикс commit_seq) →
  CAS → MAX(commit_seq) + существующие event_id → поштучный INSERT
  (ON CONFLICT DO NOTHING) → UPSERT run (COALESCE аддитивных полей) → INSERT
  receipt → commit. `_prepare_stored_event` — честная маркировка времени
  (AUDIT-S substituted=True) + durable envelope v2 в строке (граница
  AUDIT-C §14.5 закрыта).
- `list_events` — единое чтение канонического порядка: legacy-строки
  (commit_seq NULL) первыми по store-order (seq 0001), новые — по commit_seq
  (ORDER BY (commit_seq IS NOT NULL), CASE … END).
- **Migrated producers** (план §7 п.6): `record_run_event` (зеркало хука/
  сброса цели/Прогнозирования) и `record_run_event_batch` (4 карты статусов
  в `apps/api/routers/progress.py`: upload-stops/validation-checks/
  preprocessing-checks/eda-checks — по местам вызова заменены N×
  `record_run_event` на ОДИН батч) идут через `commit_event_batch`;
  содержательные ключи `event:{run_id}:{event_id}` и
  `map:{run_id}:{fp[:40]}`; fingerprint — ТОЛЬКО тело событий (контекст run
  вычисляется свежими и не дедуплицируется receipt'ом). Advisory-остаток
  (pause/resume/checkpoint/restore — прямые append_event/set_run_status) не
  мигрирован — контрактом §15.4 предусмотрено (до AUDIT-6B).
- **Миграция**: `MIGRATION_STATEMENTS = 0001 + 0002` (аддитивно, 0001 не
  переписан); файл-дубль `apps/api/migrations/0002_audit6a_atomic_ledger.sql`
  (run-метаданные context_id/data_revision/data_digest; trace_events:
  commit_seq + 8 колонок durable envelope v2; уникальный индекс
  (run_id, commit_seq) WHERE NOT NULL; таблица run_commit_receipts с FK ON
  DELETE CASCADE); `MIGRATION_FILES` — каталог с эквивалентностью,
  страхуемой тестами.
- `run.target_column=None` при `target_column_cleared` — ПРЯМАЯ запись
  (не COALESCE) — семантика сброса цели H1 сохранена.

Периметр коммита — 14 файлов: apps/api (research_runs.py, routers/progress.py,
migrations/0002), tests/api (3 файла), docs/progress_audit_contract.md
(§15), plan_progress_audit.md (статус), scripts/ (4 артефакта), worklog9.
Фронтенд (.ts/.tsx) не затронут — jest/typecheck вне периметра (паттерн
PROGR-19/20/21/24-C).

## 2. Независимая верификация базлайнов (1:1 с журналом)

- Оракул исполнителя `tests/api/test_progress_audit_6a.py` на живом PG:
  **38/38**; `tests/api/test_research_runs_postgres.py`: **17/17**;
  `tests/api/test_research_runs.py`: **60/60** — суммарно **115/115** =
  заявление журнала «115/115 полного контура на живой БД» 1:1 (свежий
  pgserver на каждый сюит; харнесс исполнителя prograudit6a_pg_runner.sh
  держит сервер живым на время прогона).
- RED-протокол исполнителя воспроизведён на worktree 9a3ed2b:
  **RED=6, FIXED-ALREADY=1, SKIPPED=0** (R1 Memory-дедуп, R2
  metadata-without-event, R3 partial-map, R4 sequence[memory+postgres],
  R5 envelope[postgres]; R5 envelope[memory] — FIXED-ALREADY) + ImportError
  их тест-модуля на базе (CommitConflictError отсутствует) — 1:1 с
  scripts/prograudit6a_red_repro.txt.
- Мутационные пробы исполнителя воспроизведены фактом протокола
  (scripts/prograudit6a_mutation_results.txt: M0 SURVIVED, 9/9 KILLED).
- Полный регресс: tests/api + tests/integration — **1645 passed / 0 failed /
  18 skipped** (R6-окружение с полной нейро-группой: документированный
  средовой класс базлайна снят полностью, ноль падений); полный tests/ —
  3529 passed / 3 errors / 18 skipped (3 errors — fixture 'snapshot' в
  tests/unit/test_preprocessing.py, задокументированный snapshot-класс
  исполнителя, к ledger отношения не имеет).
- DDL-файлы: эквивалентность 0001+0002 против MIGRATION_STATEMENTS
  подтверждена собственным нормализующим разбором (оракул MIG1) и живым
  применением файла 0002 на legacy-корпусе (MIG3–MIG5).

## 3. RED-воспроизведение СВОИХ оракулов на 9a3ed2b

git-worktree 9a3ed2b, прогон scripts/prograudit6acert_oracles.py:
**ImportError: cannot import name 'batch_body_fingerprint'** — контрактные
API задачи (CommitEventBatch/CommitReceipt/commit_event_batch/fingerprint/
MIGRATION_STATEMENTS_0002) на базе отсутствуют целиком; все группы оракулов
честно RED-как-коллекция (протокол scripts/prograudit6acert_red_repro.txt,
EXIT=1). Ложно-зелёных нет: ни один оракул не проходит на базе.

## 4. Оракулы на СВОИХ данных — scripts/prograudit6acert_oracles.py: 85/85 PASS (+ EXIT=0)

Свои данные сертификатора: run_id RUN-CERT6A-H01…H17 (+LEG/MIG/-nullbind),
event-теги c6a-hydro/*, свои payload (в т.ч. кириллица «влажность»), свой
датасет e2e-потока farm_yield_monthly.csv (72 месячные точки, date/yield,
генерация детерминирована), свои ключи идемпотентности (cert6a-*,
pg-cert6a-*), живой pgserver-PostgreSQL с чистой схемой на каждый оракул.

- **FP (6)**: детерминизм отпечатка на своём корпусе; чувствительность к
  payload/run_id/контексту; префикс sha256: + 64 hex; **межпроцессный
  детерминизм** (два субпроцесса с пиннутыми event_id/ts — один отпечаток).
- **ATOM-M (7) / ATOM-P (4)**: отказ на ПОСЛЕДНЕМ событии батча (Memory и
  живой PG): ноль событий, прежние метаданные, receipt НЕ зарегистрирован;
  честный retry тем же ключом — ровно одна копия; отказ на ПЕРВОМ событии
  после успешного корпуса — метаданные байт-в-байт прежние (PG-откат:
  run-строка не создана).
- **SEQ-M (3) / SEQ-P (4)**: непрерывный префикс 1..N при чередовании
  батчей и одиночных advisory-записей; независимость sequence per run;
  2 конкурентных потока × 20 событий — непрерывный 1..40 без дублей/дыр;
  живой PG: legacy-строки (SQL-вставка с commit_seq NULL) читаются ПЕРВЫМИ
  (store-order), новые с commit_seq=1; legacy sequence честно None.
- **RCP-M (9) / RCP-P (7)**: безключевой батч (события+sequence пишутся,
  receipt нет); два РАЗНЫХ ключа на одно тело приняты независимо; retry
  СТАРОГО ключа ПОСЛЕ дописанных событий — прежний watermark и ТЕ ЖЕ
  accepted-ids, ноль записей; форма receipt (6 полей to_dict);
  get_commit_receipt; **accepted_event_ids = фактически принятые** (батч
  [дубль корпуса, новый] → accepted ровно [новый]) — в возвращённом
  объекте (RCP8/RCPG6) и в ПРОЧИТАННОМ из строки PG (RCP9/RCPG7);
  IdempotencyConflictError без записи (PG); durable receipt читается новым
  объектом store/коннектом (RCPG5).
- **CAS-M (8) / CAS-PG (8)**: stored NULL при ОТСУТСТВУЮЩЕМ run — первичная
  привязка; совпадающий контекст принимается; **stale-сценарий полного
  вида** (производитель прочитал ctx-1 → advisory-писатель перевёл контекст
  на ctx-2 → производитель коммитит с expected=ctx-1) — CommitConflictError
  ДО записи, ноль событий производителя; **ключ идемпотентности пережил
  CAS-отказ** (retry с исправленным expected принят); expected=None
  отключает CAS; **stored NULL при СУЩЕСТВУЮЩЕЙ строке run (shell-строка
  PG-append / advisory-батч без контекста) — привязка, не конфликт**.
- **COA-M (6) / COA-PG (6)**: None-батч не стирает context/revision/digest;
  receipt None-батча несёт СЛИТЫЙ (хранимый) контекст, не пустой из батча;
  частичное обновление (только digest) — контекст сохранён;
  target_column записывается НАПРЯМУЮ (None сбрасывает цель — семантика
  H1, не COALESCE).
- **PAR-M (3) / PAR-PG (3)**: дедуп append (run_id, event_id) — ровно один
  факт; глубокие копии (мутация прочитанного payload не портит stored);
  durable envelope v2 (schema_version=2/server_result/operation_id/
  context_id) переживает запись/чтение в ОБОИХ хранилищах.
- **E2E (8)**: свой CSV через живой API (/v1/internal/upload) → полная карта
  остановок «Загрузки» — ОДИН batch с непрерывным sequence-префиксом;
  содержательный ключ `map:{run_id}:{fp[:40]}` восстанавливается СВОИМ
  пересчётом отпечатка из слоя 1; повтор POST = НОВАЯ поставка (новые
  event_id) — честная P07-семантика наблюдений, слой 1 симметрично растёт;
  store-retry ТОГО ЖЕ батча (те же event_id первой поставки) — прежний
  receipt, ноль дубликатов.
- **MIG (5)**: файл 0002 == MIGRATION_STATEMENTS_0002 (собственный
  нормализующий разбор, 16 утверждений); каталог MIGRATION_FILES 0001+0002;
  legacy-корпус (ТОЛЬКО 0001 + свои строки) → применение ФАЙЛА 0002 →
  legacy читаем, sequence None, батч+receipt на мигрированном корпусе с
  watermark=1.

## 5. Мутационная кампания СВОИХ мутантов — scripts/prograudit6acert_mutations.py: 9/9 KILLED, 0 выживших; контроль выжил

Набор ДИЗЪЮНКТЕН к M0/M1–M9 исполнителя (другие классы/точки); дисциплина:
backup + побайтовое восстановление + md5 после каждого мутанта и в finally
(урок PROGR-19); аварийный останов при неединичном якоре. Каналы: oracle
(85 своих оракулов, сами поднимают pgserver) + repo (сюита исполнителя на
живом PG).

| Мутант | Класс | Вердикт |
|---|---|---|
| CM-0 | no-op контроль | SURVIVED (харнесс достоверен) |
| CM-1 | fingerprint: payload исключён из материала («тот же ключ + другой payload молча принят») | KILLED-ORACLE-ONLY (FP2) |
| CM-2 | Memory CAS: stored NULL трактуется как конфликт (первичная привязка сломана) | KILLED-ORACLE-ONLY (CAS-M8) |
| CM-3 | Memory append_event: дедуп корпуса снят (advisory I8/P20) | KILLED-BOTH |
| CM-4 | PG commit_seq от MAX(seq) BIGSERIAL (BIGSERIAL принят за committed-order) | KILLED-ORACLE-ONLY (SEQP1/MIG5) |
| CM-5 | PG list_events: legacy-first порядок снят | KILLED-BOTH |
| CM-6 | PG receipt: accepted = все id батча вместо принятых | KILLED-ORACLE-ONLY (RCPG7) |
| CM-7 | Memory receipt.context_id из батча вместо слитого run | KILLED-ORACLE-ONLY (COA-1b) |
| CM-8 | PG upsert run: data_digest без COALESCE | KILLED-BOTH |
| CM-9 | Memory идемпотентность: short-circuit снят (retry перезаписывает receipt) | KILLED-BOTH |

## 6. Эволюция оракулов (открытая фиксация, прецедент PROGR-24-C-CERT R4)

Первая редакция сюита (75 оракулов) дала 2 выживших и 1 PATTERN-MISS:
CM-1 — неточный якорь (отступы) — исправлен; **CM-2 и CM-6 выявили РЕАЛЬНЫЕ
дыры покрытия ОБОИХ каналов** (не продукта): первичная привязка на stored
NULL при СУЩЕСТВУЮЩЕЙ строке run и durability accepted-ids в прочитанном
receipt не были пины ни сюитой исполнителя, ни первой редакцией оракулов —
добавлены CAS-7/8, RCP9, RCPG7 (85/85), после усиления оба мутанта убиты.
Также уточнены сценарии FP1/FP6 (фабрика генерирует новый event_id на вызов —
«тот же корпус» требует пиннутых id), CAS-M3 (полный stale-сценарий с
advisory-сдвигом контекста) и E2E5–7 (повтор POST = новая поставка по
P07-семантике контракта §15.3; retry того же батча — уровень store).

## 7. Находки (акт §7)

- **F-6A1 (РЕКОМЕНДАЦИЯ, покрытие repo)**: 5 из 9 моих мутантов (CM-1/2/4/6/7)
  пережили repo-канал — сюита исполнителя не пинит: чувствительность
  отпечатка к payload (их conflict-тест различает тела по event_id), CAS
  stored-NULL при существующей строке, commit_seq против BIGSERIAL на
  смешанном корпусе, durability accepted-ids частичного батча, слитый
  context_id в receipt. Все 5 прикрыты оракулами сертификации; перенос пинов
  в repo-сюиты рекомендован следующей тестовой задачей.
- **F-6A2 (НАБЛЮДЕНИЕ, тест-гигиена)**: PG-сюиты требуют СВЕЖЕЙ схемы на
  прогон (фикстура DROP+миграции); на переиспользованном сервере между
  сюитами возможны артефакты состояния — харнесс исполнителя и оракулы
  сертификации соблюдают контракт (fresh schema/pgserver), дефектом продукта
  не является.
- **R1 (Info)**: е2е-поток сертификации подтвердил P07-семантику «новая
  поставка карты = новые наблюдения» — осознанный контракт до AUDIT-2A;
  транспортный retry того же батча защищён идемпотентностью store.
- **R2 (Info)**: границы совпадают с заявленными: Redis/DataFrame вне
  транзакции; P09/доставка — AUDIT-6B; advisory-продюсеры не мигрированы;
  строгая обязательность v2 — AUDIT-6B.

## 8. Регрессионный контур и границы сертификации

- Адресные сюиты 115/115 на живом PG; полный tests/api+integration 1645/0/18
  (R6-среда); продуктовые файлы после мутаций md5 == HEAD; фронтенд не
  затронут (jest/typecheck вне периметра).
- Сертифицируется реализация задачи AUDIT-6A на коммите 18bdac2. Live-Postgres
  — временный pgserver-инстанс (тот же паттерн Донастройка_2 п.1); production
  Redis/Postgres render.com, Vercel-деплой и браузерные потоки — вне
  периметра (эксплуатационная приёмка — AUDIT-6C/H29-30).

## 9. Вердикт: PASSED

Ядро приёмки AUDIT-6A подтверждено независимо на своих данных: атомарный
ledger существует в единой точке и атомарен на ОБОИХ хранилищах (отказ на
любом событии батча — ноль событий и прежние метаданные, receipt не
регистрируется); sequence — транзакционная позиция с сериализацией по run
(непрерывный префикс под конкурентностью, BIGSERIAL не принят за
committed-order, legacy-first каноническое чтение); receipt/идемпотентность
честны (retry без дублей, конфликт без записи, accepted = фактически
принятые — в объекте и в durable-строке); CAS отклоняет stale ДО записи и
не потребляет ключ; COALESCE-слияние не стирает метаданные, сброс цели
пишется напрямую; паритет I8/дедуп/глубокие копии/envelope v2 выдержан;
миграция 0002 аддитивна и применима к legacy-корпусу (файл == python-
утверждения); migrated producers идут одним батчем с содержательными
ключами. RED-протоколы исполнителя и сертификатора воспроизведены 1:1;
базлайны 115/115 и 1645/0 совпали; 85/85 оракулов; 9/9 своих мутантов убиты
(4 — обоими каналами, 5 — оракулом с задокументированными repo-гэпами),
контроль выжил. Противоречий «код vs контракт v0.5-6A» не найдено.

**Deliverable:** ZIP cisstat-prograudit6a-certification.zip → открытый
контейнер сессии (download): docs/cert_prograudit6a_2026-10-11.md,
scripts/prograudit6acert_oracles.py (+ .txt), scripts/prograudit6acert_red_repro.txt,
scripts/prograudit6acert_mutations.py (+ _mutation_results.txt),
worklog/worklog9.md. Без commit/push (AGENTS.md).
