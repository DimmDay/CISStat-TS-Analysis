# PGV-06 — Pure comparison resolver (документ поставки)

**Задача:** spec_passport_graphics_visual.md §13, строка PGV-06 (зависимость PGV-05).
**Дата:** 2026-10-29. **База:** main@4479321 (PGV-04-FIX), рабочее дерево чистое.
**Критерий готовности (§13):** «Прежняя семантика refs, cutoff/reuse/incompatible
contexts проверены».

## 1. Постановка и граница

§9 прямо фиксирует: «Общий pure comparison engine выделяется из session orchestration:
существующая `_compare_ts_props` через versioned adapter, без дублирования формул в
TypeScript. Вход — immutable refs. Frozen PassportComparisonSnapshot/1: ordered
refs/path, checkpoint metadata, numeric deltas/category/list/qualitative changes,
method/schema versions, gaps/context». До поставки сравнение паспортов существовало
только внутри session orchestration (`routers/session.py::compare_dataset_passports`
вызывал приватный движок `app/core/passport._compare_ts_props` напрямую); durable-путь
(сравнение из immutable refs без активной сессии/DataFrame, AC09-дух) отсутствовал.
Именно его требуют последующие задачи: PGV-13 (P02 builder «сравнение из refs, без
DataFrame»), PGV-14 (пагинация), PGV-15 (UI сравнения).

Runtime-границы: P02 documents/lifecycle — PGV-13; печатная композиция — PGV-07;
пагинация страниц/колонок — PGV-14; UI «Сравнить паспорта» — PGV-15. Резолвер —
ТОЛЬКО чистое сравнение: ни capture, ни промоушен, ни пересчёт науки (AC06-дух),
ни одной записи в реестры (проверяется тестом read-only).

## 2. Файлы поставки

| Файл | Статус | Содержание |
|---|---|---|
| `apps/api/passport_comparison.py` | **НОВЫЙ** | Резолвер `pgv.passport_comparison/1`: versioned adapter над существующим движком, попарное сравнение snapshot-записей PGV-05, trajectory/explicit-refs режимы, XOR-честность совместимости, confirmation-строка reuse, gaps/completeness |
| `apps/api/routers/session.py` | Изменён | Orchestration идёт через versioned adapter `compare_passports_via_engine` (2 строки: импорт + call-site); ответ эндпоинта байт-в-байт прежний |
| `tests/api/test_pgv06_passport_comparison.py` | **НОВЫЙ** | 32 теста (6 классов): границы модуля/adapter-parity, trajectory (refs/cutoff/reuse), несовместимые контексты, explicit refs, полнота/определения, панель/доступ/чистота |
| `docs/pgv06_passport_comparison.md` | **НОВЫЙ** | Этот документ |
| `scripts/pgv06/` | **НОВЫЙ** | red_protocol.txt, green_protocol.txt, regression_protocol.txt, smoke_protocol.txt, check_resolver.py (smoke) |
| `worklog/worklog11.md` | Обновлён | Запись PGV-06 |

Единственное изменение существующего кода — `routers/session.py`: удалён прямой импорт
приватного движка, добавлен импорт adapter'а (фактический вызов — та же функция
движка под теми же аргументами; формулы не тронуты). `app/core/passport.py` НЕ
изменён ни байтом — единственный источник формул сохранён.

## 3. Ключевые решения

1. **Versioned adapter (§9, без дублирования формул).** `compare_passports_via_engine`
   — единственная точка вызова движка: делегирует существующему
   `app.core.passport._compare_ts_props` AS-IS. Пин `COMPARISON_ENGINE =
   {"id": "app.core.passport._compare_ts_props", "version": "v1.0"}` фиксирует
   метод в каждом frozen snapshot (§9: method versions). Паритет-оракулы: adapter ==
   движок на реальных паспортах; попарный вывод эндпоинта == вывод adapter'а на тех
   же паспортах. Mutant-оракул: прямой импорт `_compare_ts_props` в orchestration
   убивается AST-гейтом.

2. **Контракт `pgv.passport_comparison/1` (frozen PassportComparisonSnapshot/1).**
   Поля: `schema_version`, `mode` (trajectory_checkpoint | explicit_refs), `run_id`,
   `ordered_refs`, `path`, `comparisons` (пары: from/to stage+ref+snapshot_id+
   captured_at, блок `comparison` — вывод движка AS-IS, `cross_context`),
   `confirmation` (confirmed_at/reused/unchanged/reused_ref/previous_ref),
   `checkpoint` (checkpoint_ref/artifact_id/stage/universe/confirmed_at/flags/
   provenance), `context`, `cross_context`, `aliases`, `method_versions`
   (engine + per-record passport_schema_version/calculation_version AS-IS),
   `definitions` (absolute/relative delta определения, zero_denominator_reason,
   delta_color ≠ значимость), `gaps`, `completeness` (complete|partial).
   Снапшот детерминирован: без собственного времени (только времена записей).

3. **Два режима, две семантики соседства (прежняя семантика проверена).**
   - *trajectory_checkpoint* (default, «резолвер использует trajectory checkpoint»):
     путь — замороженные `stage_refs` чекпоинта на момент подтверждения (cutoff:
     более поздние captures не подмешиваются — проверено мутант-тестом), порядок —
     ранг этапов (start → validation → exit → modeling_entry); отсутствующая точка —
     явный gap, пары строятся по доказанным соседним точкам (семантика
     session-пропуска missing validation); unchanged-подтверждение НЕ добавляет
     нулевую дублирующую колонку (§9/AC11), отдельная строка confirmation несёт
     confirmed_at и reused ref. Durable-деривация unchanged: reused И предыдущая
     ссылка отсутствует/равна (freeze не пишет previous при равенстве —
     session-семантика `previous_snapshot_id == snapshot_id`); reused с доказанным
     отличным previous — возврат к старому снимку: modeling_entry в пути как АЛИАС
     (один snapshot_ref, два адреса; to_ref совпадает с validation, AC11).
   - *explicit_refs* (произвольный выбор UI, «UI показывает IDs»): ordered refs КАК
     ЗАДАНО (включая обратный порядок); пары — только соседние разрешённые позиции
     заданной последовательности (молчаливый «мост» через дыру запрещён); повтор ref
     — алиас (`aliases[].path_position`) без нулевой пары; в каждой паре присутствуют
     from/to snapshot_id (IDs для UI).

4. **Несовместимость — только по доказуемому (AC13/AC14, XOR-честность).**
   Проверки пары: target_column, universe (panel vs single — смешение запрещено),
   entity (когда доказан), passport_schema_version (когда известен). None/legacy_unknown
   — НЕ значение: отказ на неизвестном не фабкуется. Cross-context (известные разные
   context_id) — отказ вне явного режима; в явном режиме — сравнение с маркировкой
   `cross_context=true` на паре и в снапшоте. Ошибка — `PassportComparisonIncompatible`
   с машиночитаемыми `reasons` (API-слой отображает как 409 comparison_incompatible,
   §11). Units: durable passport-записи сегодня units не записывают — ось не
   проверяема без фабкации, зафиксировано здесь (честный предел, не молчаливый пропуск).

5. **Gaps и completeness (§9: «Missing validation — gap, не ноль»).**
   Content-проблемы записей (missing_artifact/corrupt) — явные gaps
   (`content_missing`/`content_corrupt` с деталью из content_gap_reason); пары,
   затронутые дырой, не строятся; здоровые соседние пары строятся. Dangling refs
   чекпоинта — gaps из reader'а AS-IS. `completeness=complete` только при нулевых
   gaps; partial явно перечисляет пропуски.

6. **Определения метрик (AC13: zero denominator reason).** `definitions` описывают
   ФАКТИЧЕСКИЕ конвенции движка: `delta = v_new - v_old`; `delta_pct =
   (delta / abs(v_old)) * 100`; zero-denominator: при |v_old| ≤ 1e-10 относительное
   изменение не определено — движок подставляет 0.0 при |delta| < 1e-10, иначе 100.0;
   цвет delta не означает статистическую значимость. Определения верифицированы
   parity-оракулом (описывают, не переписывают).

## 4. TDD RED→GREEN

- **RED:** 32/32 FAILED — `FileNotFoundError: apps/api/passport_comparison.py`,
  session orchestration ещё импортирует движок напрямую
  (scripts/pgv06/red_protocol.txt).
- **GREEN:** 32 passed после трёх честных доуточнений оракулов:
  1. маршруты API — `/v1/internal/upload`, `/v1/session/dataset/passport/*`
     (не `/api/*`);
  2. subjects — `SubjectRef.from_session`, а не строковые псевдонимы;
  3. rs-записи создаются при подтверждении чекпоинта (PGV-04): корпусу с
     `list_passport_snapshots` нужен полный пайплайн до modeling_entry.
- В ходе GREEN уточнена durable-семантика reuse (см. §3.3) — оракулы приведены к
  ней БЕЗ ослабления: unchanged исключает дублирующую колонку, reused-алиас
  адресуется ключом этапа подтверждения.

## 5. Верификация

- **Адресный регресс:** pgv02+pgv03+pgv04+pgv05+dataset_passport+
  passport_session_state+pgv04cert (оракула+findings) — 254 passed, 0 failed.
- **Дельта-0 полного tests/api** (одна среда, кэш pytest отключён): база 4479321 —
  68F/3048P/44S (прогон 1) и 67F (прогон 2, список; одна неустойчивая средовая
  проба между прогонами — известные классы psycopg/upload_db/forecasting_session/
  garch/egarch); HEAD — 67F/3081P/44S. Список 67 FAILED идентичен base vs HEAD
  (diff пуст): дельта поставки = +32 passed (корпус PGV-06), 0 новых падений,
  0 изменённых падений.
- **Сборка:** py_compile OK; import apps.api.main OK — 221 маршрут (паритет;
  новых HTTP-маршрутов задача не добавляет — резолвер library-level по точкам
  изменения спеки); adapter parity OK.
- **Smoke** (scripts/pgv06/check_resolver.py): полный пайплайн → резолюция по
  чекпоинту (path 4 точки, 3 пары, complete) → паритет с session-эндпоинтом 3/3.

## 6. Ограничения и преемники

- Проверки совместимости применяются к доказуемым полям durable-записей; units и
  entity вне чекпоинт-контекста сегодня не записываются — оси честно непроверяемы
  (не фабкуются); при появлении полей в payload проверки подхватятся без изменения
  контракта.
- HTTP-экспозиция резолвера (409 comparison_incompatible на API-границе) —
  вместе с P02-эндпоинтами PGV-13; текущий session-эндпоинт сохраняет прежний
  контракт ответа.
- Пагинация колонок/этапов печатного сравнения — PGV-14; UI — PGV-15.
