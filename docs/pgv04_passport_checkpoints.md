# PGV-04 — Durable checkpoint/backfill (документ поставки)

**Задача:** spec_passport_graphics_visual.md §13, строка PGV-04 (зависимость PGV-02).
**Дата:** 2026-10-29. **База:** main@f71936f (PGV-03-FIX), рабочее дерево чистое.
**Критерий готовности (§13):** «Reused handoff хранит confirmed_at/trajectory отдельно, retry без capture».

## 1. Постановка и граница

Каждый EDA handoff (`modeling_entry` и панельный `panel_entry`) фиксируется durable-артефактом
`pgv.passport_checkpoint/1`, включая reused snapshot. Субстрат PGV-02 (валидатор
`validate_passport_checkpoint`, `register_passport_checkpoint`, `get_passport_checkpoint`) не
менялся ни байтом — поставка замыкает capture-сторону и backfill: до неё чекпоинты существовали
только в session-состоянии и терялись вместе с сессией, траектория подтверждений была недоступна
durable-чтению (AC09/AC10-субстрат), а reused handoff не имел durable представления (AC11).

Runtime-границы: renderer/jobs/UI — PGV-07/08/09/15; PassportHistoryReader — PGV-05; сравнение —
PGV-06; P01/P02 builders — PGV-13. Наука не пересчитывается ни одним путём поставки (AC06).

## 2. Ключевые решения

1. **rs-записи снимков паспортов.** Чекпоинт ссылается на снимки через rs-* (контракт PGV-02),
   поэтому поставка гарантирует существование доказуемых durable-записей: одна rs-запись
   ReportSnapshot-реестра на session-снимок (`idempotency_key = pgv-passport:{snapshot_id}`,
   «старые snapshots не переписываются»). Запись — адресуемый ФАКТ (kinds=["D02"], sections=[],
   reproducibility=limited с причиной `passport_snapshot_record`), не документ; полное содержимое
   паспорта — в паспортном артефакте (kind="passport", промоушен notify_passport_captured —
   прецедент C03), он прицепляется зависимостью с pin-причиной `passport_record:{rs-id}`. Без
   артефакта (legacy-сессии до C03) — честный content-гэп, фабкация запрещена (R03).

2. **Синхронная заморозка (producer_capture).** `notify_passport_checkpoint_confirmed`
   вызывается из точек capture (POST /dataset/passport/modeling_entry, POST
   /panel/passport/confirm) после фиксации session-фактуры. Отсутствие обязательных точек
   траектории (validation/exit для modeling_entry) — `PromotionUnavailable` → info-журнал БЕЗ
   durable-receipt: штатный поток «start → modeling_entry» легитимен и не является сбоем
   промоушена. Прочие сбои — durable-receipt, ответ эндпоинта не ломается.
   Честная семантика частичной rs-записи (PGV-04-FIX F-P4C3): rs-записи вовлечённых снимков
   создаются ДО проверки полноты траектории и при честном недоборе ОСТАЮТСЯ в реестре — это
   адресуемые факты существующих session-снимков (не фабкация; идемпотентность §8 не нарушена,
   повторный вызов/добор переиспользуют их без переписывания); сам durable-чекпоинт при
   недоборе не регистрируется.

3. **Backfill (legacy_import) — «retry без capture».** Sweep-точка моделирования
   (`notify_modeling_artifacts_updated`) добирает чекпоинты без durable представления ТОЛЬКО из
   доказуемых session-записей обеих вселенных: single — `passport_checkpoints`, panel —
   `panel_entry_checkpoints` (PGV-04-FIX F-P4C1: ранее читалось несуществующее поле
   `panel_passport_checkpoints` — панельные чекпоинты молчаливо не добирались, критерий §13
   для panel_entry не enforced). Уже замороженные (любой provenance) пропускаются по producer_key
   без чтения payload — конфликтов контента не возникает, provenance первого успеха сохраняется.
   Изоляция per-entry (PGV-04-FIX F-P4C2, паритет sweep-цикла notify_modeling_artifacts_updated):
   честный недобор (`PromotionUnavailable`) — info-гэп со счётчиком skipped БЕЗ receipt; прочий
   сбой ОДНОЙ записи (битая легаси-фактура → `ArtifactPayloadInvalid`, конфликт, KeyError) —
   durable-receipt класса сбоя промоушена + счётчик failed (ключ присутствует только при сбоях),
   добор остальных ПРОДОЛЖАЕТСЯ — доставка восстановима, следующий sweep не упирается в
   блокирующий сбой партии. Честный недобор точек траектории ПЕРМАНЕНТЕН для конкретного
   чекпоинта (снимки позже confirmed_at в его траекторию не попадают — фильтр «на момент
   подтверждения»); retry покрывает сбои синхронной заморозки (transient) и legacy-чекпоинты
   с полной траекторией.

4. **Траектория «на момент подтверждения».** Снимки этапов фильтруются по
   `captured_at <= checkpoint.confirmed_at` (история append-only — фильтр доказуем); более поздние
   снимки в траекторию не попадают (AC10-дух: комплект будет использовать выбранную траекторию,
   не latest каждой стадии).

5. **Честность полей.** `confirmed_at` — из session-записи (время промоушена не подставляется,
   AC12); flags.created/reused — по created_snapshot; unchanged НЕ заявляется (False): session-
   контур не производит доказуемо отличный от reused «unchanged»-случай (409 на повторное
   подтверждение того же fingerprint), поле остаётся контрактом валидатора для будущих источников;
   context — текущий (run, context_id, data_revision) на момент заморозки: для синхронной
   заморозки это контекст подтверждения (один request), для backfill — контекст импорта, что
   честно маркируется provenance=legacy_import; панельный entity_id = entity_column (идентификатор
   entity-вселенной, AC14); previous_snapshot_ref = None при session-конвенции «previous = сам
   снимок» (панельный confirm) — самоссылка не записывается (запрет F-P2C4).

6. **checkpoint_id durable = `pck-` + session checkpoint_id.** Детерминированная деривация:
   идемпотентность §8 сохраняется между capture/backfill, формат pck-* по валидатору PGV-02.

7. **Попутный честный фикс (reused handoff).** В capture modeling_entry промоушен паспорта
   переводится на `stage=snapshot.stage` (фактический stage снимка): при reused handoff
   идемпотентно находится существующий артефакт `passport:{snapshot_id}` вместо честного отказа
   «снимок modeling_entry отсутствует» — устранён receipt-шум легитимного состояния (класс
   «промоушен недостижимого источника»).

## 3. Точки изменения

| Файл | Статус | Содержание |
|---|---|---|
| `apps/api/passport_checkpoints.py` | НОВЫЙ | Единая реализация: `ensure_passport_snapshot_record`, `freeze_passport_checkpoint`, `build_passport_checkpoint_payload`, `backfill_passport_checkpoints`, `durable_checkpoint_id` |
| `apps/api/promotion_integration.py` | изменён | `notify_passport_checkpoint_confirmed` (синхронная заморозка, honest-skip без receipt); sweep-точка `notify_modeling_artifacts_updated` добирает чекпоинты (`counts["passport_checkpoint"]`) |
| `apps/api/routers/session.py` | изменён | capture modeling_entry: вызов заморозки + честный фикс stage=snapshot.stage |
| `apps/api/routers/modeling_session.py` | изменён | panel build: промоушен панельного паспортного артефакта (C03-прецедент); panel confirm: заморозка чекпоинта |
| `tests/api/test_pgv04_passport_checkpoints.py` | НОВЫЙ | Корпус 24 теста (см. §4) |
| `docs/pgv04_passport_checkpoints.md` | НОВЫЙ | Этот документ |
| `scripts/pgv04/check_documents.py` | НОВЫЙ | Doc-contract гвард (документация == поставка) |
| `worklog/worklog11.md` | изменён | Запись задачи |

Миграции не добавляются (артефакты — в существующих таблицах artifact/snapshot реестров); пины
16 файлов / маршруты 221 / kinds 10 — неизменны. Runtime science не задет.

## 4. TDD-протокол и верификация

- **RED:** корпус 25 тестов на базе f71936f — 21 failed / 1 passed (честный import-RED
  `ModuleNotFoundError: apps.api.passport_checkpoints` + поведенческие; 1 passed — живость
  honest-skip, который обязан остаться зелёным и после GREEN).
- **GREEN:** 24 passed (итоговый корпус после уточнения трёх оракулов — см. уроки).
- **Адресный регресс:** pgv02 (51), pgv03, dataset_passport, passport_session_state,
  deepar_panel_pivot, doclog_recheck_fix — зелёные; modeling_workflow 4F — воспроизведены на
  чистой базе f71936f (средовой класс psycopg отсутствует в песочнице).
- **Дельта-0 полного tests/api** (одна среда, кэш pytest отключён — урок DOCLOG-8): HEAD
  **67F/2999P/44S** vs база f71936f **67F/2975P/44S** — FAILED-ID байт-идентичны 67/67
  (diff пуст), +24 passed = ровно корпус; известный ±1 флейк
  `test_doclog9_profiles::test_pdfa_render_markers_and_determinism` воспроизведён изолированно
  (граница секунды, F-D9C1 — средовой, не поставка).
- **Сборка:** py_compile 5 файлов OK; `import apps.api.main` OK — **221 маршрут** (паритет),
  ARTIFACT_KINDS 10, миграции 16 (не тронуты).

## 5. Честные границы

1. Контекст backfilled (legacy_import) чекпоинтов — контекст ИМПОРТА (момент заморозки), не
   момент подтверждения: контекст подтверждения legacy-чекпоинта из session-записей недоказуем;
   маркировка provenance честна, mislabeling исключён документированием семантики.
2. rs-записи без паспортного артефакта (legacy-сессии до C03) несут факт снимка без content-
   зависимости; content-гэп закрывается PassportHistoryReader (PGV-05) по своим правилам.
3. unchanged-флаг не производится ни одним путём поставки (недоказуем из session-записей) —
   поле остаётся валидным контрактом для будущих источников.
4. Панельный fixture повторяет продовое состояние (dataset/run/владелец после upload); панельный
   поток без upload — 422 контракта `_panel_session_or_422`, не сценарий поставки.
5. Живой PostgreSQL не задействован (Memory-сторы; PG-зеркала — пины PGV-02, не дублировались);
   docker/Render не проверялись (дифф не трогает runtime-инфраструктуру).
6. Pre-existing наблюдение (вне скоупа): первый upload-запрос TestClient пишет receipt
   `data_version:upload "write denied: anonymous"` — субъект резолвится до установки cookie;
   класс известен по C03-поставке.

## 6. Уроки сессии

1. **Штатный поток «start → modeling_entry» легитимен** — отсутствие validation/exit не сбой:
   receipt'ом security-audit не замусоривается (info-журнал + счётчик honest-skip).
2. **Честный недобор перманентен для конкретного чекпоинта**: фильтр траектории «на момент
   подтверждения» не позволяет «дообогатить» его поздними снимками — retry покрывает сбои
   заморозки и legacy-импорт, не фабрикацию траектории.
3. **Тестовый MultiEdit-цикл**: частичное применение правок оракула ловится только прогоном —
   RED-корпус перечитывался после каждой правки (целостность оракулов — ответственность
   исполнителя, прецедент PGV-02 «дефекты оракула»).
4. **Reuse-поиск снимка** находит ПОСЛЕДНИЙ совпадающий fingerprint (exit-снимок при возврате
   ряда) — оракул AC11 пинует «новая физическая копия не создана», а не конкретный snapshot_id.

## 7. PGV-04-FIX (2026-10-29): сертификационные находки F-P4C1–F-P4C3

Исправление находок акта сертификации `docs/cert_pgv04_2026-10-29.md` (база main@ad597cb,
PGV-05 не затронут). Продуктовый дифф — только `apps/api/passport_checkpoints.py`;
замороженные инструменты сертификации (Class A/Class B корпуса, акт) не менялись ни байтом.

1. **F-P4C1 (средняя; класс F-P2C2 «контракт не enforced» + молчаливый пропуск).**
   `backfill_passport_checkpoints` читал несуществующее поле session `panel_passport_checkpoints`
   (реальное — `panel_entry_checkpoints`): панельные чекпоинты никогда не добирались sweep-каналом
   и не попадали ни в frozen, ни в skipped — критерий §13 «retry без capture» для panel_entry не
   enforced. Фикс: чтение реального поля; панельный чекпоинт добирается как legacy_import с
   entity-контекстом (AC14) и stage_refs.panel (rs-*). Мёртвый сломанный хелпер repo-корпуса
   `_seed_panel_checkpoints` (N-P4C3 — вызвал бы ValueError) переведён на реальный panel-API
   контура и оживлён тестом `test_backfill_covers_panel_checkpoints` (задуманный и не написанный
   панельный backfill-тест); мутант акта M01 (drop panel-списка) после фикса убивается
   repo-каналом (верификация scripts/pgv04fix/verify_mutants.py).

2. **F-P4C2 (средняя; нарушение per-entry устойчивости sweep-канала).** Backfill ловил только
   `PromotionUnavailable`: прочий сбой одной записи (`ArtifactPayloadInvalid` при битой
   легаси-фактуре — например утраченные panel_columns; `ArtifactConflictError`; KeyError битой
   session-записи) прерывал ВЕСЬ добор — остальные легитимные чекпоинты не доставлялись, каждый
   следующий sweep получал тот же сбой (доставка не восстановима). Фикс: per-entry try/except
   (паритет sweep-цикла notify_modeling_artifacts_updated) — сбойная запись получает
   durable-receipt `artifact_promotion_failed` (единая точка receipt-семантики
   promotion_integration, operation=backfill_passport_checkpoint, producer_key=pgv.checkpoint:pck-*)
   + счётчик failed (ключ присутствует только при сбоях — существующие оракулы точных словарей
   счётчиков не затронуты); добор остальных продолжается; `PromotionUnavailable` остаётся честным
   info-гэпом (skipped) без receipt.

3. **F-P4C3 (низкая; документная честность, класс F-P3C2-подобный).** Докстринг
   `freeze_passport_checkpoint` утверждал при честном недоборе «вызывающий гарантированно ничего
   не записал» — фактически rs-записи вовлечённых снимков создаются ДО отказа на недостающей
   точке траектории. Фикс документный (поведение не менялось — rs-записи честные адресуемые
   факты): докстринг функции, докстринг модуля и этот документ описывают частичную rs-запись
   честно (создаются до проверки полноты, при недоборе остаются; идемпотентность §8 не нарушена;
   сам чекпоинт при недоборе не регистрируется).

TDD: Class B акта (tests/api/test_pgv04_cert_findings.py) 7 RED на родителе ad597cb → 8/8 GREEN
после фикса (B6-инвариант GREEN на обеих сторонах) без правки смысла оракулов; repo-корпус
расширен 24 → 25 (панельный backfill-тест), Class A 22 — без изменений, GREEN; doc-гвард
scripts/pgv04/check_documents.py — GREEN.
