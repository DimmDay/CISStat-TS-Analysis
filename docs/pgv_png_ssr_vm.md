# VM: выпуск PGV-PNG-SSR с сохранением UDS

После review/гейтов/commit/push тимлида. Из корня репозитория на VM, один
оператор. Исправляются общий print layout и renderer; штатный coherent release собирает три образа с
одинаковой ревизией и новыми immutable pins. Нужен **новый** bundle, прежний
`922ff70c2381` и его evidence сохраняются как история. Миграций нет.
Никакие команды ниже не извлекают значения `.env`/DSN/MFA/worker keys.
Нельзя считать новую версию развёрнутой после одного `git pull`/build.

## 1. Подготовить новые образы

```bash
set -euo pipefail
git pull --ff-only
export PGV13_BUNDLE="/opt/cisstat/releases/pgv-png-ssr-$(git rev-parse --short HEAD)-$(date -u +%Y%m%dT%H%M%SZ)"
pgv13_release() {
  env -u CISSTAT_WORKER_KEY -u CISSTAT_AUTH_MFA_KEYS -u CISSTAT_AUTH_MFA_ACTIVE_KEY \
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

В данном инциденте старый render остаётся uncertain. Нулевой claimed и здоровый
health не доказывают отсутствие исполнителей. В окно обслуживания прекратить
новые действия пользователей и **физически остановить старые publishers и
renderer**, сохраняя все контейнеры, volumes, image IDs и резервы. Это даёт
реальное quiescence для переключения; БД job не объявляется завершённым.
Команды ниже остановят web/API/renderer до apply, сайт временно недоступен.
Сначала candidate/recreate/check выше должны пройти.

```bash
PGV13_OLD_RENDERER=$(docker ps -aq \
  --filter "label=com.docker.compose.project=$PGV13_RENDERER_PROJECT" \
  --filter 'label=com.docker.compose.service=print-renderer')
test -n "$PGV13_OLD_RENDERER"
test "$(printf '%s\n' "$PGV13_OLD_RENDERER" | wc -l)" -eq 1
docker stop --time 30 cisstat-stack-web-1 cisstat-stack-api-1 "$PGV13_OLD_RENDERER"
docker inspect --format '{{.Name}} running={{.State.Running}} pid={{.State.Pid}}' \
  cisstat-stack-web-1 cisstat-stack-api-1 "$PGV13_OLD_RENDERER"
```

Для всех трёх обязательны running=false и pid=0; иначе не утверждать quiescence.
Если есть другие API/modeling/delivery publishers, их тоже надо штатно
остановить/дождаться в этом окне. При нестандартных именах не подставлять чужой
контейнер. Не удалять контейнеры, IPC/scientific volumes, reservations/proofs.
После этой проверки `--quiesced` означает физическую остановку, а не обнуление
SQL-счётчиков. `release.py` читает baseline images у остановленных контейнеров
через compose ps -a и сохраняет ordered inputs; запускает новые pinned images.

```bash
pgv13_release apply --quiesced --bundle "$PGV13_BUNDLE" \
  --ab-report "$PGV13_BUNDLE/ab.json" --native-report "$PGV13_BUNDLE/candidate-recreated.json"
python3 scripts/pgv13uds/verify_vm.py --renderer-project "$PGV13_RENDERER_PROJECT" \
  --api-project cisstat-stack --sandbox-report "$PGV13_BUNDLE/ab.json" \
  --out "$PGV13_BUNDLE/live.json"
curl -fsS https://api.datasetup.ru/health
```

После live PASS и выдачи свободного слота ниже: в UI загрузить новый датасет, подтвердить дату/цель,
проверить первый экспорт Обзора, графика и EDA, ready в «Документах исследования»
и реальные скачанные PNG. Исторические результаты не надо пересоздавать
научными расчётами. Полная PGV-CERT остаётся отдельной приёмкой обеих оболочек.
Перезапуски используют сохранённые base inputs + generated overlays текущего
bundle; rollback — по его baseline. Старые образы/IPC/science volumes сохраняются.


## Сохранённый hold и свободный слот для новой проверки

Runtime fix не переписывает прежний remote_unknown proof. Старый uncertain
и reserved1 останутся; это ожидаемо. Для проверки новой операции нужен ещё
один честно выделенный слот. Если уже внедрена отдельная панель ресурсов,
назначить своему Account concurrency2 (или требуемый конечный лимит).
Эта SSR-поставка саму панель/0038 не содержит, VM базой подтверждена64a6604.

До внедрения панели можно применить **штатную operator CLI AUTH12**. Только
после успешного нового release/live, для подтверждённого в инциденте служебного
Account c8ec43be-bd1a-407d-bbaa-93e1ca05524e. Сначала читается CAS version и
проверяется прежнее состояние root Account: active/internal, concurrency1,
spent0/reserved1, без grant/parent. При изменившемся состоянии команда прервётся;
не править SQL ради продолжения. Это увеличение общего лимита1→2 с аудитом,
а не refund/reset/bypass. Reserved1 остаётся; после нового успешного PNG он
тоже останется1. Параметр --expected-version защищает от гонки.

```bash
PGV13_SLOT_VERSION=$(docker exec -i cisstat-stack-api-1 python - <<'PYCODE'
from apps.api.authentication.storage import PostgresAccessStore
try:
    with PostgresAccessStore.from_env().transaction(readonly=True) as tx:
        row=tx.connection.execute("""
          SELECT b.version FROM auth_resource_budgets b
          JOIN auth_budget_scopes s USING(scope_id)
          JOIN auth_accounts a ON a.account_id=s.account_id
          WHERE b.scope_id='c8ec43be-bd1a-407d-bbaa-93e1ca05524e'
            AND s.kind='account' AND s.parent_id IS NULL
            AND a.plan='internal' AND a.status='active'
            AND b.metric='concurrency' AND b.period='lifetime'
            AND b.limit_units=1 AND b.spent=0 AND b.reserved=1
            AND NOT EXISTS(SELECT 1 FROM auth_budget_scopes g
                           WHERE g.account_id=a.account_id AND g.kind='grant')
        """).fetchone()
        if not row: raise ValueError()
        print(row['version'])
except Exception:
    raise SystemExit('budget_state_changed_or_unavailable')
PYCODE
)
docker exec -it cisstat-stack-api-1 python scripts/auth12/manage_budget.py budget-set \
  c8ec43be-bd1a-407d-bbaa-93e1ca05524e concurrency \
  --limit-units 2 --expected-version "$PGV13_SLOT_VERSION" \
  --reason 'PGV-PNG-SSR: one additional slot; previous uncertain reservation preserved'
```

Тестовый trial grant.analysis10/spent10 — отдельный лимит; увеличение admin
concurrency его не меняет. Индивидуальные выдачи/панель ресурсов — отдельная
поставка, которую надо объединять с SSR fix с повторной генерацией AUTH00
и гейтами, если тимлид решит включать обе в один commit.

Rollback по docs/pgv13_release.md, тот же bundle, действительное quiescence.
Не откатывать usage/ledger и не понижать concurrency ниже занятых слотов.
Научные артефакты не пересчитывать и не редактировать: существующие frozen
payload без warnings поддерживаются новым renderer автоматически.


Для UI-приёмки создать **новое исследование**. Старая кнопка того же view/run
может вернуть прежний deduplicated rendering job: SSR fix не возобновляет
uncertain и не создаёт новый научный результат. Старую историю сохраняем
для отдельного AUTH13 восстановления. Готовность нового экспорта подтвердить
реально скачанным PNG, не одним202/queued и не readiness renderer.
