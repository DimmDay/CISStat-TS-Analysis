# PGV-13-IMAGE-ASSETS — исправление состава API image

20.11.2026. База — `dd6ce31` + переданный43-file пакет PGV-13-DOCUMENTS
(SHA256 `70316a86eacc0d5ca1f852bce0f30f1e0902d68b9f19d26e193048c0a99a00aa`).
Новый SHA сервера после применения того пакета не предоставлялся; агент не
выполнял повторный fetch main, commit/push или операции Docker на VM.

## Причина и исправление

Операторский run остановился в setup на отрицательной проверке create:
оба ответа содержали `passport_document_unavailable`/«Экспорт временно
недоступен». Это generic503 из router, не ожидаемый uniform404.

В реально использованном API Dockerfile отсутствовал COPY двух runtime twins:
`config/print_schema.json` и `config/visual_registry.json`. Backend читает их
через `apps.api.print_schema`. В request_passport_document вызов _validate_profile
предшествует object authorization: отсутствующий print_schema вызывает
FileNotFoundError ещё до owner/foreign/missing развилки, broad handler даёт503.
Точно этот missing path воспроизведён stdlib reader в файловой проекции
исходного Docker recipe. Local ASGI/native тест имел полный repository config,
поэтому этот image-only дефект не выявлял. Startup/UDS smoke тоже не загружал
печатный каталог — прежние PASS не были проверкой P01/P02 content.

API Dockerfile теперь копирует оба исходных JSON в `/app/config/`; финальный
RUN читает их настоящим reader, проверяет версии, три профиля и px/mm/ppi до
revision stamp. Ни fallback-каталог, ни дополнение payload не добавлены.
Config content/TS/render layout/HTTP methods/paths/DTO и object guards прежние.

Run gate дополнительно проверяет assets в самом immutable API image до
создания временной БД: наличие, JSON/catalog validity и точные SHA256. Оба JSON
включены в source parity и внутри native client. Finalize требует это evidence.
Client failure печатается в финальной сводке сразу; в uniform404 диагностике
теперь есть фактический status каждого ответа. Отрицательные проверки не ослаблены.

## Почему нужен новый согласованный комплект

Старый API image `sha256:c5285274…` остаётся неизменным и не содержит нужных
файлов. Установка только host harness не исправляет этот image. Нужна новая
сборка после commit/push этого пакета. Release protocol связывает все3 image
одной revision/tree, поэтому используется штатный build api/web/print-renderer;
для нового renderer image нужен новый A/B, candidate/recreate и live evidence.
Старые JSON/manifest/pins не редактировать и не переносить как доказательство
новых image IDs. Точечный docker cp/config bind mount не является исправлением.

Зависимости pip/base stages могут использовать cache. Из-за COPY apps/api/
(включая сам Dockerfile) scientific smoke может выполниться повторно; следить
за build logs из второго SSH-терминала. API build guard намеренно не пропускается.

## VM — новый bundle и baseline текущего UDS релиза

После локальной распаковки/review/gates, commit/push тимлида:

```bash
git pull --ff-only
pgv13_release() {
  env -u CISSTAT_AUTH_MFA_KEYS -u CISSTAT_AUTH_MFA_ACTIVE_KEY \
    python3 scripts/pgv13release/release.py "$@"
}
# Сохранить старый bundle; не удалять его и старые images/volumes.
export PGV13_PREVIOUS_BUNDLE="${PGV13_BUNDLE:-/opt/cisstat/releases/pgv13-3b13214-20261120T101532604464185Z}"
export PGV13_BUNDLE="/opt/cisstat/releases/pgv13-$(git rev-parse --short HEAD)-$(date -u +%Y%m%dT%H%M%S%NZ)"
printf 'Build logs:\n%s/build-api-web.log\n%s/build-renderer.log\n' "$PGV13_BUNDLE" "$PGV13_BUNDLE"
pgv13_release build --bundle "$PGV13_BUNDLE"

export PGV13_RENDERER_PROJECT=deployment
pgv13_release capture --bundle "$PGV13_BUNDLE" \
  --renderer-project "$PGV13_RENDERER_PROJECT"
source "$PGV13_BUNDLE/pins.env"
pgv13_release prepare-ipc --bundle "$PGV13_BUNDLE"

python3 scripts/pgv13sandbox/probe.py --with-chroot --pids-limit 512 \
  --image "$CISSTAT_UDS_RENDERER_IMAGE" \
  --expected-revision "$PGV13_SOURCE_REVISION" --expected-tree "$PGV13_SOURCE_TREE" \
  --out "$PGV13_BUNDLE/ab.json"
python3 -c 'import json,sys; assert json.load(open(sys.argv[1]))["conclusion"]=="CHROOT_RULE_CANDIDATE"' "$PGV13_BUNDLE/ab.json"
```

Выполнять поэтапно; при nonzero/failed сохранить вывод и остановиться. Capture
теперь сохраняет текущий UDS baseline, а не прежний legacy; откат к нему также
вернёт старый API без print twins. Это честная граница fallback, не content PASS.

## Новый candidate и проверка пересоздания

```bash
docker compose -p "$PGV13_CANDIDATE_PROJECT" \
  -f apps/print-renderer/build/deployment/docker-compose.yml \
  -f "$PGV13_BUNDLE/candidate.json" \
  up -d --wait --wait-timeout 120 --no-deps --no-build --pull never print-renderer
python3 scripts/pgv13uds/verify_vm.py --renderer-project "$PGV13_CANDIDATE_PROJECT" \
  --sandbox-report "$PGV13_BUNDLE/ab.json" --api-image "$PGV13_API_IMAGE" \
  --out "$PGV13_BUNDLE/candidate-first.json"
docker compose -p "$PGV13_CANDIDATE_PROJECT" \
  -f apps/print-renderer/build/deployment/docker-compose.yml \
  -f "$PGV13_BUNDLE/candidate.json" kill -s SIGKILL print-renderer
docker compose -p "$PGV13_CANDIDATE_PROJECT" \
  -f apps/print-renderer/build/deployment/docker-compose.yml \
  -f "$PGV13_BUNDLE/candidate.json" \
  up -d --force-recreate --wait --wait-timeout 120 --no-deps --no-build --pull never print-renderer
python3 scripts/pgv13uds/verify_vm.py --renderer-project "$PGV13_CANDIDATE_PROJECT" \
  --sandbox-report "$PGV13_BUNDLE/ab.json" --api-image "$PGV13_API_IMAGE" \
  --previous-report "$PGV13_BUNDLE/candidate-first.json" \
  --out "$PGV13_BUNDLE/candidate-recreated.json"
pgv13_release check --bundle "$PGV13_BUNDLE" \
  --ab-report "$PGV13_BUNDLE/ab.json" --native-report "$PGV13_BUNDLE/candidate-recreated.json"
```

## Apply/live и повтор P01/P02

Следующий блок — только после успешного preflight, остановки новых запусков
и завершения текущих jobs. `--quiesced` подтверждает уже выполненный drain,
не выполняет его автоматически.

```bash
pgv13_release apply --quiesced --bundle "$PGV13_BUNDLE" \
  --ab-report "$PGV13_BUNDLE/ab.json" --native-report "$PGV13_BUNDLE/candidate-recreated.json"
# Дождаться готовности API/renderer.
python3 scripts/pgv13uds/verify_vm.py --renderer-project "$PGV13_RENDERER_PROJECT" \
  --api-project cisstat-stack --sandbox-report "$PGV13_BUNDLE/ab.json" \
  --out "$PGV13_BUNDLE/live.json"
curl -fsS https://api.datasetup.ru/health

# Host venv/Tesseract уже установлены предыдущим этапом.
PGV13_PG_CONTAINER="$(docker ps -q \
  --filter label=com.docker.compose.project=cisstat-stack \
  --filter label=com.docker.compose.service=postgres)"
export PGV13_POSTGRES_IMAGE="$(docker inspect --format '{{.Image}}' "$PGV13_PG_CONTAINER")"
export PGV13_DOCUMENTS_OUT="/opt/cisstat/releases/pgv13-documents-$(date -u +%Y%m%dT%H%M%S%NZ)"
/opt/cisstat/venvs/pgv13accept/bin/python scripts/pgv13accept/verify_vm.py run \
  --bundle "$PGV13_BUNDLE" --renderer-project "$PGV13_CANDIDATE_PROJECT" \
  --postgres-image "$PGV13_POSTGRES_IMAGE" --out "$PGV13_DOCUMENTS_OUT"
```

Ждать автоматического11-case PNG/OCR результата. Отчёт прошлой неудачной попытки
сохраняется; новый run — в новый каталог. Human visual review/finalize остаются
обязательными по `docs/pgv13_document_acceptance.md`; pgv13_certifiedfalse.
Фактический rebuild/A-B/P01-P02 native Docker результат ещё PENDING VM.

## Проверки

```bash
python -m unittest discover -s tests/unit -p test_pgv13_image_assets.py -v
python -m unittest discover -s tests/unit -p test_pgv13_accept.py -v
python -m unittest discover -s tests/unit -p test_pgv13_release.py -v
# Только disposable PostgreSQL, CISSTAT_PGV13_CERT_DSN уже задан:
python -m unittest scripts.pgv13accept.test_native -v
python scripts/auth06/check_routes.py
```

Локально выполнены projection/stdlib-reader tests и реальные subprocess build
guard/image probe в projected filesystem, с negative missing/corrupt cases.
Это не фактический Docker build. Native ASGI/jobs тест использует контролируемый
PNG transport double, не заменяет product PNG/OCR. Протоколы:
`scripts/pgv13accept/protocols/image-assets/`. Роуты/DTO прежние, AUTH-00
fingerprints Dockerfile/config/tool/test sources обновлены; default gates прежние.
