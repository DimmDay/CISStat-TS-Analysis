# PGV-13-OCR-FIX — P01/P02 и проверка скачанных PNG

20.11.2026. База: dd6ce31 + полный предыдущий PGV-13-DOCUMENTS/IMAGE-ASSETS
пакет. Синхронизация с новым GitHub HEAD в этом исправлении не выполнялась.
Нет commit/push, SSH или изменений VM из сессии разработки.

## Причины и решение

* P01: frozen fixture содержит `seasonal_periods`. В известном печатном словаре
  такого ключа нет: компонент честно выводит исходный ключ неизвестной группы.
  Oracle ошибочно требовал «Сезонные периоды». Теперь требуется фактический ключ;
  fixture/payload, исторические refs, число групп и маркер БЕРЁЗА не дополнены.
  Корпус содержит 9 известных групп и 2 неизвестные (`seasonal_periods`,
  `certificate_tail`), а не все 12 групп, поддерживаемых печатным словарём.
* P02: заголовки разделов были 14px, «Определения» — 10px. В диагностике оператора
  целая страница теряла заголовки; crop распознал «Определения» с confidence96.35,
  но «категориальные» оставалось неверным/0. Все три заголовка P02 теперь 22px,
  bold700, line-height1.4. Текст/значения/формулы/reasons не переписаны.
* OCR: все области с тёмными пикселями выделяются независимо от payload и
  ожидаемых слов. Разрыв — 64 полностью пустые строки; нижний колонтитул остаётся.
  Области не перекрываются. Увеличение Lanczos3x (2x/1x при лимите 24MP), PSM6,
  координаты TSV переводятся обратно в координаты исходного PNG. Отдельно
  фиксируются boxes/scale/input hashes/raw TSV hashes; исходный PNG неизменен.
* Для ASCII ключей (`FFT`, `seasonal_periods`, `partial`, reasons) используется
  отдельный английский проход тех же пикселей. Русские/смешанные фразы, числа и
  русские occurrence counts проверяются только по rus+eng. Фразы между проходами
  не склеиваются. Confidence>=20, обязательные фразы/числа/точные counts сохранены.
  В контроле русский словарь ошибочно читал FFT как ЕЕТ; слитное FFT-периоды
  давало английскому проходу confidence0 для всего смешанного слова. Печатная
  подпись теперь «FFT — периоды»: самостоятельное FFT распознаётся уверенно.
  Это изменение подписи, научный ключ `fft` и его значения прежние.
* Finalize сразу сообщает о незавершённой автоматической приёмке. OCR FAIL больше
  не выдаётся за «Native PostgreSQL client failed». Обе TSV hash-bound и повторно
  проверяются при finalize; старый report несовместим с новым tool hash/pipeline.

Увеличение OCR-входа не доказывает удобство печати. Читаемость при фактическом
масштабе, кириллица, overlap/clipping и значения требуют review всех 11 PNG.
Общая типографская шкала/геометрия/pagination не менялись. Особенно проверить
P01 reused set: универсальная pagination/page-set остаётся PGV-14.

## Проверки и границы

TDD RED: 5 новых Python tests (6 отказов с subtests), отдельный печатный RED.
GREEN: 62 Python unit/release tests, 54 print tests, 2 настоящих Tesseract
контроля, 11 native PostgreSQL/AuthSession/managed-jobs/download сценариев.
Native local test использует PNG transport double, не Chromium. Локальные
Tesseract controls используют синтетические пиксели, не продуктовые PNG.
Docker daemon/VM недоступны; реальные новый image/A-B/PNG/review остаются VM.
Протоколы: `scripts/pgv13accept/protocols/ocr-fix/`.

HTTP/renderer routes, guards, DTO, IPC, seccomp, cgroups, DB migrations не менялись.
AUTH-00 обновляет reviewed-source fingerprints и строку прежней CLI boundary;
новых boundaries нет. `scripts/local_gates.py` не изменяется; explicit checks
добавлены в local_gates.md. ZIP содержит полный накопленный пакет этапа documents
с этим исправлением. Распаковать после review; перед commit использовать manifest
`scripts/pgv13accept/files.txt`. Не заменять исходники без проверки локальных diff.

## VM — новая согласованная сборка

Меняется compiled print layout: **старые images и OCR отчёты не подходят**.
Не переиспользовать bundle, не переписывать старые manifest/report/review.
После локальных gates, commit/push тимлида и pull на VM из корня checkout:

```bash
git pull --ff-only
pgv13_release() {
  env -u CISSTAT_AUTH_MFA_KEYS -u CISSTAT_AUTH_MFA_ACTIVE_KEY \
    python3 scripts/pgv13release/release.py "$@"
}
export PGV13_BUNDLE="/opt/cisstat/releases/pgv13-ocr-$(git rev-parse --short HEAD)-$(date -u +%Y%m%dT%H%M%S%NZ)"
pgv13_release build --bundle "$PGV13_BUNDLE"
```

При каждом nonzero остановиться. Далее последовательно выполнить прежнюю
цепочку `docs/pgv13_release.md`: capture текущего baseline → source нового
pins.env → prepare-ipc → НОВЫЙ A/B → candidate-first → candidate-recreated →
preflight. Перед apply обеспечить штатный drain jobs; apply/live — отдельный
операторский этап. Ниже те же команды; production project `deployment` взят
из предоставленного оператором `docker ps`, его нужно сверить при изменении VM.

```bash
export PGV13_RENDERER_PROJECT=deployment
pgv13_release capture --bundle "$PGV13_BUNDLE" \
  --renderer-project "$PGV13_RENDERER_PROJECT"
source "$PGV13_BUNDLE/pins.env"
pgv13_release prepare-ipc --bundle "$PGV13_BUNDLE"
python3 scripts/pgv13sandbox/probe.py --with-chroot --pids-limit 512 \
  --image "$CISSTAT_UDS_RENDERER_IMAGE" \
  --expected-revision "$PGV13_SOURCE_REVISION" \
  --expected-tree "$PGV13_SOURCE_TREE" --out "$PGV13_BUNDLE/ab.json"
python3 -c 'import json,sys; assert json.load(open(sys.argv[1]))["conclusion"]=="CHROOT_RULE_CANDIDATE"' "$PGV13_BUNDLE/ab.json"

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
  up -d --wait --wait-timeout 120 --force-recreate --no-deps --no-build --pull never print-renderer
python3 scripts/pgv13uds/verify_vm.py --renderer-project "$PGV13_CANDIDATE_PROJECT" \
  --sandbox-report "$PGV13_BUNDLE/ab.json" --api-image "$PGV13_API_IMAGE" \
  --previous-report "$PGV13_BUNDLE/candidate-first.json" \
  --out "$PGV13_BUNDLE/candidate-recreated.json"
pgv13_release check --bundle "$PGV13_BUNDLE" \
  --ab-report "$PGV13_BUNDLE/ab.json" --native-report "$PGV13_BUNDLE/candidate-recreated.json"
```

Только после успешных предыдущих шагов и штатного drain:

```bash
pgv13_release apply --quiesced --bundle "$PGV13_BUNDLE" \
  --ab-report "$PGV13_BUNDLE/ab.json" --native-report "$PGV13_BUNDLE/candidate-recreated.json"
python3 scripts/pgv13uds/verify_vm.py --renderer-project "$PGV13_RENDERER_PROJECT" \
  --api-project cisstat-stack --sandbox-report "$PGV13_BUNDLE/ab.json" \
  --out "$PGV13_BUNDLE/live.json"
curl -fsS https://api.datasetup.ru/health
```

## Новая приёмка P01/P02

После всех release gates выше; зависимости host venv прежние. Production DB
не используется. PG image берётся только у ровно одного контейнера:

```bash
PGV13_PG_CONTAINER="$(docker ps -q \
  --filter label=com.docker.compose.project=cisstat-stack \
  --filter label=com.docker.compose.service=postgres)"
export PGV13_POSTGRES_IMAGE="$(docker inspect --format '{{.Image}}' "$PGV13_PG_CONTAINER")"
export PGV13_DOCUMENTS_OUT="/opt/cisstat/releases/pgv13-documents-ocr-$(date -u +%Y%m%dT%H%M%S%NZ)"
/opt/cisstat/venvs/pgv13accept/bin/python scripts/pgv13accept/verify_vm.py run \
  --bundle "$PGV13_BUNDLE" --renderer-project "$PGV13_CANDIDATE_PROJECT" \
  --postgres-image "$PGV13_POSTGRES_IMAGE" --out "$PGV13_DOCUMENTS_OUT"
```

Если есть FAIL, прислать detail/failed_cases, обе TSV и соответствующие PNG.
Не отмечать review flags без просмотра. При automated_passed:true нужны review
всех PNG и заполненный review.json по docs/pgv13_document_acceptance.md; затем:

```bash
/opt/cisstat/venvs/pgv13accept/bin/python scripts/pgv13accept/verify_vm.py finalize \
  --report "$PGV13_DOCUMENTS_OUT/report.json" --review "$PGV13_DOCUMENTS_OUT/review.json"
```

Даже accepted.json удостоверяет только этот scope P01/P02. Whole
`pgv13_certified:false` сохраняется: общий сертификат/реальный rollback не
заменяются OCR или данным исправлением.
