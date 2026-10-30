# PGV-09 — Jobs/PNG renderer integration: проектирование и поставка

Дата: 30 октября 2026. База: `962ccda` (main, `git fetch` открытого
репозитория; detached-проверка HEAD). Спецификация:
`spec_passport_graphics_visual.md` §4/§10/§11/§13 (строка PGV-09),
родительский контракт `spec_documentation_logging.md` §11/§17/§18.
AGENTS.md соблюдён: commit/push не выполнялись.

## 1. Постановка и границы

Строка задачи (§13): «**PGV-09 | PGV-02, PGV-08 | Jobs/PNG renderer
integration | document_jobs/render_worker/renditions | Lease/staging/
CAS/cancel/missing dependency не дают broken ready**».

Зависимости выполнены прежними поставками: PGV-02 (durable inputs,
`visual_print_snapshot`/`document_print_revisions`, миграция 0016) и
PGV-08 (изолированный renderer-контейнер, HTTP `POST /v1/render` с
`pgv.render_payload/1`, readiness/dependency-манифест, hard timeout).

PGV-09 замыкает контур: **Python-слой document jobs остаётся
authority** (§4: «Python jobs остаются authority. Новый worker получает
разрешённую PNG job через service interface/lease; только backend
завершает staged object/CAS→ready»). Рендер научной печатной ревизии
(V01, basis `visual_print_snapshot`) уходит в PGV-08-контейнер; байты
возвращаются в общий жизненный цикл renditions (stage→commit→CAS→ready).

В границах поставки:

- клиент контейнера (`apps/api/png_renderer_client.py`) с честной
  таксономией ошибок;
- мост frozen durable-входов в `pgv.render_payload/1`
  (`apps/api/print_render_payload.py`);
- печатные jobs/renditions (print_revision_id) в
  `document_jobs.py` (Memory+Postgres, миграция 0017);
- ветка print-job в `document_render_worker.py` с контрактом
  terminal/transient ошибок;
- HTTP-маршрут `POST /v1/documentation/print-revisions/{id}/renditions`.

Не входит (свои задачи): producer-контент конкретных остановок
(PGV-10…12), P01/P02 basis (PGV-13), page-set/ZIP/пагинация (PGV-14),
UI-пикер (PGV-15). Контент секций берётся из durable visual_result
(`payload.data`) по каноническим формам; незнакомая форма — честный
terminal `missing_section_content`, никакого фабрикования (§3.6).

## 2. Точки изменения и решения

| Точка | Решение |
|---|---|
| apps/api/png_renderer_client.py | stdlib `urllib` (без новых зависимостей в API-образе); env `CISSTAT_PNG_RENDERER_URL/TIMEOUT_S/ENABLED`; 200 гейтится PNG-подписью (`\x89PNG…`) и pHYs-наличием; коды ответа → исключения таксономии |
| apps/api/print_render_payload.py | `build_render_payload(snapshot, content_by_section, request_id)` собирает `pgv.render_payload/1`; `section_content_from_visual_result` отображает `payload.data` → контент секций по renderer_kind; preflight — зеркало PGV-01 `validate_print_snapshot` до постановки job |
| apps/api/document_jobs.py | `DocumentJobRecord/DocumentRenditionRecord.print_revision_id`; `request_print_rendition` (авторизация → uniform 404 → идемпотентность AC09 → 429-лимиты → queued job с basis_artifact_id); `complete_render(source_sha256)` — единый hash печатной rendition = digest basis-артефакта; Memory/Postgres паритет |
| apps/api/document_render_worker.py | ветка print-job: resolve basis → сборка payload → preflight → `renderer.render_page` в daemon-потоке с join(timeout) → `complete_render` (CAS-гейты прежние); таксономия ошибок: terminal {render_dependency_unavailable, invalid_payload, payload_too_large, missing_section_content, render_basis_unavailable, renderer_bad_output, unsupported_format, snapshot_unavailable}, transient {render_timeout, renderer_busy, renderer_unavailable, render_failed} |
| apps/api/routers/documentation.py | POST /print-revisions/{print_revision_id}/renditions → 202+status_url; uniform 404 чужих/несуществующих ревизий (AC18); ошибки через `_map_service_errors` |
| apps/api/migrations/0017_pgv9_print_renditions.sql + MIGRATION_STATEMENTS_0017 | аддитивно: `document_jobs.print_revision_id/basis_artifact_id`, `document_renditions.print_revision_id`, DROP NOT NULL у snapshot_id (FK сохраняется), частичный UNIQUE `(print_revision_id, format, redaction_profile) WHERE print_revision_id IS NOT NULL`, FK на document_print_revisions (DO $$ IF NOT EXISTS) |

### 2.1 Почему PNG-гейт на клиенте

§11: «Hash mismatch — failed integrity_error, не новый расчёт»;
broken ready запрещён критерием задачи. Контейнер обещает PNG с pHYs;
протокольное нарушение (прокси/ошибка) не должно становиться готовым
файлом: 200 без PNG-подписи — terminal `renderer_bad_output` на job,
байты не stage'ятся.

### 2.2 Таксономия retry (§11/§18)

- `render_dependency_unavailable` (503 missing_browser/missing_fonts/
  missing_bundle) — **terminal** (AC17: «render_dependency_unavailable —
  deterministic terminal failure, без бесконечного retry»).
- `render_timeout` (503 render_timeout), `renderer_busy` (429),
  `renderer_unavailable` (refused/5xx) — **transient**: requeue с
  attempt+1 до MAX_ATTEMPTS, после — честный terminal failed (AC24:
  контейнер может перезапуститься; AC20: попытки ограничены).
- `invalid_payload` (422), `payload_too_large` (413),
  `missing_section_content`, `render_basis_unavailable` — **terminal**:
  retry детерминированный дефект не чинит.
- Cancel (§17): идемпотентен; CAS-гейты `complete_render` (свежая
  запись + повторная сверка перед ready) наследуются print-путём без
  изменений — позднее завершение не публикует отменённый вывод (AC20).

### 2.3 Единый hash печатной rendition

Критерий завершения DOCLOG-5 §19 «все rendition имеют один snapshot
hash» распространяется на печатный слой: печатная rendition несёт
`snapshot_payload_sha256 = payload_sha256` basis-артефакта
(visual_print_snapshot). Подмена/расхождение байтов основы ловится при
чтении артефакта; hash рендер-байтов — content_sha256 rendition
(integrity-гейт чтения прежний).

## 3. Риски и меры

| Риск | Мера |
|---|---|
| Ложный ready при недоступном контейнере | terminal/transient таксономия + тест D-класса: ни одной rendition ни в одном отказном сценарии |
| Двойной рендер (два worker'а) | прежний lease-механизм (claimed_at/lease_expires_at, живой lease не перехватывается) — покрывается тестом на print-job |
| Позднее завершение после cancel | CAS-гейты complete_render — тест D9 на print-job |
| Смешанный snapshot/print в одном ключе идемпотентности | отдельный ключ print: (print_revision_id, format, profile); snapshot_id="" у печатных записей |
| Несовместимость Memory/Postgres | миграция 0017 + MIGRATION_STATEMENTS_0017 + parity-тесты (паттерн PROGR-5.1) |
| Расширение контента ломает legacy PNG | legacy `render_snapshot_png` (ChartSpec claims) не тронут: печатный путь — новый формат job'ов, старый путь D01–D12 без изменений (AC22) |

## 4. Приёмочные сценарии (покрытие поставкой)

| AC | Покрытие |
|---|---|
| PGV-AC17 | 503 dependency → terminal `render_dependency_unavailable`; readiness-манифест контейнера уважается клиентом; тесты D2/B2 |
| PGV-AC18 | чужая/несуществующая print revision → uniform 404 (C3/C4, E2); job/content — прежние гейты |
| PGV-AC20 | cancel queued/rendering + позднее завершение (D8/D9); timeout → requeue/failed без готовых байтов (D3); bad output → terminal без stage (D12/B8) |
| PGV-AC06 | worker читает только durable-артефакты; renderer-контейнер получает frozen payload; наука не вызывается (конструкция + тесты D-класса) |
| PGV-AC24 | renderer_unavailable → transient requeue: восстановление контейнера между попытками завершает job (D5-вариант) |

Честные границы: реальный Chromium/контейнер в среде сессии
недоступен (унаследовано от PGV-08: Docker/Chromium install заблокирован
gateway) — контейнерная E2E не пересертифицируется; HTTP-контракт
клиента проверяется реальным TCP-раундтрипом на локальном
http.server (класс B), жизненный цикл — инъекцией fake-renderer'а
(класс D). Пиксельная корректность PNG — зона PGV-08/CERT.

## 5. PGV-09-FIX (2026-10-30): исправления находок сертификации F-P9C1/N-P9C2

Независимая сертификация (docs/cert_pgv09_2026-10-30.md, вердикт
FAILED/recovery required) выявила блокер write-пути печатных jobs/
renditions на Postgres-бэкенде (F-P9C1) и неверную таксономию отказа
непериализуемого payload'а (N-P9C2). Исправление — задача
PGV-09-FIX; строки §2/§3 выше сохранены как история поставки 09c79aa,
этот раздел описывает фактическое поведение после исправления.

### 5.1 F-P9C1: durable-ключи печатных записей (NULL-семантика)

Корень дефекта: in-process записи используют `''` как маркер «нет
значения», а Postgres-адаптер передавал их в колонки как есть. Для
FK/UNIQUE-контуров 0010 пустая строка — обычное значение: FK
`document_jobs/document_renditions.snapshot_id → report_snapshots`
нарушался первой же печатной записью (0017 снял NOT NULL в расчёте на
NULL), FK `document_renditions.revision_id → document_revisions`
нарушался переносом `dprint-…` из `job.revision_id`, а общий ключ
`UNIQUE('', format, profile)` с `ON CONFLICT DO UPDATE` молча
перехватывал чужую строку rendition.

Исправление (по recovery-плану акта §7):

1. **Адаптер пишет NULL** (`_pg_nullable_text` в
   `apps/api/document_jobs.py`): пустые маркеры `snapshot_id`,
   `revision_id`, `print_revision_id`, `basis_artifact_id` печатаются
   NULL'ом; NULL проходит проверку FK и не участвует в равенстве
   UNIQUE (NULLS DISTINCT). In-process `''`-маркер и Memory-паритет
   сохранены (авторский корпус не изменён).
2. **Цель конфликта — по роду записи** (`register_rendition`):
   печатная rendition апсертится по частичному индексу 0017
   `ON CONFLICT (print_revision_id, format, redaction_profile) WHERE
   print_revision_id IS NOT NULL` (идемпотентность печатной цели без
   пересечения с snapshot-ключом); snapshot-путь — прежний
   `ON CONFLICT (snapshot_id, format, redaction_profile)` (AC09).
   Побочный дефект того же семейства устранён: пустой
   `print_revision_id` snapshot-пути пишется NULL'ом и не занимает
   частичный индекс (иначе две PNG-rendition разных снимков одного
   профиля коллодили на живом PG).
3. **complete_render**: печатная rendition несёт `revision_id=''`
   (durable NULL); связь цели — `print_revision_id` с FK 0017.
   `job.revision_id` (авторская конвенция: несёт print_revision_id)
   сохранён — у `document_jobs.revision_id` нет FK.
4. **Чтение**: `_job_from_row`/`_rendition_from_row` отображают
   durable NULL обратно в `''` (прежний `str(None)` давал строку
   `"None"` и ломал `find_*`-идемпотентность).
5. **Миграция 0018** (`migrations/0018_pgv9fix_print_rendition_keys.sql`
   = `MIGRATION_STATEMENTS_0018`, каталог 18 файлов/107 statements):
   `ALTER TABLE document_renditions ALTER COLUMN revision_id DROP NOT
   NULL` — FK сохранён (NULL проходит проверку), legacy D01–D12
   защищён по-прежнему.

Доказательство: `tests/api/test_pgv09fix_write_path.py` — мини-модель
ограничений 0010+0016+0017+0018 (SQLite) с replay РЕАЛЬНЫХ форм INSERT
адаптера (перехват через fake-соединение): печатные job/rendition
проходят FK; две печатные ревизии сосуществуют (перехват строки
исключён); snapshot-путь сохраняет идемпотентность; update-ветка не
занимает частичный индекс. Граница честности: живой Postgres в среде
отсутствует (унаследовано от CERT) — живой прогон миграций
0001…0018 + write-пути остаётся обязательным шагом приёмки.

### 5.2 N-P9C2: сериализация payload'а — terminal invalid_payload

`PngRendererClient.render_page` сериализует payload ДО сетевого блока
в собственной ветке: `TypeError/ValueError` (`allow_nan=False` — NaN/
inf вне канонического freeze, чужие типы) → `RendererPayloadInvalid`
(terminal `invalid_payload`, вне `TRANSIENT_ERROR_CODES`), а не
transient-переоткладывание до исчерпания попыток. Сетевой вызов не
выполняется вовсе; сообщение несёт только тип дефекта (AC21).

### 5.3 Верификация исправления

- RED→GREEN: 19/20 оракулов RED на базе cf520d8 (реальные формы:
  FK-нарушения ×6, `str(None)`, перенос `dprint-…`, сырой
  ValueError/TypeError, отсутствие 0018), после исправления 20/20
  GREEN (протоколы `scripts/pgv09fix/protocols/`).
- Мутанты на своих мутантах (кампания `scripts/pgv09fix/
  mutation_campaign.py`, протокол `fix_mutation_campaign.json`):
  8 откатов элементов исправления FX1–FX8 — **8/8 KILLED** моим
  корпусом; авторский корпус (38+14) — 0/8 (ALIVE) — подтверждение,
  что закрываемые пробелы именно эти.
- Регресс: полный `pytest tests/api` — 3237P/64F/42S против
  сертифицированной базы 3216P/65F/42S: +20 оракулов FIX, 0 новых
  отказов; единственное расхождение — предсуществующий флаковый
  doclog9-pdfa determinism (в этом прогоне GREEN).
- `verify_local.py` — VERDICT PASS (адресная suite, затронутый
  регресс 680P, паритет 0018, состояние дерева).
