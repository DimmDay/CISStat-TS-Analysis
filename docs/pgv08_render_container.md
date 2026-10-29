# PGV-08 — Sandboxed renderer container (документ поставки)

**Дата:** 29 октября 2026. **База:** `main@c3dab21` (PGV-07-CERT; поставка PGV-07 — 726b31d, PGV-06-FIX — 0756a34, PGV-07-CERT — c3dab21). **Статус:** изолированный контейнер рендера PNG поверх общего print-бандла PGV-07; jobs/CAS/lease не менялись (PGV-09). **Родительский контракт:** `spec_documentation_logging.md` §11/§12/§18. **Проектная спека:** `spec_passport_graphics_visual.md` §4.1, §7, §11–13 (строка PGV-08), §14 (приёмочные сценарии).

---

## 1. Назначение и границы

PGV-08 реализует строку PGV-08 проектной спеки: «**Sandboxed renderer container**», точки изменения «`apps/print-renderer/build/deployment`», критерий готовности — «**Final image smoke кириллица/IH/A4, no-network/non-root/hard timeout**». Контейнер принимает frozen payload `pgv.render_payload/1` (снапшот PGV-01 + контент секций), собирает print page ИЗ ОБЩЕГО БАНДЛА PGV-07 (§4.1: «без второй реализации» — react-dom/server, не Python-дубль) и растеризует её headless Chromium в PNG профиля с pHYs 300 ppi.

**Границы поставки (честно):** print-бандл (presentation) — PGV-07; очередь/lease/CAS/renditions — PGV-09; producer-адаптеры экранных остановок — PGV-10…12; builders P01/P02 — PGV-13. Экранная science-геометрия для `recharts_svg` приходит сериализованным frozen SVG (`svg_xml` — §4.1 passthrough); её подключение к экранам — PGV-10…12, без него секция честно печатает placeholder («научная геометрия не приложена»), график не фабрикуется.

## 2. Состав поставки (файлы)

| Файл | Роль |
|---|---|
| `apps/print-renderer/package.json` | workspace-пакет `@cisstat/print-renderer`; точные пины: `playwright-core 1.57.0` (== chromium-1200), `react/react-dom 18.3.1` |
| `apps/print-renderer/tsconfig.build.json` | Сборка dist из монорепо (rootDir `../..` — dist содержит компилированный print-бандл PGV-07) |
| `apps/print-renderer/src/rendererCore.tsx` | Чистое ядро (без playwright): версии контрактов (`pgv.render_payload/1`, `print-renderer/1`, порт 8907), валидация payload (коды паритета PGV-01), dependency-манифест (AC17), sandbox-спецификация + политика запросов (AC19), санитайзер frozen SVG, pHYs-инъекция 300 ppi (AC16), SSR print page (CSP `default-src 'none'`, reset, lang=ru), hard-timeout зажим (AC20), тела ошибок с честной retryability |
| `apps/print-renderer/src/renderWorker.ts` | Браузерный слой: config (env allowlist `CISSTAT_PRINT_RENDERER_*`), ленивый синглтон браузера с честной диагностикой, дедлайн на ВЕСЬ рендер (§11), SIGKILL браузера по таймауту, cleanup контекста в finally, семафор max_concurrent, ReadyzCache |
| `apps/print-renderer/src/server.ts` | HTTP-сервис (node:http, без express): `GET /healthz`, `GET /readyz` (browser/fonts/bundle + mini-smoke кириллицы; провал probe → 503, никогда не ложный ready), `POST /v1/render` (PNG + X-Render-* заголовки), `POST /v1/smoke`; лимит тела 8 MiB (честный 413), SIGTERM-shutdown |
| `apps/print-renderer/src/smokeScenarios.ts` | Смоук-сценарии на своих данных: S1 «кириллица» (figure-landscape, карточки+таблица), S2 «IH» (a4-landscape, PrintIhConditionalMatrix), S3 «A4» (a4-portrait); структурные проверки PNG байт-уровнем (IHDR == px профиля, pHYs 11811, непустой IDAT, различимость sha256) |
| `apps/print-renderer/src/smoke.ts` | Entrypoint контейнера: `--serve` (прод), `--probe` (healthcheck), `--smoke` (полный смоук финального образа) |
| `apps/print-renderer/src/rendererCore.test.ts` | Jest-оракулы ядра: 35 тестов — версии, pHYs (вставка после IHDR/идемпотентность/конверсия ppi/CRC), dependency-манифест (AC17), sandbox-политика (AC19), санитайзер, таймаут-контракт (AC20), валидация payload, SSR (кириллица/IH/геометрия/CSP/без script и внешних URL/честный placeholder/таблицы/карточки) |
| `apps/print-renderer/build/Dockerfile` | Multi-stage: build (node:24-bookworm-slim + tsc) → browsers (пин `playwright@1.57.0` → chromium-1200 в /opt/pw-browsers + fonts-dejavu-core) → final (non-root uid 10001, USER, HEALTHCHECK probe, EXPOSE 8907, env hard timeout 60) |
| `apps/print-renderer/build/deployment/docker-compose.yml` | `network_mode: none`, `user: 10001:10001`, `read_only: true`, tmpfs `/tmp` noexec+nosuid, `cap_drop: ALL`, `no-new-privileges`, mem 2g, pids 128, healthcheck `/readyz`, публикация только на 127.0.0.1 |
| `apps/print-renderer/build/deployment/README.md` | Runbook: сборка/запуск/смоук образа/проверки изоляции/HTTP-контракт/слои AC19/таймаут/риски R1–R4 |
| `tests/api/test_pgv08_render_container.py` | Python-оракулы deployment-инвариантов: 22 теста — пины Dockerfile/package.json, no-network/non-root/read-only/cap-drop/tmpfs, hard timeout 60 == PGV-01, kill в worker, маршруты, отсутствие секретов (паттерны фактического использования), env-allowlist, смоук кириллица/IH/A4, runbook |
| `scripts/pgv08/verify_local.py` | Браузерная приёмка на реальном Chromium (тот же пин, что в Dockerfile): 20 E2E-проверок (§4) |
| `scripts/pgv08/check_documents.py` | Doc-contract гвард поставки |
| `scripts/pgv08/protocols/` | red_jest.txt, red_python.txt, smoke_run.json, local_verification.json, server_main.log, server_dependency.log |
| `jest.setup.js` | +polyfill TextEncoder/TextDecoder (SSR-оракулы react-dom/server в jsdom) — единственное изменение вне print-renderer |
| `package.json`, `package-lock.json` | workspace `apps/print-renderer` + пин playwright-core 1.57.0 |
| `worklog/worklog11.md` | Запись Task ID: PGV-08 |

## 3. Проектные решения

### 3.1. Node-рендерер с общим бандлом, не вторая реализация (§4.1)

Print-бандл PGV-07 — React TSX; рендер-контейнер собирает страницу через `react-dom/server` из ТЕХ ЖЕ компонентов (PrintPageFrame/printSections/printIh), поэтому screen и print остаются одной реализацией научной геометрии. tsc-сборка включают `packages/ui/print/**` в dist (rootDir монорепо) — контейнеру не нужен исходный tree: dist + react/react-dom + playwright-core. Python-дубль композиции сознательно не создаётся.

### 3.2. Sandbox — защита в глубину (AC19)

Слои: (1) контейнер — `network_mode: none`, non-root 10001, read-only, `cap_drop ALL`, no-new-privileges, tmpfs noexec/nosuid; (2) браузер — страница с `javaScriptEnabled=false`, `serviceWorkers=block`, `bypassCSP=false`, запуск без GPU/фоновых служб; (3) политика запросов — http/https/file/blob/ftp/ws абортятся ДО сети, разрешены только `data:`/`about:blank`; (4) контент — страница только из SSR-строки общего бандла (никакого пользовательского HTML), CSP meta `default-src 'none'`, frozen SVG санитизируется (script/foreignObject/on*/внешние href — с честными warnings в `X-Render-Sanitized-Warnings`); (5) секреты — env только `CISSTAT_PRINT_RENDERER_*`, worker не читает и не принимает cookie/токены («worker без browser secrets»). Chromium-песочница сознательно НЕ выключается (`--no-sandbox` не используется): при недоступном userns запуск падает честно (fail-closed), а не ослабляет изоляцию (R1).

### 3.3. Hard timeout на весь рендер (AC20, §11)

Дедлайн = `min(options.timeout_s, CISSTAT_PRINT_RENDERER_HARD_TIMEOUT_S)`, зажим [1, cap], по умолчанию 60 s == `PRINT_LIMITS.render_timeout_s` каталога PGV-01 (пин через каталог, не литерал). Дедлайн покрывает ВЕСЬ рендер (dependency-манифест → запуск → контекст → setContent → layout → скриншот → pHYs): SSR/layout не могут выйти за cap. Превышение — `RenderTimeoutError` → SIGKILL процесса браузера → сброс синглтона (следующий запрос повторяет честную диагностику) → cleanup контекста в `finally`; ответ 503 `render_timeout` с `X-Render-Retryable: true` (очередь PGV-09 переоткладывает по своим attempt-лимитам). Temp-след Chromium убирается `context.close()`, `/tmp` контейнера — tmpfs.

### 3.4. Честный readiness (AC17, §12)

`/readyz` проверяет browser/fonts/bundle РАЗДЕЛЬНО: путь браузера обязан СУЩЕСТВОВАТЬ (непустая строка не признаётся зависимостью), шрифты — пинованные файлы DejaVu, бандл — импорт ядра. Поверх манифеста — mini-smoke реального рендера кириллицы (scale 0.05); провал probe → 503 `render_dependency_unavailable`/`smoke_probe_failed` (находка E2E: промежуточная версия возвращала «ready» с checks.smoke=false — исправлено, ложный ready запрещён). `render_dependency_unavailable` — терминальная (retryable=false): бесполезный retry исключён; коды причин — `missing_browser`/`missing_fonts`/`missing_bundle`.

### 3.5. pHYs 300 ppi (AC16)

Скриншот Chromium не несёт физического размера; ядро вставляет pHYs (unit=метр, 11811 px/m для 300 ppi) сразу после IHDR с пересчётом CRC, идемпотентно (существующий чанк заменяется), байты изображения не трогаются. PNG получает честные метаданные 300 ppi: Pillow читает dpi=(300, 300); пиксели профиля (2400×1500 / 2480×3508 / 3508×2480) соответствуют мм листа.

### 3.6. Детерминизм (§12)

Пины: node:24-bookworm-slim, playwright-core 1.57.0 == chromium-1200 (Chrome for Testing 143.0.7499.4), fonts-dejavu-core (DejaVu Sans — голова `PRINT_FONT_STACK`), `--force-color-profile=srgb`, `--font-render-hinting=none`, `--hide-scrollbars`. Byte-determinism подтверждена в pinned runtime E2E (два рендера — sha256 совпали); между билдами — semantic/visual tolerance по §12. Смоук — последовательный (вердикт не зависит от max_concurrent).

## 4. TDD и верификация

**RED (jest):** `rendererCore.test.ts` до реализации — collection RED `TS2307: Cannot find module './rendererCore'` (честный Import-RED, `protocols/red_jest.txt`). **RED (python):** 22/22 FAILED на отсутствующих файлах поставки (`protocols/red_python.txt`).

**GREEN:** ядро 35/35; deployment-оракулы 22/22. В процессе GREEN оракулы поймали три дефекта самих оракулов (shortRef keep=10, ru-группировка «9 876», CRC-офсет) — исправлены в оракулах; два дефекта РЕАЛИЗАЦИИ пойманы E2E и исправлены: (1) дедлайн покрывал только скриншот — переписан на весь рендер; (2) readiness возвращал «ready» при проваленном smoke-probe и признавал непустой несуществующий путь браузера — исправлено на честный 503.

**Смоук образа (критерий §13):** `--smoke` — passed: кириллица 2400×1500, IH 3508×2480, A4 2480×3508, все pHYs 11811, хэши различимы (`protocols/smoke_run.json`, ~0.5 s/страница).

**Браузерная приёмка E2E (`verify_local.py`, реальный chromium-1200): 20/20 PASSED** (`protocols/local_verification.json`): readyz=ready (browser/fonts/bundle/smoke); кириллица — размеры/300 dpi/непрозрачный белый фон (AC23)/ink>0.5%/**OCR tesseract rus распознал «Оборот розничной торговли по месяцам»**; IH — синие тепловые ячейки >0.3%, OCR заголовка; A4 — пропорция 210/297 (AC16); byte-determinism sha256 (§12 pinned); AC19 — враждебный SVG (script/foreignObject/onload/remote img/file): слушатель получил 0 соединений, sanitized_warnings=4, PNG валиден; AC20 — 9000×6 с timeout_s=1 → 503 render_timeout retryable=true, после kill обычный рендер 200 (восстановление); AC17 — сервер с `/nonexistent` браузером: readyz 503 missing_browser, render 503 render_dependency_unavailable terminal; перегрузка — 3 параллельных → [200, 200, 429].

**Регресс:** полный jest 2656 тестов: 2651 passed + ровно 5 известных RED-свидетельств PGV-07-CERT (Class B: F-P7C1/C2/C3 в `scripts/pgv07cert/test_p7cert_findings.test.tsx`, ждут PGV-07-FIX) — новых падений 0; TextEncoder-полифилл класса средовых полифиллов (ResizeObserver/IntersectionObserver). `typecheck:all` ✓.

## 5. Вклад в приёмочные сценарии (§14)

| Сценарий | Вклад PGV-08 |
|---|---|
| PGV-AC04 | Печать всегда из инлайнов light-темы бандла; контейнер не имеет экранной темы; byte-determinism E2E |
| PGV-AC16 | pHYs 300 ppi + точные px всех трёх профилей + пропорция A4 (оракулы ядро+E2E) |
| PGV-AC17 | Dependency-манифест browser/fonts/bundle + smoke-probe; 503 render_dependency_unavailable без ложного ready (E2E-7) |
| PGV-AC19 | Слои sandbox: no-network/non-root/JS-off/request-block/CSP/санитайзер/env-allowlist; E2E-5: 0 внешних соединений, секретов нет (python-оракул) |
| PGV-AC20 | Дедлайн всего рендера + SIGKILL + cleanup + retryable-контракт; E2E-6: timeout→kill→recovery |
| PGV-AC23 | Смоук образа кириллица/IH/A4; E2E пиксельная форензика (непрозрачный фон/ink/синие ячейки) + OCR-rus заголовков; частичный tesseract-контекст — честная граница |
| PGV-AC24 (база) | Worker без состояния сессии: kill/перезапуск браузера прозрачен для очереди (E2E-6.recovery); полная приёмка обеих оболочек — PGV-09/CERT |

## 6. Ограничения и переходы

1. **Docker-демона в среде сессии нет** (честная граница R2): финальный образ не собирался в сессии; deployment доставлен как код (Dockerfile/compose/runbook), приёмка выполнена на ТОМ ЖЕ пинованном стеке (chromium-1200/DejaVu/node 24), смоук образа — entrypoint `--smoke`, чекающийся пином chromium-1200 на этапе сборки.
2. `recharts_svg` принимает сериализованный frozen SVG (`svg_xml`); подключение экранной геометрии producer'ами — PGV-10…12; без него — честный placeholder без фабкации.
3. Пагинация page-set/ZIP — PGV-14; контейнер рендерит одну страницу за запрос (`pageIndex/pageCount` — метаданные подвала).
4. OCR-ru в среде — загруженная tessdata_fast (session tooling вне репо); в CI образе OCR-контур — отдельная задача CERT (PGV-AC23 в полном объёме).
5. Манифест sha256 поставки не ведётся (указание тимлида, прецедент серии).
