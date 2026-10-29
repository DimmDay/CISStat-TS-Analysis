# PGV-05 — PassportHistoryReader (документ поставки)

**Задача:** spec_passport_graphics_visual.md §13, строка PGV-05 (зависимость PGV-04).
**Дата:** 2026-10-29. **База:** main@c4e90b8 (PGV-04), рабочее дерево чистое.
**Критерий готовности (§13):** «Чтение без Redis/DataFrame, schema gaps/legacy_unknown
честны».

## 1. Постановка и граница

§8 прямо фиксирует: «`PassportHistoryReader` читает registry/ObjectStore, а не
SessionStore. Snapshot включает полные groups/metrics/categories/lists/reasons/warnings,
schema/calculation version, target/date/entity, snapshot_id, fingerprint/context/
data_revision, captured/created time и data_ref. source_hash и fingerprint — разные поля
с определением алгоритмов». До поставки durable-факты existed (rs-записи PGV-04,
passport-артефакты C03, чекпоинты PGV-04), но читались только по-отдельности низкоуровневыми
lookup'ами (`get_passport_checkpoint`, `find_idempotent`); единого read-only контракта
истории паспортов — траекторий по выбранному подтверждению, полных snapshot-записей,
списков-пикеров — не было. Именно его требуют последующие задачи: PGV-06 (сравнение),
PGV-13 (P01/P02 builders «полные паспорта/сравнение из refs, без DataFrame»),
PGV-15 (picker/preview UI).

Runtime-границы: P01/P02 builders — PGV-13; печатный layout — PGV-07; renderer/jobs —
PGV-08/09; UI «Документы исследования» — PGV-15. Reader — ТОЛЬКО чтение: ни capture, ни
промоушен, ни пересчёт науки (AC06), ни одной записи в реестры.

## 2. Файлы поставки

| Файл | Статус | Содержание |
|---|---|---|
| `apps/api/passport_history.py` | **НОВЫЙ** | Reader `pgv.passport_history/1`: snapshot-записи §8, trajectory-чтение (AC10/AC11), списки-пикеры (§10), XOR-честность (AC12), изоляция вселенных (AC14), access-контур (AC18-дух) |
| `tests/api/test_pgv05_passport_history.py` | **НОВЫЙ** | 18 тестов (6 классов): границы модуля/AC09, траектории AC10/AC11, контракт записи §8, честные gaps AC12, панель AC14, пикеры/доступ |
| `docs/pgv05_passport_history.md` | **НОВЫЙ** | Этот документ |
| `worklog/worklog11.md` | Обновлён | Запись PGV-05 |
| `scripts/pgv05/` | **НОВЫЙ** | red_protocol.txt, green_protocol.txt, debug_traj.py (диагностика), check_reader.py (smoke) |

Существующий runtime-код НЕ изменён ни байтом (нулевая поверхность регрессии; точки
изменения спеки «passport_documents/ObjectStore/refs» — читающие стороны: новый модуль
+ существующие реестры используются только через уже сертифицированные API чтения).

## 3. Ключевые решения

1. **Контракт `pgv.passport_history/1`.** Versioned read-контракт (прецедент PGV-01/02):
   snapshot-запись несёт `schema_version`, `snapshot_ref` (rs-*), `session_snapshot_id`
   (обратная деривация из idempotency-ключа `pgv-passport:{sid}`), `artifact_id`, `stage`,
   `universe`, `passport` (ПОЛНОЕ содержимое КАК ЕСТЬ — не сокращается), `content_status`
   (present/missing_artifact/corrupt) + `content_gap_reason`, schema/calculation version,
   target/date, `fingerprint`, `source_hash`+`source_hash_algorithm`, `context_id`/
   `data_revision`, `data_ref`, `captured_at`/`created_at`.

2. **Два разных хэша с определёнными алгоритмами (§8).** `source_hash` = SHA-256
   канонического JSON payload'а паспортного артефакта (identity КОНТЕНТА; ==
   `payload_sha256` реестра, алгоритм объявлен полем `source_hash_algorithm` =
   `sha256(canonical_json)`); `fingerprint` = series_fingerprint данных на capture
   (identity ДАННЫХ, алгоритм `app.core.passport.series_fingerprint`). Тест пинует
   равенство значений.

3. **Два разных доказуемых времени.** `captured_at` — из rs-записи (время capture
   сессии); `created_at` — из артефакта (время durable-промоушена). Ни одно не
   подменяется другим, время чтения не подставляется (AC12).

4. **Резолюция rs→артефакт — только доказуемые связи.** Зависимость
   `artifact:{id}` (pin-причина `passport_record:{rs-id}`, §16) → fallback по
   producer-ключу `passport:{session_snapshot_id}` (порядок промоушена C03/PGV-04:
   артефакт мог появиться позже заморозки rs-записи). Оба источника — registry-факты;
   run-принадлежность проверяется на каждом шаге (глобальные `get_snapshot_record`/
   `get_artifact` без проверки run'а не используются вслепую).

5. **Целостность (T8/T16).** ObjectStore content-addressed ключ (расхождение —
   `ArtifactIntegrityError`) + сверка sha256 прочитанных байтов с `payload_sha256`
   реестра + разбор JSON + сверка `payload.snapshot_id` с `session_snapshot_id`
   (подмена ассоциации). Любой отказ — `content_status="corrupt"` с деталью, контент
   НЕ выдаётся; при этом `captured_at`/`source_hash` остаются доказуемыми из
   registry-метаданных (честная деградация без выдуманных дат).

6. **XOR-конвенция «значение либо явная причина»** (прецедент print_schema
   digest-XOR-reason): каждое недоказуемое поле — None + машина-причина
   `legacy_unknown` (не существовало/не записано: payload паспорта не самоназван —
   schema/calculation version текущих captures честно `legacy_unknown`, НЕ выдуманный
   «v1») или `integrity_failure` (существует, но не верифицируется). Значение+причина
   одновременно запрещены.

7. **Траектория «на выбранное подтверждение» (AC10).** Читаются ТОЛЬКО замороженные
   refs чекпоинта (stage_refs/snapshot_ref/previous_snapshot_ref); более поздние снимки
   в траекторию не попадают, старые snapshots не переписываются. Reused handoff
   резолвится в ИСХОДНЫЙ снимок: тот же rs-факт адресуется и ключом физического этапа
   (exit), и ключом пути подтверждения (modeling_entry) — одна запись, два адреса пути,
   никакой четвёртой копии (AC11). Недостающие ссылки — явные gaps
   (`missing_snapshot_record`/`not_a_passport_record`), partial-чтение перечисляет
   пропуски (§9-дух), commit-факты чекпоинта (confirmed_at/flags/context) читаются
   независимо от content-гэпов.

8. **Доступ (AC18-дух).** `authorize_run_access(action="read")` через единый сервис
   промоушена; отказ — `PassportHistoryAccessDenied` uniform (чужой run и несуществующий
   run неразличимы). Чтение не создаёт артефактов/записей/пинов (тест пинует счётчики).

## 4. TDD-протокол

- **RED:** 18/18 FAILED (`scripts/pgv05/red_protocol.txt`) — модуль отсутствовал;
  протокол: ModuleNotFoundError apps.api.passport_history.
- **GREEN:** 18 passed (после двух честных доуточнений оракулов: (а) пайплайн
  baseline-гейт требует мутаций между capture — последовательность PGV-04; (б) rs-реестр
  добавлен в reset-фикстуру — list-тесты чувствительны к межтестовому состоянию;
  в reader'е уточнено алиасирование reused-подтверждения под ключ этапа пути).
- **Адресный регресс:** pgv02+pgv03+pgv04 (164), dataset_passport+passport_session_state
  (40), deepar_panel_pivot+doclog_recheck_fix (58/1 skip) — 262 passed
  (`scripts/pgv05/green_protocol.txt`).
- **Дельта-0 полного tests/api:** HEAD 67F/3017P/44S vs база c4e90b8 67F/2999P/44S —
  дельта ровно +18 passed (корпус), FAILED-счёт 67=67; состав — известные средовые
  классы (psycopg/upload_db/forecasting_session/garch/egarch), паспортных падений нет.
- **Сборка:** py_compile OK; import apps.api.main OK — **221 маршрут** (паритет),
  ARTIFACT_KINDS 10, миграции 16 (не тронуты — поставка не меняет SQL-слой); AST-гейт:
  в passport_history.py нет импортов session_store/pandas/redis.

## 5. Честные границы

1. **Панельная изоляция снимков:** `universe` записи выводится из stage passport-
   артефакта; у записей без артефакта (legacy до C03) stage недоказуем — universe=None,
   под universe-фильтр такие записи не попадают (приписать вселенную нельзя); без
   фильтра список показывает их с честными гэпами.
2. **entity_id на snapshot-записи:** панельная entity-вселенная доказуемо живёт в
   context чекпоинта (PGV-04), snapshot-запись entity не дублирует; AC14 покрыт
   trajectory-контекстом + universe-фильтрами списков.
3. **schema/calculation version:** текущие captures не самоназваны —
   `legacy_unknown` для всей существующей истории; контракт reader'а читает
   `passport_schema_version`/`calculation_version` из payload, когда будущие captures
   начнут их нести (без изменения reader'а).
4. **rs-запись без stage:** rs-факт не несёт stage (он в артефакте) — stage записи без
   контента = None; сортировка/фильтры учитывают это явно.
5. **Живой PostgreSQL не задействован** (Memory-сторы; паритеты Memory/Postgres чтения
   — наследие PGV-02/04, дублирование зеркал не потребовалось: reader ходит через
   registry-ABC). docker/Render не проверялись (дифф не трогает runtime-инфраструктуру).
6. **Pre-existing наблюдение** (вне скоупа, класс PGV-04): первый upload-запрос
   TestClient пишет receipt `data_version:upload "write denied: anonymous"` — субъект
   резолвится до установки cookie.

## 6. Уроки сессии

1. **Baseline-гейт паспорта** запрещает фиксацию идентичных снимков — TDD-последовательности
   обязаны мутировать ряд между capture (прецедент PGV-04; повторение ошибки стоит
   одного RED-прогона).
2. **Порядок reset-фикстур важен для list-оракулов**: rs-реестр — отдельный singleton;
   без `reset_snapshot_registry_for_testing()` list-тесты ловят межтестовое состояние
   (проявляется только в полном прогоне, не в изоляции).
3. **Два адреса одного факта**: reused-подтверждение честно адресуется и физическим
   этапом (exit), и путём подтверждения (modeling_entry) — это алиасинг записи, а не
   её копия; оракул AC11 пинует отсутствие НОВОГО rs-ref/артефакта, а не второй ключ.
4. **Субъект пайплайн-тестов** — субъект cookie-сессии КЛИЕНТА (run создаётся
   приложением с owner-биндингом этой сессии), не сидированной константы; access-контур
   reader'а сделал эту тонкость фейлящей, а не тихой.
