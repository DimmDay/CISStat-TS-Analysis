# DOCLOG-0 — Идентичность и контракт (контрактный документ)

*Task DOCLOG-0, 2026-10-22. Спецификация-источник: `spec_documentation_logging.md`
(§9.1 «Модель идентичности и происхождения», §15 «Права, tenancy и защита
выдачи», §15.1 «Переход от текущих сессий», §19 строка DOCLOG-0, §20 AC06,
§22 «Решения для старта»). База: main@cc5c14e. Поставка следует AGENTS.md
(TDD RED→GREEN→регресс, без commit/push).*

## 1. Постановка и граница задачи

DOCLOG-0 — первый блокер эпика документирования/логирования (§19):
**«нельзя читать чужой run/document/artifact/job во всех путях,
существующий report учтён»**. В границу задачи вошли: owner/tenant/scopes,
политика legacy-владения, threat model, схемы IDs/validity/completeness —
и их применение к СУЩЕСТВУЮЩЕМУ run-контуру (слой 2 «Прогресса»):
все run-маршруты закрыты объектной авторизацией. Вне границы (по §19):
durable-артефакты (DOCLOG-1), ReportSnapshot (DOCLOG-2), телеметрия/
durable audit-поток (DOCLOG-3), UI выдачи (DOCLOG-4). Здесь audit-след
решений — журнал приложения (`AccessDecision`), durable-поток — будущая
задача DOCLOG-3.

## 2. Что реализовано (карта изменений)

| Файл | Состав |
|---|---|
| `apps/api/identity.py` (НОВЫЙ) | Субъекты/tenant/scopes, псевдонимизация, validity-схемы, решающая таблица `authorize_run_access`, threat model в докстринге модуля |
| `apps/api/plans.py` | `AuthenticatedPrincipal` + аддитивные `subject_id`/`tenant_id`/`scopes` (None — честное отсутствие) |
| `apps/api/auth.py` | Аддитивный формат реестра ключей `key:role:plan[:subject:tenant[:scopes]]` (scopes через «+»); fail-closed: subject==key запрещён; без явного subject — псевдоним ключа, НЕ значение; публичный `resolve_principal_for_key` |
| `apps/api/session_store.py` | `AnalysisSession` + `owner_subject`/`tenant_id` (аддитивные, сериализуются — урок F1), `ensure_owner_binding()` (first-write-wins), `SESSION_SCHEMA_VERSION` 3→4 |
| `apps/api/research_runs.py` | `ResearchRun` + `owner_subject`/`tenant_id`/`ownership` (аддитивные Optional, NULL/отсутствие = легаси); merge-семантика COALESCE (Memory `_merge_run_additive` + SQL upsert); привязка при создании в `_mirror_run_base`; гвард зеркала слоя 2 (чужой субъект в bound-run не пишет); `MIGRATION_STATEMENTS_0006` |
| `apps/api/migrations/0006_doclog0_run_ownership.sql` (НОВЫЙ) | Аддитивная миграция: 3 колонки + 2 индекса; файл — дубль каталога (паритет страхуется тестами) |
| `apps/api/routers/progress.py` | Единая точка `_authorized_run` (объектная авторизация) на 9 run-маршрутах: detail, report, pause, resume, checkpoints, restore, delivery (2), mentor/next-step; restore наследует владельца; uniform 404 (тело 404 не различает отсутствие и отказ) |
| `apps/api/upload_common.py`, `apps/api/routers/session.py` | Привязка владельца в единой точке регистрации датасета (файл И БД) и демо-загрузке |
| `apps/api/storage_diagnostics.py` | `/health/ops` — честный identity-блок (режим, enforcement, дефолт-tenant, факт конфигурации реестра БЕЗ значений) |
| `tests/api/test_doclog0_identity.py` (НОВЫЙ) | 42 оракула: псевдонимизация, validity, каталог scopes, реестр, решающая таблица, персистенция, миграция, API-гейты, restore-наследование, гвард зеркала, ops-блок |

## 3. Идентичность: субъект, tenant, scopes

### 3.1. Субъект (§15: «стабильный безопасный ID, не значение API-key»)

- **Псевдоним**: `subject_pseudonym(material)` = `subj-` + HMAC-SHA256(соль,
  материал)[:16] (hex). Материал (значение ключа/cookie) невосстановим и
  не содержится в псевдониме (T4). Один материал — один субъект
  (стабильность); смена соли (env `CISSTAT_IDENTITY_SALT`) меняет все
  псевдонимы (ротация — часть политики).
- **Соль**: по умолчанию — явно задокументированная dev-константа
  (`_DEV_SALT`); продакшен обязан задать `CISSTAT_IDENTITY_SALT`
  (§22: решения — versioned ADR, не молчаливые значения).
- **Приоритет резолва** (`resolve_request_subject`): валидный API-ключ →
  субъект ключа (явный `subject_id` реестра или псевдоним ключа); иначе
  cookie-сессия → **замороженный владелец серверной записи** сессии
  (`AnalysisSession.owner_subject` — first-write-wins/restore-наследование),
  иначе детерминированный суррогат cookie; без cookie и ключа — аноним.
  Tenant/subject из НЕподписанных браузерных заголовков не принимаются —
  таких полей в контракте просто нет (§15).
- **Почему замороженный владелец приоритетен суррогату**: restore выдаёт
  сессии НОВЫЙ cookie при УНАСЛЕДОВАННОМ владельце — идентичность
  продолжает владелец, а не новый носитель (континуитет, не новое
  владение).

### 3.2. Tenant

- Серверное поле привязки (`tenant_id`), дефолт `tenant-default`; из
  запроса НЕ читается (R09/T5: query-параметр tenant не определяет
  границу доверия). Сравнение — часть решающей таблицы: mismatch
  запрещает ЛЮБОЙ непривилегированный исход, включая серверный
  континуитет создателя.

### 3.3. Scopes (каталог обязательных прав §15)

`Scope`: `documentation.read/write/export/approve/publish`,
`artifact.data.read`, `logs.read/export`, `audit.read`, `support.grant`,
`policy.admin` — ровно 11. Базовая выдача по роли: ADMIN — полный каталог
(контракт §15.1 «новые admin endpoints сохраняют текущую ADMIN-проверку»);
INTERNAL_ANALYST/EXTERNAL_USER — пусто: documentation.* приходит с
DOCLOG-4+ через policy layer, до тех пор НЕ фантазируется. Явная выдача —
6-й сегмент записи реестра (`scopes` через «+»; запятая занята
разделителем записей). reviewer/support — permission sets (scopes), не
новые enum-роли.

## 4. Владение run: схемы и жизненный цикл

### 4.1. Поля (аддитивные Optional — прецедент AUDIT-6A/PROGR-24)

| Поле | ResearchRun | AnalysisSession | Смысл |
|---|---|---|---|
| `owner_subject` | субъект-владелец | замороженный владелец сессии | псевдоним, не ключ/cookie |
| `tenant_id` | граница доверия | граница сессии | серверный дефолт |
| `ownership` | `"bound"` \| отсутствие | — | явное `bound` ТОЛЬКО у созданных после DOCLOG-0 |

- **None/NULL = честное отсутствие** (легаси-корпус): состояние
  `unresolved` ВЫЧИСЛЯЕТСЯ резолвером (`effective_ownership`), данные не
  переписываются задним числом (§9.2). Словарь run не фабкует поля.
- **Привязка при создании**: `_mirror_run_base` создаёт run только
  `ownership="bound"` с субъектом сессии (§15.1: «owner/tenant binding
  на создание run»). Существующие запуски не перепривязываются: смена
  `session_id` (restore/«последний известный» §5) владельца не меняет.
- **Сериализация**: оба уровня переживают персистенцию (run: to_dict/
  from_dict + COALESCE-merge Memory/Postgres; сессия: session_to_dict/
  from_dict — урок F1 PROGR-25-A-CERT).
- **Миграция 0006**: `ALTER TABLE research_runs ADD COLUMN IF NOT
  EXISTS owner_subject|tenant_id|ownership TEXT` + индексы; читатели
  раньше писателей, legacy-строки остаются читаемыми (NULL).

### 4.2. Решающая таблица `authorize_run_access` (первый совпавший строкец)

| # | Условие | Исход (reason) |
|---|---|---|
| 1 | анонимный субъект (нет cookie и ключа) | DENY `anonymous` |
| 2 | роль ADMIN (key-субъект) | ALLOW `admin` |
| 3 | режим `dev_single_user` | ALLOW `dev_single_user_isolated` |
| 4 | bound ∧ subject==owner ∧ tenant совпал | ALLOW `owner` |
| 5 | bound ∧ session_id==run.session_id (СЕРВЕРНАЯ запись) ∧ tenant совпал | ALLOW `creator_continuity` |
| 6 | bound ∧ иначе | DENY `foreign_session` |
| 7 | unresolved ∧ session_id==run.session_id ∧ tenant совпал | ALLOW `creator_continuity` |
| 8 | unresolved ∧ иначе | DENY `unresolved_foreign` |

Fail-closed: неизвестная комбинация — отказ. **Uniform 404**: отказ
неотличим от отсутствия запуска (код и тело совпадают, сообщение без
run_id) — существование ресурса не дисклоужается тем, у кого нет прав
(R09/§15.2); причина живёт в `AccessDecision` (серверный журнал,
псевдонимы; DOCLOG-3 заменит logger на durable-поток). WRITE-действия
(pause/resume/checkpoints/restore) проходят ту же таблицу с
`action="write"`.

### 4.3. Политика legacy-владения (§15.1)

- Легаси-run (без полей) — `unresolved`; читают создавшая cookie-сессия
  (СЕРВЕРНАЯ запись `run.session_id`, не клиентское заявление) либо
  ADMIN. Это НЕ назначение владельца — непрерывность того же принципала.
- **Внешний share/publish/export через новый сервис для unresolved
  ЗАПРЕЩЕНЫ** — контур DOCLOG-4+ обязан проверять `ownership=="bound"`.
- Привязка легаси — только административная миграция по проверенному
  реестру с записью основания и audit (будущий контур); назначать
  владельца тому, кто первым назвал run_id, запрещено (§15.1).
- **Restore**: gate проверяет владение ДО создания новой сессии; новая
  сессия НАСЛЕДУЕТ субъекта bound-запуска (континуитет); легаси-run
  восстанавливает только создавшая cookie-сессия; `run.session_id`
  перелинковывается на новую сессию (§5 «последний известный» — владелец
  при этом не меняется).

### 4.4. Гвард зеркала слоя 2 (эшелонирование, T2)

`record_run_event` не пишет события от чужого субъекта в bound-run
(fail-closed, warning; легаси-run — прежняя перелинковка §5;
`dev_single_user` — объявленная изоляция). Restore-путь пишет через
`commit_event_batch` напрямую и уже за гейтом.

## 5. Режимы идентичности (`CISSTAT_IDENTITY_MODE`)

| Режим | Семантика |
|---|---|
| `session_scoped` (ДЕФОЛТ, enforced) | каждая cookie-сессия — свой субъект-суррогат; новые run привязаны; чужой доступ отказан. Честный дефолт multi-посетительских развертываний (Render/Vercel) |
| `dev_single_user` (явный) | ЯВНО объявленная изоляция одного аналитика: cross-session разрешён и помечен `dev_single_user_isolated`; не выдаётся за multi-tenant production (§15.1) |
| `scoped` | производственный контракт (субъекты из ключей/portal assertion); структура готова, полный адаптер portal assertion — будущая задача; поведение сейчас = session_scoped (честно помечено) |

Незнакомое значение — fail-closed к `session_scoped` + warning.
`/health/ops.identity` раскрывает режим, enforcement (`owner_bound`),
дефолт-tenant и факт конфигурации реестра ключей (bool, без значений).

## 6. Threat model (реестр угроз контура DOCLOG-0)

| ID | Угроза | Митigation (точка) |
|---|---|---|
| T1 | Держатель run_id (аноним/чужая сессия) читает run/отчёт — прежний report route без owner-проверки (F08 спеки) | решающая таблица на всех 9 run-маршрутах, uniform 404 (progress.py::_authorized_run) |
| T2 | Чужая cookie-сессия пишет в чужой запуск (pause/resume/checkpoints) | тот же gate action="write" + гвард зеркала слоя 2 (research_runs.record_run_event) |
| T3 | Restore назначает владельца тому, кто первым назвал run_id (запрет §15.1) | gate до создания сессии; наследование субъекта, не новое владение; легаси — только создавшая сессия |
| T4 | API-key/cookie используются как идентичность; утечка носителя = кража личности | псевдоним HMAC-SHA256 (identity.subject_pseudonym); subject==key запрещён в реестре; salt env для продакшена |
| T5 | Tenant-граница снимается подменой параметров запроса | tenant — серверное поле привязки; из запроса не читается; mismatch deny в таблице |
| T6 | Секреты в операционных поверхностях | /health/ops identity-блок — режим + bool конфигурации; AccessDecision/логи — псевдонимы; тест-пин «ключ не попадает в ops» |

Границы: ingress/auth-настройки продакшена не исследовались (как в
PROGR-AUDIT-1, H29/H30-класс); доказанной публичной утечки не
утверждается — блокер промышленной выдачи, не обвинение.

## 7. Схемы validity/completeness

- **IDs**: run `RUN-XXXXXXXX` (канон ensure_run_id; `is_valid_run_id`);
  субъект `subj-<hex16>` (серверные суррогаты; префикс `subj-` —
  ЗАРЕЗЕРВИРОВАННОЕ пространство: subj- вне hex-шаблона невалиден);
  tenant `tenant-<a-z0-9->{1,32}`; явные субъекты реестра/портала —
  непустые, без пробелов, ≤64.
- **Validity**: псевдоним детерминирован и стабилен; subject==key
  отклоняется парсером реестра; ownership вне `"bound"` не фабкуется.
- **Completeness** (`AccessDecision`): allowed/reason/run_id/action/
  requester_subject/requester_via — достаточно для будущего audit-потока
  DOCLOG-3; reason НЕ попадает в HTTP-ответы (uniform 404).
- **Разделение имён (§9.1)**: в новых документах `research_run_id` —
  идентификатор исследования (RUN-*), не вычислительного запуска;
  легаси-поля API не переименовываются молча.

## 8. TDD-протокол и рекалибровка затронутых тестов

**RED**: 40 failed + 2 честно-зелёных пина (владелец читает своё; админ
читает чужое — контракты, обязанные остаться зелёными; прецедент
PANEL-MODELS-3c). **GREEN**: 42/42 (3 находки GREEN: зарезервированный
namespace `subj-*`; разделитель scopes «+» — запятая занята записями
реестра; creator-continuity не обходит tenant-границу).

**Рекалибровка F08-класса** (тесты, кодировавшие прежнюю семантику
«знание run_id = право»): три честных паттерна —
- **P1 (континуитет)**: сид/доступ run на cookie-сессии клиента —
  «аналитик читает СВОЙ запуск» (test_mentor_rules: пин клиента
  «seed-session»; test_admin_progress_api: «sess-1»; test_run_report:
  `_seed_full_run(client=...)`; test_progress_progr13b);
- **P2 (admin-ключ)**: сценарии, где нужен доступ к чужому run по
  смыслу задачи (деградация Наставника при истёкшей сессии; снимок
  чекпоинта из чужой сессии; фильтрация корпуса слоя 2) — ADMIN-ключ
  сохраняет текущий контракт §15.1;
- **P3 (bearer владельца при restore)**: «другое устройство»
  восстанавливает запуск С cookie владельца — bare run_id больше не
  право (test_research_runs, test_progress_audit_1a/8, 13b, integration
  cert); новый cookie читается из ответа.

**Пины схемы**: `SESSION_SCHEMA_VERSION` 3→4
(test_session_store/test_status_original_series — история бампов в
комментариях). **Базлайн-сверка**: полный pytest tests/ — дельта 0 против
чистого cc5c14e (git stash; средовой класс базы: psycopg DSN песочницы,
neural-зависимости вне каталога, statsmodels-эпоха — идентичен
сертификационным отчётам). Jest 205 сюит / 2278 тестов зелёные;
typecheck:all 0; next build standalone успешен.

## 9. ADR (решения для старта, §22)

1. **Субъект-суррогат сессии** — транзитный контракт dev/standalone:
   анонимные cookie-сессии получают псевдоним-субъект; полный
   production-субъект (portal assertion/JWT) — будущая задача; в
   `scoped`-режиме поведение задокументировано как временное.
2. **Uniform 404 вместо 403** — существование ресурса не дисклоужается;
   отладочная причина — в серверном журнале (`AccessDecision`).
3. **`creator_continuity` как страховой континуитет** — серверная запись
   `run.session_id` (создание/перелинковка §5) допускает создавшую
   сессию к её запуску даже после возможной потери owner-полей сессии;
   границы tenant/владелец не обходятся.
4. **Разделитель scopes «+»** — запятая занята разделителем записей
   реестра; формат расширяется только аддитивно (rolling deploy).
5. **Привязка легаси — только админ-миграция** — автоматического
   backfill нет ни в коде, ни в данных; индексы 0006 создаются сразу
   (дешевле, чем догонять после роста корпуса).
6. **Дефолт-режим `session_scoped`** — multi-посетительское развертывание
   ts-standalone не объявляет одного аналитика; включение
   `dev_single_user` — осознанный операционный выбор.

## 10. Честные границы и следующие шаги

- Продакшен обязан: задать `CISSTAT_IDENTITY_SALT`; при включении
  durable-хранилища — миграция 0006 применяется автоматически
  (`run_migrations`); `dev_single_user` не включать на multi-tenant
  развертываниях.
- Не покрыто и НЕ заявляется: живой PostgreSQL-прогон 0006 (паттерн
  AUDIT-6A pgserver — приёмка при следующем durable-срезе), portal
  assertion-адаптер (`scoped`-режим), UI-поверхность документов
  (DOCLOG-4), durable audit-поток (DOCLOG-3), админ-миграция легаси-владения.
- Следующие задачи по §19: DOCLOG-1 (устойчивые артефакты) и параллельно
  DOCLOG-3 (telemetry/audit foundation).
