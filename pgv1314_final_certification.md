# Окончательная сертификация задач PGV-13 и PGV-14

База: `77cbd70251d9dc46eff82f78ac2b5f92ebc0d155`, 24.11.2026.
Норматив: spec_passport_graphics_visual.md, задачи13/14; §7–9, PGV-AC06,
09–16,18–21,23 в границах passport builder/page-set. PGV15 UI, PGV16 и общий
PGV-CERT всех scientific sites в этот акт не входят.

## Полученное доказательство VM

`upload/1(1).txt` подтверждает восстановление API `cb1635c…`, web `0c74b32…`,
renderer `55278b45…` и успешный `capture` baseline с transport=uds. Это прежний
релиз4a6d1f73ebec, точка отката. В выводе нет нового A/B/candidate/recreate/live,
PNG страниц, OCR или review. `pgv13_certified:false` в capture корректен.
Нельзя объявить две задачи сертифицированными по этому выводу.

## Решение

Новый CLI `scripts/pgv1314cert/verify.py` замыкает цепочку:

1. `local` — свежая сборка renderer, точный manifest pytest и357 print/Jest
   assertions без skips,18 независимых typography controls, CP1252 regression,
   actual ASGI/карта, typecheck и production builds обеих оболочек. Frozen
   fingerprints runtime/tool/catalog/lock/spec, hashes всех raw reports/logs.
   Только Memory contracts; реальные PG/AuthSession/jobs проверяет следующий шаг.
   Любой failure/подмена/пропуск/изменение sources оставляет FAIL. Source DSN,
   worker/login/SMTP/MFA credentials не передаются локальным probes.
2. `plan` — только печатает bash-план продолжения **после capture**, используя
   ровно заданный bundle/его manifest и baseline projects. Нет ls/latest,
   повторного capture/build, source непроверенного pins.env или авто-apply.
   Уже существующие native evidence не перезаписываются. Прежний release gate
   требует точный image-source HEAD: план временно выбирает этот committed SHA
   и возвращает tool revision после apply/live. Допускается только доказанный
   host-only descendant; изменение API/print/runtime требует новых images.
3. `run` — требует успешные local + A/B + first/recreated + live, запускает
   существующий isolated PostgreSQL/AuthSession/CSRF/AUTH13 managed-worker
   client на **всех11** неизменных случаях. Каждый downloaded PNG/ZIP/JSON,
   каждый page CRC/geometry/300ppi/pixel/OCR/hash, source binding и document
   semantics проверяются прежним PGV14 pipeline. Плотные случаи не исключаются
   и не заменяются ожидаемыми413. Дополнительный pinned API-image/UDS client
   проверяет >20 pages и indivisible row: именно HTTP413, правильный code,
   retryable=false и header=false, без PNG/частичного ZIP. Cgroups/hardening
   и cleanup тоже обязательны; production DB не используется.
4. `issue` — повторно читает каждый файл, все PNG/OCR/metadata и review каждой
   страницы; не доверяет одному passed/accepted. Фиксированный semantic oracle
   берётся из native fixture definition (вынесен без изменения данных/формул),
   его нельзя ослабить в report.json. Bundle hashes, точные7 compiled paths,
   source fingerprints,11cases, registry/session/financial-holds proof,
   budgets и свежая read-only live проверка **всех трёх** images/markers/socket
   связываются в immutable `pgv.tasks_certification/1`.

Только шаг4 выставляет `task_certification.PGV-13=true` и `PGV-14=true`.
`full_pgv_certified=false` остаётся: общий PGV-CERT не заявляется. Старые
частные reports/их `pgv13_certified:false` не переписываются. Source/image/report
identity и истинность review не заменяются подписью аналитика «всё прошло».

## Риски и контроли

Неполные/дублированные tests, skipped/xfail, stale report, wrong image/volume,
чужой compiled module, уменьшенный OCR oracle, false retryability, утраченный
checkpoint/case, scientific sessions/holds, path traversal/symlink, неподтверждённая
последняя страница и existing certificate блокируют выдачу. `validate_acceptance`
в старом host verifier выделен как read-only функция; прежний finalize использует
её же, его политика не ослаблена. API/renderer/shared print bytes/SQL/HTTP routes
не меняются. Новый инструмент исполняет только reviewed отдельный test contour.
Shell plan не меняет release guard, security profiles, volumes или live сервисы.
Сам агент не выполняет VM rollout/commit/push.

## VM: продолжить с полученного capture

После ZIP → review/gates → commit/push тимлида → `git pull --ff-only` на VM.
Сохраните **точный** путь уже captured PGV14 bundle; не выбирайте его через ls.
Ниже переменная B должна указывать именно на этот каталог с manifest/baseline.
Host venv нужны API/scientific requirements для local tests, а для run/issue
также Pillow и установленный Tesseract rus+eng. Docker API/science остаются
в собственных disposable контурах.

```bash
# Из корня чистого committed checkout:
export B='/opt/cisstat/releases/ТОЧНЫЙ_CAPTURED_PGV14_BUNDLE'
python3 scripts/pgv1314cert/verify.py plan --bundle "$B" > "$B/resume-pgv1314.sh"
# Просмотреть весь файл, затем выполнить candidate/preflight (apply ещё не вызывается):
source "$B/resume-pgv1314.sh"
# После штатного operator drain, без active/uncertain jobs:
pgv1314_apply_after_drain
```

`plan` не вызывает `capture` второй раз. Если native files уже существуют,
сохраните их и продолжите соответствующий шаг вручную по docs/pgv13_release.md.
Не удаляйте baseline/evidence ради запуска с начала. Если runtime действительно
отличается от manifest revision, требуется новый coherent api/web/renderer
bundle (`release.py build`) и новый capture; старый bundle не переписывать.
Изменения этой поставки host-only: сами по себе rebuild не требуют.

Затем из возвращённого tool checkout, new output directories вне репозитория:

```bash
export PYC='/opt/cisstat/venvs/pgv1314cert/bin/python'
# В venv заранее установить scripts/pgv1314cert/requirements.txt; npm ci выполнен.
"$PYC" scripts/pgv1314cert/verify.py local --out "$B/pgv1314-local"
export PG_IMAGE="$(docker image inspect postgres:16 --format '{{.Id}}')"
"$PYC" scripts/pgv1314cert/verify.py run --bundle "$B" \
  --local "$B/pgv1314-local/summary.json" --postgres-image "$PG_IMAGE" \
  --out "$B/pgv1314-native"
```

Открыть `review.html`, затем каждую PNG в полном размере. Скопировать
review.template.json в review.json; заполнить reviewer/aware reviewed_at,
только после реального просмотра выставить5 критериев каждой страницы.
При дефекте оставить false и сохранить finding; не редактировать hashes/PNG.

```bash
"$PYC" scripts/pgv1314cert/verify.py issue --bundle "$B" \
  --local "$B/pgv1314-local/summary.json" --report "$B/pgv1314-native/report.json" \
  --review "$B/pgv1314-native/review.json" --out "$B/pgv1314-native/certificate.json"
```

Ожидаемый итог — CERTIFIED только двух задач. Missing Docker/reports/review,
nonzero, прошлый capture или control doubles никогда не выдают certificate.
Сохранить оба evidence directories/bundle/certificate; DB/IPC/science volumes,
старые images и rollback baseline не удалять. Rollback — прежний release.py
rollback --quiesced из исходного release source с сохранёнными inputs.

## Локальные gates поставки

Default `pgv1314cert` и CI Ubuntu/Windows проверяют независимые issuer controls.
Отдельный Linux CI job может создать полный local evidence artifact; он всё равно
не сертификат без VM/run/issue. Полный local command доступен выше. Перед AUTH00:

```bash
git add --pathspec-from-file=scripts/pgv1314cert/files.txt
python scripts/local_gates.py --only pgv1314cert,pgv14,auth00 --skip-install
```

Local runner сохраняет существующие инфраструктурные CA/proxy настройки
(NODE_EXTRA_CA_CERTS/SSL_CERT_FILE и др.), чтобы next/font мог штатно проверить
TLS. TLS verification не отключается; секреты платформы в env не передаются.
Jest paths в evidence нормализованы относительно checkout, поэтому CI artifact
переносим при идентичных fingerprints. Первичный запуск в сессии честно дал FAIL
на next/font SELF_SIGNED_CERT_IN_CHAIN из-за излишне урезанного CA env;
протокол сохранён, это не успешная production сборка.
