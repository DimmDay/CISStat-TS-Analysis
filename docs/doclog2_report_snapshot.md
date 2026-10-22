# DOCLOG-2 — Снимок и сборщик (контрактный документ)

*Task DOCLOG-2, 2026-10-22. Спецификация-источник: `spec_documentation_logging.md`
(§6 «Что документировать на каждом этапе», §7 «Форматы», §8 «Логическая
архитектура», §9 «Модель идентичности», §10 «ReportSnapshot и согласованное
чтение», §19 строка DOCLOG-2 и §19.1, §20 AC01/AC02/AC03/AC05/AC09/AC13).
База: main@78769bd (DOCLOG-0 + DOCLOG-0-CERT + DOCLOG-1 включены). Поставка
следует AGENTS.md (TDD RED→GREEN→регресс, без commit/push).*

## 1. Постановка и граница задачи

DOCLOG-2 — третий срез эпика документирования/логирования (§19):
**«ReportSnapshot/cutoff, claim refs, adapters D01–D09, отсутствие
пересчётов»**. Критерий завершения (§19, та же строка): **concurrent
mutation не смешивает версии, current/stale/unknown и gaps честны**.
Вне границы (по §19): HTTP-выдача и UI документов (DOCLOG-4), форматы/
render worker (DOCLOG-5), approvals/publish/D10/D11/retention (DOCLOG-6),
telemetry/аудит (DOCLOG-3), мониторинг D12 (DOCLOG-8). Новых HTTP-маршрутов
поставка НЕ добавляет (паритет решения DOCLOG-1: §17 помечает маршруты
«предлагаемыми», очередь DOCLOG-4; авторизация встроена в сервис, поэтому
будущие маршруты не смогут её забыть).

Проблема (факты спеки): текущий отчёт (`app/core/run_report.py`, F03)
строится из живого зеркала сессии и не равен автономному архиву
результатов; watermark = размер canonical corpus (§10.2: его нельзя
приравнивать к позиции durable ledger); «наличия маршрута или зелёного
статуса недостаточно для утверждения о воспроизводимости» (§1 итог).
DOCLOG-2 создаёт замороженный ReportSnapshot: один атомарный снимок
фактов до cutoff + dependency manifest, из которого будущие рендеры
(§7: JSON/HTML/MD — P0) строят ВСЕ форматы без пересчёта науки (R06).

## 2. Что реализовано (карта изменений)

| Файл | Состав |
|---|---|
| `apps/api/report_snapshot.py` (НОВЫЙ) | Контракт `doclog.report_snapshot/1` (§10.1): `ReportSnapshot` (snapshot_id `rs-`+hex32, cutoff, template, knowledge_version, locale/timezone/classification/redaction, completeness, reproducibility, sections/claims, dependencies, approval=null) + `SourceCutoff` (last_sequence/event_count/ordering_quality canonical\|legacy + event-id manifest ДЛЯ legacy — §10.2 «не синтетический достоверный seq») + `SnapshotRegistry` ABC + Memory + Postgres (ленивый psycopg, миграция 0008 на первом коннекте — паритет фабрик DOCLOG-1) + `knowledge_registry_version()` (sha256 registry_data.json — версия реестра знаний, относительно которой разрешаются methodology-ref секций) + фабрики singleton/reset |
| `apps/api/snapshot_builder.py` (НОВЫЙ) | `SnapshotService` — сборщик §10.2: авторизация (write на сборку, read на чтение — решающая таблица DOCLOG-0), протокол согласованного чтения (двойное чтение run-metadata + ledger, стабильность cutoff — «эквивалентный consistency token», расхождение → `SnapshotConflict` = 409/retry, НИЧЕГО не пишется), адаптеры секций D01–D09 (claims с event_refs/result_refs/validity/evidence_level — только durable-факты), вычисление validity current/stale/unknown, честные gaps (missing_refs/reproducibility), dependency manifest + авто-pin артефактов/чекпоинтов с причиной `snapshot:{id}`, идемпотентность (UNIQUE(run_id, idempotency_key); тот же ключ+тело → прежний снимок, другое тело → 409) |
| `apps/api/migrations/0008_doclog2_snapshots.sql` (НОВЫЙ) | `report_snapshots` (UNIQUE(run_id, idempotency_key); bytes — в object store, content-addressed) + `report_snapshot_dependencies` (manifest: ref_kind artifact\|checkpoint\|event, reason; UNIQUE(snapshot_id, ref_kind, ref_id)); FK ON DELETE CASCADE — паритет артефактов/ledger |
| `apps/api/research_runs.py` | `MIGRATION_STATEMENTS_0008` + запись в каталоге `MIGRATION_FILES` (файл-дубль, паритет страхуется тестами — паттерн 0007); `run_migrations` применяет 0008 автоматически |
| `apps/api/storage_diagnostics.py` | `/health/ops.snapshots` — backend реестра снимков, тип object store, факт конфигурации root (bool, БЕЗ путей/DSN — T6/T10; паритет ops.artifacts) |
| `tests/api/test_doclog2_snapshots.py` (НОВЫЙ) | Оракулы: контракт снимка, cutoff canonical/legacy, согласованного чтения (гонки → 409-семантика, ничего не пишется), реестр (идемпотентность/конфликты/миграция-паритет/DDL), авторизация (владелец/чужой/аноним/admin/creator-continuity/read-gate), адаптеры D01–D09 (включая panel-семантику D09 и honest gaps), отсутствие пересчётов (AC05-инвариант), pins/зависимости, целостность байтов снимка, knowledge_version/AC03, диагностика |

## 3. Контракт снимка (§10.1 — схема `doclog.report_snapshot/1`)

Канонический JSON (та же сериализация, что DOCLOG-1: sort_keys, компактные
разделители, allow_nan=False — NaN/Infinity → отказ, не маскировка):

```json
{
  "schema_version": "doclog.report_snapshot/1",
  "snapshot_id": "rs-<hex32>",
  "research_run_id": "RUN-XXXXXXXX",
  "context_id": null,
  "data_revision": 0,
  "data_ref": "artifact:art-...",
  "data_digest": {"algorithm": "cisstat-data-v1", "value": "..."},
  "source_cutoff": {"last_sequence": 12, "event_count": 12,
                    "ordering_quality": "canonical",
                    "event_id_manifest": null},
  "captured_at": "2026-10-22T...",
  "template": {"id": "research-report", "version": "1.0"},
  "knowledge_version": "sha256:...",
  "locale": "ru-RU",
  "display_timezone": "Europe/Moscow",
  "classification": "private",
  "redaction_profile": "owner-v1",
  "completeness": {"status": "partial", "missing_refs": ["artifact:art-..."]},
  "reproducibility": {"status": "limited", "reasons": ["missing_data_artifact"]},
  "sections": [{"code": "D02", "kind": "source_passport",
                "title": "Паспорт источника",
                "methodology_stage": "upload",
                "claims": [{"text": "...",
                            "event_refs": ["event:..."],
                            "result_refs": ["artifact:art-..."],
                            "validity": "current",
                            "evidence_level": "server_result"}]}],
  "dependencies": ["artifact:art-...", "checkpoint:...", "event:..."],
  "approval": null
}
```

- **approval всегда null** (§10.1 пример) — согласование/публикация D11 —
  DOCLOG-6; поле зарезервировано схемой, чтобы ревизия контракта не
  меняла bytes-семантику.
- **classification/redaction_profile** — пилотные значения по умолчанию
  §22 («default private/no sharing»): `private` / `owner-v1`; профили
  раскрытия — DOCLOG-4/7.
- **knowledge_version** = `sha256:<hex>` артефакта промоушена реестра
  знаний (`apps/api/knowledge/registry_data.json`). Секции НЕСУТ
  methodology_ref (`methodology_stage`) — ссылку на этап реестра; тексты
  методологии в P0 НЕ встраиваются (встраивание в rendition — DOCLOG-5):
  версия фиксирует базу разрешения ссылок (AC03: новая версия реестра не
  меняет сохранённую ревизию — снимок immutable, пересборка = новый
  снимок с новой knowledge_version).
- **data_ref/data_digest** — ссылка на продвинутый data_frame-артефакт
  (DOCLOG-1 `checkpoint_data`), чья data_revision совпадает с целевой;
  algorithm/value — из артефакта (§9.3: НЕ пересчитывается). Отсутствие —
  честное `null` + `missing_data_artifact` в reproducibility (§10.2 п.4:
  «без надёжных артефактов — явно partial»).

### 3.1. SourceCutoff (§10.2)

| Поле | Источник | Честность |
|---|---|---|
| `last_sequence` | max(sequence) по событиям run в durable ledger до cutoff | реальная позиция ledger (НЕ watermark размера корпуса §10.2) |
| `event_count` | число событий корпуса | отдельное число; sequence может иметь пропуска и быть глобальным |
| `ordering_quality` | `canonical` если у ВСЕХ событий есть sequence (порядок = canonical_event_order §trace_events); иначе `legacy` | частичный sequence корпус не переупорядочивает |
| `event_id_manifest` | ordered event-id список — ТОЛЬКО для legacy | «закреплённый ordered manifest, не синтетический достоверный seq»; для canonical — null (sequence авторитетен, §18-бережливость) |

### 3.2. Claims (утверждения секций)

`{"text", "event_refs": ["event:<id>"], "result_refs": ["artifact:<id>"],
"validity": "current"|"stale"|"unknown", "evidence_level": str|null}`:

- **validity на момент cutoff — часть frozen snapshot** (§10.1 R07):
  артефакт с context/revision == целевым → `current`; известные
  context/revision, не совпадающие с целевыми → `stale` («исторически
  выполненное не равно пригодному»); metadata отсутствует (legacy) →
  `unknown`. События до cutoff → `current` (свершившийся факт).
  Отсутствие ref → `unknown`, НЕ current.
- **evidence_level** — из ledger события (`resolve_evidence_level`,
  реестр §trace_events); у артефактных claims — evidence уровня события
  генерации НЕ фабкуется: артефактный claim несёт evidence_level=null
  если источник не событие (честное отсутствие, §9.2 «новая версия схемы
  не повышает доказательность задним числом»).

## 4. Протокол сборки (§10.2) и согласованная чтение (AC02)

1. **Авторизация** subject/tenant (action="write") решающей таблицей
   DOCLOG-0 (`authorize_run_access`) ВНУТРИ сервиса (R09/T7 — паритет
   DOCLOG-1; знание run_id — не право).
2. **Идемпотентная проверка**: (run_id, idempotency_key) в реестре →
   тот же request_fingerprint → возврат СОХРАНЁННОГО снимка без
   пересборки (§10.3 «повтор с тем же телом возвращает прежний
   job/revision»); другое тело → `SnapshotIdempotencyConflict` (409).
3. **Чтение №1**: run metadata + canonical events до конца корпуса →
   cutoff₁; фиксация целевого context/data_revision из run-зеркала
   (запрос может закрепить свои — расхождение с текущим состоянием →
   `SnapshotConflict`, честный 409: историческая пересборка произвольной
   ревизии требует DataVersion-резолвера — граница DOCLOG-5+).
4. **Сборка секций** D01–D09 из ТОЛЬКО durable-источников: run metadata,
   ledger-события (to cutoff), артефакты реестра DOCLOG-1 (payload
   читается с проверкой sha256 — T8). Сессия НЕ читается вовсе
   (AC05: ноль научного состояния в пути сборки).
5. **Чтение №2 + сверка**: run metadata и events перечитываются;
   (context_id, data_revision) или cutoff изменились →
   `SnapshotConflict` (409/retry), НИЧЕГО не регистрируется —
   «409 на этапе сборки, не смешанный документ» (§10.2 п.3, AC02).
   Двойное чтение = эквивалентный consistency token: удержание длинной
   транзакции на время сборки секций не требуется (ADR-2).
6. **Коммит**: канонические байты снимка → staging→verify→commit object
   store (паритет DOCLOG-1 §10.2 п.6) → регистрация метаданных + manifest
   зависимостей + pin артефактов/чекпоинтов (reason=`snapshot:{id}`,
   §16 «metadata graph хранит причины ссылок») в ОДНОЙ операции реестра
   (Memory: замок; Postgres: одна транзакция).

**Отсутствие пересчётов (§10.2 п.5, AC05)**: сборщик и чтение снимка не
вызывают научных операций: нет fit/query/перезаписи статусов; чтение
снимка — read-only по всем контурам (проверяется tripwire-тестом:
сессия/ledger/артефакты/статусы до и после байт-в-байт). Render worker
(будущий DOCLOG-5) будет читать снимок, не живой run.

## 5. Адаптеры секций D01–D09 (§6)

Источник фактов — durable-слой: ledger-события (до cutoff), артефакты
DOCLOG-1, run metadata. Ничего не берётся из живой сессии; отсутствие
данных — честная секция с unknown-claim, не фабкация (R03/AC01).

| Код | kind | Факты → claims |
|---|---|---|
| D01 | plan | target/date/датасет из run metadata; ref на событие target_column_changed/structure_confirmed когда есть; форма плана (гипотезы/baseline/loss) в durable-слое не хранится → честная unknown-claim («не зафиксирован») |
| D02 | source_passport | паспорт-артефакты (stage start), upload_completed/structure_confirmed события; source bytes fingerprint — ссылка (source_bytes_sha256 артефакта) |
| D03 | quality_protocol | validation_check_status события (метка/статус из payload), паспорт stage=validation |
| D04 | transformation_recipe | correction_applied/preprocessing_check_status события; reversed/loss-поля — только из payload событий (сессия не читается) |
| D05 | eda_note | eda_check_status события, паспорт modeling_entry (checkpoint-факт EDA→Modeling handoff) |
| D06 | experiment_protocol | oof_backtest-артефакты — claim на каждый (model_id, backtest_run_id, parameter/oof signatures, input_kind); нет продвинутых → honest gap |
| D07 | model_card | model_card-артефакты (card_id, model_id, traceability checkpoint) |
| D08 | forecast_release | forecast-артефакты (forecast_id, generated_at, model_card_id; horizon/alpha — из payload ЧТЕНИЕМ, без пересчёта) |
| D09 | panel_appendix | passport input_kind=panel_entity + oof_backtest с panel-блоком; per-entity/pooled scale/method перечисляются КАК ЕСТЬ; изоляция от однорядных (R4/AC13) |

Секции запрашиваются списком kind (D01–D09 идентификаторы вида
`"D01"`/`"plan"`); template `research-report` = все запрошенные.
Каждая секция — `{"code", "kind", "title", "methodology_stage",
"claims": [...]}`.

## 6. Completeness и reproducibility (§10.1)

- **completeness.status** = `complete` ⇔ все ССЫЛАЕМЫЕ refs разрешаются:
  result_ref конверта событий указывает на существующий артефакт,
  зависимости артефактов существуют, байты артефактов проходят sha256.
  Иначе `partial` + `missing_refs` (ref-образные строки:
  `artifact:<id>`). Отсутствие событий/артефактов этапа — НЕ missing ref
  (это честное «не достигнуто», секция несёт unknown-claim), фабкуть
  несуществующие refs запрещено (R03).
- **reproducibility.status** = `ready` ⇔ data_ref разрешается И все
  current-артефакты D06–D09 прошли проверку целостности; иначе `limited`
  с причинами: `missing_data_artifact`, `missing_oof_artifact`,
  `artifact_integrity_failure:<id>` (§10.1 пример: «missing_oof_artifact»).

## 7. Идемпотентность и согласованность (§10.3, AC09/AC02)

- **Ключ**: клиентский `idempotency_key`; без него — выводимый
  `auto:<sha256(body+cutoff)>`. UNIQUE(run_id, idempotency_key).
- **Fingerprint тела** = канонический JSON (kinds, locale, template,
  classification, redaction_profile, закреплённые context/revision).
- Тот же ключ + то же тело → прежний снимок (`created=False`), пересборки
  НЕТ. Тот же ключ + другое тело → `SnapshotIdempotencyConflict` (409).
- Выводимый ключ включает cutoff → изменение состояния рождает НОВЫЙ
  снимок (новую заморозку), а авто-повтор на неизменном состоянии не
  плодит дубли (§10.3 cache/idempotency семантика).
- **Гонка сборки**: два конкурентных вызова — реестр гарантирует один
  коммит на ключ (ON CONFLICT → чтение существующего); снимок уходит в
  409-семантику конфликта, если cutoff поехал между чтениями (AC02).

## 8. Threat model (продолжение реестра DOCLOG-0/1)

| ID | Угроза | Mitigation (точка) |
|---|---|---|
| T13 | Смешение версий: сборка читает run/события, мутируемые параллельно → документ из разных контекстов | двойное чтение + сверка cutoff/(context,revision) перед коммитом; расхождение → SnapshotConflict, ничего не пишется (AC02) |
| T14 | Снимок как лазейка пересчёта («свежий отчёт = скрытый refit») | сборщик читает ТОЛЬКО durable-слой (run/ledger/артефакты); сессия не открывается; tripwire-тест на неизменность научного состояния (AC05) |
| T15 | Чужой снимок по знанию snapshot_id | авторизация action=read внутри каждого чтения; uniform-отказ без дисклоужения (R09/T7-паритет) |
| T16 | Подмена байтов/метаданных сохранённого снимка | content-addressed object store + payload_sha256 при каждом чтении → SnapshotIntegrityError (T8-паритет) |
| T17 | Фабкацияrefs/доказательности: неизвестное выдано за current | validity-матрица current/stale/unknown по metadata артефакта; evidence_level не фабкуется; missing_refs честны (R07/AC01) |
| T18 | Незащищённые зависимости: pruning удаляет чекпоинт, на который ссылается снимок | dependency manifest + pin reason=snapshot:{id} через ТОТ ЖЕ pins-механизм DOCLOG-1 (keeper merge уже защищён) |

Границы: живой PostgreSQL-прогон 0008 — при следующем durable-срезе
(паттерн AUDIT-6A/DOCLOG-1); HTTP-выдача — DOCLOG-4; форматы/renditions —
DOCLOG-5; approvals — DOCLOG-6; document_jobs очередь — §10.3 явно НЕ
реализуется задачей DOCLOG-2 (синхронная сборка, worker'ы — DOCLOG-5).

## 9. ADR (решения для старта, §22)

1. **Сервисный слой без новых HTTP-маршрутов** — паритет ADR-1 DOCLOG-1;
   §17-маршруты — DOCLOG-4, авторизация уже встроена.
2. **Двойное чтение + сверка cutoff вместо длинной транзакции** —
   эквивалентный consistency token (§10.2 п.2): удержание снапшота
   транзакции на время сборки секций несовместимо с free-tier Postgres и
   синхронным сервисным вызовом; сверка гарантирует тот же результат —
  mixed-документ невозможен, конфликт честен (409/retry).
3. **Снимок в общем object store** (content-addressed) — паритет
   артефактам; отдельная раскладка потребовала бы второй store-абстракции
   без выигрыша (§8.1 «тот же интерфейс»).
4. **Манифест событийных id — только для legacy** — canonical-порядок
   уже авторитетен sequence (§trace_events); постоянный manifest на
   canonical-корпус раздувал бы снимок без прироста доказательности
   (§18-бережливость).
5. **knowledge_version = sha256 реестра; тексты не встраиваются (P0)** —
   версия фиксирует базу methodology-ref; встраивание текстов в rendition
   и pin текстов в manifest — DOCLOG-5 (AC03 не нарушается: снимок
   immutable, пересборка = новая ревизия).
6. **Авто-ключ включает cutoff** — повтор на неизменном состоянии не
   создаёт дубль; изменившееся состояние рождает новую заморозку;
   клиентский ключ даёт строгую идемпотентность §10.3.

## 10. Честные границы и следующие шаги

- Не покрыто и НЕ заявляется: живой PostgreSQL-прогон 0008; HTTP-выдача/
  preview/UI (DOCLOG-4); рендеры форматов и rendition-очередь (DOCLOG-5);
  approvals/publish/supersede (DOCLOG-6); полный GC (DOCLOG-6); историческая
  пересборка произвольной data_revision (DataVersion-резолвер — DOCLOG-5+).
- Секции D01–D09 фиксируют durable-доступные факты; методические тексты
  и человекочитаемые rendition'ы — следующие срезы (DOCLOG-4/5).
- Следующие задачи по §19: DOCLOG-3 (telemetry/audit foundation — можно
  параллельно), DOCLOG-4 (UI и MVP выдачи поверх снимков).
