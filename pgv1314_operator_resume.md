# PGV13/PGV14 — передача оператору VM, 24.11.2026

В предоставленном выводе capture успешен. Сохраните этот bundle и baseline.
Точный абсолютный путь нового PGV14 bundle в attachment не напечатан; задайте
его явно в B, без `ls ... | head -1`. Проекты/новые pins читаются из его
manifest/baseline. Старые IDs в выводе — только rollback baseline, не новые pins.

После review ZIP → commit/push тимлида → чистого `git pull --ff-only`:

```bash
set -euo pipefail
export B='/opt/cisstat/releases/ТОЧНЫЙ_CAPTURED_PGV14_BUNDLE'
python3 scripts/pgv1314cert/verify.py plan --bundle "$B" > "$B/resume-pgv1314.sh"
# Сначала просмотреть файл полностью. Затем:
source "$B/resume-pgv1314.sh"
# Только после operator drain, без active/uncertain jobs:
pgv1314_apply_after_drain
```

`source` выполняет candidate/A-B/recreate/preflight, определяет функцию apply,
но не вызывает её. Прежний release guard exact image-source HEAD сохранён;
после apply/live функция возвращает исходный tool commit. План не выполняет
build/capture повторно и не меняет старые evidence. Если runtime отличается от
manifest revision, он откажет: нужен новый согласованный bundle по прежнему
release runbook. Только host изменения данной поставки rebuild не требуют.

## Локальные доказательства

Рекомендован поставленный `pgv1314-local-evidence-77cbd70.zip` либо artifact
Linux CI `pgv1314-local-contracts-NOT-NATIVE-CERTIFICATE` из ТОЙ ЖЕ поставки.
Распаковать весь artifact вне checkout в `$B/pgv1314-local` (summary.json
должен лежать прямо в этом каталоге). CLI повторно проверит каждый hash,
точный состав тестов и все fingerprints; иной source version не подходит.
Jest paths переносимы. Это успешно выполненные local probes, не native image
acceptance, не самостоятельный сертификат.

Для run/issue достаточно host-окружения существующего PGV13 accept tool:
Python3.12, Pillow, Git/Docker и Tesseract с rus+eng. Например:

```bash
export PYC='/opt/cisstat/venvs/pgv13accept/bin/python'
"$PYC" -m pip install -r scripts/pgv13accept/requirements.txt
# Tesseract должен уже иметь rus и eng, без fallback.
export PG_IMAGE="$(docker image inspect postgres:16 --format '{{.Id}}')"
"$PYC" scripts/pgv1314cert/verify.py run --bundle "$B" \
  --local "$B/pgv1314-local/summary.json" --postgres-image "$PG_IMAGE" \
  --out "$B/pgv1314-native"
```

Чтобы самостоятельно пересоздать local artifact, требуется отдельный host
venv с **обоими** `apps/api/requirements.txt` и
`scripts/pgv1314cert/requirements.txt`, системные зависимости полного API,
Node/npm и `npm ci`. Не заменяйте этим тонкий host venv, если используете уже
готовое совпадающее evidence. Создавайте новый каталог результата:

```bash
# В полноценном dev/CI runtime:
python -m pip install -r apps/api/requirements.txt -r scripts/pgv1314cert/requirements.txt
npm ci --include=dev --workspaces --include-workspace-root --ignore-scripts --no-audit --no-fund
python scripts/pgv1314cert/verify.py local --out "$B/pgv1314-local-new"
```

## PNG/review/сертификат

После successful run открыть review.html и КАЖДУЮ PNG всех11 случаев в полном
размере. Скопировать review.template.json в review.json, заполнить reviewer,
aware reviewed_at и5 flags каждой страницы только после реального просмотра.
При дефекте сохранить false/finding и новый отчёт; hashes/PNG не редактировать.

```bash
"$PYC" scripts/pgv1314cert/verify.py issue --bundle "$B" \
  --local "$B/pgv1314-local/summary.json" --report "$B/pgv1314-native/report.json" \
  --review "$B/pgv1314-native/review.json" --out "$B/pgv1314-native/certificate.json"
"$PYC" -c 'import json,sys; r=json.load(open(sys.argv[1],encoding="utf-8")); print(r["state"],r["task_certification"],"pages=",r["page_count"])' "$B/pgv1314-native/certificate.json"
```

Только здесь ожидается CERTIFIED PGV-13/PGV-14. Общий PGV-CERT/PGV15/16 не
заявляется. Перед issue live images проверяются заново read-only. Старые
частные reports/pgv13_certified:false, source hashes и baseline не переписывать.
Нет новой SQL migration, отключения sandbox, сброса данных/keys/holds или
`down -v`. До получения реального native/review certificate обе задачи
не объявлены окончательно сертифицированными.
