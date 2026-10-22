# DOCLOG-1 — Устойчивые артефакты (контрактный документ)

*Task DOCLOG-1, 2026-10-22. Спецификация-источник: `spec_documentation_logging.md`
(§9.1 «Модель идентичности и происхождения», §9.3 «Данные из БД и восстановление»,
§10.2 «Протокол сборки», §16 «Хранение, неизменность и удаление», §19 строка
DOCLOG-1 и §19.1, §20 AC04/AC05/AC06/AC08/AC09/AC13). База: main@fb26f6f
(DOCLOG-0 включён). Поставка следует AGENTS.md (TDD RED→GREEN→регресс,
без commit/push).*

## 1. Постановка и граница задачи

DOCLOG-1 — второй срез эпика документирования/логирования (§19):
**«Metadata/ObjectStore/schema/digests/staging/pins; адаптеры паспортов,
OOF, cards, forecasts»**. Критерий завершения (§19, та же строка):
**результаты доступны после TTL-сессии, pin выдерживает checkpoint-pruning,
panel types сохраняются**. Вне границы (по §19): ReportSnapshot/сборщик
(DOCLOG-2), телеметрия/durable-аудит (DOCLOG-3), UI и HTTP-выдача
(DOCLOG-4), форматы/worker (DOCLOG-5), approvals/publication/полный GC
(DOCLOG-6). Новых HTTP-маршрутов поставка НЕ добавляет: §17 прямо
помечает их «предлагаемыми», а очередь реализации относит выдачу к
DOCLOG-2/4; доступ к артефактам в этой задаче — сервисный слой с той же
объектной авторизацией DOCLOG-0 (`authorize_run_access`), которую
будущие маршруты обязаны использовать (защита от забытого гейта).

Проблема (факты спеки): сессия и её буфер не могут быть единственным
архивом исследования (F01: Redis TTL 30 дней, трасса слоя 1 ограничена
1000 событиями); keeper «последних пяти» чекпоинтов может удалить
снимок, на который ссылается утверждённый документ (F10/H07); CSV-
перезапись чекпоинта не гарантирует схему (H10); прогноз связан с
cookie-сессией (F04/H02). DOCLOG-1 создаёт долговременный слой
результатов, независимый от сессии.

## 2. Что реализовано (карта изменений)

| Файл | Состав |
|---|---|
| `apps/api/artifact_store.py` (НОВЫЙ) | Digest-схемы (три РАЗНЫХ типа §9.3), `ResultArtifact`/`ArtifactPin`, `ArtifactObjectStore` (локальный content-addressed адаптер: staging → verify → commit → read с проверкой целостности), `ArtifactRegistry` ABC + Memory + Postgres (ленивый psycopg, паритет фабрики бэкендов runs), pins-реестр, sweep осиротевшего staging (grace period), фабрики singleton/reset |
| `apps/api/artifact_promotion.py` (НОВЫЙ) | Адаптеры-промоутеры: паспорт (однорядный + panel_entry), backtest/OOF (однорядный и panel_entity), Model Card, forecast, данные чекпоинта (CSV); каноническая JSON-сериализация (allow_nan=False); **объектная авторизация внутри сервиса** (write/read через `authorize_run_access`); авто-pin зависимостей; честные отказы (нет снимка/NaN/чужой доступ) |
| `apps/api/migrations/0007_doclog1_artifacts.sql` (НОВЫЙ) | Таблицы `research_artifacts` (UNIQUE(run_id, producer_key)) и `research_artifact_pins` (UNIQUE(run_id, ref_kind, ref_id)); индексы; FK ON DELETE CASCADE — артефакты живут вместе с запуском (паритет ledger) |
| `apps/api/research_runs.py` | `MIGRATION_STATEMENTS_0007` + запись в каталоге `MIGRATION_FILES` (файл-дубль, паритет страхуется тестами); `run_migrations` применяет 0007 автоматически |
| `apps/api/routers/progress.py` | Keeper «последних пяти» чекпоинтов: keep-список объединяется с pinned checkpoint-id; сбой lookup пинов — prune ПРОПУСКАЕТСЯ (fail-closed для защиты: неизвестное состояние пинов не удаляет файлы) |
| `apps/api/storage_diagnostics.py` | `/health/ops.artifacts` — backend реестра, тип object-store, факты конфигурации (bool, БЕЗ путей/DSN — T6) |
| `tests/api/test_doclog1_artifacts.py` (НОВЫЙ) | 59 оракулов: digest-схемы, staging-протокол, реестр, pins, авторизация промоушена, адаптеры (включая panel_entity), долговечность после утраты сессии, выживание pinned-снимка при prune (включая реальный POST-маршрут чекпоинта), честные отказы |

## 3. Digest-схемы (§9.3: три типа не взаимозаменяемы)

| Поле | Формула | Смысл |
|---|---|---|
| `payload_sha256` | SHA-256 канонических байт артефакта | `artifact_content_sha256`: байты сохранённого объекта; проверяется при каждом чтении (T8) |
| `data_digest` | `{algorithm: "cisstat-data-v1", value: SHA-256}` | версионированная семантика нормализации ДАННЫХ (для kind=data_frame); канонизация CSV задокументирована записью algorithm/version |
| `source_bytes_sha256` | существующий dataset fingerprint | точные байты исходного файла; НЕ пересчитывается, переносится ссылкой |

Каноническая сериализация JSON-полезной нагрузки:
`json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)`.
NaN/Infinity НЕ маскируются: отказ промоушена с честной причиной
(дух AC12 — не ноль и не pass). Отдельно фиксируется `media_type`
(`application/json` / `text/csv`) и `size_bytes`.

## 4. ObjectStore и staging-протокол (§10.2 п.6, AC08)

Раскладка (root: env `CISSTAT_DATA_DIR`, иначе `<repo>/data` — паритет
`DatasetFileStore`):

```
{root}/artifacts/objects/{sha256[:2]}/{sha256}   -- commit (content-addressed)
{root}/artifacts/staging/{staging_id}            -- stage до коммита
```

Протокол: `stage_bytes` (запись в staging, вычисление sha/size) →
`commit_staged` (ПЕРЕЧИТЫВАЕТ staging-файл, сверяет sha256+size —
расхождение: fail-closed, staged удаляется, метаданные НЕ регистрируются;
затем атомарный `os.replace` в objects) → регистрация в реестре той же
операцией сервиса. Crash-матрица: падение до коммита — осиротевший
staging-файл без ссылки (убирается `sweep_orphan_staging` с grace
period); после записи объекта до реестра — осиротевший content-object
(безвреден, полный mark-and-sweep GC — DOCLOG-6, граница честно
задокументирована); метаданные появляются ТОЛЬКО после валидного
объекта — «полузакоммиченных» записей не бывает. Чтение всегда
проверяет sha256: расхождение — `ArtifactIntegrityError` (не тихие
битые байты, T8). Storage key производит ТОЛЬКО сервер из хэша —
путей traversal из имён клиента не существует (T9).

## 5. Реестр метаданных (§8.1: тот же Postgres, новые таблицы)

`ArtifactRegistry`: Memory (паритет MemoryResearchRunStore: замок,
копии записей) + Postgres (ленивый psycopg, `run_migrations` на первом
коннекте — тот же паттерн, что runs). Идемпотентность промоушена:
UNIQUE(run_id, producer_key) — повторный promote того же источника
возвращает существующий артефакт без дубля (AC09); тот же producer_key
с другим контентом — конфликт без записи.

`ResultArtifact` (поля §9.1): artifact_id (`art-`+uuid4hex), run_id,
kind (`passport`|`oof_backtest`|`model_card`|`forecast`|`data_frame`),
schema_version `doclog.artifact/1`, producer_key, media_type,
payload_sha256/size/storage_key, data_digest (algorithm+value),
source_bytes_sha256 (ссылка), context_id/data_revision (момент создания,
честное отсутствие), input_kind + panel-блок (панельная семантика),
dependencies (checkpoint/event/card refs), refs, created_by (псевдоним
субъекта DOCLOG-0), created_at. FK run_id → research_runs CASCADE —
паритет ledger (удаление запуска уносит его артефакты; publish-контур
DOCLOG-6 введёт свою политику).

Pins: `ArtifactPin(pin_id, run_id, ref_kind, ref_id, reason, created_by,
created_at)`, UNIQUE(run_id, ref_kind, ref_id) — идемпотентны. ref_kind
`checkpoint` защищает файл снимка от keeper «последних пяти» (AC04);
`artifact` — зависимость артефакта. Снятие пина — отдельное действие;
последующий prune удаляет уже незащищённое.

## 6. Адаптеры-промоутеры (§19: «без повторного fit при экспорте»)

Каждый адаптер: ЧИТАЕТ существующую запись (сессия — источник факта,
не права), сериализует канонически, коммитит через staging-протокол,
регистрирует с producer_key, при наличии зависимостей — создаёт pin.
Авторизация ВНУТРИ сервиса: `authorize_run_access(run, subject,
action="write")` на промоушен и `action="read"` на чтение (R09 —
«одна объектная авторизация»; знание artifact_id не является правом,
T7); отказ — исключение с AccessDecision (маршруты DOCLOG-4 обязаны
маппить в uniform 404).

| Адаптер | Источник | producer_key | Панельная семантика |
|---|---|---|---|
| паспорт | `latest_passport(stage)` / `latest_panel_passport()` | `passport:{snapshot_id}` | panel_entry: stage сохранён, `input_kind="panel_entity"`, изолирован от однорядного списка (R4) |
| backtest/OOF | `modeling_artifacts.backtests[model_id]` | `backtest:{backtest_run_id}` | panel_entity: блок `panel` (n_entities/balance/entity_columns_order/entity_metrics/pooled_*_scale + method) переносится КАК ЕСТЬ |
| Model Card | `modeling_artifacts.model_cards[card_id]` | `card:{card_id}` | input_kind из execution_contract |
| forecast | `modeling_artifacts.forecasts[forecast_id]` | `forecast:{forecast_id}` | frozen: points/horizon/alpha/ci_method/lineage — байт-в-байт из сессии, никогда не пересчитывается (§6 D08) |
| данные чекпоинта | `DatasetFileStore` CSV | `checkpoint_data:{checkpoint_id}` | data_digest по CSV-байтам; АВТО-pin checkpoint-зависимости (демонстрация pin-механизма) |

Отсутствие источника (нет снимка/карты/прогноза) — честный
`PromotionUnavailable`, ничего не фабкуется (R03).

## 7. Threat model (продолжение реестра DOCLOG-0)

| ID | Угроза | Mitigation (точка) |
|---|---|---|
| T7 | Знание artifact_id/run_id даёт доступ к чужому результату | авторизация `authorize_run_access` ВНУТРИ каждого сервисного вызова (write/read); отказ с AccessDecision, не утечка содержимого |
| T8 | Подмена/порча байтов артефакта (content-addressed путь угадан/диск повреждён) | content-addressed раскладка + проверка sha256 при КАЖДОМ чтении; расхождение — ArtifactIntegrityError, битые байты не выдаются |
| T9 | Path traversal через идентификаторы/имена клиента | storage key производит сервер из SHA-256; staging_id серверный; идентификаторы валидируются; имён клиента в раскладке нет |
| T10 | Секреты (пароль БД/DSN/API-key) попадают в артефакт/метаданные | адаптеры переносят ТОЛЬКО научные полезные нагрузки; source-происхождение — ссылками (fingerprint/query_ref-заготовка), не содержимым; /health/ops.artifacts — факты-bool без путей |
| T11 | Prune «последних пяти» удаляет зависимость pinned-артефакта | keep-список объединяется с pinned checkpoint-id; сбой lookup пинов — prune пропускается (fail-closed), warning |
| T12 | Тихая подмена данных канонизацией (NaN→null, перезапись) | allow_nan=False; канонизация зафиксирована записью algorithm/version; отказ вместо молчаливой правки |

Границы: Postgres-прогон 0007 на живой БД — приёмка при следующем
durable-срезе (паттерн AUDIT-6A/DOCLOG-0); полный mark-and-sweep GC
объектов, retention/hold, backup/restore — DOCLOG-6; HTTP-выдача —
DOCLOG-4.

## 8. TDD-протокол

**RED**: `tests/api/test_doclog1_artifacts.py` — 57 ошибок на
отсутствующем контуре (`apps.api.artifact_store`/`artifact_promotion`
не существуют; фикстура изоляции импортирует модуль — все оракулы
красные честно). В ходе GREEN корпус расширен до 59 (+2: честный
not_initialized /health/ops.artifacts; маршрут-уровень AC04 через
реальный POST /v1/progress/runs/{id}/checkpoints с пином). Корпус
дизъюнктен repo-корпусу (RUN-D1xxxxxx), изоляция каждого теста —
паттерн test_doclog0_identity.py (свой tmp_path/CISSTAT_DATA_DIR, сброс
singleton-фабрик ВКЛЮЧАЯ session store — ревизионный конфликт
повторного сида одной и той же сессии между тестами). Находки GREEN
(ошибки КОРПУСА, не кода): (1) hex-ссылка — 64 символа ("d1"*32, не
*16); (2) sweep-тест: старение orphan через os.utime вместо grace=0
(иначе удаляются ВСЕ staged, включая свежий); (3) маршрут-тест: ранний
чекпоинт обязан быть зарегистрирован В ledger (store.add_checkpoint) —
файл снимка без ledger-записи не попадает в keeper-список;
(4) повторный сид сессии между тестами требует
reset_session_store_for_testing.

**GREEN**: 59/59. Полный регресс: множества FAILED/ERROR идентичны
чистому fb26f6f (двойной прогон, comm — дельта 0; 100 строк средового
класса: psycopg DSN песочницы, neural-зависимости вне каталога —
идентично сертификационным отчётам). Адресные смежные контуры зелёные
(research_runs 60/60, doclog0 42/42, audit-8, audit-6c, session_store;
2 фейла audit-6c — в базлайне). Пины схемы: SESSION_SCHEMA_VERSION не
меняется (артефакты не трогают сессию); миграция 0007 аддитивна
(читатели раньше писателей, legacy-корпус без артефактов остаётся
читаемым). Сборка: импорт всех затронутых модулей + сборка
FastAPI-приложения (183 маршрута), каталог миграций — 41 утверждение /
7 файлов.

## 9. ADR (решения для старта, §22)

1. **Сервисный слой без новых HTTP-маршрутов** — §17 помечает API
   «предлагаемым», очередь DOCLOG-4; авторизация встроена в сервис,
   поэтому будущие маршруты не смогут её забыть (эшелонирование T1
   DOCLOG-0 + T7).
2. **Content-addressed object store** — sha256-раскладка даёт дедуп,
   целостность при чтении и серверные ключи без traversal; каталоги
   по префиксу хэша (2 символа) — паритет классической объектной
   схемы; распределённый object storage (S3-подобный) — тот же
   интерфейс `ArtifactObjectStore` при production-профиле (§8.1).
3. **Артефакты каскадно живут с run** — паритет ledger/чекпоинтов;
   разделение «удалить из workspace / revoke / физический purge» и
   независимая жизнь published-пакетов — DOCLOG-6 (§16).
4. **Авто-pin зависимостей при промоушене** — pin создаётся
  _promоутером_ с reason=artifact_id (прослеживаемая причина, §16:
   «metadata graph хранит причины ссылок»); ручное управление пинами —
   методы реестра, UI — DOCLOG-4.
5. **JSON-канон без NaN** — отказ вместо маскировки; data_frame-путь —
   CSV (паритет чекпоинтов, §12 п.4), Parquet+schema — DOCLOG-5 (P1).
6. **Пины в той же durable-таблице** — pins переживают процесс/сессию,
   как и артефакты; отдельный pins-кэш создал бы вторую истину.

## 10. Честные границы и следующие шаги

- Продакшен обязан: при включении durable-хранилища миграция 0007
  применяется автоматически (`run_migrations`); root артефактов —
  общий с DatasetFileStore (`CISSTAT_DATA_DIR`), для private object
  storage — конфигурация следующего durable-среза.
- Не покрыто и НЕ заявляется: живой PostgreSQL-прогон 0007; HTTP-выдача
  и UI; полный GC/retention; шифрование at rest; распределённый object
  store; ретрай-очередь промоушена (синхронный вызов в этой задаче).
- Следующие задачи по §19: DOCLOG-2 (ReportSnapshot-сборщик поверх
  артефактов) и параллельно DOCLOG-3 (telemetry/audit foundation).
