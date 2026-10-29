# PGV-08 — Sandboxed renderer container: recovery delivery

Дата: 29 октября 2026. База исправлений: bddc180218dffaa1a81f10d9f1998f250f174d0d.
Исходный PGV-08-CERT FAILED сохранён в docs/cert_pgv08_2026-10-29.md как история.
Новый акт: docs/cert_pgv08_fix_2026-10-29.md. Это исправленная поставка, не заявление
о том, что отсутствующие ранее файлы уже находились в исходном коммите.

## 1. Назначение и границы

Frozen pgv.render_payload/1 → общий print-бандл PGV-07 → светлый PNG с pHYs 300 ppi.
Рендер не запускает науку. Jobs/lease/CAS/renditions интегрирует PGV-09; producer
экранных графиков — PGV-10…12; P01/P02 — PGV-13; page-set/pagination — PGV-14.

Исправлены F-P8C1…C7 и наблюдения N-P8C1…C6. Количество тестов берётся из
scripts/pgv08fix/protocols/jest_final.json, а не из исторической арифметики.
PGV-07 doc-contract в исходной записи worklog исправлен 62/62 → 41/41;
акт прежней сертификации не переписывался. Исходные протоколы PGV-08 не
выдаются за новые. server_main.log/server_dependency.log теперь содержат
реальные payload-free журналы повторной HTTP-проверки (cold shell launch и
отказ missing_browser), а не восстановленные задним числом старые PNG-логи.

## 2. Состав кода

| Путь | Назначение |
|---|---|
| apps/print-renderer/src/rendererCore.tsx | Общая валидация profile/scale/pixel budget, URL allowlist, SVG reference sanitation, pHYs, SSR composition |
| apps/print-renderer/src/renderWorker.ts | Deadline, отдельный BrowserServer на запрос, kill/cancel/cleanup, SSR thread, concurrency |
| apps/print-renderer/src/launchGuard.ts | PID до handshake, cancellation gate, SIGKILL группе, приватная временная папка; /bin/sh читает скрипт с noexec tmpfs |
| apps/print-renderer/src/htmlWorker.ts | Прерываемый SSR того же PGV-07 бандла, не второй renderer |
| apps/print-renderer/src/server.ts | HTTP/liveness/readiness/render/smoke и shutdown реального worker |
| apps/print-renderer/src/smoke.ts | --probe/--smoke; --serve делегирует реальному server/shutdown |
| apps/print-renderer/src/smokeScenarios.ts | Кириллица/IH/A4, согласованные n=600 и row_totals=100+200+300 |
| apps/print-renderer/build/Dockerfile | Multi-stage Node 24, playwright 1.57.0/chromium-1200, DejaVu, USER 10001, readiness |
| apps/print-renderer/build/deployment/docker-compose.yml | network none/read-only/non-root/caps/tmpfs/лимиты; без фиктивного host port |
| apps/print-renderer/build/deployment/README.md | Build/run/smoke/host sandbox prerequisites, границы |
| scripts/pgv08fix/ | Новые RED/GREEN, runtime HTTP/SSR, mutation/verification evidence |
| tests/api/test_pgv08_render_container.py | Deployment checks и новый parity oracle геометрии shared catalog |

## 3. Deadline и sandbox

На запрос выделен отдельный BrowserServer — таймаут одного не убивает соседний.
Playwright Browser.process() не является публичным API; используется BrowserServer.
Cold-launch PID доступен через приватный shell gate до Chromium handshake.
При дедлайне сначала выставляется cancellation marker, затем SIGKILL группе:
поздний wrapper не может запустить браузер, уже запущенная группа убивается.
После завершения launch/cleanup удаляется приватная временная папка.

Playwright дополнительно ограничивает launch/connect оставшимся бюджетом;
SSR выполняется в отдельном worker thread и прекращается по AbortSignal.
Контекст/скриншот/cleanup входят в тот же deadline. Для production используются
полные профили scale=1; мини-probe 0.05..1 допустим, отрицательный/нечисловой/
больший 1 scale отклоняется до запуска, действует независимый лимит 12 MP.

Chromium sandbox включён явно chromiumSandbox:true; отсутствие --no-sandbox
в нашем массиве само по себе этого не гарантировало. Браузеру передаётся только
минимальное окружение HOME/TMPDIR/locale, не переменные с секретами API.
JS выключен, SW block, bypassCSP=false, CSP default-src 'none'; font-src 'none'.
Request allowlist — только inline data:/about:blank; пустая строка сохранена
как non-request sentinel совместимости. Неизвестные схемы/relative URLs denied.
SVG href/src/xlink разрешают локальные fragments/inline data, остальное удаляется
с предупреждениями; sanitize — защита в глубину, не приём произвольного user HTML.

pHYs удаляется из любой позиции и вставляется один раз после IHDR с новым CRC;
повреждённый/усечённый PNG отвергается. Readiness кэширует и 200, и 503 на TTL
30s, поэтому исправленная dependency видна после TTL. У успешного 200 нет
ошибочного X-Render-Retryable. Старый grep-счётчик процессов удалён: recovery=200
не доказывает отсутствие сирот, для этого есть отдельная cold-process проба.

## 4. Проверки и честные границы

PGV-AC02: семантика IH/знаменатели проверяются Jest на своих и исправленных fixtures.
PGV-AC16: pHYs/CRC/геометрия и parity каталога — unit/static; новые пиксельные размеры
финального image в этой среде не пересертифицированы.
PGV-AC17: реальные HTTP 503 missing_browser без ложного ready и 422 scale до browser.
PGV-AC19: allowlist/CSP/JS/SW/sandbox flag/environment и deployment checks; kernel
sandbox в финальном image требует отдельной проверки на target host.
PGV-AC20: fake-clock late launch + реальный Playwright subprocess PID lifecycle,
HTTP timeout, worker-thread abort и cleanup. Cold executable — намеренно медленный
shell, не настоящий Chromium; эта граница явно есть в runtime report.
PGV-AC23: SSR кириллица и smoke inputs проверены; новый raster/OCR image gate не выполнен.

Docker-демона в среде сессии нет. Chromium download заблокирован gateway;
подробности scripts/pgv08fix/protocols/browser_install.txt. Следовательно полный
критерий §13 «Final image smoke кириллица/IH/A4, no-network/non-root/hard timeout»
остаётся BLOCKED по среде, не объявляется PASSED на основании mocks или статики.
Runbook содержит финальный image gate; нельзя ослаблять sandbox ради зелёного теста.
