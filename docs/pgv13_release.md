# PGV-13-RELEASE — согласованный релиз, этап 4

База разработки: `b27b62fed02e89c505b88b2cc749520e8e7e115e`, 20.11.2026.
Поставка готовит инструменты сборки/проверки/отката. В среде разработки нет
Docker CLI/daemon: реальные image IDs, новый A/B и VM rollout пока не получены.
Unit/subprocess doubles не выдаются за успешную сборку или native проверку.

## Контракт релиза

* `release.py build` принимает только чистый committed checkout, проверяет
  AUTH-00 HEAD до/после build и собирает api/web/renderer из одной ревизии.
  Revision определяется на VM в момент сборки, а не подменяется базой b27b62f:
  после push этой поставки это будет следующий commit тимлида.
* Все три Dockerfile ставят OCI `org.opencontainers.image.revision`,
  `io.cisstat.source-tree` и `/usr/local/share/cisstat/build.json` в FINAL stage.
  Legacy build без аргументов получает `unverified`, который release gate отвергает.
  Новый manifest хранит три разных immutable `sha256:` image IDs, full Git SHA/tree,
  checksum профиля и generated overlays. Это provenance исходников и конкретных
  образов, не обещание bit-reproducible apt/pip/base-image сборки.
* API/web собираются Compose, поэтому сохраняются штатные `.env` public campaign
  build args. Личные SMTP/MFA/DB/worker secrets в build args не добавляются.
  Если действующие build overrides меняют build args, передайте тот же ordered
  список через повторяемый `--stack-file` и при build. Нового образа billing worker
  этот этап не создаёт; меняются только три запрошенных сервиса.
* A/B получает явный НОВЫЙ renderer image ID и проверяет его revision/tree.
  Работающий renderer не используется как источник нового image. Release A/B
  выполняется при512 PID/2GiB с четырьмя arms; cgroup maxima читаются внутри них.
  Отчёт старого `1837bee8…`, другой tree/revision или старый лимит128 не подходят.
  Если причинный результат отличается от CHROOT_RULE_CANDIDATE, rollout блокируется,
  профиль автоматически не расширяется/не отключается.
* Candidate имеет отдельные project и IPC volume. Native verifier сохраняет
  реальный `api_image_id`, требует cancel/deadline/lock/read-only/PNG controls.
  Production preflight принимает только успешный candidate после recreate
  с теми же новыми image IDs и candidate volume.
* API IPC RO+nocopy/GID10001; renderer10001:10001 RW, network:none, readonly root,
  cap_drop ALL, NNP, docker-default, reviewed seccomp,512 PID/2GiB и прежний tmpfs.
  Нет новых портов, host sysctl, cap_add или socket/secret forwarding.
* Capture берёт исходные Compose files из labels живых контейнеров (можно
  передать явные ordered `--stack-file`/`--renderer-file`). Проверяется согласие
  с реальными images/mounts/resources/hardening и безопасными IPC env полями.
  Полные Env/config с DSN/SMTP/MFA не сохраняются и не печатаются. Исходные
  YAML/JSON должны остаться на месте и с теми же hashes. `.env` сохраняет оператор.
* Rollback сохраняет реальные старые IDs и старую topology. При старом UDS
  сохраняются его volume/RO/RW/socket/profile/лимиты; при legacy не выдумывается
  новый IPC. Старый legacy transport blocker может вернуться — это возврат baseline,
  а не успешная UDS приёмка. Неизвестные/custom renderer namespace/command/egress
  settings требуют отдельного review и не нормализуются молча.
* Apply/rollback — отдельные явные действия с `--quiesced` после drain jobs.
  Сначала останавливаются web/api publishers, затем переключается renderer,
  затем api/web. Partial failure журналируется; автоматического rollback нет.
  Собственный незавершённый operation journal разрешает восстановить отсутствующий
  сервис; чужой/неизвестный image блокирует перезапись. Один оператор управляет
  релизом; внешние параллельные Docker/Compose изменения не допускаются.
* Нет DDL/DB rollback, сброса ключей/квот, force-release uncertain jobs,
  `down -v` или удаления IPC/scientific volumes. Старые images/inputs сохраняются.

## VM: подготовка и сборка

После ZIP → локальный review/gates → commit/push тимлида → VM pull.
Команды ниже из корня репозитория. Нужны Docker/Compose и Python3.12,
настроенная существующая `deployment/cisstat-stack/.env` и место под старые/новые
образы и finite candidate. Release directory — ВНЕ checkout, не в Git/pgdata.

```bash
git pull --ff-only
export PGV13_BUNDLE="/opt/cisstat/releases/pgv13-$(git rev-parse --short HEAD)-$(date -u +%Y%m%dT%H%M%SZ)"
pgv13_release() {
  env -u CISSTAT_AUTH_MFA_KEYS -u CISSTAT_AUTH_MFA_ACTIVE_KEY \
    python3 scripts/pgv13release/release.py "$@"
}
pgv13_release build --bundle "$PGV13_BUNDLE"
```

При nonzero остановиться: manifest остаётся BUILDING, export pins не выдаётся.
После исправления причины используйте новый bundle path; Docker layer cache
сохраняется. Не использовать новый image tag как подтверждение build.

## Сохранение действующего baseline

Найдите именно production renderer project, не оставшийся candidate:

```bash
docker ps --filter label=com.docker.compose.service=print-renderer \
  --format '{{.Names}}  {{.Label "com.docker.compose.project"}}'
# Вписать действительное имя из вывода:
export PGV13_RENDERER_PROJECT='deployment'
pgv13_release capture --bundle "$PGV13_BUNDLE" \
  --renderer-project "$PGV13_RENDERER_PROJECT"
source "$PGV13_BUNDLE/pins.env"
pgv13_release prepare-ipc --bundle "$PGV13_BUNDLE"
```

`deployment` — пример имени, не утверждение о VM. Для нестандартного stack
project передавайте `--stack-project` при build/capture. Capture не заменяет
существующий baseline.json; неправильный source/config/mount даёт отказ до up.
Инициализация volumes — новым non-root image; неверные owner/modes не ремонтируются.

## Новый A/B → отдельный candidate → recreate

```bash
python3 scripts/pgv13sandbox/probe.py --with-chroot --pids-limit 512 \
  --image "$CISSTAT_UDS_RENDERER_IMAGE" \
  --expected-revision "$PGV13_SOURCE_REVISION" --expected-tree "$PGV13_SOURCE_TREE" \
  --out "$PGV13_BUNDLE/ab.json"
python3 -c 'import json,sys; assert json.load(open(sys.argv[1]))["conclusion"]=="CHROOT_RULE_CANDIDATE"' "$PGV13_BUNDLE/ab.json"

docker compose -p "$PGV13_CANDIDATE_PROJECT" \
  -f apps/print-renderer/build/deployment/docker-compose.yml \
  -f "$PGV13_BUNDLE/candidate.json" \
  up -d --no-deps --no-build --pull never print-renderer
python3 scripts/pgv13uds/verify_vm.py --renderer-project "$PGV13_CANDIDATE_PROJECT" \
  --sandbox-report "$PGV13_BUNDLE/ab.json" --api-image "$PGV13_API_IMAGE" \
  --out "$PGV13_BUNDLE/candidate-first.json"

# Только candidate — проверка SIGKILL/stale socket/lifetime flock:
docker compose -p "$PGV13_CANDIDATE_PROJECT" \
  -f apps/print-renderer/build/deployment/docker-compose.yml \
  -f "$PGV13_BUNDLE/candidate.json" kill -s SIGKILL print-renderer
docker compose -p "$PGV13_CANDIDATE_PROJECT" \
  -f apps/print-renderer/build/deployment/docker-compose.yml \
  -f "$PGV13_BUNDLE/candidate.json" \
  up -d --force-recreate --no-deps --no-build --pull never print-renderer
python3 scripts/pgv13uds/verify_vm.py --renderer-project "$PGV13_CANDIDATE_PROJECT" \
  --sandbox-report "$PGV13_BUNDLE/ab.json" --api-image "$PGV13_API_IMAGE" \
  --previous-report "$PGV13_BUNDLE/candidate-first.json" \
  --out "$PGV13_BUNDLE/candidate-recreated.json"
```

Не продолжать при nonzero/failed. Дождаться healthy после up; если gate был
запущен раньше readiness, сохранить его FAIL и повторить, не редактируя JSON.
Старый production renderer остаётся нетронутым на этих шагах.

## Preflight → apply → live проверка

```bash
pgv13_release check --bundle "$PGV13_BUNDLE" \
  --ab-report "$PGV13_BUNDLE/ab.json" --native-report "$PGV13_BUNDLE/candidate-recreated.json"

# После операционного drain: нет текущих render/modeling jobs.
# Не снимать uncertain/financial holds для получения этого состояния.
pgv13_release apply --quiesced --bundle "$PGV13_BUNDLE" \
  --ab-report "$PGV13_BUNDLE/ab.json" --native-report "$PGV13_BUNDLE/candidate-recreated.json"

python3 scripts/pgv13uds/verify_vm.py --renderer-project "$PGV13_RENDERER_PROJECT" \
  --api-project cisstat-stack --sandbox-report "$PGV13_BUNDLE/ab.json" \
  --out "$PGV13_BUNDLE/live.json"
curl -fsS https://api.datasetup.ru/health
```

Apply использует pinned generated stack/renderer overlays, а не старый activate.py.
Успешный up означает только совпадение запущенных image IDs; readiness и native
transport подтверждаются следующими командами. Source profile copy проверяется
по содержимому, а не по прежнему абсолютному пути. Полный P01/P02 PNG/content/
visual/OCR/job-download акт — следующий этап, `pgv13_certified` остаётся false.

Для следующих перезапусков используйте сохранённые **base stack inputs + stack.json**
и **renderer base + renderer.json** с теми же project names. Base-only up вернёт
старую topology. Не удалять bundle/pins/baseline/старые images до принятия релиза.
Можно остановить только candidate теми же `-p/-f` и `down` БЕЗ `-v`.

## Откат

После остановки/drain publishers, из того же checkout с неизменными inputs:

```bash
pgv13_release rollback --quiesced --bundle "$PGV13_BUNDLE"
curl -fsS https://api.datasetup.ru/health
```

Сохраняются DB/keys/science_data/worker proofs и оба IPC volumes. `operation.json`
показывает фазу и возможное partial изменение. При стороннем image/config drift
автоматическое переключение блокируется: оператор сначала сверяет фактическую
ситуацию с baseline, а не правит checksums/manifest для обхода отказа.

## Локальная проверка поставки

```bash
python -m unittest discover -s tests/unit -p test_pgv13_release.py -v
python -m pytest scripts/pgv13sandbox scripts/pgv13uds/test_vm.py scripts/pgv13cert/test_deployment.py -q
git add --pathspec-from-file=scripts/pgv13release/files.txt
python scripts/local_gates.py --only auth00 --skip-install
```

Новых default gates нет; explicit release checks описаны в local_gates.md.
AUTH-00 отражает OS/Docker operator boundary; HTTP methods/paths/DTO прежние.
В сессии:16 unit controls,72 focused regression, fresh renderer build и обе
production Next builds PASS. Docker/реальный merge/copy-up/build/A-B/recreate/
live/rollback на VM ещё PENDING. Локальные протоколы — scripts/pgv13release/protocols.
