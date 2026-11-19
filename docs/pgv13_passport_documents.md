# PGV-13 — P01/P02 builders: паспорта и сравнение из durable refs

Задача `spec_passport_graphics_visual.md` §13, строка PGV-13 (зависимости
PGV-05, PGV-06, PGV-09). Дата: 2026-11-18. База: `fc510f0` (origin/main).

## 1. Постановка и критерий готовности

«**P01/P02 builders**; точки изменения — passport_documents/snapshot_builder/
lifecycle; критерий — **Полные паспорта/сравнение из refs, без DataFrame,
reused checkpoint работает**».

Путь B (§1/§10.2): в «Документах исследования» аналитик восстанавливает
сохранённые паспорта (один / комплект траектории) и их сравнение, печатное
представление рендерится и скачивается как PNG — **без активного DataFrame,
без живой cookie-сессии и без пересчёта науки** (§3.1, AC06, AC09). PGV-15
(пикер/preview UI «Документов») и PGV-14 (pagination/page-set/ZIP) — добирающие
задачи; эта поставка — builders + lifecycle + рендер-интеграция конвейера
PGV-09 для печатных типов P01/P02.

Приёмочные сценарии в скоупе: AC09 (полные группы после утраты
session/Redis), AC10 (выбранная траектория, не latest каждого stage), AC11
(reused modeling_entry — подтверждение + исходный снимок, без ложной
четвёртой копии), AC12 (missing/corrupt — gaps/integrity failure, не выдумки),
AC13 (P02 numeric/category/list/qualitative, zero-denominator reason,
несовместимость закрыта), AC14 (panel не смешивается с single-series).
AC18-дух (uniform 404) и AC06 (без науки) — на границах поставки.

## 2. Состояние исходников (факты на fc510f0)

| Компонент | Факт |
|---|---|
| PGV-02 (`report_snapshot.py`) | Каталог `pgv.document_catalog/2` уже содержит P01/P02 (`PRINT_DOCUMENT_KINDS`); таблица document_print_revisions (миграция 0016) |
| PGV-05 (`passport_history.py`) | `read_passport_snapshot/read_passport_trajectory/list_*` — полные snapshot-записи §8 из registry/ObjectStore; XOR-честность; access-gate |
| PGV-06 (`passport_comparison.py`) | Frozen `pgv.passport_comparison/1` (trajectory/explicit-refs); reuse-семантика AC11; несовместимость `PassportComparisonIncompatible` |
| PGV-09 (`document_jobs.py`) | `request_print_rendition` — basis-каталог ТОЛЬКО `visual_print_snapshot`; P01/P02 → `PrintRenderBasisUnsupported` с отсылкой к PGV-13 |
| PGV-07 (`packages/ui/print/`) | `printPassport.tsx` (PrintPassportPage, вход — запись PGV-05), `printComparison.tsx` (PrintPassportComparisonPage, вход — снапшот PGV-06) — pure-компоненты готовы, контейнером НЕ маршрутизируются |
| PGV-08 (`rendererCore.tsx`) | SECTION_KINDS = 5 видов (html_table/html_heatmap/html_cards/ih_conditional/recharts_svg); паспортных видов нет |
| Реестр PGV-00 | Паспортные сайты — адаптер `pgv-04/*` (source passport, D02); pgv-13-адаптеров нет — эта задача вид-реестр НЕ трогает (UI-пикер — PGV-15) |

## 3. Ключевые проектные решения

1. **Frozen печатные входы — новые versioned artifact kinds** (§6 «producer
   adapter фиксирует print input», §10.2 «revision с frozen refs/pins без
   capture и перерасчёта»):
   - `passport_print_snapshot` — payload `pgv.passport_print_snapshot/1` —
     самодостаточный печатный вход P01: записи истории паспортов (зеркало
     PGV-05, pgv.passport_history/1) встроены в секции целиком
     (groups/metrics/provenance/content_status) — контент НЕ пере-выводится
     при рендере;
   - `passport_comparison_snapshot` — payload
     `pgv.passport_comparison_print_snapshot/1` — печатный вход P02: frozen
     сравнение (pgv.passport_comparison/1) встроено в секцию целиком.
   Самодостаточность = честность: XOR-причины/content_status фиксируются В
   МОМЕНТ сборки (AC12), рендер не может «додумать» утраченное позже.
2. **Верхнеуровневая форма снапшота паритетна VisualPrintSnapshot/1** — та же
   рамка печати PrintPageFrame (print.profile_id, display.title/subtitle,
   view_id/scope «вид», dimensions). `view_id = "passport.document.p01" /
   "passport.document.p02"` — идентификатор печатного контракта документа, НЕ
   сайт реестра PGV-00 (реестр — только научные визуализации; PGV-15 добавит
   пикер). `scope = "passport" | "comparison"` — значения каталога PGV-01.
3. **Новые секционные виды рендера** (`pgv.render_payload/1`, §4.1 «общий
   print-бандл — единственная реализация», без второй реализации на Python):
   - `passport_record` — секция несёт запись истории → контейнер рендерит
     `PrintPassportPage` (PGV-07);
   - `passport_comparison` — секция несёт frozen сравнение → контейнер
     рендерит `PrintPassportComparisonPage` (PGV-07).
   Python НЕ перерисовывает паспорт (паритет «recharts не перерисовывается»):
   запрет фабкации групп/причин наследуется компонентом PGV-07.
4. **Без CAS current-context (сознательно)**: POST /passport-documents
   восстанавливает ИСТОРИЧЕСКИЕ refs — ожидание контекста клиента к ним не
   применимо (§3.3 «Stale относительно текущих данных не уничтожает
   историческую действительность»; контракт §11 несёт refs/checkpoint, не
   expected_context). Целостность обеспечивают content-addressed хранение +
   payload_sha256-сверка freeze/чтения (T8) и producer_key-идемпотентность.
5. **Идемпотентность** (§11/§12.2): producer_key
   `pgv.passport_print:{mode}:{refs}:{digest16}` /
   `pgv.passport_comparison_print:{mode}:{refs}:{digest16}` (digest — SHA-256
   канонического JSON identity-ядер записей/сравнения) → find-by-producer →
   та же ревизия (basis_fingerprint) → тот же активный/ready job. Повторный
   запрос дубликатов не создаёт (§12.2).
6. **Пины зависимостей** (§16): passport-артефакты present-записей пинятся
   причиной `passport_print:{artifact_id}` / `passport_comparison:{artifact_id}`
   (AC08-компенсация при отказе — паритет freeze_visual_print_snapshot).
   Content-гэп-записи (missing/corrupt) пинов не получают — контента нет.
7. **Доступ**: read — reader'ы PGV-05/06; write/freeze —
   PromotionService._authorized_run(write); чужой run — единый
   `PassportDocumentAccessDenied` (404, без дисклоужения, AC18-дух).
   Несовместимость — `PassportDocumentIncompatible` (409
   comparison_incompatible с reasons, §9/AC13/AC14). Отсутствующий
   checkpoint/ref — `PassportDocumentSourceUnavailable` (409
   source_unavailable; пересчёт запрещён). Неверная форма запроса — 422.
8. **Частичность честна** (§9): комплект из траектории с недостающими/
   битыми точками строится с gap-записями (content_status
   missing_artifact/corrupt) и `completeness="partial"`; сравнение — пары
   только соседних разрешённых позиций (резолвер PGV-06). Unavailable не
   фабрикуется (§3.6). Полный комплект «одна страница» — существующий
   однопейджный конвейер; pagination/page-set/ZIP — PGV-14.

## 4. API (§11, предлагаемые контракты — теперь реализованы)

| Операция | Семантика |
|---|---|
| `GET /v1/documentation/runs/{run_id}/passport-sources` | Пикер (§10): список паспортных rs-записей (§8) + чекпоинтов без session DataFrame; read-only |
| `POST /v1/documentation/runs/{run_id}/passport-documents` | `mode` single/set/compare; single — `snapshot_refs=[rs-*]` (ровно 1); set — `checkpoint_id` ИЛИ `snapshot_refs` (≥2); compare — то же (≥2 / чекпоинт); → P01/P02 revision + PNG job (202) |

Карта роутов AUTH-00 регенерируется (`inventory.py --write`); обоих новых
маршрута — review в `docs/auth00/policy_review.json` (passport_documents.py —
новый reviewed source). Гейт `check_routes` (AUTH-00): added = ровно 2 новых
ID, missing = пусто, прочие записи — только evidence/fingerprints.

## 5. Точки изменения

| Файл | Изменение |
|---|---|
| `apps/api/artifact_store.py` | +2 kinds каталога ARTIFACT_KINDS |
| `apps/api/visual_artifacts.py` | версии схем, валидаторы, producer-ключи, freeze (без CAS, пины, компенсация) |
| `apps/api/passport_documents.py` | **НОВЫЙ** — builders + lifecycle + list_passport_sources |
| `apps/api/print_render_payload.py` | load по kind (самодостаточные входы), секции passport_record/passport_comparison |
| `apps/api/document_jobs.py` | basis-каталог рендера: + passport_print_snapshot/passport_comparison_snapshot |
| `apps/api/routers/documentation.py` | +GET passport-sources, +POST passport-documents |
| `apps/print-renderer/src/rendererCore.tsx` | +2 секционных вида, маршрутизация на PrintPassportPage/PrintPassportComparisonPage |
| `tests/api/test_pgv13_passport_documents.py`, `apps/print-renderer/src/rendererCore.test.ts` | RED→GREEN корпус |
| `docs/auth00/inventory.json/md`, `docs/auth00/policy_review.json`, `scripts/local_gates.md` | карта роутов/review (новые маршруты) |

## 6. Риски и меры

- **Дублирование печатной логики на Python** — исключено архитектурно: Python
  только переносит frozen записи в payload; группы/баннеры/причины печатает
  компонент PGV-07 (AST-граница в тестах).
- **Ложная «четвёртая копия» reused** — резолвер PGV-06 уже убирает
  дубликат из path; builder печатает confirmation строкой (пин-тест).
- **Смешивание panel/single** — несовместимость резолвера (universe) → 409;
  isolation-тест AC14.
- **Скрытый пересчёт науки** — builders читают только registry/ObjectStore
  через PGV-05/06 (AST-гейт: без session_store/pandas/redis); lifecycle не
  вызывает capture (AC06/AC09).
- **Порча/подмена** — payload_sha256-сверка при freeze и при чтении basis
  worker'ом (T8-дух); расхождение — honest failure, не рендер.
- **Старые reader'ы/legacy D01–D12** — не тронуты: каталог документных типов
  расширяется аддитивно, validate_print_snapshot (PGV-01) не меняется.

## 7. Поставка и VM

ZIP task-only в download/ (см. files.txt); чейн доставки: ZIP → локальная
распаковка → push тимлида → pull на VM → docker compose. Изменён UI-бандл web
(только импорты print-бандла не меняют runtime web? НЕТ: web не менялся —
печатные компоненты живут в контейнере рендера и API), поэтому:

- **api** — изменён (новые модули/роуты/jobs-гейт) → rebuild;
- **print-renderer** — изменён rendererCore.tsx (новые секции) → rebuild
  контейнера PGV-08 (имя образа/сервис — см. команды ниже);
- **web** — НЕ меняется (стендalone-оболочка печатных паспортов не касается);
- **postgres** — схема НЕ меняется (нет миграций; kinds — реестр-каталог).

VM-команды (актуальный UDS rollout поверх db10ada, из корня):

```bash
docker compose --project-directory deployment/cisstat-stack -f deployment/cisstat-stack/docker-compose.yml -f deployment/cisstat-stack/docker-compose.renderer-uds.yml build api web
docker build -f apps/print-renderer/build/Dockerfile -t cisstat-print-renderer:pgv13-uds .
export CISSTAT_UDS_RENDERER_IMAGE="$(docker image inspect --format '{{.Id}}' cisstat-print-renderer:pgv13-uds)"
```

Дальнейшие init volume → isolated candidate → новый image A/B → native API-image
UDS/PNG gate → recreate/stale socket gate → production renderer/api/web —
**docs/pgv13_uds_transport.md**, раздел «VM-команды». Выбранный renderer compose:
base + `apps/print-renderer/build/deployment/docker-compose.uds.yml`; его image
берётся из CISSTAT_UDS_RENDERER_IMAGE, pinned ID ровно построенного образа.
API compose: base + `deployment/cisstat-stack/docker-compose.renderer-uds.yml`.
Base compose без UDS overlay — прежняя topology, не заявленная работоспособной.

Web включён в обязательный согласованный rollout: исходный PGV-13 добавил
compiled BFF proxy paths. Отсутствие новой правки frontend в текущей задаче
не делает старый web совместимым. Локально проверяются сборки обеих оболочек.
Не применять прежний activate.py к UDS-конфигурации: его запрет mounts защищает
старую конфигурацию, это не image-upgrade инструмент. Старый A/B report не
распространяется на новый image. Миграций/host policy changes нет.
Полная PGV-13/PNG visual/job acceptance после транспорта остаётся отдельной.
