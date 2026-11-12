# AUTH-CERT — Сквозная приёмка сервиса (design)

Дата: 12.11.2026. База: 3c3e8b7 (AUTH-25 + HOTFIX-01/02 в origin/main; сервер и образы VM на ней, схема 0033/0034/0035 применена). Постановка: spec_auth_architecture.md (строка DAG AUTH-CERT, §10, §12.5) + spec_auth.md (§16 п.7, §17 AUTH-AC01…30). Зависимости выполнены: AUTH-07, AUTH-10, AUTH-11, AUTH-14, AUTH-16…20, AUTH-25 (worklog12).

## 1. Объект приёмки и границы

AUTH-CERT не добавляет функциональность: это независимая приёмка ЦЕЛОГО контура отдельными suite'ами
(API / demo-forum / concurrency / failures / billing / browser). Код продукта не меняется; поставка =
оракулы + гейты + документ приёмки. «Сквозная» означает проверку ШВОВ между задачами, которые ни одна
отдельная задача не могла проверить:

- один User в двух Account не переносит данные/кэши/ключи; MONO→MULTI сохраняет run IDs (§10);
- OWNER не ADMIN; internal entitlement не отменяет tenant/object policy (§10, AC03);
- Demo проходит upload→validation→preprocessing→EDA→bounded modeling→forecast; прямой
  tuning/custom/прикладной endpoint закрыт (§10, AC18);
- одновременные invite/seat/CU admission, crash после reserve/до queue и после execute/до settle
  не создают двойной расход или бесплатный результат (§10, AC13/AC14);
- pause/revoke/expiry действуют на upload, analysis, downloads, progress, restore, polling (AC15);
- ENV removal / key rotation / backup restore сохраняют владение и не воскрешают отзыв (§10, AC27);
- billing: callback spoof / повтор и out-of-order webhook / refund-versus-spend race / chargeback
  после settle / seat churn / purchased на смене цикла / приватность MEMBER / integer rounding (§12.5).

## 2. Ключевые решения

- **D1. Объект — полный `apps.api.main`** (285 маршрутов, полный middleware-стек: CORS configured
  origins, TelemetryContext, TraceHook, AUTH-06 origin/cookie гейты). Прецедент PROGR-AUDIT-CERT:
  подмножество роутеров маскирует швы (CORS/origin-конфликты, hook-порядок), поэтому cert строит
  production-like деплой целиком, а не копирует подмонтажи отдельных задач.
- **D2. Deployment-like среда, а не schema-per-test.** Один disposable PostgreSQL 16.2 (pgserver под
  непривилегированным UID) на процесс приёмки; для каждого suite-класса — чистая база (CREATE/DROP
  DATABASE с uuid-именем) и полная цепочка миграций 0019→0035 реальным мигратором refund_migrations
  (рекурсивно гарантирует 0019…0034). Модель «один деплой — много субъектов»: isolation через
  уникальные логины/campaigns/email, а не через отдельные схемы — паритет прод-топологии, без которой
  AC06/AC07/AC25 (кросс-субъектные инварианты) вырождаются.
- **D3. required-режим хранения.** CISSTAT_STORAGE_MODE=required: session/runs/artifacts/snapshots/
  documents factories на том же disposable DSN (сами применяют свою DDL при конструировании), старт
  через настоящий lifespan (_lifespan) на TestClient. AUTH-CERT принимает реальный стартовый контур,
  а не advisory-подмену.
- **D4. Транспорт — настоящий HTTP** (fastapi.testclient поверх ASGI): CSRF-токен из /v1/auth/csrf,
  Origin из configured_origins (CISSTAT_AUTH_ALLOWED_ORIGINS), first-party cookies (__Host-cisstat_auth,
  __Host-cisstat_csrf),MFA-челленджи, demo enter/resume с resume-cookie. Составные оракулы AC21–AC23
  проверяют форму Set-Cookie (host-only, без Domain/Expires-утечек) и отказы CSRF/Origin на живом стеке.
- **D5. Шесть suite-файлов** («отдельные API/browser/concurrency/failure suites» DAG-строки):
  `test_authcert_browser.py` — статические оракулы UI-слоя обеих оболочек (без DSN, входит в default-гейт);
  `test_authcert_api.py` — identity/session/MFA/admin/team (AC01–AC05, AC09/AC10, AC17, AC21–AC23, AC25, AC03);
  `test_authcert_demo.py` — форум (AC06/AC07/AC11/AC12/AC15/AC18 + §10 pipeline E2E);
  `test_authcert_concurrency.py` — гонки (AC13/AC14/AC26 + §10 no-double-spend, threads + PG-уровень);
  `test_authcert_failures.py` — отказы (AC19/AC20/AC27 + §10 key rotation/ENV removal/restore);
  `test_authcert_billing.py` — финансовый слой (§12.5 сквозные композиции).
- **D6. Harness — общий модуль `authcert_harness.py`** (не test_*.py, чтобы discovery не поднимал как
  suite): разворачивание Deployment (база+миграции+stores+app.state), фабрика HTTP-клиентов,
  admin-bootstrap (MfaService.prepare_bootstrap/bootstrap), демо-кампании, уникальные идентификаторы,
  supervised-child среду для bounded modeling (паритет AUTH-16: CISSTAT_WORKER_KEY + proof dir +
  CISSTAT_STORAGE_MODE=required). Никаких правок продового кода: только env/state подстановка в
  пределах тестового процесса.
- **D7. TDD-протокол приёмки:** RED-1 — гейт `verify_postgres.py` до существования suite-файлов даёт
  «No tests ran» → exit 1 (не PASS по построению); GREEN — полный прогон на disposable PG; затем
  предрегистрированная мутационная кампания: дизъюнктные ослабления контура (по одному на suite),
  каждый мутант обязан быть убит cert-оракулом, восстановление по backup-копии с побайтовым cmp
  (практика §20 саммари). Мутации применяются во временных копиях, коммит не создаётся.
- **D8. Гейты:** новый default `authcert` (browser-сюита: py_compile-независимая статика + структура
  оболочек) и opt-in `authcert-postgres` (native API/demo/concurrency/failures/billing) — флаг
  `--with-authcert-postgres` и `excluded.add` в ОДНОМ изменении (урок AUTH-22-HOTFIX-01);
  `verify_postgres.py` без DSN возвращает 2, skips запрещены (паритет auth25). CI
  `.github/workflows/authcert.yml` (Ubuntu/Windows contracts + PG16/18 native).
- **D9. Роуты и инвентарь:** HTTP-маршруты не меняются (поставка без продового кода). Гейт
  check_routes/AUTH-00: actual == inventory (281), added/missing=[], отпечатки пересчитываются
  официальным `inventory.py --write` после финализации новых файлов (порядок «производные → inventory»).
- **D10. Честные границы акта:** реальный браузер/E2E не запускался (UI-слой: статические оракулы +
  ссылка на полный Jest 2882/2skips AUTH-24); Redis в auth-контуре проекта отсутствует (AUTH-20) —
  требование спеки «реальный PG/Redis» фиксируется как «реальный PG; Redis-требование N/A для текущего
  контура»; IdP/SMTP/магазин не вызывались; money-путь проходим только через trusted-провижининг
  (WalletService/issue-команды), provider-адаптер не трогается; AC30 (ёмкость) —
  не замеряется заново: опирается на measured AUTH-14 reference (90/90 checks) и помечена
  «эксплуатационная приёмка при launch»; PG18/Windows — удалённая CI-матрица. Никакого
  «production certified»: вердикт — cert-suite PASS на disposable PG + открытые пункты операторской
  приёмки (VM).

## 3. Точки изменения (файлы)

- NEW `tests/integration/authcert_harness.py` (deployment-харнесс)
- NEW `tests/integration/test_authcert_{browser,api,demo,concurrency,failures,billing}.py`
- NEW `scripts/authcert/{verify_postgres.py,verify_browser.py,requirements.txt,files.txt}`
- scripts/local_gates.py/.md (+2 гейта: default authcert, opt-in authcert-postgres)
- NEW `.github/workflows/authcert.yml`
- NEW `docs/authcert/{design.md,verification.md}` (verification — матрица AC01…30 → cert-тест/существующий suite/граница)
- worklog/worklog12.md (запись AUTH-CERT)

Не меняются: apps/**, deployment/**, миграции, OpenAPI/TS/proxy-карты (маршруты прежние).

## 4. Риски

- R1: lifespan полного приложения стартует фоновых воркеров — в cert-прогоне все переключатели
  выключены (CISSTAT_DELIVERY_WORKER_ENABLED=0, CISSTAT_DOCUMENT_RENDER_WORKER_* off, sweepers
  INTERVAL=0), worker_bootstrap получает валидный ключ (иначе честный warning, старт не роняется).
- R2: общий процесс + один app-синглтон: каждый тест ставит app.state.auth_access_store и env через
  patch.dict с addCleanup; проникновение состояния между тестами контролируется уникальными
  идентификаторами субъектов и финальной сверкой счётчиков.
- R3: supervised child (реальный baseline) — CPU/время: только monthly-ряд 120 точек, folds≤3,
  trials≤2, один запуск на cert-прогон (как в AUTH-16 native).
- R4: гонки на threads против TestClient — ASGI-портал потокобезопасен для независимых запросов;
  конкурентность строго ограничена 2–8 потоками и валидируется пост-условиями (счётчики PG), а не
  таймингами.
