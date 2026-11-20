# PGV-13 — P01/P02 content, jobs/download, pixel/OCR и visual review

Этап 5, база `dd6ce317083733eec15a33b464ea9bb8f50be93f`, 20.11.2026.
Первоначальная release image revision — `3b13214466a31fb9ceeebe583abd64812e3bd042`.
Предыдущий live UDS PASS сохранён в `worklog/pgv13_release_vm_2026-11-20.md`.

**PGV-13-IMAGE-ASSETS:** эта API revision не содержала config print twins.
Нужен новый согласованный bundle по `docs/pgv13_api_image_assets.md`. Ниже
используется уже установленный путь нового bundle, не исторический3b13214.

## Архитектура и границы

Новый explicit host CLI `scripts/pgv13accept/verify_vm.py` использует существующий
release bundle, новый A/B, успешные candidate-recreated/live reports и именно
выделенный release candidate. Production renderer для этой нагрузки отвергается.
Создаётся отдельная internal Docker network, PostgreSQL в tmpfs и временный
API-client на immutable API image из release manifest. PostgreSQL image —
явный уже имеющийся `sha256:`; pull/build не выполняются. Портов на host нет.

API-client имеет read-only root и IPC mount RO+nocopy/GID10001, finite2GiB/256PID,
tmpfs /tmp, cap_drop ALL и NNP. Renderer сохраняет прежние network:none,
seccomp/AppArmor/UID10001/512PID/2GiB; native hardening/cgroup checks повторяются.
Исходный renderer не пересоздаётся раннером, DB/API/client resources временные.
Их удаление требует собственного случайного label; `rm -v` касается только
собственных контейнеров и их anonymous volumes. Named IPC volumes сохраняются.
Ошибки cleanup блокируют приёмку, неизвестные ресурсы не удаляются.

В API image через stdin передаётся только новый проверяемый client harness.
Production DSN, .env, MFA/SMTP/worker keys и science/proof volumes не передаются.
Случайные пароль PostgreSQL и test worker key живут только в тестовом контуре.
База `pgv13accept_<32 hex>` должна быть новой и пустой до explicit migrations.
Остальные имена или уже существующие таблицы отвергаются до изменений.
Миграции и записи accounts/budgets/worker ledger выполняются только там.

Harness использует **настоящее `apps.api.main.app`**, его routes/middleware,
настоящие PostgreSQL registries, AuthSession/CSRF, AUTH-13 managed worker
и штатный PngRendererClient. Lifespan/background daemons не запускаются:
тот же worker обслуживается явно через `run_once`. AuthSession создаётся
через настоящий SessionService; публичные login/MFA/email/BFF/browser flows
не входят в этот акт. SubjectRef используется только при trusted seed fixture,
не как подмена request identity. HTTP identity/authority/payload не подменяются.

Нет DataFrame/capture науки: fixture — собственные уже сохранённые факты,
analysis SessionStore запрещён, таблица analysis_sessions остаётся пустой.
Все render workers должны стать completed, held reservations — 0.
Это HTTP через ASGI TestClient в production API image, не запросы к публичному
datasetup.ru и не запись тестовых исследований в production БД.

## Фиксированный корпус

| Сценарии | Число PNG | Проверяемые факты |
| --- | --- | --- |
| P01 single | 3 | figure-landscape, A4 landscape/portrait; все 11 групп fixture: 9 известных и 2 неизвестные; кириллица |
| P01 reused set | 1 | три физических refs, подтверждение checkpoint, без четвёртой копии |
| P02 explicit comparison | 3 | три профиля; mean0→7, delta7/delta_pct100 и явное определение нулевого базиса, category/list/qualitative |
| P02 reused checkpoint | 1 | выбранные исторические refs и отдельное подтверждение |
| P01 missing/corrupt | 2 | partial, явный gap/reason, отсутствие выдуманного passport content |
| P02 missing | 1 | partial с перечисленным гэпом, без подмены нулём |
| **Всего** | **11** | фиксированные IDs/профили, нет skips/xfail или урезания набора |

Дополнительно сохраняется более новый невыбранный passport source. Его sentinel
не должен попасть в исторические документы. Чужой create/job/download и missing
объект имеют одинаковый публичный отказ404 (игнорируется только случайный
request_id, code/message/остальные поля сравниваются). Missing single и
panel/single comparison дают штатные409, отсутствие CSRF —403.

Каждый PNG проходит: POST202 → queued GET → реальный managed worker через UDS →
ready GET → авторизованный download → content SHA/size metadata → повторный
download и ready/queued idempotency. Проверяются attachment/image/png/nosniff/
private,no-store, anonymous/foreign denials и durable audit-тройка
download_requested/response_stream_started/response_stream_finished.

## Pixel/OCR и визуальная приёмка

PGV-13-OCR-FIX: текущий порядок и новая обязательная сборка —
`docs/pgv13_ocr_fix.md`. Новый OCR использует неперекрывающиеся pixel bands,
ограниченное увеличение и отдельный eng pass для ASCII labels; порог20 и
обязательные фразы/числа/counts сохранены. Старые отчёты не финализировать.

OCR читает **скачанные PNG pixels**, не HTML/DOM/SSR text. Проверяются подпись,
CRC, profile dimensions, pHYs300ppi, непрозрачность/ink coverage. Tesseract
обязан иметь rus+eng; язык/fallback/нулевой набор не пропускаются. В отчёте
фиксируются версия OCR и SHA256 обоих traineddata, boxes/confidence/ожидаемые
группы и числа. Missing text/низкая confidence/выход boxes за image bounds
дают FAIL. Фикстуры не укорачиваются ради прохождения profile: clipping/потеря
групп должны оставаться finding, особенно для более плотных P01/P02 страниц.
Универсальная pagination/page-set остаётся отдельной задачей PGV-14.

Автоматический green не означает доказанной визуальной корректности.
`review.html`, полные PNG, raw payload JSON и OCR TSV сохраняются для просмотра.
Нужен отдельный операторский review всех11 картинок: читаемость, кириллица,
отсутствие overlap/clipping, правильность значений и reasons. Template имеет
все flags=false. Review привязан к SHA всего report и hashes PNG/payload/OCR;
изменённые evidence, пропуски/дубли сценариев или хотя бы один false запрещены.

Успешный run: `automated_passed:true`, `p01_p02_accepted:false`, review PENDING.
После настоящего review `finalize` пишет immutable `accepted.json` с
`p01_p02_accepted:true`. **`pgv13_certified:false` остаётся в обоих режимах**:
этот scope не заменяет общий акт PGV-13, публичный UI/BFF/login или VM rollback.

## VM: установка и актуальная ревизия образов

После ZIP → локальный review/gates → commit/push тимлида → VM pull:

```bash
git pull --ff-only
: "${PGV13_BUNDLE:?Set the new bundle path from docs/pgv13_api_image_assets.md}"
source "$PGV13_BUNDLE/pins.env"

# Отдельный host Python, вне checkout. Системный Python/API image не меняются.
python3 -m venv /opt/cisstat/venvs/pgv13accept
/opt/cisstat/venvs/pgv13accept/bin/python -m pip install -r scripts/pgv13accept/requirements.txt
sudo apt-get update
sudo apt-get install -y tesseract-ocr tesseract-ocr-rus tesseract-ocr-eng
tesseract --list-langs

# Только отдельный candidate, подготовленный этапом4.
docker compose -p "$PGV13_CANDIDATE_PROJECT" \
  -f apps/print-renderer/build/deployment/docker-compose.yml \
  -f "$PGV13_BUNDLE/candidate.json" \
  up -d --wait --wait-timeout 120 --no-deps --no-build --pull never print-renderer

# Читаем только immutable image ID уже работающего PostgreSQL.
PGV13_PG_CONTAINER="$(docker ps -q \
  --filter label=com.docker.compose.project=cisstat-stack \
  --filter label=com.docker.compose.service=postgres)"
export PGV13_POSTGRES_IMAGE="$(docker inspect --format '{{.Image}}' "$PGV13_PG_CONTAINER")"
export PGV13_DOCUMENTS_OUT="/opt/cisstat/releases/pgv13-documents-$(date -u +%Y%m%dT%H%M%S%NZ)"
/opt/cisstat/venvs/pgv13accept/bin/python scripts/pgv13accept/verify_vm.py run \
  --bundle "$PGV13_BUNDLE" \
  --renderer-project "$PGV13_CANDIDATE_PROJECT" \
  --postgres-image "$PGV13_POSTGRES_IMAGE" \
  --out "$PGV13_DOCUMENTS_OUT"
```

Нужен ровно один PG container в выбранном stack project; если selection пустой
или неоднозначный, сначала уточнить project/service, не подставлять mutable tag.
Раннер сверяет image markers с bundle и runtime sources с image revision Git;
новый docs/cert commit разрешён только при прежних product bytes. API source
hashes сверяются также внутри image, compiled renderer hashes фиксируются.
Если runtime изменён — остановиться и выполнить новую согласованную сборку/A-B,
не переписывать manifest или старые JSON для обхода проверки.

В run видны phases, native heartbeat каждые10с и имя каждого OCR case.
При FAIL исходные PNG/отчёт сохраняются; новый run — только в новый out.
Не повторять builder с дополнением payload и не превращать gaps в пустой PASS.
Для разбора передать `report.json`, соответствующие PNG/payload/TSV; report
не содержит DSN/паролей/.env, но каталог700 следует сохранять закрытым.

## Просмотр и finalize

Скопировать evidence directory на свою машину по штатному SSH/SCP. Открыть
`review.html`, каждую PNG в полном размере и при необходимости `.payload.json`.
После проверки скопировать `review.template.json` в `review.json`, заполнить
`reviewer`, aware ISO timestamp `reviewed_at`, затем отмечать только проверенные
flags каждого из11 cases. При дефекте сохранить false и finding, не finalize.

```bash
/opt/cisstat/venvs/pgv13accept/bin/python scripts/pgv13accept/verify_vm.py finalize \
  --report "$PGV13_DOCUMENTS_OUT/report.json" \
  --review "$PGV13_DOCUMENTS_OUT/review.json"
```

Результат `accepted.json` отдельно от неизменяемого automated report. Lifecycle
state release operation.json не редактируется ради нового статуса приёмки.
Production services/DB/ключи/holds и release baseline остаются прежними.

## Локальные controls и честность результатов

```bash
python -m pip install -r scripts/pgv13accept/requirements.txt
python -m unittest discover -s tests/unit -p test_pgv13_accept.py -v
python -m unittest scripts.pgv13accept.test_ocr -v
# Только disposable native PostgreSQL, переменная уже задана безопасно:
python -m unittest scripts.pgv13accept.test_native -v
python scripts/auth06/check_routes.py
```

Native test требует `CISSTAT_PGV13_CERT_DSN` на disposable сервер с CREATE/DROP
DATABASE: создаётся/удаляется собственная база. Он использует настоящий ASGI/
AuthSession/CSRF/managed worker, но PNG TCP transport double; это **не** Chromium,
UDS или product OCR acceptance. Unix sockets в локальном executor запрещены,
поэтому double слушает только loopback TCP. Real OCR controls используют отдельно
созданные известные кириллические pixels и Tesseract, не выдаются за P01/P02 PNG.
Нет Docker daemon в executor; реальный `run` остаётся PENDING VM.

AUTH-00: новых HTTP/worker routes нет. Добавлена manual operator boundary
`internal_operation:pgv13.document_acceptance`, отдельная policy/test sources
reviewed. Default local_gates.py не расширяется; explicit команды документированы.

Сам run требует чистый committed tool checkout и AUTH-00 HEAD-parity. Hashes
четырёх tool inputs записываются и повторно проверяются при finalize. Для reused
P01 OCR требует три видимых кириллических tail markers: одна сохранившаяся
первая карточка не выдаётся за полный комплект. После завершения требуется
0 analysis_session rows,11 completed workers и0 held reservations в test DB.

Run выполняет `api_print_assets` preflight до temporary PostgreSQL: оба JSON
должны быть в самом API image, проходить catalog validation и совпадать по hash
с reviewed Git inputs. Finalize требует этот результат. В финальной CLI сводке
теперь сразу есть client_failure, а uniform404 diagnostic содержит HTTP status.
