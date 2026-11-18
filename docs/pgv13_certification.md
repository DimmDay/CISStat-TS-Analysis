# PGV-13 — независимая сертификация, 18.11.2026

**Вердикт: NOT CERTIFIED / возврат на доработку.** Проверенная база —
`5d83967b83ddccd74db552ac4d05a43012073ec8` (PGV-13 «P01/P02 builders»).
Штатные 39 Python и 41 renderer-тест проходят, но независимые проверки
воспроизводят блокеры. Успех штатного набора не подтверждает готовность PNG.
Продуктовый код этой поставкой не исправляется; это акт, воспроизводимые
отрицательные проверки и диагностика. Нельзя выкатывать базу как принятую PGV-13.

## Метод и границы

Изучены `AGENTS.md`, `spec_passport_graphics_visual.md`, PGV-13 и его журнал,
контур PGV-00…12: durable promotion/storage, reader/comparison/checkpoints,
print basis/revision/jobs, Python→TypeScript payload, общий print frame,
renderer/launch guard, Dockerfile/compose и порядок развёртывания.
Работа велась в отдельном checkout точной базы, без commit/push и изменений VM.

Оракул `scripts/pgv13cert/test_contracts.py` создаёт собственные факты через
реальные PromotionService, ReportSnapshot и checkpoint registry. Он не импортирует
fixtures авторских тестов. Три физических паспорта имеют mean=0/7/11,
категории, списки периодов, неприменимую метрику с причиной и неизвестную группу
с маркером. Два подтверждения возврата к старту различаются ID/временем;
отдельное unchanged-подтверждение ссылается на паспорт выхода.
Читаются сохранённые refs, не DataFrame. Проверка потери сессии запрещает
обращение к SessionStore; это не физическое уничтожение production-сессии.

Memory и native PostgreSQL запускают одинаковые проверки. Native использует
настоящий PostgreSQL 16.2 и отдельную временную БД на тест, а не SQLite/мок.
Object store локальный. SubjectRef — доверенный аутентифицированный контекст
владельца с scopes; проверяется object gate против реального другого principal.
Полный login/SMTP/CSRF/managed-worker AUTH-13 путь здесь не сертифицируется.

`ssr()` передаёт точный JSON Python в скомпилированный production
`rendererCore.buildPrintHtml`. В двух проверках тела/подтверждения применяется
явно названный `diagnostic_envelope`: только тестовые sampling/result/warnings,
чтобы изолировать следующие дефекты после F-C13-00. Это контрфактический
зонд, не исправление и не доказательство работоспособности исходного payload.
Два отдельных raw-теста никаких полей не добавляют и падают.

Штатный worker сначала запускает браузер и только затем SSR. Поэтому сообщение
о sandbox на VM может маскировать F-C13-00. Этот блокер воспроизведён независимо
от браузера; утверждение «worker падает до запуска Chromium» неверно.

## Находки

### F-C13-00 / P0 — настоящий P01/P02 payload не рендерится

`apps/api/passport_documents.py::_snapshot_skeleton` не создаёт `sampling`,
`result`, `warnings`, ожидаемые общим `packages/ui/print/printLayout.tsx`.
Вызов Python builder → durable basis → build_print_render_payload_from_basis →
скомпилированный buildPrintHtml падает для single и compare:
`TypeError: Cannot read properties of undefined (reading 'applicable')`.
После диагностического добавления sampling следующий обязательный доступ —
`snapshot.result.result_ref`. Схемная валидация этот разрыв не останавливает.
Авторские TS-тесты подставляют паспортные секции в полный V01 envelope и потому
не проверяют фактическую границу языков.

Оракул: `test_python_payload_passes_actual_compiled_renderer[single/compare]`.
До устранения и проверки настоящего payload успешный запуск sandbox недостаточен.

### F-C13-01 / P1 — профиль ревизии расходится с frozen payload

После single/compare в `figure-landscape` запрос тех же refs в `a4-portrait`
создаёт ревизию A4, но переиспользует frozen basis с figure-landscape.
Ключ/digest producer не различает профиль. Геометрия рендера берётся из basis.
Оракул проверяет сохранённую ревизию и реальный payload, а не только ответ API:
`test_requested_profile_matches_revision_and_render_payload` (оба режима).

### F-C13-02 / P1 — reused печатается четвёртым полным паспортом

Для unchanged handoff `mode=set` выдаёт четыре `passport_record` секции на три
физических refs: modeling_entry-алиас повторяется целым паспортом. AC11 требует
факт подтверждения со ссылкой на источник без нового полного паспорта.
Checkpoint-метаданные P01 хранятся как `checkpoint_id/confirmed_at/flags`,
а общий frame ищет `checkpoint.reused` и `times.checkpoint_confirmed_at`.
В SSR не видны ID и время подтверждения даже после обхода F-C13-00 тестовым
envelope. Оракулы: `test_p01_reused_checkpoint_prints_three_records_and_confirmation`,
`test_p01_confirmation_is_visible_in_compiled_renderer`.

### F-C13-03 / P1 — разные подтверждения получают метаданные первого

Два валидных checkpoint с теми же refs, но разными ID/временем имеют одинаковый
producer key P01. Ответ второго запроса содержит второй checkpoint_id, а его
frozen snapshot — первый. Это нарушение исторической адресации AC10/11;
повторено и на PostgreSQL. Оракул:
`test_different_confirmation_keeps_its_own_frozen_metadata`.

### F-C13-04 / deployment — инструкции и топология не дают доказанного rollout

| Подпункт | Наблюдаемый источник | Следствие |
| --- | --- | --- |
| 04a | Основные VM-команды `docs/pgv13_passport_documents.md` строят `cisstat-print-renderer:pgv13`, renderer compose запускает `:pgv08-fix` | Построенный образ не выбирается compose |
| 04b | PGV-13 добавил два пути в compiled BFF allowlist; основной rollout строит только api и объявляет web необязательным | Старый web не получает новые proxy paths; нужен rebuild web |
| 04c | Renderer compose: `network_mode: none`, нет ports/IPC; API compose не задаёт `CISSTAT_PNG_RENDERER_URL`, HTTP-клиент использует loopback API | У поставленных compose нет доступного межконтейнерного HTTP endpoint |

04c — унаследованный интеграционный разрыв, не новый код PGV-13. Существование
иной конфигурации VM/override не проверено. Это finding о поставленных файлах,
не утверждение о сетях работающей VM. Внешний curl к host:8907 из исходной
инструкции не подтверждает readyz renderer в отдельном namespace без ports.
Source-тесты `test_deployment.py` дают 3 FAIL; защита sandbox остаётся 1 PASS.
Тест предпосылки транспорта не заменяет проверку реального соединения API→renderer.

## Sandbox: подтверждённое и открытое

Сообщение коллеги о VM принято как симптом. Доступа к VM, Docker daemon и её
Chromium stderr в этой сессии нет. Точная причина **OPEN**, не сертифицирована.

Локальный smoke использовал системный Chromium, а не pinned Chromium образа.
Первый запуск остановился на недоступном `/tmp`; повтор с writable TMPDIR
дошёл до `ProcessSingleton ... socket() ... Operation not permitted`, SIGABRT,
до открытия страниц. Это ограничения локальной среды/AF_UNIX, не доказательство
VM-проблемы user namespaces. Оба вывода сохранены без подмены результатом PASS.
Docker отсутствует: diagnostic local exit=2, final-image run не выполнен.

На базе сохранены `chromiumSandbox: true`, non-root 10001, read-only root,
cap_drop ALL, no-new-privileges. Не добавлены `--no-sandbox`, privileged,
root, seccomp=unconfined, изменения sysctl/AppArmor. Официальная документация
[Playwright Docker](https://playwright.dev/docs/docker) описывает non-root и
seccomp/user namespaces как условия sandbox; это направление проверки, а не
разрешение отключить защиту или без проверки заменить pinned версии проекта.

После переноса этой поставки на VM выполнить из корня репозитория:

```bash
bash scripts/pgv13cert/diagnose_vm.sh
```

Скрипт не меняет хост/контейнеры/БД: читает выбранные namespace sysctls,
выполняет временный `unshare -Ur true`, показывает только image/user/network/
security options, UID/версии/NoNewPrivs/Seccomp/CapEff, опрашивает readyz внутри
renderer и отдельно из API. Не выводит `.env`, Docker Env или credentials.
Exit 2 — среды/Docker нет; 1 — readiness/transport блокирован; 0 — только эти
пробы прошли, не полная сертификация P01/P02. Host unshare сам по себе ничего
не доказывает о namespace policy контейнера. Для окончательного диагноза нужны
также очищенные от чувствительных данных stderr реального Chromium и данные
хостовой политики (включая применённые compose overrides), после чего
отдельно проверяются H-VM1 sandbox policy и H-VM2 образ/транспорт.

## Проверки и трассируемость

| Требование / риск | Независимый оракул | Результат / граница |
| --- | --- | --- |
| PGV-13, AC06/09: полные durable facts без SessionStore | all_groups_survive, source_hash; запрет SessionStore | PASS; без нового science вызова по изученному пути, не полная science-instrumentation |
| AC10: заданная историческая траектория P02 | exact ordered_refs, numeric/category/list/qualitative delta, definitions | PASS |
| AC11: reused/unchanged, время/источник | три физических refs, compiled SSR подтверждения | FAIL F02; alias P02 сохраняется |
| AC10/11: разные подтверждения | два checkpoint с теми же refs | FAIL F03 |
| AC12: пропавший/повреждённый источник | gap/partial, single unavailable, испорченные bytes | PASS; не вся матрица отказов хранилища |
| AC13: zero base, численные и качественные изменения | mean 0→7, delta_pct=100 по принятому определению, reason, category/list/qualitative | PASS |
| AC14: panel против single | есть штатный тест PGV-13 | PASS штатного набора; отдельного panel oracle здесь нет |
| Object gate | чужой account/subject и отсутствующий run | PASS доменного пути, не полный HTTP/Auth transport |
| Python→TS печать P01/P02 | точный payload в compiled SSR | FAIL F00 |
| Профиль/идемпотентность | сохранённая revision/basis/job | точный повтор PASS, смена профиля FAIL F01 |
| Контейнер/sandbox/PNG | final image/Chromium/jobs/artifact delivery | OPEN/BLOCKED, браузер не принял страницы |

Итоговые сырые результаты (без xfail/skip и без обращения RED в PASS):

| Прогон | Результат | Протокол в scripts/pgv13cert/protocols/ |
| --- | --- | --- |
| Независимые contracts, Memory | 7 FAIL / 7 PASS | independent-memory.txt/xml |
| Те же contracts, PostgreSQL 16.2 | 7 FAIL / 7 PASS, 0 skipped/errors | independent-postgres.txt/xml |
| Чистая база + распаковка ZIP, повтор gate | те же 10 FAIL / 8 PASS, exit 1 | overlay-cert.txt |
| Полный сертификационный gate (contracts + deployment) | 10 FAIL / 8 PASS, exit 1 NOT CERTIFIED | cert-final.txt |
| Штатный PGV-13 Python, pinned API runtime | 39 PASS | repo-python-pinned.txt |
| Штатный rendererCore TS | 41 PASS | repo-ts.txt |
| AUTH-00/AUTH-01 unit regression | 86 PASS | auth-regression.txt |
| renderer tsc; embedded + standalone production builds | PASS; 20 / 27 страниц | renderer-build.txt, web-builds.txt |
| Executable mutation control, repo / oracle | оба GREEN | mutations/control-*.txt |
| drop_group / wrong_source_hash / wrong_job_id | все 3 убиты обоими каналами | mutations/matrix.json и отдельные логи |

Mutation campaign регистрирует ожидания до запуска, использует subprocess runtime
wrappers без правок production-файлов. Oracle control включает только три
положительных теста, поэтому исходные известные FAIL не могут имитировать
уничтожение мутанта. Repo survival не скрывается общей цифрой. Все три repo
канала также RED: это полезная проверка чувствительности существующих тестов,
не доказательство полноты и не отмена F00…04. До/после hash production builder
одинаков. Изначальный `independent-first.txt` содержит ошибку собственной fixture
(недопустимый previous_ref), затем она исправлена; это не finding о продукте.

## Повтор локально

Нужны Node/npm и Python с scientific runtime API плюс сертификатор:

```bash
python -m pip install -r scripts/pgv13cert/requirements.txt
npm ci
python scripts/pgv13cert/verify.py
# Ожидаемый результат на проверенной базе: exit 1 / NOT CERTIFIED.
```

Для native задать `CISSTAT_PGV13_CERT_DSN` только на disposable PostgreSQL
с CREATE DATABASE (никогда production DSN) и запустить
`python scripts/pgv13cert/verify.py --postgres`. Тест создаёт/удаляет собственные
временные БД. Без DSN `--postgres` возвращает 2 до тестов, не PASS.
Mutation replay: `python scripts/pgv13cert/mutations.py` после renderer build.
Нужна Git-история с `fc510f0` для проверки rollout allowlist.

Новый gate явно opt-in, в default `local_gates.py` не добавлен. Зелёный default
не является сертификацией PGV-13. Сначала исправление находок, затем повтор
этих raw-тестов без смягчения оракулов и приёмка конечного образа.

## Роуты, поставка и условия повторной приёмки

Эта поставка не меняет HTTP handlers/paths/methods, DTO, BFF, OpenAPI или UI.
284 API / 288 bindings / 663 inventory entries сохранены. В policy review
добавлены исходники сертификационных Python-инструментов/requirements;
также обновлён fingerprint изменённого `scripts/local_gates.md`.
inventory регенерирован для fingerprints. Исходная PGV-13 действительно меняла
роуты: GET passport-sources и POST passport-documents, что требует нового web
bundle. Проверки actual ASGI, inventory и strict INDEX фиксируются в routes.txt.

Поставка содержит только новые инструменты/протоколы, этот акт, дополнение
worklog12, local_gates.md, manifest и карту AUTH-00. Исходные runtime bytes базы
сохранены. Для применения **сертификационного** ZIP не нужны миграции или
пересборка образов. Не следует выдавать docker build/up этой поставки за
исправление PGV-13.

Повторная приёмка требует: F00…03 GREEN на точных payload и обеих БД;
согласованный image tag и rebuild api+web+renderer после продуктового исправления;
проверенный транспорт API→renderer и действующий sandbox на целевой VM;
настоящие P01 single/set/reused и P02 comparison → worker → PNG bytes → сохранение
и авторизованная выдача, при обоих профилях, с проверкой содержимого/полноты,
отсутствия fabricated четвёртого паспорта и правильного checkpoint/time.
Нужно визуально проверить конечные PNG (не один HTTP 200/PNG header), включая
длинные/кириллические группы, и failure/timeout path без отключения sandbox.
Пагинация/page-set/ZIP относятся к PGV-14, picker UI к PGV-15: их отсутствие
не записано отдельным блокером PGV-13. Выполненные здесь проверки не заявляются
real-browser E2E, pixel/OCR acceptance, Windows/Docker/VM certification или
полным default/scientific regression.

## Дополнение VM на 338b15a

Тимлид предоставил реальный вывод VM: readyz503 с Chromium `No usable sandbox!`/SIGABRT и отдельный API URLError. Теперь VM sandbox blocker подтверждён; прежнее OPEN относится к точной политике отказа, а не существованию сбоя. AppArmor restriction=1 и host uid_map denial — ведущая гипотеза, но контейнерный audit/profile и вклад seccomp пока не установлены. Подробный разбор, границы и следующий read-only сбор: `docs/pgv13_vm_followup.md`. Известные контрактные блокеры/вердикт не изменились.
