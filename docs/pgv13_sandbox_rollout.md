# PGV-13: опциональная активация sandbox candidate, 19.11.2026

**Текущий статус на19.11.2026: operational renderer gate PASS по выводу VM
тимлида.** На image1837bee8… с PID budget512 прошли полный структурный PNG smoke
и readyz, без новых PID/OOM событий. Подробности/границы — в конце документа.
Полная PGV-13 по-прежнему NOT CERTIFIED.


База9cffdcd29522872e3aaa045861b7343dea9cb3c7. На VM тимлид подтвердил
CHROOT_RULE_CANDIDATE: из4 сопоставимых arms только namespaces-chroot печатает,
при isolation=true у всех. Это доказанный положительный **mini-PNG эксперимент**,
не полная безопасность профиля/приёмка всей PGV-13. Факты —
scripts/pgv13sandbox/protocols/rollout/vm_evidence.json (user-provided).

## Состав и риск изменения

Committed `apps/print-renderer/build/deployment/chromium.seccomp.json` равен
chroot_profile(profiles()[1]): pinned Moby base с clone/setns/unshare и chroot
ALLOW, default ERRNO и остальные правила сохранены. Это полный reference profile,
**не четыре правки автоматически извлечённые из текущего Docker builtin**:
reference и Docker29.9.2 не объявляются идентичными. Pin/source/модификации и
копия Apache2 LICENSE рядом; исходный vendor не меняется.

Base Compose не меняется. activate.py подключает два явных overlay:
immutable validated image/pull never и абсолютный путь seccomp/явный docker-default.
Default mode read-only: считывает полный старый report, а не короткую stdout-матрицу;
проверяет согласованность candidate, ровно4 arm names, триfailed/одинpassed,
exit/isolation/launch/security fields, reference pin и точный профиль.
Это проверка внутренней согласованности файла оператора, не цифровая аттестация.

Текущий renderer image ID и AppArmor должны совпасть с report; при новом image
нужен новый A/B. Через настоящий `docker compose config --format json` preflight
проверяет итоговые UID10001, readonly/init, NNP, cap_dropALL, отсутствие cap_add/
privileged/ports/volumes/devices/shared namespaces, networknone, memory2g/pids512 (forward) или128 (rollback)/
shm256m и tmpfs/tmp. Вывод config не печатается, .Env Docker не читается.
Применяется поставленный base Compose; произвольные VM overrides не клонируются.
Если merge/формат отличается, helper отказывает до up; не обходите preflight.

`--apply` выполняет только compose up одного print-renderer с --no-deps,
--no-build, --pull never, --force-recreate. Возможна короткая пауза; выполняющиеся
рендеры могут прерваться. API/web/БД не пересоздаются, image не меняется.
Никакие sysctl/AppArmor host profiles, privileged/SYS_ADMIN/no-sandbox не включаются.
При ошибке после начала up Docker daemon мог уже изменить контейнер:
mutation_started=true в error JSON. Автоматический rollback не маскирует исходную
ошибку; состояние нужно проверить. Readiness/full smoke автоматически не заявляются.

## Операторская команда после ZIP→локальный push→VM pull

Из корня checkout, используя существующий успешный JSON:

```bash
# Только preflight, без изменения служб:
python3 scripts/pgv13sandbox/activate.py --report /tmp/pgv13-chroot-ab.json

# Повторяет preflight и пересоздаёт только renderer с проверенным image ID:
python3 scripts/pgv13sandbox/activate.py --report /tmp/pgv13-chroot-ab.json --apply
```

Зависимости: Python3 stdlib, Docker/Compose с config JSON; sudo для изменения
host policy не требуется. Docker privileges у оператора должны уже быть.
Нет pip/npm/install/build или миграции. Если /tmp report потерян после reboot,
восстановить подлинный report либо заново выполнить --with-chroot на текущем image;
короткая матрица не заменяет полный файл. Не редактировать исходные evidence
поля ради прохождения проверки. Source code helper не commit/push/pull Git.

## Проверки после recreate

```bash
python3 scripts/pgv13sandbox/verify_service.py --out /tmp/pgv13-service-smoke.json
```

Нужны passed полного Cyrillic/IH/A4 smoke и readyz200 на рабочем контейнере.
Клиент обращается к существующему HTTP-worker; отдельный CLI-worker рядом с
HTTP-сервером для этой проверки больше не запускается.
Кэш readiness30s действует внутри server, CLI full smoke — отдельный холодный
worker. Затем проверяются реальные ограничения/нагрузка, timeout/cancel,
PNG-content и авторизованная выдача. Не считать код выхода0 helper или mini-PNG
достаточным для этой приёмки. При transient connection failure сразу после up
проверить состояние/health контейнера и повторить readiness после старта.

API target_scope loopback/ConnectionRefusedError не исправляется данным rollout:
networknone сохранён, транспорт API→renderer всё ещё требует отдельного решения.
Поэтому полный diagnose_vm.sh может продолжать возвращать1 из-за API даже при
renderer_readyz200. F-C13-00…03 и остальные условия сертификата PGV-13 открыты.
В целом NOT CERTIFIED сохраняется.

## Откат и последующие recreate

```bash
python3 scripts/pgv13sandbox/activate.py --report /tmp/pgv13-chroot-ab.json --rollback
```

Helper использует тот же image-only overlay и base без sandbox overlay:
seccomp возвращается к builtin, image ID остаётся тестированным. Это восстановление
предыдущей конфигурации и, вероятно, прежнего No usable sandbox, не исправление.
Профиль не меняет глобальную политику Docker daemon. Простой restart сохраняет
конфигурацию существующего контейнера, а base-only compose up/recreate может
снять overlay. Для дальнейших recreate применять тот же helper/file set;
после смены image нужна новая evidence. --rollback также требует согласованный
report/current image; для произвольных старых/изменённых конфигураций нужен review.

## Верификация исходной rollout-поставки

TDD initial17 activation RED → final34 GREEN (20activation+14probe); Docker
subprocess stubbed. Проверены допустимый и поддельный report, exact profile,
unsafe merged config drift, immutable image mismatch, no-action default,
per-service flags, absolute profile env, rollback без потери image, возможная
mutation при up failure. Source-byte parity, actual routes/strict INDEX и clean
ZIP overlay фиксируются в protocols/rollout. Renderer tsc build проверяется;
full default/Windows/Docker Compose merge/actual activation агентом не исполнялись.

Default local_gates.py не меняется; opt-in contracts:
`python -m pytest scripts/pgv13sandbox -q`. Карта AUTH-00 учитывает новые reviewed
sources/deployment assets без изменения HTTP/DTO/BFF paths. Агент не делал
commit/push и не имеет прямого подключения к VM. Реальный persistent-service
результат исходного rollout сначала был PENDING; после capacity512 оператор
подтвердил PASS рабочего operational gate (см. итог ниже). Mini-PNG candidate
также CONFIRMED по данным тимлида.

Официальные форматы, проверены19.11.2026: [Compose merge](https://docs.docker.com/reference/compose-file/merge/), [Docker seccomp](https://docs.docker.com/engine/security/seccomp/). Реальный merge всё равно проверяется установленным Docker Compose до up, не эмулируется YAML-конкатенацией.


## 19.11.2026: подтверждённый PID ceiling и ограниченный capacity fix, базаf614a90

После активации sandbox рабочий CLI full smoke упал с pthread_create EAGAIN.
Тимлид измерил pids.current70, pids.max128, pids.peak128, pids.events max92;
memory.current165732352/max2147483648, memory.events max/oom/oom_kill0,
RLIMIT_NPROC и address space unlimited. PID/thread ceiling реально достигался.
Это подтверждённый resource blocker, не повтор No usable sandbox/chroot.
Источник нормализован в protocols/capacity/vm_evidence.json, прямого доступа нет.

В предыдущей процедуре CLI создавал ещё один PrintRenderWorker в контейнере,
делящем128 задач с сервером/readiness. Его admission был отдельным от service
worker; это могло усиливать конкуренцию. Из фактов нельзя вычислить точное
минимальное число задач для любой будущей нагрузки, поэтому512 — **ограниченный
кандидат бюджета**, требующий измерения на VM, не доказанный оптимум.
Memory2g/NNP/UID/caps/readonly/networknone/seccomp/AppArmor/образ не меняются.

Новый docker-compose.capacity.yml задаёт только pids_limit512. Base Compose и
исторические isolated A/B остаются128; activate.py теперь по умолчанию подключает
capacity overlay для forward check/apply и проверяет именно512 в реальном merged
config. В JSON helper явно указан pids_limit. --rollback по умолчанию снимает
sandbox и capacity, оставляя тот же image ID и прежний бюджет128.

Сохранить sandbox, но вернуть только старый PID budget можно отдельно:

```bash
python3 scripts/pgv13sandbox/activate.py --report /tmp/pgv13-chroot-ab.json --apply --pids-limit 128
```

Это аварийное восстановление предыдущего бюджета с известным resource defect,
не исправление. Принимаются только128/512, не0/-1/unlimited. Обычный --apply
после новой поставки переводит working renderer на512 без build/pull images.
Тот же --apply может прервать текущие рендеры при recreate, как описано выше.

verify_service.py — stdlib host wrapper + Node HTTP client внутри namespace
контейнера. Импортируется только fs, не renderer worker. После bounded liveness
poll отправляются POST /v1/smoke и GET /readyz существующему service. Снимаются
before/after pids/current/max/peak/events, memory/current/max/events, parent
UID/NNP/Seccomp/CapEff. Exit0 требует smoke200+passed, readyz200+ready/smoke,
реальные budgets512/2g, delta pids.events.max=0, delta oom=oom_kill=0 и parent
hardening. Неизвестные counters не приравниваются к0. pids.peak — дополнительная
диагностика, на старом kernel может отсутствовать; новые pressure events обязательны.
Старые события в before не отменяются нулевой дельтой: оценивается окно проверки,
не вся история. Это не concurrency2 stress, pixel/OCR или P01/P02 acceptance.

Raw HTTP body/scenario errors и метрики сохраняются в --out; stdout содержит
checks/deltas/сценарии и короткие fatal/EAGAIN причины. При потере HTTP сохраняются
before/after доступные counters и setup error. Старый положительный JSON заменяется
RUNNING/error до нового запуска. Timeout bounded (до360s host wrapper), exit1 —
checks failed, exit2 — setup/transport/inconsistent exit; все сохраняют
pgv13_certified=false. Код0 не означает сертификат всей PGV-13.

TDD targeted RED8 → final49 controls (23activate+14probe+12verification).
Собственно Node client выполняется в VM-контексте Node с mocked fs/fetch:
проверены точные существующие routes/methods и отсутствие нового worker import,
PID growth, OOM, missing counters, старый budget, smoke/readiness/transport failure.
Дополнительно CLI сохраняет/проверяет child exit/report и stale-report replacement;
capacity-only rollback сохраняет sandbox. Docker/Chromium тут не исполнялись.
Настоящие512/full smoke результаты теперь получены от тимлида: PASS
для наблюдаемого окна (см. итог ниже). Renderer build/ASGI/INDEX/ZIP overlay —
protocols/capacity. Исторический sandbox candidate остаётся подтверждённым.

Первичные справочники: [cgroup v2 PID controller](https://docs.kernel.org/admin-guide/cgroup-v2.html#pid),
[pthread_create EAGAIN](https://man7.org/linux/man-pages/man3/pthread_create.3.html).
Новый источник отказа не даёт оснований отключать sandbox или устанавливать DBus
по сопутствующим предупреждениям. API transport и F-C13-00…03 всё ещё открыты.


## Итог19.11.2026: рабочий renderer operational PASS

Источник — stdout оператора после активации и HTTP verification, не прямой
запуск агента. Нормализованный полный вывод сохранён в
scripts/pgv13sandbox/protocols/ops_pass/vm_evidence.json. VM Git HEAD не был
напечатан в этой конкретной реплике; база записи — main36f32ae.

| Проверка | Результат |
| --- | --- |
| Immutable image | sha256:1837bee8994e42b97b548de5ecf4d3e026f8b3e6624d9ac42822a4ed290f81b3 |
| Working full smoke / readyz | HTTP200 / HTTP200, passed=true |
| Cyrillic / IH / A4 | все5 структурных PNG checks true у каждого: signature, dimensions, pHYs300ppi, non-empty IDAT, non-trivial bytes |
| PID controller | max512; current19→19; peak148→152; events.max0→0 |
| Memory controller | max2147483648; current70045696→93175808; max/oom/oom_kill0→0 |
| Parent hardening check | true по verifier |
| Whole PGV-13 certification | false |

Таким образом, устранение sandbox launch blocker и PID ceiling подтверждено
положительным операционным прогоном на **этом image/config и в этом окне**.
Пик152 сам по себе превышает прежний128; возвращать working budget128 как
исправление нельзя. Задачи вернулись к19 после проверки, но это не длительный
leak/stress test; изменение memory current не интерпретируется как доказательство
наличия/отсутствия утечки. Нулевая дельта pressure событий касается окна измерения.

PASS относится к структурному V01/full-smoke runtime. Здесь нет самостоятельного
pixel/OCR/семантического доказательства корректности кириллицы/всех графиков,
реального P01/P02 job→PNG→авторизованный download или concurrency2 stress.
API→renderer остаётся OPEN: последний ConnectionRefusedError не перепроверен
этим выводом; topology/client исходники здесь не исправлены. F-C13-00…03 тоже
не закрыты: passport_documents.py/print_render_payload.py/printLayout.tsx в
main36f32ae побайтно прежние относительно5d83967. Исторические raw FAIL не
превращены в PASS из-за инфраструктурного успеха.

Для документальной поставки принятого результата не нужны новый recreate,
образ, миграция или повтор smoke. Она обновляет evidence/акт/worklog и
fingerprint этого runbook в AUTH-00, без изменения routes/config/runtime.
Следующий предмет приёмки — оставшиеся контрактные исправления и сквозной
API→renderer→реальные документы. Агент не commit/push и не выполнял VM-команд.
