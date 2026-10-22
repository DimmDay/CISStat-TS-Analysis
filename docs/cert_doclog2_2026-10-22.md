# Акт независимой сертификации DOCLOG-2 — снимок и сборщик

*Дата: 2026-10-22. Аудируемая поставка: коммит `288fdde` «Task ID: DOCLOG-2
(2026-10-22) — Snapshot and collector: ReportSnapshot/cutoff, claim refs,
adapters D01–D09, no recalculations» на базе `main@78769bd` (DOCLOG-0 +
DOCLOG-0-CERT + DOCLOG-1). Дерево сертификации: fa8c949 (HEAD main);
`git diff 288fdde fa8c949 -- app/ apps/ tests/ rules/ src/ packages/` = 0
строк — атрибуция переносится. Сертификатор: независимый контур на СВОИХ
данных (`scripts/doclog2cert/`, корпус RUN-D2C*/d2cert-*, дизъюнктен
repo-корпусу RUN-D2A*/d2-seed-* и корпусам D0C*/D1C*). Режим «без
манифеста sha256» (указание тимлида), целостность дерева — git + md5-паспорта
файлов мутационной кампании. Продуктовый код и тесты репозитория аудитом
НЕ менялись.*

## Вердикт: **НЕ СЕРТИФИЦИРОВАНО** (блокирующий продуктовый дефект F-D2C1; все прочие контуры поставки — PASSED)

---

## 1. Предмет и граница аудита

Поставка DOCLOG-2 (§19 спеки `spec_documentation_logging.md`): «ReportSnapshot/
cutoff, claim refs, adapters D01–D09, отсутствие пересчётов»; критерий
завершения — «concurrent mutation не смешивает версии, current/stale/unknown
и gaps честны». Состав поставки (git show --stat 288fdde):

| Файл | Объём | Статус |
|---|---|---|
| `apps/api/report_snapshot.py` | 879 строк | НОВЫЙ |
| `apps/api/snapshot_builder.py` | 1055 строк | НОВЫЙ |
| `apps/api/migrations/0008_doclog2_snapshots.sql` | 60 строк | НОВЫЙ |
| `docs/doclog2_report_snapshot.md` | 264 строки | НОВЫЙ |
| `tests/api/test_doclog2_snapshots.py` | 1579 строк | НОВЫЙ |
| `apps/api/research_runs.py` | +64/−1 | ОБНОВЛЁН (0008) |
| `apps/api/storage_diagnostics.py` | +28 | ОБНОВЛЁН (health) |

Границы поставки честны: новых HTTP-маршрутов нет (паритет ADR-1 DOCLOG-1),
approvals/renditions/queue — DOCLOG-4/5/6.

## 2. Сверка заявлений с кодовой базой

Все ключевые заявления worklog/контрактного документа подтверждены чтением
кода: контракт `doclog.report_snapshot/1` (to_dict без registry-полей —
канонические байты без самоссылки); snapshot_id `rs-<hex32>`; SourceCutoff
(last_sequence = max известных sequence, event_count отдельно, manifest
только для legacy, честный ноль пустого корпуса); validity-матрица
current/stale/unknown (оба метаданных отсутствуют → unknown); адаптеры
D01–D09 только на durable-фактах (сессия не открывается — AC05);
двойное чтение + сверка mirror-key(context/revision/digest/target) и
stability-key cutoff; идемпотентность (UNIQUE(run_id, idempotency_key),
auto-ключ с cutoff, конфликт тел → 409-семантика); pins с причиной
`snapshot:{id}` через механизм DOCLOG-1; approval=null; knowledge_version =
sha256 registry_data.json; health-блок snapshots (peek без провокации).
Численности сходятся: 9 видов документов, 31 колонка SELECT/INSERT,
миграция 45 statements / 8 файлов, FastAPI 183 маршрута (без изменений).

**НЕ подтверждено (блокер, см. §4): работоспособность Postgres-ветки чтения
реестра снимков.**

## 3. Оракулы на СВОИХ данных — 79 оракулов (scripts/doclog2cert/)

Юнит-контур (70): контракт и каталок D01–D09 по СПЕКЕ (не по docs задачи);
snapshot_id/validity-границы; resolve_kinds (алиасы/порядок/дедуп/ошибки);
knowledge_version (совпадение с ручным sha256; честный None при отсутствии
файла); cutoff (canonical/legacy/частичный-sequence/bool-последовательность/
пустой/stability-key); validity-матрица всех углов (включая rev-без-ctx и
dict-носителя); Memory-реестр (копии R1, идемпотентность, scope, сортировка,
probe); **Postgres-зеркало** (fake-psycopg раундтрип по прецеденту
fakeredis: INSERT-параметры → строка SELECT-порядка → `_record_from_row`,
плюс статическая сверка 31 колонки INSERT≡SELECT≡%s); сборщик (авторизация
7 исходов, uniform-отказ build/read, creator-continuity, согласованное
чтение с шпионами-инъекциями event/revision/metadata, «ничего не пишется»,
адаптеры D01–D09 на своём корпусе фактов, bool-ловушка D08, панельная
изоляция R4, data_ref только-current + перенос digest, идемпотентность
AC09, pins артефактов/чекпоинтов с причиной, целостность чтения слоя 1
(ArtifactIntegrityError) и слоя 2 (SnapshotIntegrityError по подмене
payload_sha256 реестра), tripwire AC05 «сборка/чтение/список не трогают
науку», иммутабельность старых заморозок). API-контур (9): owner-binding
через реальный POST /v1/session/demo, uniform-404 run-маршрутов не сломан,
/health и /health/ops snapshots-блок (facts-only, без путей/DSN — T6/T10),
science-state трипваер на живом HTTP-контуре.

**GREEN ×2: 76/76 PASS** (кроме трёх оракулов Postgres-зеркала — см. §4;
стабильность повторным прогоном, 4.97s/4.87s). Протоколы:
`protocols/oracle_green_run1.txt`, `oracle_green_run2.txt`.

## 4. Блокирующий продуктовый дефект F-D2C1

**`PostgresSnapshotRegistry._record_from_row` передаёт в конструктор
`ReportSnapshot` несуществующее поле `created_at` → `TypeError` на КАЖДОМ
вызове.** У дата-класса есть только `captured_at`; поле `created_at`
существует лишь как колонка БД (row[30]) и в `_SELECT_COLUMNS`.

Исполнимо доказано тремя оракулами Postgres-зеркала (RED на 288fdde):
- `test_register_then_get_roundtrip` — чтение снимка по snapshot_id;
- `test_find_idempotent_returns_existing_with_same_fingerprint` — поиск по
  идемпотентному ключу;
- `test_conflict_replay_path_raises_409_semantics` — конфликт-перечитывание
  register_snapshot.

Плюс прямой вызов: `TypeError: ReportSnapshot.__init__() got an unexpected
keyword argument 'created_at'`.

Поражаемая поверхность (всё, что читает строки БД реестра снимков):
`get_snapshot_record` (чтение снимка — T15-контур), `find_idempotent`
(идемпотентный replay §10.3/AC09), `list_records` (листинг), конфликт-ветка
`register_snapshot` (сверка fingerprint при ON CONFLICT). Первая сборка
снимка в Postgres-режиме работает (INSERT + executemany не читают строки),
но любое ПОВТОРНОЕ обращение — чтение, replay, листинг — падает TypeError.

**Почему не поймано repo-корпусом**: `tests/api/test_doclog2_snapshots.py`
покрывает только Memory-backend (живой PostgreSQL — документированная граница
среды); Postgres-ветка не имеет контракт-зеркала (в отличие от Redis-путей,
где прецедент fakeredis-параметризации закреплён). Индексация row[0..30]
корректна — дефект локализован одним kwarg.

**Класс дефекта**: идентичен блокирующему дефекту `fit_panel_var:806`
(PANEL-MODELS-3b-CERT: «НАЙДЕН блокирующий продуктовый дефект. Вердикт: НЕ
СЕРТИФИЦИРОВАНО») — runtime-недееспособность durable-ветки при зелёном
Memory-корпусе. Критерий §19 «результаты доступны после TTL-сессии» в
durable-режиме (production Render, storage-mode required — AUDIT-6C) не
выполняется: чтение сохранённого снимка невозможно.

### 4.1. План устранения (для задачи DOCLOG-2-FIX)

1. Минимальный фикс: исключить `created_at=` из конструирования
   `ReportSnapshot` в `_record_from_row` (registry-метаданным достаточно
   `captured_at` из байтов снимка; альтернатива — колонку row[30]
   транслировать в `captured_at`-fallback). Однострочная правка.
2. Перенести PG-зеркальные оракулы сертификатора в repo-сюиту (fake-psycopg
   раундтрип + статическая сверка 31 колонки) — гвард класса F-D2C1.
3. Регресс: repo-сюита + полный pytest дельта-0 + пересертификация Postgres-
   ветки (при живом PG — паттерн AUDIT-6A, при следующем durable-срезе).

## 5. RED на родителе 78769bd (git worktree)

- Статические факты: **15/15 RED** (`red_repro.py` →
  `protocols/red_static_facts.json`): report_snapshot.py/snapshot_builder.py/
  миграция 0008/repo-тест/контрактный документ отсутствуют;
  MIGRATION_STATEMENTS_0008, каталог MIGRATION_FILES и конкатенация — без
  0008; COMPONENT_SNAPSHOTS/build_snapshots_health/snapshots-блок health
  отсутствуют; main.py/research_runs.py не знают report_snapshot; каталог
  миграций родителя ровно 0001–0007.
- Оракульный корпус на родителе: **77/77 ERROR** (ImportError отсутствующего
  контура — коллекция честно красная). Протокол:
  `protocols/red_oracle_corpus.txt`.

## 6. Мутационная кампания — СВОИ мутанты, двухканальная схема

28 боевых мутантов + 3 no-op-контроля на 4 целях (report_snapshot.py 16,
snapshot_builder.py 10, storage_diagnostics.py 1, research_runs.py 1);
точечные байтовые замены с контролем ровно 1 вхождения; восстановление из
памяти с md5-паспортом. Каналы: REPO = tests/api/test_doclog2_snapshots.py
(68, корпус исполнителя); ORACLE = корпус сертификатора (76 GREEN-оракулов;
3 F-D2C1-RED исключены из канала — они красны на любом мутанте из-за
блокера, что честно задокументировано).

**Итог: 28/28 KILLED (20 DUAL-KILLED + 8 ORACLE-ONLY), 0 SURVIVED,
контроли 3/3 ALIVE, RESTORE-FAIL 0, дерево восстановлено байт-в-байт
(md5-паспорта до/после идентичны, git diff пуст).** Протокол:
`protocols/mutations_protocol.json`.

ORACLE-ONLY класс (вклад независимого корпуса; рекомендация переноса пинов
в repo-сюиты): M03 (дедупе resolve_kinds), M08 (last_sequence=max на
неплотных sequence), M13 (глубокие копии sections в copy()), M14
(fingerprint-конфликт на уровне Memory-реестра — repo-тест проходит через
сервис, который проверяет тело раньше реестра), M15 (копии при get), M16
(сортировка list_records), M25 (payload_sha256-гейт слоя 2), M26
(bool-горизонт D08). Зона Postgres-внутренностей (_record_from_row/SQL)
на этом дереве валидируется статическим оракулом 31-колонки; поведенческие
мутанты SQL-пути — после фикса F-D2C1 (честная граница кампании).

## 7. Полный регресс и сборка

- Цель (fa8c949 ≡ 288fdde по продуктовым файлам): **4471 passed / 31 failed /
  66 skipped** (478s). Родитель 78769bd (worktree): **4403 passed / 31 failed /
  66 skipped** (481s).
- **Дельта-0 доказана побайтно**: множества 31 FAILED-ID
  (`regress_failed_ids_target.txt` / `_parent.txt`) ИДЕНТИЧНЫ (diff пуст).
  Прирост passed +68 = repo-сюита исполнителя (test_doclog2_snapshots.py).
- Классы средовых 31: 14 × MNS-SPEC-PATH (перемещение спек), 7 ×
  progress_audit_5b (psycopg DSN песочницы), 5 × neural-интеграционные пути,
  1 × deepar, 4 × прочие средовые (candidates/contract/panel/workflow) —
  предсуществующие, ноль содержательных падений.
- Сборка: импорт всех затронутых модулей (8/8); FastAPI-приложение —
  **183 маршрута** (новых HTTP-маршрутов нет — паритет заявлению); каталог
  миграций **45 statements / 8 файлов**; DOCUMENT_KINDS = 9.

## 8. Находки

- **N1 = F-D2C1 (БЛОКИРУЮЩАЯ)** — см. §4.
- **N2 (неблокирующая)**: legacy `event_id_manifest` не персистится в
  metadata-строке Postgres (колонки нет; `_record_from_row` возвращает
  manifest=None при ordering_quality=legacy). Полный cutoff с manifest
  живёт в канонических байтах снимка (чтение через `_load_content`
  полное), но metadata-путь (find_idempotent в Postgres-режиме) отдаёт
  урезанный cutoff — расхождение Memory/Postgres metadata-представления.
  Кандидат: колонка manifest в миграции 0008 либо явная фиксация границы
  «metadata ≠ content» в контрактном документе.
- **N3 (неблокирующая)**: `SnapshotService.dependency_refs` не авторизуется
  (docstring: «для аудита; авторизация на уровне снимка/маршрута DOCLOG-4»).
  Ref-строки (kind:id) раскрываются без проверки субъекта. Пока маршрутов
  нет — поверхности нет; зафиксировать в постановке DOCLOG-4 обязательным
  гейтом (дух T15: знание snapshot_id — не право).
- **N4 (неблокирующая)**: `_load_content` — валидный JSON, не декодируемый в
  контракт (нет обязательных полей), даёт TypeError вместо
  SnapshotIntegrityError (классификация ошибки). Во всех достижимых случаях
  с непустым payload_sha256 первым срабатывает sha256-гейт; класс
  проявляется только на legacy-записях с пустым паспортом целостности.
- **N5 (положительное)**: Memory-контур поставки согласован и честен:
  двойное чтение AC02 с полным mirror/stability-key (включая revision —
  покрыто моим оракулом инъекции ревизии), AC05-трипваеры чистые,
  идемпотентность §10.3 точная (auto-ключ с cutoff рождает новую
  заморозку), pins с причиной через механизм DOCLOG-1, целостность —
  двумя слоями (store content-key + registry payload_sha256).
- **N6 (рекомендация)**: перенести ORACLE-ONLY пины (8) в repo-сюиты.

## 9. Честные границы сертификации

Живой PostgreSQL-прогон миграции 0008 и Postgres-реестра — вне среды
(паттерн AUDIT-6A: при следующем durable-срезе); Postgres-ветка проверена
контракт-зеркалом (fake-psycopg) и статической сверкой DDL/колонок.
Поведенческие мутанты SQL-внутренностей — после устранения F-D2C1.
HTTP-выдача/renditions/approvals — вне границы поставки (DOCLOG-4/5/6).

## 10. Итог

Контракт, адаптеры D01–D09, согласованное чтение, идемпотентность, pins,
целостность и отсутствие пересчётов в Memory-режиме подтверждены оракулами
на СВОИХ данных, мутационной кампанией (28/28, 0 выживших) и полным
регрессом с дельтой-0. **Вердикт: НЕ СЕРТИФИЦИРОВАНО** — блокирующий
дефект F-D2C1 (TypeError на всех путях чтения Postgres-реестра снимков)
делает недействительным критерий §19 в durable-режиме. Рекомендация:
задача DOCLOG-2-FIX по плану §4.1 с последующей пересертификацией
(объём: PG-зеркальные оракулы + полный регресс + кампания SQL-зоны).
