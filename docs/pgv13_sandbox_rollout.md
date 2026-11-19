# PGV-13: опциональная активация sandbox candidate, 19.11.2026

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
privileged/ports/volumes/devices/shared namespaces, networknone, memory2g/pids128/
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
docker compose -f apps/print-renderer/build/deployment/docker-compose.yml \
  exec -T print-renderer node \
  apps/print-renderer/dist/apps/print-renderer/src/smoke.js --smoke

docker compose -f apps/print-renderer/build/deployment/docker-compose.yml \
  exec -T print-renderer node -e \
  "fetch('http://127.0.0.1:8907/readyz',{signal:AbortSignal.timeout(70000)}).then(async r=>{console.log(r.status,await r.text());process.exit(r.ok?0:1)}).catch(e=>{console.error(e.name);process.exit(1)})"
```

Нужны passed полного Cyrillic/IH/A4 smoke и readyz200 на рабочем контейнере.
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

## Верификация поставки

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
результат этой поставки пока PENDING; mini-PNG candidate — CONFIRMED по данным тимлида.

Официальные форматы, проверены19.11.2026: [Compose merge](https://docs.docker.com/reference/compose-file/merge/), [Docker seccomp](https://docs.docker.com/engine/security/seccomp/). Реальный merge всё равно проверяется установленным Docker Compose до up, не эмулируется YAML-конкатенацией.
