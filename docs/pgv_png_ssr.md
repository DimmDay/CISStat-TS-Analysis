# PGV-PNG-SSR — backend payload и необязательные предупреждения

База64a6604b84c9d258a784adf13f7feec2f4fdeaba,27.11.2026 Москва. AGENTS изучен.
VM: uncertain render phase0, lease10:36UTC, signed spool local stopped=true,
remote_unknown=true, outcome=completed. API10:35:02UTC renderer_unavailable;
ответ HTTP500; renderer event render_failed/print SSR failed.
Это не успешный PNG. Старый резерв не сбрасывается.

Локальное воспроизведение на точной базе: native PG16, настоящий upload,
visual freeze/export/basis → build_print_render_payload_from_basis;3 synthetic
payload графика/гистограммы/технической таблицы. Валидатор renderer принимает
все3; compiled buildPrintHtml падает TypeError в PrintNotes: items undefined,
чтение length. Настоящий compiled htmlWorker возвращает print SSR failed.
Python canonical snapshot не содержит warnings/data_flow; они необязательны
для validator, TS builder buildMinimalValidSnapshot добавляет warnings:[],
поэтому прежние unit/readiness/P01/P02 fixtures скрыли несовместимость.

Проект: warnings — optional metadata enrichment. Отсутствие означает отсутствие
переданных заметок, не подмену научных значений/предупреждений. PrintNotes
принимает отсутствующее поле как пустой список; имеющиеся заметки сохраняет.
Поданные null/число/строка/массив не-строк renderer отклоняет на входе422.
Frozen snapshot не изменять/не дописывать defaults при рендере. Не трогать
scientific producers/refs/CAS/ACL/квоты/состояния worker. remote_unknown остаётся
консервативным: generic HTTP500 и TTL не дают права освобождать старый hold.

TDD: прямой SSR из настоящих backend fixtures (не TS convenience builder),
сохранение заметок/отсутствие мутации, malformed metadata refusal; compiled
Worker проверяется без mock. Native cross-language test генерирует payload
заново и запускает compiled Worker; старые PNG integration cases сохраняются.
Default/strict opt-in native local gates +CI; AUTH00 source parity и неизменные
route entries; renderer build + обе Next builds. VM Chromium/UDS/live отдельно.


Итоги: RED9F/1P; GREEN10/10 new cases, исходные layout/core regression вместе
96/96. Compiled worker3/3 backend fixtures PASS. Native PG16:1 новый cross-language
case (3 wire payload) +5 старых PNG lifecycle/integration cases =6/6, skips0,
leftover DB=[]. Strict native local gate PASS. Renderer tsc и обе Next production
builds Node22.23.5 PASS, genuine Inter fonts через offline hook; прежнее Tailwind
broad content warning. AUTH00 entries669 остаются прежними; API285/bindings289.
Полный print-regression и final INDEX/ZIP протоколы приложены в scripts/pgv_png_ssr.
VM actual Chromium/UDS/UI/download и восстановление старого hold не объявляются
успешными на основании SSR unit tests. Панель ресурсов — отдельная поставка,
не часть этой базы/SSR patch. Новая схема/DDL/миграция0038 для SSR не требуются.
VM: docs/pgv_png_ssr_vm.md, новые coherent images, физическое quiescence после
candidate/check; старые jobs/reservations не удаляются. При reserved1/limit1
проверку нового PNG разрешает отдельная конечная выдача concurrency2 штатной
AUTH12 operator CLI с CAS и аудитом (либо через отдельно внедрённую панель).
