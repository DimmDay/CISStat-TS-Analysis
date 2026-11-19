# PGV-13 — API → renderer, HTTP over Unix socket

База db10adab4ba513cc14735b4ceb3a9a645e3da637. План: новый opt-in UDS
transport; TCP compatibility для существующих локальных инструментов.
Новый IPC env явно выбирает UDS, без fallback к loopback/TCP/proxy/redirect.
HTTP пути /healthz, /readyz, /v1/render, /v1/smoke прежние. API остаётся
единственной authority job/CAS/artifacts; renderer получает только frozen
payload, без cookies/DSN/ключей. Новая transport boundary классифицируется AUTH-00.

## Права и lifecycle

Renderer UID:GID10001:10001, каталог /run/cisstat-renderer 0750, socket
render.sock 0660. Отдельный named volume только для API и renderer; API mount
read-only + supplementary GID10001, renderer RW. API image сейчас root —
перевод всего scientific API на non-root не входит в задачу и не заявляется.
Каталог заранее создаётся в renderer image с marker; external volume сначала
инициализируется этим image, API mount volume.nocopy=true. Чужие owner/mode,
symlink, regular file, активный endpoint не исправляются автоматическим chmod.

Производственный entrypoint держит kernel flock на renderer.lock весь срок
процесса (exec/no-fork). Stale lockfile не удаляется: lock снимает kernel при
смерти процесса. Под lock допустимо удалить только свой stale socket после
ECONNREFUSED и проверки inode; остальные ошибки/живой listener — отказ.
Начальный bind под umask077, затем chmod0660. Shutdown закрывает listener,
HTTP connections, worker/browser; restart после SIGKILL покрывается native gate.
Никаких public ports/networks/cap_add/host sysctl. В volume нет научных данных
или секретов; захват API/renderer означает доверенную внутрисервисную сторону.

## Бюджеты и отмена

UDS stdlib http.client: fixed paths/Host, no redirects/proxies, finite
JSON (allow_nan=False) до IO; request cap8MiB, PNG cap50MiB, error/readiness64KiB. Общий monotonic
бюджет ≤60s, включая connect/headers/body (slow trickle не продлевает deadline).
Watchdog shutdown/close прерывает socket IO; cancel — отдельный сигнал.
Legacy worker передаёт soft deadline, stop/cancel закрывают соединение. Managed
AUTH-13 adapter явно передаёт IPC path в изолированный child (не платформенный
env); его остановка закрывает FD, remote_unknown proof не подменяется PASS.
Server abort при закрытии HTTP response `/v1/render` отменяет только свой render: SSR
thread/launch guard/browser kill, освобождение admission. Timeout и hard cap
остаются независимыми; отменённый job не может публиковаться в ready.
HTTP upload deadline/connection cap/body cap/concurrency ограничены.

## Проверка

TDD: Python wire tests выполняют реальные HTTP bytes по TCP socket adapter,
потому что текущая среда запрещает AF_UNIX bind (EPERM). Это явно не native
UDS proof. Node lifecycle tests проверяют FS/net refusals с doubles; native
Unix socket/UID-GID/read-only mount/restart/final image — отдельный VM gate.
Сборки/совместимость/default gates проверяются после реализации. Общая PGV-13
не получает сертификат от одного transport теста.

## VM-команды

Все команды после pull **данной поставки**, из корня repo. Кандидаты,
построенные на db10ada, не содержат UDS: нужны новые API/renderer images.
Команды требуют Bash/Docker Compose v2; actual merge проверяется на VM.
Не выполнять старый activate.py после включения UDS: он запрещает mounts
для прежнего topology. Его profile/лимиты не ослабляются в этой поставке.

### 1. Сборка, pin, инициализация только candidate volume

```bash
docker compose --project-directory deployment/cisstat-stack \
  -f deployment/cisstat-stack/docker-compose.yml \
  -f deployment/cisstat-stack/docker-compose.renderer-uds.yml build api web
docker build -f apps/print-renderer/build/Dockerfile -t cisstat-print-renderer:pgv13-uds .
export CISSTAT_RENDERER_PROJECT="$(docker compose -f apps/print-renderer/build/deployment/docker-compose.yml config --format json | python3 -c 'import json,sys; print(json.load(sys.stdin)["name"])')"
export CISSTAT_UDS_RENDERER_IMAGE="$(docker image inspect --format '{{.Id}}' cisstat-print-renderer:pgv13-uds)"
export CISSTAT_RENDERER_SECCOMP_FILE="$PWD/apps/print-renderer/build/deployment/chromium.seccomp.json"
export CISSTAT_RENDERER_IPC_VOLUME=cisstat_renderer_ipc_pgv13_candidate
docker volume create "$CISSTAT_RENDERER_IPC_VOLUME"
docker run --rm --pull=never --network=none --read-only --user=10001:10001 \
  --cap-drop=ALL --security-opt=no-new-privileges:true \
  --mount "type=volume,source=$CISSTAT_RENDERER_IPC_VOLUME,target=/run/cisstat-renderer" \
  --env CISSTAT_PRINT_RENDERER_SOCKET=/run/cisstat-renderer/render.sock \
  "$CISSTAT_UDS_RENDERER_IMAGE" node apps/print-renderer/dist/apps/print-renderer/src/socketTransport.js
```

Последняя команда копирует image-owned directory/marker в **пустой** volume и
проверяет owner/mode/lock. Неверный ранее созданный volume даёт отказ, не
автоматическую смену прав. Нельзя использовать science_data или Docker socket.
Named volume не следует публиковать в других сервисах/проектах.

### 2. Candidate, новый A/B и настоящий API-image → UDS → PNG

```bash
docker compose -p cisstat-pgv13-uds-candidate \
  -f apps/print-renderer/build/deployment/docker-compose.yml \
  -f apps/print-renderer/build/deployment/docker-compose.uds.yml \
  config --quiet
docker compose -p cisstat-pgv13-uds-candidate \
  -f apps/print-renderer/build/deployment/docker-compose.yml \
  -f apps/print-renderer/build/deployment/docker-compose.uds.yml \
  up -d --no-build --pull never --no-deps print-renderer
COMPOSE_PROJECT_NAME=cisstat-pgv13-uds-candidate \
  python3 scripts/pgv13sandbox/probe.py --with-chroot --out /tmp/pgv13-uds-ab.json
python3 scripts/pgv13uds/verify_vm.py --renderer-project cisstat-pgv13-uds-candidate \
  --sandbox-report /tmp/pgv13-uds-ab.json --api-image cisstat-api:pgv13-uds \
  --out /tmp/pgv13-uds-candidate.json
```

Не продолжать при nonzero/failed/inconclusive. A/B — новые четыре временных
контейнера именно нового immutable image; profile не берётся из old image report.
Candidate client — одноразовый новый API image с network:none, RO volume,
UID0 + group10001, без platform env/DSN/секретов. Gate сверяет source hash API
client, actual mounts/hardening/UID-GID/modes/cgroups/no newPID-OOM; затем
readyz и 3 настоящих full-size PNG с dimensions/CRC/pHYs/IDAT/distinct hashes.
Это не pixel/OCR/P01-P02/job-download сертификат. TCP8907 обязан быть закрыт.

### 3. Проверка flock и stale socket после SIGKILL

При работающем candidate второй процесс обязан получить nonzero от flock;
он не имеет права удалить endpoint живого listener:

```bash
if docker run --rm --pull=never --network=none --read-only --user=10001:10001 \
  --cap-drop=ALL --security-opt=no-new-privileges:true \
  --mount "type=volume,source=$CISSTAT_RENDERER_IPC_VOLUME,target=/run/cisstat-renderer" \
  --env CISSTAT_PRINT_RENDERER_SOCKET=/run/cisstat-renderer/render.sock \
  "$CISSTAT_UDS_RENDERER_IMAGE" /usr/local/bin/cisstat-print-renderer; then
  echo 'BLOCKED: second listener acquired the same lock'; exit 1
fi
# Только isolated candidate, не production:
docker compose -p cisstat-pgv13-uds-candidate \
  -f apps/print-renderer/build/deployment/docker-compose.yml \
  -f apps/print-renderer/build/deployment/docker-compose.uds.yml kill -s SIGKILL print-renderer
docker compose -p cisstat-pgv13-uds-candidate \
  -f apps/print-renderer/build/deployment/docker-compose.yml \
  -f apps/print-renderer/build/deployment/docker-compose.uds.yml \
  up -d --force-recreate --no-build --pull never --no-deps print-renderer
python3 scripts/pgv13uds/verify_vm.py --renderer-project cisstat-pgv13-uds-candidate \
  --sandbox-report /tmp/pgv13-uds-ab.json --api-image cisstat-api:pgv13-uds \
  --previous-report /tmp/pgv13-uds-candidate.json --out /tmp/pgv13-uds-recreated.json
```

Сохранённый socket inode в volume переживает SIGKILL. Новый listener под lock
убирает только собственный ECONNREFUSED endpoint; повторный gate требует
новый container ID, тот же volume/image и успешные PNG. Nonzero второго
процесса сам по себе ещё не доказательство flock: сохранить его stderr и
повторный successful gate, который подтверждает, что active listener не повреждён.
При неготовом только что пересозданном сервисе дождаться healthy и повторить gate;
не изменять результат failed в отчёте вручную.

### 4. Production после обоих candidate PASS

Остановить candidate без удаления volume; использовать **отдельный** production
volume. Текущий old renderer продолжает работать до production up. Сохранить
старые API/web/renderer image IDs и действующие overrides для отката.

```bash
docker compose -p cisstat-pgv13-uds-candidate \
  -f apps/print-renderer/build/deployment/docker-compose.yml \
  -f apps/print-renderer/build/deployment/docker-compose.uds.yml down
export CISSTAT_RENDERER_IPC_VOLUME=cisstat_renderer_ipc_v1
docker volume create "$CISSTAT_RENDERER_IPC_VOLUME"
docker run --rm --pull=never --network=none --read-only --user=10001:10001 \
  --cap-drop=ALL --security-opt=no-new-privileges:true \
  --mount "type=volume,source=$CISSTAT_RENDERER_IPC_VOLUME,target=/run/cisstat-renderer" \
  --env CISSTAT_PRINT_RENDERER_SOCKET=/run/cisstat-renderer/render.sock \
  "$CISSTAT_UDS_RENDERER_IMAGE" node apps/print-renderer/dist/apps/print-renderer/src/socketTransport.js
docker compose -p "$CISSTAT_RENDERER_PROJECT" -f apps/print-renderer/build/deployment/docker-compose.yml \
  -f apps/print-renderer/build/deployment/docker-compose.uds.yml \
  up -d --force-recreate --no-build --pull never --no-deps print-renderer
docker compose --project-directory deployment/cisstat-stack \
  -f deployment/cisstat-stack/docker-compose.yml \
  -f deployment/cisstat-stack/docker-compose.renderer-uds.yml config --quiet
env -u CISSTAT_AUTH_MFA_KEYS -u CISSTAT_AUTH_MFA_ACTIVE_KEY \
  docker compose --project-directory deployment/cisstat-stack \
  -f deployment/cisstat-stack/docker-compose.yml \
  -f deployment/cisstat-stack/docker-compose.renderer-uds.yml \
  up -d --no-build --pull never --no-deps api web
```

Production project name сохранён до candidate rollout в CISSTAT_RENDERER_PROJECT.
Проверьте его совпадение с label com.docker.compose.project прежнего сервиса:

```bash
python3 scripts/pgv13uds/verify_vm.py --renderer-project "$CISSTAT_RENDERER_PROJECT" \
  --sandbox-report /tmp/pgv13-uds-ab.json --out /tmp/pgv13-uds-live.json
curl -fsS https://api.datasetup.ru/health
```

Здесь gate использует **живой API container**, проверяет совпадение volume и
userns mapping двух контейнеров, API RO mount даже для root, UDS/PNG и источник
клиента. Никакого обращения к публичному localhost:8907. Образы/overlays/pin/
profile/volume нужно сохранять в операторской конфигурации для следующих up;
запуск только base compose вернёт legacy topology. Миграций БД нет.

Откат — остановить новые print jobs, вернуть сохранённые API/web и renderer
images с **прежними** compose overlays без UDS mount/env, сохранить sandbox и
512 limit; при этом известный old transport blocker вернётся. IPC volumes
не удалять автоматически; научных данных в них нет. Готовность после отката
проверять прежними средствами, не переносить new-image PASS на old image.

## Первичные основания

Node24 IPC lifecycle/HTTP socketPath: https://nodejs.org/docs/latest-v24.x/api/net.html
и https://nodejs.org/docs/latest-v24.x/api/http.html. Инициализация Docker volume:
https://docs.docker.com/engine/storage/volumes/. Это основания дизайна,
не замена native проверкам на конкретном Docker/kernel/AppArmor.

Native gate дополнительно проверяет lifetime flock по выделенному exit73
второго `flock --nonblock`, затем явный cancel и deadline на full-size A4.
API закрывает реальные UDS FD; renderer обязан записать оба уникальных
request_id как render_cancelled. После этого проходят три полных PNG.
Oversize request отказывается до IO; независимый receiver body-cap проверен
реальным Node HTTP test. Если отрицательный рендер успел завершиться до50ms,
gate блокирует приёмку, не выдаёт несостоявшуюся отмену за PASS.
Legacy activate.py имеет новый fail-closed guard для active UDS mount, поэтому
не может молча восстановить TCP-only topology.

Shell entrypoint и его .gitattributes принудительно LF, включая Windows checkout;
исполняемый mode задаётся Docker COPY --chmod=0555, не зависит от ZIP/Git mode.
