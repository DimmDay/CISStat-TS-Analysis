# Команды VM — PGV13/PGV14, база77cbd70

Разработка сертификатора и локальная проверка завершены. Итоговый сертификат
задач ещё не выдан: требуются native11-case прогон и визуальный review КАЖДОЙ
PNG. Во вложенном ранее выводе подтверждён только capture baseline.

## 1. Применить код

В полном пакете находятся два отдельных ZIP. Распакуйте исходный
`cisstat-pgv13-pgv14-finalcert-77cbd70.zip` в корень checkout. Просмотрите
изменения и выполните локальные gates. Commit/push выполняет тимлид.

```bash
git add --pathspec-from-file=scripts/pgv1314cert/files.txt
python scripts/local_gates.py --only pgv1314cert,pgv14,auth00 --skip-install
```

После commit/push и CI на VM из корня репозитория:

```bash
set -euo pipefail
git pull --ff-only
# Вписать ТОЧНЫЙ путь уже captured PGV14 bundle; не использовать ls/latest.
export B='/opt/cisstat/releases/ТОЧНЫЙ_CAPTURED_PGV14_BUNDLE'
export PYC='/opt/cisstat/venvs/pgv13accept/bin/python'
# Если этого venv ещё нет, создать один раз:
if [ ! -x "$PYC" ]; then python3 -m venv /opt/cisstat/venvs/pgv13accept; fi
"$PYC" -m pip install -r scripts/pgv13accept/requirements.txt
```

PYC с Pillow нужен уже для `plan`; scientific runtime на host для plan/run/issue
не нужен. Tesseract с rus+eng и Docker/Git должны быть установлены. Точный B
не был напечатан в присланном логе; его нужно взять из вашей VM-сессии.

## 2. Завершить уже captured релиз

```bash
"$PYC" scripts/pgv1314cert/verify.py plan --bundle "$B" > "$B/resume-pgv1314.sh"
# Просмотреть ВЕСЬ файл до исполнения:
cat "$B/resume-pgv1314.sh"
source "$B/resume-pgv1314.sh"
```

План выполняет A/B/candidate/recreate/preflight. Он не пересобирает образы,
не повторяет capture и не вызывает live apply автоматически. Прежний guard
exact image-source HEAD сохраняется; после apply/live tool commit возвращается.
Если runtime отличается от manifest revision, план откажет: новый coherent
build/capture выполняется по docs/pgv13_release.md в НОВОМ bundle. Для самих
host-изменений этой поставки новые images не нужны.

Только после штатного operator drain, без active/uncertain jobs:

```bash
pgv1314_apply_after_drain
```

Не удалять baseline/старые images/DB/IPC/science volumes и не обнулять holds.
Если native evidence уже существует, plan откажет вместо перезаписи. Продолжайте
со своего подтверждённого этапа по runbook, сохраняя старые результаты.

## 3. Перенести local evidence и запустить native

Загрузите `pgv1314-local-evidence-77cbd70.zip` на VM вне checkout. Впишите его
путь ниже. Новый целевой каталог не должен существовать:

```bash
export LOCAL_ZIP='/ПУТЬ/НА/VM/pgv1314-local-evidence-77cbd70.zip'
test ! -e "$B/pgv1314-local"
"$PYC" -m zipfile -e "$LOCAL_ZIP" "$B/pgv1314-local"
export PG_IMAGE="$(docker image inspect postgres:16 --format '{{.Id}}')"
"$PYC" scripts/pgv1314cert/verify.py run --bundle "$B" \
  --local "$B/pgv1314-local/summary.json" --postgres-image "$PG_IMAGE" \
  --out "$B/pgv1314-native"
```

Все hashes/fingerprints и153+357 точных тестов перепроверяются. При изменённом
коде нужен свежий совпадающий CI/local artifact. Сам local artifact НЕ native
сертификат. Native run проверяет все11 случаев/каждую страницу и реальные
page-cap/oversized-atom отказы на pinned API/renderer images в isolated контуре.
Production DB для нагрузки не используется.

## 4. Проверить каждую PNG и выдать сертификат

Открыть `$B/pgv1314-native/review.html`, затем КАЖДУЮ PNG в полном размере.
Скопировать template в review.json, заполнить reviewer/aware reviewed_at и
5 критериев каждой страницы только после реального просмотра. При дефекте
оставить false/finding; не менять hashes/PNG ради GREEN.

```bash
cp -n "$B/pgv1314-native/review.template.json" "$B/pgv1314-native/review.json"
# Здесь выполнить реальный review и заполнить review.json.
# После этого:
"$PYC" scripts/pgv1314cert/verify.py issue --bundle "$B" \
  --local "$B/pgv1314-local/summary.json" --report "$B/pgv1314-native/report.json" \
  --review "$B/pgv1314-native/review.json" --out "$B/pgv1314-native/certificate.json"
"$PYC" -c 'import json,sys; r=json.load(open(sys.argv[1],encoding="utf-8")); print(r["state"],r["task_certification"],"pages=",r["page_count"])' "$B/pgv1314-native/certificate.json"
```

Только последняя успешная выдача даёт CERTIFIED PGV-13/PGV-14. Общий PGV-CERT,
PGV15/16 не заявляются. Certificate immutable; существующий не перезаписывается.
Старые raw reports/pgv13_certified:false относятся к отдельным стадиям, их
нельзя вручную исправлять на true.
