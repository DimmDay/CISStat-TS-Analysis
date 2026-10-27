# DOCLOG-PDF-FONT-DEPLOY-1 — акт поставки (2026-10-27)

**Задача (тимлид):** «Синхронизируйся до 9390ab5. Проверяем "Документы" дальше. Исправление скачивания реализовано, но кроме формата pdf. Сценарий — собрать формат: нажимаем PDF, worker задумывается, ставит в очередь, потом выдает ошибку: "Задание djob-0b70499…: Ошибка (failed) (попытка 2)". Воспроизведи ошибку, найди причины и устрани.»

**База:** 9390ab5 (DOCLOG-DL-FIX-1), git fetch + pull --ff-only, рабочее дерево чистое до начала работ. No commit/push (AGENTS.md).

---

## 1. Разбор сценария

Формат pdf — тяжёлый (HEAVY_RENDITION_FORMATS, §7 P1): POST
`/v1/documentation/revisions/{id}/renditions` → **202 queued** → фоновый
`DocumentRenderWorker` (apps/api/document_render_worker.py) захватывает
задание (lease), читает frozen-снимок и вызывает чистый рендер
`render_snapshot_pdf` (apps/api/document_renditions.py). Рендер PDF
требует TTF-шрифт из **allowlist** `_PDF_FONT_CANDIDATES`
(AC16: чтение ФС рендером ограничено фиксированным списком; §7:
кириллица требует встроенного шрифта):

- `/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf` (+ Bold)
- `/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf` (+ Bold)

Отсутствие шрифта — честный `RenderDependencyError("font_unavailable: …")`
→ worker классифицирует `render_dependency_unavailable` как
**детерминированную** ошибку → **терминальный failed сразу** (§18:
очередь не крутится впустую, attempt не растёт). Это уже покрыто тестами
doclog5 (`test_dependency_unavailable_is_terminal`,
`test_pdf_font_unavailable_is_honest_error`).

## 2. Root cause (воспроизведён)

**Деплой-образ собирается из `python:3.12-slim` (apps/api/Dockerfile,
render.yaml: `runtime: docker`, `dockerfilePath: ./apps/api/Dockerfile`),
а slim-образы Debian НЕ содержат системных шрифтов** — пакеты
fonts-dejavu*/fonts-liberation в образ не устанавливались ни одним слоем
Dockerfile. Следствия:

- P0-форматы (md/html/json/csv/jsonl — чистый Python) работают;
- бинарные без шрифтов (xlsx — openpyxl, zip — zipfile, parquet — pyarrow)
  работают;
- **PDF и PNG** (единственные, требующие allowlist-шрифт) — терминальный
  failed `render_dependency_unavailable` при живых остальных форматах —
  в точности наблюдаемое «сломан только pdf».

**Про «(попытка 2)»:** неудачная попытка НЕ ретраится (детерминированная
ошибка), attempt job'а фиксирован при постановке как
`len(prior_jobs)+1`. Повторный клик «Собрать формат: PDF» после первой
неудачи создаёт **новый** job той же цели с attempt=2 — снова терминальный
failed. Протокол воспроизведения: клик №1 → failed (попытка 1), клик №2 →
**failed (попытка 2)**, клик №3 → failed (попытка 3) — точный эквивалент
наблюдения тимлида.

## 3. Динамическое воспроизведение

`scripts/doclog_pdf_repro/reproduce_pdf_failure.py` (TestClient +
Memory-бекенды, паттерн корпуса DOCLOG-4/5; namespace RUN-DPF*/dpf-;
worker управляется вручную `run_once()`; протокол
`protocols/repro_result.json`):

- **S1 baseline (шрифты в ФС есть — локальная/dev-среда и починенный
  образ):** POST pdf → 202 queued → worker → **ready**, rendition ready,
  26 930 байт, `head=%PDF-1.4`, Content-Disposition
  `attachment; filename="document-….pdf"` (фикс 9390ab5 на месте) —
  код рендера и конвейер корректны.
- **S2 симуляция деплой-образа (allowlist-шрифты удалены из ФС):**
  клик №1 → terminal failed, attempt=1, error_code=
  `render_dependency_unavailable`; клик №2 → **failed (попытка 2)**;
  клик №3 → failed (попытка 3).

Вывод: код PDF-рендера исправен; причина — зависимость среды деплоя.

## 4. Исправление (TDD RED→GREEN)

Философия DEPLOY-1 (инцидент 2026-09-25): зависимость среды обязана
падать НА СБОРКЕ образа, а не в runtime у аналитика.

**RED** (`tests/api/test_doclog_pdf_font_deploy.py`, новый): 3 failed /
1 passed —

1. `test_dockerfile_installs_dejavu_fonts` — в образ установлен
   `fonts-dejavu-core` (пакет предоставляет ровно первичного кандидата
   allowlist);
2. `test_dockerfile_build_time_font_guard` — сборка образа проверяет
   шрифт временем сборки (`python -c … _resolve_font`, fail-closed:
   без шрифта образ не собирается);
3. `test_dockerfile_references_doclog_pdf_font_deploy_task` — слой
   снабжён маркером задачи (регламент комментария зависимостей файла,
   паттерн UPLOAD-DB-7/DEPLOY-1);
4. `test_font_allowlist_primary_matches_dejavu_package` — пин
   сопряжения код↔образ (passed сразу: фиксирует allowlist).

**Код:** apps/api/Dockerfile —

- в системный apt-слой добавлен `fonts-dejavu-core` (--no-install-recommends,
  стиль файла) с комментарием DOCLOG-PDF-FONT-DEPLOY-1;
- перед `ENV PYTHONUNBUFFERED` добавлен build-time guard:
  `RUN python -c "from apps.api.document_renditions import _resolve_font; …"`
  — `_resolve_font()` читает только ФС (os.path.isfile) и не требует
  reportlab (reportlab импортируется лениво внутри рендера), проверка
  легка и надежна; семантика многострочного `python -c` в double quotes
  верифицирована под `sh -c` (dash).

**GREEN:** сюит 4/4 passed; регресс `tests/api/test_docker_image_layout.py`
(DEPLOY-1) 4/4 passed — структура Dockerfile не нарушена; полный
doclog-корпус `pytest tests/api -k "doclog or documentation"` → **608
passed / 1 skipped** (604 предыдущих + 4 новых, ноль регрессий). Runtime
Python-код не менялся (дифф = Dockerfile + новый тест + скрипты репро),
поэтому полный tests/api не прогонялся — граница зафиксирована ниже.

## 5. Эффект исправления

После пересборки образа на Render (следующий деплой):

- «Собрать формат: PDF» проходит путь queued → rendering → **ready**;
  скачивание отдаёт валидный PDF с `attachment` (9390ab5);
- PNG-рендер (тот же allowlist-шрифт) чинится тем же слоем;
- если шрифт по какой-то причине снова исчезнет из образа — сборка
  упадёт на guard-слое с явным сообщением, а не молча выдаст
  «Ошибка (failed)» аналитику;
- существующие failed-задания остаются честными failed-записями (§10.3);
  повторный клик после пересборки создаст новую попытку (limit
  MAX_JOB_ATTEMPTS=5 на цель).

Рекомендации вне скоупа (не реализованы): (a) карта человекочитаемых
подсказок для error_code в панели «Ошибка сборки формата» (сейчас сырой
код `render_dependency_unavailable` — diagnose-информация есть, но не
переведена для аналитика); (b) опционально — бандлинг TTF в репозиторий
как fallback, если образы будут меняться (лицензии DejaVu допускают
редистрибуцию).

## 6. Границы

Docker-сборка образа в песочнице не выполнялась (docker недоступен):
корректность Dockerfile подтверждена парсинг-тестами
(test_docker_image_layout + новый сюит) и исполнением guard-команды под
`sh -c` с локальным allowlist-шрифтом. Живой деплой Render не прогонялся.
Memory-бекенды/TestClient; UI не менялся. Full-suite регресс не
запускался (дифф не затрагивает runtime-код Python — граница сознательная,
докlog-корпус + docker-layout зелёные).

## 7. Поставка

ZIP `cisstat-doclog-pdf-font-deploy-1.zip` → открытый контейнер сессии
(download/) + веб-страница поставки :3000 с кнопкой скачивания.
Файлы: apps/api/Dockerfile; tests/api/test_doclog_pdf_font_deploy.py
(нов); scripts/doclog_pdf_repro/{reproduce_pdf_failure.py,
protocols/repro_result.json} (нов); docs/doclog_pdf_font_deploy_2026-10-27.md
(нов, этот акт); worklog/worklog11.md (запись). Без commit/push (AGENTS.md).
