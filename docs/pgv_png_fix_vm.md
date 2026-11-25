# VM: выпуск PGV-PNG-FIX с сохранением UDS

После review/гейтов/commit/push тимлида. Из корня репозитория на VM, один
оператор. Исправляется API; штатный coherent release собирает три образа с
одинаковой ревизией и новыми immutable pins. Нужен **новый** bundle, прежний
`922ff70c2381` и его evidence сохраняются как история. Миграций нет.
Никакие команды ниже не извлекают значения `.env`/DSN/MFA/worker keys.
Нельзя считать новую версию развёрнутой после одного `git pull`/build.

## 1. Подготовить новые образы

```bash
set -euo pipefail
git pull --ff-only
export PGV13_BUNDLE="/opt/cisstat/releases/pgv-png-fix-$(git rev-parse --short HEAD)-$(date -u +%Y%m%dT%H%M%SZ)"
pgv13_release() {
  env -u CISSTAT_AUTH_MFA_KEYS -u CISSTAT_AUTH_MFA_ACTIVE_KEY \
    python3 scripts/pgv13release/release.py "$@"
}
pgv13_release build --bundle "$PGV13_BUNDLE"
docker ps --filter label=com.docker.compose.service=print-renderer \
  --format '{{.Names}}  {{.Label "com.docker.compose.project"}}'
```

В последнем подтверждённом акте production renderer project — `deployment`,
stack — `cisstat-stack`. Сверить именно production в выводе, не старый candidate.
Далее используется этот project; при иной фактической topology остановиться
и выбрать её реальные ordered inputs по `docs/pgv13_release.md`.

```bash
export PGV13_RENDERER_PROJECT='deployment'
pgv13_release capture --bundle "$PGV13_BUNDLE" --renderer-project "$PGV13_RENDERER_PROJECT"
source "$PGV13_BUNDLE/pins.env"
pgv13_release prepare-ipc --bundle "$PGV13_BUNDLE"
```

## 2. Проверить новый candidate, сохранив production

```bash
python3 scripts/pgv13sandbox/probe.py --with-chroot --pids-limit 512 \
  --image "$CISSTAT_UDS_RENDERER_IMAGE" \
  --expected-revision "$PGV13_SOURCE_REVISION" --expected-tree "$PGV13_SOURCE_TREE" \
  --out "$PGV13_BUNDLE/ab.json"
python3 -c 'import json,sys; assert json.load(open(sys.argv[1]))["conclusion"]=="CHROOT_RULE_CANDIDATE"' "$PGV13_BUNDLE/ab.json"
docker compose -p "$PGV13_CANDIDATE_PROJECT" \
  -f apps/print-renderer/build/deployment/docker-compose.yml -f "$PGV13_BUNDLE/candidate.json" \
  up -d --no-deps --no-build --pull never print-renderer
python3 scripts/pgv13uds/verify_vm.py --renderer-project "$PGV13_CANDIDATE_PROJECT" \
  --sandbox-report "$PGV13_BUNDLE/ab.json" --api-image "$PGV13_API_IMAGE" \
  --out "$PGV13_BUNDLE/candidate-first.json"
docker compose -p "$PGV13_CANDIDATE_PROJECT" \
  -f apps/print-renderer/build/deployment/docker-compose.yml -f "$PGV13_BUNDLE/candidate.json" \
  kill -s SIGKILL print-renderer
docker compose -p "$PGV13_CANDIDATE_PROJECT" \
  -f apps/print-renderer/build/deployment/docker-compose.yml -f "$PGV13_BUNDLE/candidate.json" \
  up -d --force-recreate --no-deps --no-build --pull never print-renderer
python3 scripts/pgv13uds/verify_vm.py --renderer-project "$PGV13_CANDIDATE_PROJECT" \
  --sandbox-report "$PGV13_BUNDLE/ab.json" --api-image "$PGV13_API_IMAGE" \
  --previous-report "$PGV13_BUNDLE/candidate-first.json" \
  --out "$PGV13_BUNDLE/candidate-recreated.json"
pgv13_release check --bundle "$PGV13_BUNDLE" \
  --ab-report "$PGV13_BUNDLE/ab.json" --native-report "$PGV13_BUNDLE/candidate-recreated.json"
```

Любой отказ — остановка, исходный FAIL сохраняется. Повторный verifier пишет
новый output, а не перезаписывает evidence. Повтор после отказа readiness не
является заменой успешного candidate/recreate/check. Полный норматив —
`docs/pgv13_release.md`.

## 3. Переключить после операционного drain и проверить

Только после остановки текущих render/modeling работ. Uncertain/финансовые
holds не снимаются ради drain. `--quiesced` — утверждение оператора об этом
факте, а не команда автоматического ожидания.

```bash
pgv13_release apply --quiesced --bundle "$PGV13_BUNDLE" \
  --ab-report "$PGV13_BUNDLE/ab.json" --native-report "$PGV13_BUNDLE/candidate-recreated.json"
python3 scripts/pgv13uds/verify_vm.py --renderer-project "$PGV13_RENDERER_PROJECT" \
  --api-project cisstat-stack --sandbox-report "$PGV13_BUNDLE/ab.json" \
  --out "$PGV13_BUNDLE/live.json"
curl -fsS https://api.datasetup.ru/health
```

После live PASS: в UI загрузить новый датасет, подтвердить дату/цель,
проверить первый экспорт Обзора, графика и EDA, ready в «Документах исследования»
и реальные скачанные PNG. Исторические результаты не надо пересоздавать
научными расчётами. Полная PGV-CERT остаётся отдельной приёмкой обеих оболочек.
Перезапуски используют сохранённые base inputs + generated overlays текущего
bundle; rollback — по его baseline. Старые образы/IPC/science volumes сохраняются.
