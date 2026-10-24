# DOCLOG-9 — Профили организации (контракт поставки)

Задача §19: «DOCLOG-9 — профили организации | DOCX, проверяемый PDF/A, подпись/anchor/WORM при необходимости, оформление | 5+6; выбранный профиль подтверждён валидатором и organisational policy, не названием файла». База: main@659db3d (DOCLOG-0..8 включены, сертификация DOCLOG-7 коллегой включена).

## 1. Постановка и граница

Профиль организации — **версионированная организационная политика выпуска визуальной формы документа**: формат (docx/pdfa), оформление (язык, префикс заголовка, футер, организация) и гарантии (проверяемая конформность валидатором, подпись содержимого, append-only якорь, WORM-холд). Профиль — организационная сущность tenant-уровня: он НЕ является научным данным run'а (переживает run, паритет грантов DOCLOG-7), но применяется к rendition'ам документов.

Ключевой критерий §19 интерпретирован буквально: «выбранный профиль подтверждён **валидатором** и **organisational policy**, не названием файла»:

1. rendition становится ready только если структурный валидатор conformance подтвердил байты (validation record пишется ДАЖЕ при passed — доказательство подтверждения); при failed — job честно terminal failed (`profile_validation_failed`) с findings, ready-файла нет;
2. профиль применяется только если он существует, ACTIVE и соответствует формату рендера (retired/чужой формат — отказ до рендера); профиль — организационный выбор (право `policy.admin`), а не имя в запросе.

### Честные границы (не делаем и почему)

- **Подпись — не юридическая ЭП.** HMAC-SHA256 detached-манифест содержимого (§7: PDF «не электронная подпись»; квалифицированные сертификаты/CSP — организационное решение вне этой поставки). Верифицируемость байтов+метаданных — да; правовой статус — нет.
- **PDF/A-валидатор — структурный, собственный** (`pdfa-structural/1`): проверяет проверяемые маркеры PDF/A-1b (XMP `pdfaid:part=1`/`conformance=B`, OutputIntent `GTS_PDFA1` с ICC-профилем, встроенные шрифты, отсутствие Encrypt/JavaScript/OpenAction/внешних URI). Внешний валидатор veraPDF — следующий срез; до него «PDF/A» не заявляется сертификатом, только честным structural passed.
- **WORM — логический hold** (retention hold DOCLOG-6 на документе с причиной `org_profile_worm`): удаление по draft-retention не трогает. Физический object-lock (S3 Object Lock и т.п.) — организационный выбор инфраструктуры (§8.1).
- **Anchor — локальный append-only реестр** (`doc_anchor_records`, INSERT-only API), не внешний нотариальный сервис/TSN.
- **DOCX — базовый OOXML** (WordprocessingML): структура, стили, кириллица, происхождение (snapshot_id/payload_sha256, пометка generated), таблица утверждений; полные корпоративные шаблоны (.dotx) — будущий срез. Редактирование DOCX вне платформы — external rendition, платформенное approval не сохраняет (§7/§11).
- График/PDF-A при наличии сложной графики, XFA/формы, шифрование PDF — вне границы.

## 2. Ключевые решения

1. **Рендер — чистая функция от (снимок, профиль)**. Оформление профиля входит в байты, поэтому байты rendition = f(snapshot, org_profile). Детерминизм сохраняется: профиль версионирован (name+version_no UNIQUE) и содержимое профиля иммутабельно (retire создаёт статус, не правку); AC03 сохраняется на пару (снимок, профиль).
2. **Профиль фиксируется в rendition/job metadata** (`org_profile_id`, ALTER TABLE ADD COLUMN — аддитивно, паттерн 0011). Идемпотентность AC09 остаётся UNIQUE(snapshot_id, format, redaction_profile): повторный запрос той же цели с ДРУГИМ профилем → 409 `org_profile_mismatch` — одна визуальная форма на цель; смена профиля = новый выпуск через новую ревизию (§11: новая rendition не наследует статус утверждённой).
3. **pdfa — отдельная запись каталога форматов** (`doclog9`): не переименование pdf (§7 P2 «не переименовывать обычный PDF»): отдельный рендер (XMP + OutputIntent + ICC) и отдельный валидатор.
4. **ICC-профиль OutputIntent — программно** через Pillow/littlecms (`ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()`, ~588 байт, сигнатура `acsp`); отсутствие littlecms — честный `RenderDependencyError`, не тихий рендер без OutputIntent.
5. **Права (§15)**: создание/retire профиля — `policy.admin` (не автоматически у ADMIN — через scopes, паритет DOCLOG-6/7); заказ рендера с профилем — существующая `documentation.write` (владелец run'а); чтение списка профилей — аутентификация (аноним — uniform 404, решающая таблица DOCLOG-0); validations/verify — право на run.
6. **Аудит (§14.1)**: `org_profile_created`/`org_profile_retired` — mandatory (класс «смена шаблона/retention policy»); `rendition_validated`/`rendition_anchored` — standard (durable best-effort, сбой не ломает выпуск, но виден).
7. **Подпись**: ключ `CISSTAT_DOC_SIGN_KEY` (env); при отсутствии ключа у профиля с sign_contents — честный terminal failed (`sign_key_unavailable`), НЕ тихая неподписанная ready.
8. **WORM-холд ставится на документ** (RetentionRecord DOCLOG-6, hold_reason=`org_profile_worm:<profile_id>`), если профиль требует; повторная установка — идемпотентна.
9. **Ошибки HTTP (§17)**: 400 unsupported_format; 401 аноним на admin-операциях; 403 без policy.admin/права run; 404 uniform (чужой run/rendition/профиль несуществующий); 409 org_profile_mismatch / org_profile_retired / дубль (name, version_no); 422 профиль не для формата / некорректные поля; рендер-отказы — через job failed, не HTTP.
10. **UI (§12.2/§12.3)**: в панели сборки форматов — docx/pdfa + выбор активного профиля (селект, лейбл «профиль: имя vX»); в списке renditions — статус валидации ТЕКСТОМ (цвет не единственный носитель, §12.3) и кнопка «Проверить подпись»; состояния loading/empty/forbidden/error честные (паритет DOCLOG-8).

## 3. Карта изменений

НОВЫЕ:
- `apps/api/doc_profiles.py` — модель OrganizationalDocumentProfile, реестры ABC/Memory/Postgres (структурный паритет DOCLOG-8), OrgProfileService (create/retire/list/resolve/apply), валидаторы `pdfa-structural/1`, `docx-structural/1`, `signature/1`, HMAC-подпись.
- `apps/api/routers/doc_profiles.py` — 5 маршрутов `/v1/documentation/org-profiles*`, `/v1/documentation/renditions/{id}/validations`, `/v1/documentation/renditions/{id}/verify-signature`.
- `apps/api/migrations/0015_doclog9_profiles.sql` — 3 таблицы + 2 ALTER + 3 индекса.
- `packages/ui/components/doclog9-profiles-ui.test.tsx` — UI-оракулы.
- `tests/api/test_doclog9_profiles.py` — API-корпус.
- `docs/doclog9_profiles.md` — этот контракт.

ОБНОВЛЁННЫЕ:
- `apps/api/document_renditions.py` — каталог +docx/+pdfa (HEAVY), `render_snapshot_docx`, `render_snapshot_pdfa` (+XMP/OutputIntent/ICC через pypdf-обвязку), подпись-манифест.
- `apps/api/document_jobs.py` — `org_profile_id` в DocumentRenditionRecord/DocumentJobRecord; request_rendition(+org_profile_id) с resolve/идемпотентностью/409; complete_render: валидация → подпись → якорь → WORM-холд → регистрация с профилем; диспетчер `_render_snapshot_by_format(snapshot, fmt, profile)`; Postgres-паритет (SELECT/INSERT org_profile_id).
- `apps/api/document_render_worker.py` — resolve профиля по job перед рендером (unavailable → terminal failed), передача в complete_render.
- `apps/api/routers/documentation.py` — payload.org_profile_id в POST renditions.
- `apps/api/security_audit.py` — AUDIT_ACTIONS 24→28 (+org_profile_created/retired mandatory, rendition_validated/anchored standard).
- `apps/api/research_runs.py` — MIGRATION_STATEMENTS_0015 (каталог 15/93).
- `apps/api/main.py` — include нового роутера.
- `packages/ui/lib/documentation.ts` — listOrgProfiles/requestRendition(с профилем)/getRenditionValidations/verifyRenditionSignature.
- `packages/ui/components/DocumentationWorkspace.tsx` — форматы docx/pdfa, выбор профиля, статус валидации.
- `packages/ui/index.ts` — экспорт панели профиля (если вынесена).
- Пины: test_doclog5_formats_worker.py (`test_docx_and_pdfa_still_absent` — форматы введены этой задачей, пин инвертирован честно с комментарием), test_doclog2_snapshots.py, test_doclog3/4/6/7/8 (миграции/маршруты).
- `worklog/worklog11.md` — запись DOCLOG-9.

## 4. Схема данных (миграция 0015)

`doc_profiles` (org-сущность, БЕЗ FK на research_runs): profile_id PK, schema_version, name, version_no INT, format, status active|retired, language, title_prefix, footer_text, organization, validate_conformance BOOL, sign_contents BOOL, anchor_registry BOOL, worm_lock BOOL, created_by/at, retired_by/at, UNIQUE(name, version_no).

`doc_rendition_validations`: validation_id PK, rendition_id, job_id, run_id, profile_id, profile_version_no, format, validator, result passed|failed, findings JSONB, checked_at.

`doc_anchor_records` (append-only): anchor_id PK, rendition_id, content_sha256, profile_id, anchored_by, anchored_at.

ALTER document_renditions / document_jobs ADD COLUMN org_profile_id TEXT NOT NULL DEFAULT ''.

## 5. API

| Метод и путь | Назначение | Право |
|---|---|---|
| GET `/v1/documentation/org-profiles?format=` | Активные+retired профили | аутентификация (аноним 404 uniform) |
| POST `/v1/documentation/org-profiles` | Создать профиль (версия name+v) | policy.admin |
| POST `/v1/documentation/org-profiles/{id}/retire` | Вывести из действия (append-статус) | policy.admin |
| GET `/v1/documentation/renditions/{id}/validations` | Записи валидации rendition | право на run (read) |
| POST `/v1/documentation/renditions/{id}/verify-signature` | Верифицировать подпись байтов | право на run (read) |

POST `/v1/documentation/revisions/{id}/renditions` — payload дополнен `org_profile_id` (опционально; обязательный для docx/pdfa — профиль требуется: «выбранный профиль подтверждён…», безымянный выпуск PDF/A запрещён).

## 6. Критерии приёмки (оракулы)

- §19: профиль подтверждён ВАЛИДАТОРОМ (validation record, failed → не ready) и POLICY (active/формат/право), не названием.
- AC05: рендеры/валидации — чистые функции от (снимок, профиль); наука не трогается.
- AC08: failed-валидация — честный job failed; ready без passed-валидации невозможен по построению.
- AC09: идемпотентность (снапшот, формат, redaction); другой профиль той же цели — 409, не вторая версия.
- AC16: docx/pdfa — без скриптов/внешних ссылок; шрифты встроены; недоверенный текст экранирован.
- AC17: UI-состояния честные; статус валидации текстом.
- §20: «PDF/A — отдельный валидатор; не переименовывать обычный PDF».
