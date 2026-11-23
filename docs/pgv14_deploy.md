# PGV-14 — сборка и приёмка на VM

База разработки — `5be3e29b32d954f9abe009236c4546d876ec2b9b`. Изменились API,
compiled renderer и общий print bundle: требуется новый согласованный bundle
API/web/renderer. Новых миграций, host policy или Docker capabilities нет.
Старые images/baseline/volumes/evidence сохраняются. В сессии Docker отсутствует;
локальные DOM/HTTP doubles не подтверждают Chromium, UDS, OCR или final image.

После review ZIP и commit/push **тимлидом** выполните из чистого checkout на VM:

```bash
set -euo pipefail
git pull --ff-only
export PGV13_BUNDLE="/opt/cisstat/releases/pgv14-$(git rev-parse --short HEAD)-$(date -u +%Y%m%dT%H%M%SZ)"
pgv13_release() {
  env -u CISSTAT_AUTH_MFA_KEYS -u CISSTAT_AUTH_MFA_ACTIVE_KEY \
    python3 scripts/pgv13release/release.py "$@"
}
pgv13_release build --bundle "$PGV13_BUNDLE"
```

Затем **полностью** выполнить существующий порядок
`docs/pgv13_release.md`, начиная с «Сохранение действующего baseline»:

1. Определить production renderer project по Docker labels. Передать его в
   `capture --renderer-project "$PGV13_RENDERER_PROJECT"`. Здесь нет параметра
   `--prev-bundle`; прежние CLI errors из приложенного `1.txt` не evidence.
2. `source "$PGV13_BUNDLE/pins.env"`, `prepare-ipc`, новый sandbox A/B для pinned
   renderer image/revision/tree, dedicated candidate, native candidate-first,
   SIGKILL/recreate, candidate-recreated. Не пропускать nonzero/readiness failure.
3. `release check`, операционный drain, `apply --quiesced`, native live report.
   Старый UDS/seccomp/512 PID/RO/RW порядок не заменять base-only Compose up.
   Не менять hashes, не удалять volumes, не использовать no-sandbox.

После успешного нового live оставить dedicated candidate для 11-case нагрузки.
Нужны host Python3.12, Pillow и Tesseract **rus + eng**. Host scientific runtime
не нужен: продукт запускается в pinned API image. В venv достаточно
`pip install -r scripts/pgv13accept/requirements.txt`; файл
`scripts/pgv14/requirements.txt` предназначен для локальных contracts с API deps.
Выберите уже установленный PostgreSQL image по immutable ID (`docker image
inspect postgres:16 --format '{{.Id}}'`); не используйте production DSN.

```bash
export PGV14_POSTGRES_IMAGE="$(docker image inspect postgres:16 --format '{{.Id}}')"
export PGV14_OUT="$PGV13_BUNDLE/pgv14-pages"
/opt/cisstat/venvs/pgv13accept/bin/python scripts/pgv14/verify_vm.py run \
  --bundle "$PGV13_BUNDLE" --renderer-project "$PGV13_CANDIDATE_PROJECT" \
  --postgres-image "$PGV14_POSTGRES_IMAGE" --out "$PGV14_OUT"
```

`run` сохраняет все **11** исходных сценариев, включая figure/reused/missing/corrupt;
ожидает ready/download на их исходных профилях. Плотные случаи не заменяются 413
или другим профилем. Один PNG или ZIP определяется реальным количеством страниц
и режимом set. Каждый PNG проходит geometry/pHYs/CRC/hash/pixel/OCR; document OCR
проверяет всю семантику по объединению страниц. Заголовок, источник и folio
проверяются на каждой странице отдельно. Artifact payload, metadata, download,
каждый PNG и оба OCR TSV сохраняются с hashes. Native API проверяет AuthSession,
CSRF, AUTH13 jobs/idempotency, JSON/ZIP download, anonymous/foreign denial,
no-science/session и отсутствие оставшихся financial holds. Временные ресурсы
удаляются только по собственному label; production DB/renderer не используются.

Открыть `review.html` и каждую PNG в полном размере. Скопировать
`review.template.json` в `review.json`, заполнить reviewer/aware reviewed_at,
после реальной проверки выставить все 5 критериев **каждой страницы каждого
сценария**. Пропуск/изменение даже последней страницы блокирует finalize.

```bash
/opt/cisstat/venvs/pgv13accept/bin/python scripts/pgv14/verify_vm.py finalize \
  --report "$PGV14_OUT/report.json" --review "$PGV14_OUT/review.json"
```

До этого `p01_p02_accepted=false`; whole `pgv13_certified=false` сохраняется и
после этого узкого акта. Новый verifier требует version2 report/7 compiled hashes
и PGV14 tool hashes; старый single-PNG report не подходит. Исторический
`scripts/pgv13accept/verify_vm.py` по умолчанию остаётся legacy single-PNG:
для PGV14 запускать именно новый wrapper. Исторический typography sample helper
также не является page-set acceptance, хотя missing case/false-positive 413
исправлены. Нельзя объявить полную сертификацию по локальным green contracts.

Локально (зависимости установлены):

```bash
python scripts/local_gates.py --only pgv14 --skip-install
npm run build --workspace=@cisstat/print-renderer
npx jest packages/ui/print apps/print-renderer/src scripts/pgv07cert scripts/pgv08cert --runInBand
node --test scripts/pgv13typocert/oracle.spec.js scripts/pgv13typocert/contracts.spec.js
npm run typecheck:all
npm run build:all
# Только disposable PG с CREATE DATABASE, CISSTAT_PGV13_CERT_DSN в окружении:
python -m unittest scripts.pgv14.test_native -v
```

Перед строгим AUTH00 явно подготовить index только этой поставки:

```bash
git add --pathspec-from-file=scripts/pgv14/files.txt
python scripts/local_gates.py --only auth00 --skip-install
python scripts/auth06/check_routes.py
```

В агентской сессии используется отдельный временный INDEX; настоящий INDEX,
HEAD, main, GitHub и VM не изменяются. Commit/push выполняет тимлид.
