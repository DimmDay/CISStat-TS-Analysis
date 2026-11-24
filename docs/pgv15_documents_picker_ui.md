# PGV-15 — Documents picker/preview/PNG UI: дизайн, риски, применение

**База:** `main@a224296` (CISStat-TS-Analysis). **Спецификация:** `spec_passport_graphics_visual.md` §10.2, §11, §13 (строка PGV-15), приёмочные AC09–AC14, AC21, AC22, AC24.
**Зависимости:** PGV-13 (P01/P02 builders + routes), PGV-14 (page-set/ZIP + metadata_url) — выполнены.
**Критерий задачи (§13):** «Один/все/сравнение по версии, D02 не P01, ZIP страниц доступен».

## 1. Постановка

«Документы исследования» (DocumentationWorkspace) получают печатные семейства
аддитивно (§10.2):

- фильтры «Документы» (D01–D12, прежний поток — без изменений) /
  «Паспорта свойств» (P01/P02) / «Визуализации» (V01);
- «Восстановить паспорта»: пикер durable-источников → context/trajectory/
  checkpoint → сохранённые точки/gaps → один/все/сравнение → «Создать
  печатное представление» (frozen refs/pins, без capture и перерасчёта, AC06);
- предпросмотр соответствует скачиваемой версии/профилю; одна страница —
  «Скачать PNG», несколько — «Скачать все страницы PNG (ZIP)» (§10.2);
- D02 «Паспорт источника» сохраняет смысл вида каталога D01–D12 и НЕ есть
  P01 «Паспорта свойств ряда» (печать из durable-источников) — подписи
  разведены явно (критерий «D02 не P01», AC22).

## 2. Состояние исходников (проверено на a224296)

| Исходник | Установленный факт и точка расширения |
|---|---|
| apps/api/document_jobs.py | `list_print_documents` — субстрат фильтров PGV-15 (докстринг), read-авторизация; готовых renditions в ответе нет; новый view-builder здесь же |
| apps/api/routers/documentation.py | GET/POST passport-sources/passport-documents (PGV-13), POST print-revisions/{id}/renditions (PGV-09, идемпотентный replay ready), jobs/cancel/content; листинга печатных документов НЕТ |
| apps/api/document_jobs.py `_job_json` | ready job DTO несёт `output_format` и `metadata_url` (PGV-14) — UI-поллинг получает ссылку на metadata JSON |
| apps/api/passport_history.py | `list_passport_snapshots`/`list_passport_checkpoints` — записи §8/§10 (stage/universe/target/date/fingerprint/confirmed_at/flags/integrity) — данные пикера |
| apps/api/print_page_sets.py | page-set: 1 страница и mode!=set → PNG-байты; много страниц или mode=set → ZIP + metadata.json sidecar (format "json", тот же print_revision_id) |
| packages/ui/lib/documentation.ts | клиент D-каталога; JobPayload без `output_format`/`metadata_url` — аддитивные опциональные поля |
| packages/ui/lib/visualExports.ts | клиент Пути A (§10.1) — паттерн плоских ошибок {code,message} |
| packages/ui/components/DocumentationWorkspace.tsx | три бейдж-области D-каталога; семейств нет; открытие не создаёт документы |
| apps/standalone/app/documentation/* | страница standalone использует общий DocumentationWorkspace (@cisstat/ui); embedded документационной страницы не монтирует — «обе apps» покрываются общим пакетом + typecheck/build |

## 3. Решение

### 3.1 API — один новый READ-маршрут

`GET /v1/documentation/runs/{run_id}/print-documents` → 200
`{run_id, documents:[…]}`:

```json
{
  "document_id": "…", "run_id": "…", "print_kind": "P01",
  "family": "passports", "kind_title": "Паспорта свойств ряда",
  "created_by": null, "created_at": "…",
  "revisions": [{
    "print_revision_id": "dprint-…", "version_no": 1,
    "profile_id": "figure-landscape", "basis_kind": "passport_print_snapshot",
    "basis_fingerprint": "…", "created_by": null, "created_at": "…",
    "renditions": [{"rendition_id": "…", "format": "png|zip|json",
      "redaction_profile": "default", "state": "ready",
      "media_type": "…", "size_bytes": 123, "content_sha256": "…",
      "job_id": "djob-…", "created_at": "…"}]
  }]
}
```

- Источник — `DocumentDeliveryService.list_print_documents` (V01+P01+P02,
  ≤3 документов на run: `find_document_by_kind` возвращает один документ на
  код) + одна выборка `registry.list_jobs(run_id)` → готовые renditions по
  `print_revision_id` (без N+1, без байтов — только metadata §14).
- Авторизация — read через существующий `_authorized_run` (uniform
  `DocumentAccessDenied` → 404 `_DOCUMENT_NOT_FOUND_DETAIL`; существование
  чужого run не дисклоужируется, AC18). Семейства/rev/pin — как у
  листинга D-каталога (знание run_id не право, R09).
- Ответ read-only: GET не меняет scientific state и не создаёт jobs (§11).

Новые POST/методы/paths/DTO больше не добавляются: создание печатных
представлений — существующий `POST /runs/{run_id}/passport-documents`
(идемпотентность §11), сборка PNG — `POST /print-revisions/{id}/renditions`
(replay ready, AC09), поллинг/отмена/скачивание — существующие
jobs/cancel/content; metadata — `metadata_url` ready job (PGV-14).

### 3.2 UI — пакеты и потоки

Новые файлы (`packages/ui`), оба приложения получают их через @cisstat/ui:

- `lib/passportDocuments.ts` — типы контрактов + клиенты
  `listPassportSources`, `listPrintDocuments`, `requestPassportDocument`
  (single/set/compare), `requestPrintRendition` (POST print-revisions —
  reuse существующего маршрута), `passportDocumentErrorText` (плоские
  коды §17/PGV-13: 404 uniform, 409 source_unavailable/
  comparison_incompatible, 422 invalid_selection, 429 quota/retry, 503
  unavailable; null — offline).
- `components/PrintDocumentsPanel.tsx` — сохранённые печатные документы
  семейства (P01/P02 или V01): таблица версий (print_revision_id, vN,
  профиль, basis, дата), готовые форматы с размерами, кнопки:
  «Скачать PNG» (одна страница) / «Скачать все страницы PNG (ZIP)» /
  «Metadata (JSON)»; «Предпросмотр» — inline PNG (blob через
  credentials-запрос content-маршрута; объектный URL отзывается) или
  честная карточка ZIP со списком страниц из metadata.json (страницы
  комплекта не рисуются клиентом — состав печатается из frozen metadata);
  «Запросить PNG» — POST print-revisions + поллинг (replay возвращает
  готовый job, дубли не создаются).
- `components/PassportDocumentsPanel.tsx` — вкладка «Паспорта свойств»:
  (а) сохранённые P01/P02 (PrintDocumentsPanel); (б) «Восстановить
  паспорта» — режим «Один паспорт» (radio одного snapshot-ref) /
  «Комплект траектории» (radio checkpoint; default — §8) / «Сравнение»
  (radio checkpoint или два snapshot-ref); таблица источников с
  stage/universe/target/date/captured_at/fingerprint/content_status;
  подтверждение → POST passport-documents → сводка resolved-точек/gaps/
  completeness (outcome.display) → поллинг job → предпросмотр/скачивание
  (PNG или ZIP по output_format; metadata_url — JSON).
- `components/DocumentationWorkspace.tsx` — сегмент-фильтр семейств
  (кнопки aria-pressed: «Документы» / «Паспорта свойств» /
  «Визуализации»), default «Документы» (прежнее поведение байт-в-байт);
  в паспортах — честная подпись разведения D02 и P01.

JobPayload (`lib/documentation.ts`) аддитивно получает
`output_format?: string; metadata_url?: string` — паритет DTO PGV-14.

### 3.3 Карта роутов (затронута: +1 READ)

- `docs/auth00/policy_review.json`: +классификация
  `api:GET:/v1/documentation/runs/{run_id}/print-documents`
  (policy `document.object`, effects `["read"]`, admission
  `authorize-before-operation`, canonical
  `documentation.list_print_documents_route`).
- `apps/api/access_registry.v1.json`: +операция и binding.
- Регенерация в порядке access_registry → auth01 → auth06 → inventory:
  `scripts/auth01/generate.py --write` (TS-контракт обеих apps),
  `scripts/auth06/generate_proxy_routes.py --write` (allowlist),
  `scripts/auth00/inventory.py --write` (inventory.json/md).
- `scripts/pgv15/check_routes_auth00.py` — task-гейт: AST-дифф
  routers/documentation.py с картой fc510f0 = ровно 3 added
  (2×PGV-13 + 1×PGV-15), 0 removed; policy/binding присутствуют;
  basis-каталог и печатные kinds согласованы.
- `scripts/local_gates.py` НЕ меняются (корпус PGV-15 гоняют штатные
  гейты pytest (tests/) и jest; auth00/auth01/auth06 проверяют карту) —
  протокол паритета PGV-13; изменения фиксируются в local_gates.md.

## 4. Риски и меры

| Риск | Мера |
|---|---|
| Скрытая подмена D02 → P01 | Отдельные подписи/секции; D-каталог не изменяется; тест-гвард на текст разведения |
| Листинг раскрывает чужой run | Read-авторизация до чтения; uniform 404; тест на отсутствующий run |
| N+1/тяжёлый листинг | ≤3 документов, одна выборка jobs; metadata-only, без байтов |
| Дубли jobs из UI | Replay-ready идемпотентность POST print-revisions (AC09) + паритет «повторный клик» |
| PNG-предпросмотр как обход attachment | Blob через тот же защищённый content-маршрут с credentials; URL отзывается; никакого нового маршрута |
| ZIP «нарисован» клиентом | Комплект не рисуется: состав страниц из frozen metadata.json + честная подпись; скачивание ZIP как есть |
| Поломка существующих D-тестов | Фильтр default «Документы»; разметка прежних областей не меняется; существующие suite должны пройти без правок |
| TDD-дисциплина | RED-корпус до кода; negative controls; никакие skips не добавляются |

## 5. Границы поставки

Не входит (спека): PGV-16 (security/retention/coverage-гейты), полная
CERT-приёмка AC01…24 на VM, native Chromium-рендер (остаётся PGV-14 этапом),
смена форматов D01–D12, переименование D02, новые научные расчёты.
Runtime-образы API/web не требуют пересборки из-за UI-пакета — только при
выпуске новой сборки web на VM (команды выдаются отдельно).
