# DOCLOG-PDF-RENDER-DEPLOY-2 — акт поставки (2026-10-27)

**Задача (тимлид):** «Синхронизируйся до fe790c5. Полностью воспроизведи сценарий прохождения этапа "Загрузка" и выгрузи "План исследования" в PDF. У меня не работает — Ошибка сборки формата pdf: render_dependency_unavailable. Проверь e2e тестом и оракулами. По завершении выложи ZIP в открытый контейнер сессии (download/), продублируй через веб-приложение сессии (превью :3000) с кнопкой скачивания.»

**База:** fe790c5 (DOCLOG-PDF-FONT-DEPLOY-1 — фикс шрифтов уже в дереве); git fetch + checkout, дерево чистое до начала работ. No commit/push (AGENTS.md).

---

## 1. Разбор наблюдения

Формат `pdf` — тяжёлый: POST `/v1/documentation/revisions/{id}/renditions` → **202 queued** → `DocumentRenderWorker` → `render_snapshot_pdf`. Классификация (worker `_error_code`): `RenderDependencyError` → `render_dependency_unavailable` (детерминированная, терминальная); всё прочее → `render_failed` (TRANSIENT_ERROR_CODES — перезапускаемый). В **PDF-пути единственный источник** `RenderDependencyError` — `_resolve_font()` (`font_unavailable`); остальные raise-точки относятся к другим форматам: parquet-движок, PNG PIL (после фикса этого акта — честная граница), PDF/A ImageCms/pypdf.

## 2. Диагноз

**A. Наблюдаемое у тимлида.** E2E полного сценария на дереве fe790c5 — **ЗЕЛЁНЫЙ** (ниже, S1/e2e-тест). Следовательно `render_dependency_unavailable` на `format=pdf` воспроизводится **только в среде без allowlist-шрифта**: работающий контейнер Render собран **ДО** DOCLOG-PDF-FONT-DEPLOY-1 (stale-образ) — либо редеплой не выполнился, либо сборка образа упала незаметно и старый контейнер продолжает жить (free-тир). Код/конвейер корректны; лечится пересборкой/редеплоем, а правки этого акта делают состояние среды **видимым операционно**.

**B. Аудит класса отказа (латентные разрывы того же класса, сработали бы следующими):**

| Формат | Зависимость | Была объявлена в requirements.txt | Режим отказа в slim-образе |
|---|---|---|---|
| pdf | TTF allowlist (DejaVu) | n/a (система) | `render_dependency_unavailable` — закрыто DEPLOY-1 |
| pdf | reportlab | да | ImportError → `render_failed` |
| png | **Pillow (PIL)** | **НЕТ** | ImportError → `render_failed` (с пустыми ретраями: render_failed — TRANSIENT) |
| pdfa | **Pillow/ImageCms (littlecms)** | **НЕТ** | `icc_unavailable` → `render_dependency_unavailable` |
| pdfa | **pypdf** | **НЕТ** | ImportError → `render_failed` |
| parquet | pyarrow | да (эталон F14) | честный `RenderDependencyError` |

Урок F14 («не полагаться на недоказанную установку») распространён на все зависимости тяжёлых рендеров.

## 3. Воспроизведение (динамика + оракулы)

`scripts/doclog_pdf_render_env/reproduce_render_env.py` → `protocols/repro_result.json` (TestClient + Memory, namespace RUN-RENV*, worker вручную):

- **S0** `/health/ops render_dependencies` — среда полная: pdf_font (DejaVuSans) + reportlab + pillow + pypdf + pyarrow, все ok.
- **S1** полный этап «Загрузка» штатными эндпоинтами (POST `/v1/internal/upload` CSV → target/date → паспорт start → validate) → `run_id` → документ **D01 «План исследования»** (3 claims: целевая переменная, структура, честное отсутствие формы плана) → POST pdf **202 queued** → worker → **ready**, байты **%PDF-**, 27329 B, `attachment; filename="document-drend-….pdf"`. **Вердикт: конвейер зелёный.**
- **S2** модель stale-образа (allowlist-шрифты отсутствуют): клик №1 → failed attempt=1, клик №2 → failed attempt=2, `error_code=render_dependency_unavailable` в обоих — **точный эквивалент наблюдения тимлида** («(попытка 2)» = второй клик = новый job, ретраев внутри job нет).
- **S3** `/health/ops` в модели stale-образа: `render_dependencies.pdf_font.ok=false` — отказ виден **операционно, до первого клика аналитика**, без shell-доступа (у Render-контейнера его нет).

## 4. Изменения (точки)

1. **apps/api/requirements.txt** — объявлены `Pillow>=10.0.0` (render_snapshot_png, _srgb_icc_bytes/ImageCms) и `pypdf>=4.0.0` (_pdfa_postprocess) с блоком-маркером DOCLOG-PDF-RENDER-DEPLOY-2 (урок F14).
2. **apps/api/document_renditions.py** — (а) `render_dependencies_status()`: facts-only статус зависимостей тяжёлых рендеров (peek-семантика: ФС allowlist + ленивые импорты, фабрики не инициализирует); (б) честная граница PNG: отсутствие Pillow → `RenderDependencyError("pil_unavailable…")` вместо raw ImportError; (в) честная граница PDF/A: отсутствие pypdf → `RenderDependencyError("pypdf_unavailable…")` (паритет parquet-эталону §7).
3. **apps/api/main.py** — `/health/ops` несёт блок `render_dependencies` (контракт «диагностика не роняет health», peek-семантика).
4. **apps/api/Dockerfile** — (а) pip-проверка `import PIL, pypdf` в цепочке верификации (стиль redis/psycopg/db-track); (б) **executable-guard PDF**: RUN `python -c` исполняет настоящий `render_snapshot_pdf(ReportSnapshot(...))` и проверяет `%PDF-` — без рабочего PDF-рендера образ НЕ собирается (fail-closed, DEPLOY-1; font-guard проверял только наличие файла шрифта).

UI/продуктовые рендеры не менялись (только честная классификация отказа).

## 5. TDD

- **RED** (15 failed / 2 passed): requirements-декларации (3+1), Dockerfile guard'ы (2+1), `render_dependencies_status` контракт (2), `/health/ops` (3), классификация png/pypdf (2), e2e-health (1). Зелёными из старта: e2e полного сценария (доказательство корректности конвейера) и пин parquet-эталона.
- **GREEN** (17/17): `tests/api/test_doclog_pdf_render_env_deploy.py` (11) + `tests/api/test_doclog_pdf_render_env_classification.py` (3) + `tests/api/test_doclog_pdf_full_upload_e2e.py` (2: полный сценарий + health-видимость).

## 6. Регресс

- doclog/documentation/docker/upload-срез: **764 passed / 1 skipped**, 2 отказа — предсуществующие: `test_load_duckdb_csv_direct_select` (sqlalchemy.dialects:duckdb — воспроизводится на чистой fe790c5 stash-методом), `test_xlsx_five_sheets_and_determinism` (порядковый флейк: зелёный изолированно и файлом).
- `test_doclog_pdf_font_deploy.py` 4/4, `test_docker_image_layout.py` 4/4, doclog5-файл, h29/doclog0/2 — зелёные; `test_progress_audit_6c.py` 2 отказа **побайтово совпадают с чистой базой** (psycopg-специфика песочницы). **Ноль регрессий от диффа.**
- Guard-команды Dockerfile исполнены локально под `sh -c` (font-guard — ранее; новый executable-guard: `pdf render executable OK (DOCLOG-PDF-RENDER-DEPLOY-2): 25838 bytes`).

## 7. Эффект и действие для тимлида

1. **Действие по живому контуру:** передеплой сервиса (пересборка образа из fe790c5+). Проверка БЕЗ shell: `GET https://<сервис>.onrender.com/health/ops` → блок `render_dependencies`: `pdf_font.ok=true` (DejaVuSans) + reportlab/pillow/pypdf/pyarrow `ok=true` → среда полная, «Собрать формат: PDF» проходит. Если `pdf_font.ok=false` — контейнер stale: пересборка не применилась.
2. После пересборки stale-сценарий невозможен по построению: без рабочего PDF-рендера сборка образа падает с явной ошибкой (executable-guard), а не молча продолжает жить старым контейнером.
3. PNG/PDF/A-форматы больше не содержат «недоказанных установок» (F14 закрыт для всего класса тяжёлых рендеров).

## 8. Границы

Docker build в песочнице недоступен — Dockerfile верифицирован парсинг-тестами (docker-layout + оба deploy-сюита) и исполнением guard-команд под `sh -c`; живой Render не прогонялся (нет доступа); Memory/TestClient; UI не менялся; полный `tests/api` не гонялся (срез + смежные сюиты, ноль регрессий).

## 9. Поставка

ZIP `cisstat-doclog-pdf-render-deploy-2.zip` → открытый контейнер сессии (download/) + веб-страница поставки :3000 с кнопкой скачивания (верифицирована браузером). Новые: `tests/api/test_doclog_pdf_render_env_deploy.py`, `tests/api/test_doclog_pdf_render_env_classification.py`, `tests/api/test_doclog_pdf_full_upload_e2e.py`, `scripts/doclog_pdf_render_env/{reproduce_render_env.py, protocols/repro_result.json}`, `docs/doclog_pdf_render_env_2026-10-27.md`. Изменённые: `apps/api/Dockerfile`, `apps/api/requirements.txt`, `apps/api/document_renditions.py`, `apps/api/main.py`, `worklog/worklog11.md`. Без commit/push (AGENTS.md).
