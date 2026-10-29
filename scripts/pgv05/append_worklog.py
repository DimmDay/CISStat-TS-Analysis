"""Append PGV-05 entry to worklog/worklog11.md (house style: header +
one-line paragraphs)."""
from pathlib import Path

ENTRY = """
## Task ID: PGV-05 (2026-10-29) — PassportHistoryReader: чтение durable-истории паспортов из registry/ObjectStore (pgv.passport_history/1) без SessionStore/Redis/DataFrame; snapshot-записи §8 (полные groups/metrics AS-IS, schema/calculation version, target/date, fingerprint+source_hash с определёнными алгоритмами, captured/created, context/data_revision, data_ref); траектории «на выбранное подтверждение» (AC10), reused → исходный снимок (AC11), XOR-честность gaps (AC12), изоляция вселенных (AC14)

### Постановка и база

База: main@c4e90b8 (PGV-04; синхронизация git fetch + reset --hard, локальные изменения — только mode-биты 100644→100755, контента нет). Критерий §13: «Чтение без Redis/DataFrame, schema gaps/legacy_unknown честны». §8: reader читает registry/ObjectStore, а не SessionStore; snapshot включает полные groups/metrics, schema/calculation version, target/date/entity, snapshot_id, fingerprint/context/data_revision, captured/created time, data_ref; source_hash и fingerprint — разные поля с определением алгоритмов. Субстрат PGV-02/04 (rs-записи pgv-passport:*, passport-артефакты C03, чекпоинты pgv.passport_checkpoint/1) не менялся ни байтом — поставка замыкает ЕДИНУЮ read-only точку чтения истории для PGV-06/13/15.

### Проектирование → точки изменения

Точки изменения спеки «passport_documents/ObjectStore/refs» — читающие стороны: новый модуль apps/api/passport_history.py + использование уже сертифицированных API чтения реестров (get_snapshot_registry/get_artifact_registry/get_artifact_object_store); существующий runtime-код не тронут (нулевая поверхность регрессии: git diff — только новые файлы). Риски: (R1) утечка SessionStore-зависимости — AST-гейт на импорты session_store/pandas/redis в тестах; (R2) порча байтов — content-addressed ключ (T8) + сверка payload_sha256 + JSON-разбор + сверка payload.snapshot_id с session_snapshot_id, отказ → content_status=corrupt без выдачи контента; (R3) фабкация при отсутствии — XOR-конвенция «значение либо явная причина» (legacy_unknown/integrity_failure, прецедент print_schema digest-XOR-reason); (R4) доступ — authorize_run_access(action="read"), uniform-отказ PassportHistoryAccessDenied, глобальные get_snapshot_record/get_artifact проверяют run-принадлежность; (R5) смешение вселенных — universe из stage, фильтры списков, недоказуемый stage под фильтр не попадает.

### Реализация (файлы)

НОВЫЕ: apps/api/passport_history.py — PASSPORT_HISTORY_SCHEMA_VERSION=pgv.passport_history/1; snapshot-запись (snapshot_ref/session_snapshot_id — обратная деривация из idempotency-ключа, artifact_id, stage/universe, passport AS-IS, content_status+content_gap_reason, target/date, fingerprint, source_hash+source_hash_algorithm=sha256(canonical_json), context_id/data_revision, data_ref, captured_at(rs)/created_at(артефакт)); резолюция rs→артефакт по pin-зависимости artifact:{id} (причина passport_record:*) с fallback по producer-ключу passport:{sid} (порядок промоушена C03/PGV-04); read_passport_snapshot / read_passport_trajectory (замороженные stage_refs + подтверждённый снимок под ключом этапа + previous, gaps с at/reason/detail) / list_passport_checkpoints (пикер: confirmed_at, flags, provenance, context, fingerprint best-effort, integrity_status) / list_passport_snapshots (сортировка captured_at, universe-фильтр). НОВЫЕ: tests/api/test_pgv05_passport_history.py (18 тестов, 6 классов), docs/pgv05_passport_history.md, scripts/pgv05/ (red/green протоколы, check_reader.py smoke, debug_traj.py). Обновлён: worklog/worklog11.md.

### TDD RED→GREEN и уроки

RED: 18/18 FAILED — ModuleNotFoundError apps.api.passport_history (scripts/pgv05/red_protocol.txt). GREEN: 18 passed после двух честных доуточнений оракулов: (1) baseline-гейт паспорта запрещает фиксацию идентичных снимков — последовательности capture обязаны мутировать ряд (прецедент PGV-04); (2) rs-реестр — отдельный singleton: reset_snapshot_registry_for_testing добавлен в фикстуру, иначе list-оракулы ловят межтестовое состояние (проявляется только в полном прогоне); (3) в reader'е уточнено алиасирование reused-подтверждения под ключ этапа пути (modeling_entry → ИСХОДНЫЙ rs exit-снимка: одна запись, два адреса, без четвёртой копии); (4) субъект пайплайн-тестов — субъект cookie-сессии клиента (run создаётся приложением с owner-биндингом), не сидированной константы.

### Верификация

Адресный регресс: pgv02+pgv03+pgv04 (164), dataset_passport+passport_session_state (40), deepar_panel_pivot+doclog_recheck_fix (58/1 skip) — 262 passed, 0 failed (scripts/pgv05/green_protocol.txt). Дельта-0 полного tests/api (одна среда, кэш pytest отключён): HEAD 67F/3017P/44S vs база c4e90b8 67F/2999P/44S — дельта ровно +18 passed (корпус поставки), FAILED-счёт 67=67, состав — известные средовые классы (psycopg/upload_db/forecasting_session/garch/egarch), паспортных падений нет. Сборка: py_compile OK; import apps.api.main OK — 221 маршрут (паритет), ARTIFACT_KINDS 10, миграции 16 (SQL-слой не тронут); smoke scripts/pgv05/check_reader.py: чтение после reset_session_store — 4 снимка с 15 группами, picker 1 чекпоинт/4 записи.

### Честные границы

(1) schema/calculation version текущих captures — legacy_unknown для всей существующей истории (payload паспорта не самоназван; контракт читает поля из payload, когда будущие captures начнут их нести — без изменения reader'а). (2) universe записи выводится из stage артефакта; у записей без артефакта (legacy до C03) stage недоказуем — universe=None, под universe-фильтр не попадают (приписать вселенную нельзя), без фильтра видны с честными гэпами. (3) entity_id панельной вселенной живёт доказуемо в context чекпоинта (PGV-04) — snapshot-запись entity не дублирует. (4) Живой PostgreSQL не задействован (Memory-сторы; reader ходит через registry-ABC — паритеты наследуются от PGV-02/04); docker/Render не проверялись (дифф не трогает runtime-инфраструктуру). (5) Pre-existing наблюдение (класс PGV-04): первый upload-запрос TestClient пишет receipt «data_version:upload write denied: anonymous» — субъект резолвится до установки cookie.

Deliverable: ZIP cisstat-pgv05-passport-history-reader.zip → открытый контейнер сессии (download/) и веб-приложение :3000 (страница поставки с кнопкой скачивания).
"""

worklog = Path("worklog/worklog11.md")
text = worklog.read_text(encoding="utf-8")
if text and not text.endswith("\n"):
    text += "\n"
worklog.write_text(text + ENTRY, encoding="utf-8")
print("appended, new length:", len(worklog.read_text(encoding="utf-8").splitlines()), "lines")
