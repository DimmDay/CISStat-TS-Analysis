# Поведение «Собрать формат:» → «Скачать MD/HTML/JSON» — разбор (read-only)

> **ОБНОВЛЕНИЕ (2026-10-27, DOCLOG-DL-FIX-1):** рекомендованный вариант C на ядре A РЕАЛИЗОВАН (по прямому указанию тимлида, база `b0ef60e`). Content-маршрут теперь отдаёт `Content-Disposition: attachment` для ВСЕХ форматов (ядро A); в шапке панели предпросмотра добавлено действие «Открыть в новой вкладке» → санитизированный `GET /revisions/{id}/preview` (`target="_blank" rel="noopener noreferrer"`, вариант C); preview-маршрут не менялся (легитимный inline). Пин `test_doclog4_document_delivery.py` честно инвертирован (versioned-паттерн), добавлены тесты `TestRenditionDownloadSemantics` и UI-сюита `documentation-new-tab-action.test.tsx`. Спека §15.2/§17 дополнена семантикой attachment/inline. Протокол после фикса: `scripts/doclog_dl_repro/protocols/repro_result.json` (все P0 — attachment, preview — inline). Разделы ниже — исторический разбор состояния `a4277b9` (до фикса).

**Task ID:** DOCLOG-DL-REPRO-1 (2026-10-27). **База:** `main@a4277b9` (синхронизация по прямому указанию тимлида; рабочее дерево чистое). Продуктовый код не менялся; no commit/push.

**Сценарий тимлида:** пройден этап «Загрузка» → кнопка «Документы» → строка «Собрать формат:». Замечания: (1) «Скачать Markdown» даёт не файл .md в загрузки, а страницу в той же вкладке платформы; (2) HTML должен открываться новой вкладкой; (3) «Скачать JSON» тоже не скачивается. Вопрос: обещали .md — что получили? Если поведение спроектировано архитектурно — оно может вводить пользователя в заблуждение.

---

## 1. Краткий ответ

Наблюдаемое поведение **воспроизводится на `a4277b9` байт-в-байт по причинам, указанным ниже**, и объясняется двумя слоями кода:

1. **Бэкенд** отдаёт готовый файл с заголовком **`Content-Disposition: inline`** (не `attachment`) — apps/api/routers/documentation.py, `get_rendition_content` (маршрут §17 `GET /renditions/{id}/content`). Для браузера `inline` означает «покажи содержимое в текущей вкладке», а не «сохрани в загрузки».
2. **Фронтенд** рендерит кнопку как обычную ссылку `<a href={renditionContentUrl(id)}>Скачать X</a>` **без атрибута `download` и без `target="_blank"`** — packages/ui/components/DocumentationWorkspace.tsx (блок «Скачать {format} ({size})», testid `doclog4-rendition-link`). Поэтому браузер совершает переход в той же вкладке и подчиняется `inline`.

Это **не случайный сбой и не проблема прокси**: URL собирается корректно (`/api/v1/documentation/renditions/{id}/content`, first-party rewrite `/api/v1/:path*` в обеих оболочках), cookies при top-level same-origin переходе уходят, API отвечает 200 с настоящими байтами документа. Пользователь получает **именно содержимое документа**, отрисованное браузером как страница, — workspace платформы при этом замещается той же вкладкой.

**Что «получили» вместо обещанного .md:** 1266 байт честного Markdown-документа (снимок D02: заголовок, claims, partial/gaps) — но в режиме отображения, а не сохранения. Контент корректен; **неверна семантика доставки**.

**Ответ на вопрос «спроектировано ли это архитектурно»:** да, `inline` — осознанное решение DOCLOG-4 (2026-10-23), задокументированное в журнале и **закреплённое пином теста** `tests/api/test_doclog4_document_delivery.py:612` (`assert "attachment" not in content-disposition`). Но это решение **противоречит собственному контракту платформы**: спека §12.2 обещает «Для готового файла — **немедленное скачивание**», §17 описывает маршрут как «**Скачать** уже готовый файл», а UI подписывает действие «Скачать X». Следовательно — это **расхождение контракт↔код↔UI того же класса, что F-D8C1 и находки честности UI (C09)**: поведение запроектировано на уровне реализации, но не согласовано с обещанным, и потому действительно вводит пользователя в заблуждение.

---

## 2. Цепочка кода (факты по a4277b9)

### 2.1 Фронтенд

- `packages/ui/lib/documentation.ts:243` — `renditionContentUrl(renditionId)` → `${getApiBase()}/v1/documentation/renditions/{id}/content`.
- `packages/ui/lib/apiClient.ts:19` — в production-браузере `getApiBase()` = `/api` (first-party прокси), в dev — `NEXT_PUBLIC_API_URL` (кросс-домен на бэкенд).
- `apps/standalone/next.config.mjs:60-64` и `apps/embedded/next.config.mjs:23-27` — rewrite `source: "/api/v1/:path*"` на бэкенд. Маршрут content попадает под rewrite — ссылка до API доходит.
- `packages/ui/components/DocumentationWorkspace.tsx` (секция «Готовые форматы»): единственная механика — `<a data-testid="doclog4-rendition-link" href={renditionContentUrl(item.rendition_id)}>Скачать {format} ({size})</a>`. **Атрибутов `download` / `target` нет.** Отдельная blob-механика для этого места не используется.

Для сравнения — остальные «Скачать» платформы ведут себя корректно:
- `ForecastExportMenu.tsx` — fetch → blob → `URL.createObjectURL` → `anchor.download`;
- `AdminLogsDashboard.tsx:296-302` — та же blob-схема для диагностического пакета;
- `ModelingWorkflowOverview.tsx:539` — `<a href=... download>Скачать JSON</a>` (same-origin, атрибут работает);
- `TsAnalysisForecasting.tsx:934` — blob + `anchor.download` для panel-forecast CSV.

Раздел «Документы» — единственная поверхность скачивания, полагающаяся на заголовки бэкенда, при том что бэкенд отдаёт `inline`.

### 2.2 Бэкенд

- `apps/api/routers/documentation.py` (`GET /renditions/{rendition_id}/content`): `Response(content=..., media_type=..., headers={"Content-Disposition": f'inline; filename="{filename_for(...)}"', "X-Content-Type-Options": "nosniff", "Cache-Control": "private, no-store"})`.
- `apps/api/document_renditions.py` — каталог `RENDITION_FORMATS`: md → `text/markdown`, html → `text/html`, json → `application/json`, jsonl → `application/x-ndjson`, csv → `text/csv`, pdf → `application/pdf`, xlsx/parquet/zip/docx/pdfa — бинарные; `filename_for()` — безопасное имя `document-{safe_id}.{ext}` (§15.2 соблюдено).
- Отдельный легитимный inline — `GET /revisions/{revision_id}/preview` (`Content-Disposition: inline; filename="preview.html"`): это и есть панель «Предпросмотр» UI, изолированная в sandboxed iframe (`DocumentPreview.tsx`, `sandbox=""` без allow-scripts/allow-same-origin). Preview обязан быть inline — тут возражений нет.

### 2.3 Происхождение `inline`

Введено в DOCLOG-4 (коммит `2caf08e`, 2026-10-23) одновременно с контуром выдачи; работа log10 фиксирует «GET /renditions/{id}/content (… Content-Disposition inline, nosniff, Cache-Control private,no-store §15.2 …)». Пин: `tests/api/test_doclog4_document_delivery.py:612` — `assert "attachment" not in resp.headers.get("content-disposition", "")` (тест `content`-группы, корпус md). То есть `inline` — не опечатка, а зафиксированное поведение. Мотивировка в коде — «Безопасные Content-Disposition/media_type/nosniff/private,no-store (§15.2)»; спека §15.2 при этом требует лишь «безопасные имена Content-Disposition, корректные media_type, nosniff» и не предписывает именно inline.

---

## 3. Динамическая репродукция (TestClient, Memory-сторы, паттерн корпуса DOCLOG-4)

Скрипт `scripts/doclog_dl_repro/reproduce_download_behavior.py`; протокол `scripts/doclog_dl_repro/protocols/repro_result.json`. Путь владельца: сессия → bound run `RUN-DLR00001` → frozen-снимок D02 штатным сборщиком DOCLOG-2 → черновик документа (201) → POST renditions (P0 синхронны, job сразу `ready`; zip — `queued` в очередь worker'а §18) → GET content. Заголовки ответов — ровно то, что получает браузер по клику:

| Формат | Content-Type | Content-Disposition | Что делает браузер (Chrome 120+, top-level переход) |
|---|---|---|---|
| md | `text/markdown; charset=utf-8` | **inline** | Рисует текст документа как страницу **в текущей вкладке**; в «Загрузки» ничего не попадает |
| html | `text/html; charset=utf-8` | **inline** | Рисует HTML-документ **в текущей вкладке** (workspace замещён); новой вкладки нет |
| json | `application/json` | **inline** | Показывает JSON как текст/вьюер **в текущей вкладке**; файл не сохраняется |
| jsonl | `application/x-ndjson` | **inline** | Текст в текущей вкладке (или download — зависит от сборки браузера) |
| csv | `text/csv; charset=utf-8` | **inline** | Текст в текущей вкладке |
| pdf | `application/pdf` | inline | Встроенный PDF-вьюер в текущей вкладке |
| xlsx / parquet / zip / docx / pdfa | бинарные | inline | Тип отобразить невозможно → браузер **скачивает** файл (filename берётся из Content-Disposition) |

Вывод матрицы: действие «Скачать X» **истинно только для бинарных форматов**; для md/html/json/jsonl/csv/pdf/svg/png происходит переход на контент в той же вкладке. Поведение зависит от формата — отсюда и ощущение непредсказуемости: «Скачать XLSX» скачивается, «Скачать MD» — нет.

Штатные пины DOCLOG-4 при этом зелёные (`pytest tests/api/test_doclog4_document_delivery.py -k "content or markdown or attachment"` → 5 passed): закреплён именно inline — то есть код соответствует своему пину, а расхождение живёт между пином и контрактом спеки/UI.

---

## 4. Ответы на три замечания

**1) «Выбираем Markdown, жмём “скачать Markdown”, получаем не файл .md, а страницу в той же вкладке. Обещали .md — что получили?»**
Получили сам документ (байты рендера MD-шаблона снимка — в репродукции 1266 B: заголовок «Документ исследования (снимок …)», секции D02, claims с validity) — браузер отрисовал его как текстовую страницу, заменив workspace. Файл в загрузки не попадает, потому что (а) заголовок `inline`, (б) у ссылки нет `download`-атрибута. Обещание «немедленное скачивание» (§12.2) и подпись «Скачать» не выполняются для рендеримых типов.

**2) «Выбираем HTML, жмём “Скачать” — вкладка должна открываться новой страницей».**
Сейчас открывается **та же** вкладка (нет `target="_blank"`, заголовок inline). Замечу: ожидание «новой вкладки» для HTML-документа разумно как минимум, но архитектурно корректнее различить две операции: «Предпросмотр» (уже есть — sandboxed iframe в панели, inline оправдан) и «Скачать» (должен сохранять файл, т.е. `attachment`). Тогда HTML тоже будет честно скачиваться файлом .html, а просмотр останется в панели; открывать в новой вкладке страницу-рендер — возможная дополнительная опция, но не замена скачивания.

**3) «Выбираем JSON, жмём “скачать JSON” — получаем вкладку платформы, не файл .json».**
То же самое: `application/json` + inline → JSON отображается в текущей вкладке. Файл не сохраняется.

**Про формулировку «html страницу на вкладке самой платформы»:** уточнение по коду и репродукции — страница-рендер приходит **с content-маршрута API** (не из Next.js): URL попадает под rewrite, API отвечает 200 с байтами документа. «Страницей платформы» это выглядит потому, что переход происходит в той же вкладке и любой ответ браузер показывает как документ. Если бы сессия к моменту клика была потеряна, в той же вкладке отрисовался бы JSON-ошибки (404 «Документ не найден») — тот же класс наблюдения «страница вместо файла».

---

## 5. Классификация: спроектировано, но вводит в заблуждение

- **Спроектировано на уровне реализации:** да — inline введён сознательно в DOCLOG-4 и закреплён пином; безопасные составляющие (nosniff, private,no-store, безопасное имя файла, санитизация HTML-рендера: html.escape, нейтрализация javascript:/data:/vbscript:, без script/img/link) — реальны и полезны.
- **Согласовано с контрактом — нет.** Три источника обещают скачивание: спека §12.2 («немедленное скачивание»), спека §17 (маршрут «Скачать уже готовый файл»), UI-подпись «Скачать X». Реализация даёт «открыть в текущей вкладке» для рендеримых форматов. Это расхождение контракт↔код класса F-D8C1/C09 — в проекте такие находки закрывались отдельными фикс-срезами с честным обновлением пинов (versioned-паттерн).
- **Практический вред:** пользователь теряет workspace (переход в той же вкладке), не получает файл, обязан жать «Назад» и терять позицию в интерфейсе; для md/json выглядит как «ничего не скачалось, что-то сломалось». Побочный эффект безопасности: top-level рендер `text/html` rendition в контексте API-origin слабее изоляции, чем предназначенный для этого sandboxed iframe предпросмотра (сейчас риск закрыт полной санитизацией рендера, AC16, но `attachment` уменьшил бы поверхность по построению).

## 6. Рекомендации (без реализации — read-only срез)

1. **Точечный вариант (бэкенд, одна точка):** для `GET /renditions/{id}/content` заменить `inline` на `attachment` (preview-маршрут не трогать — там inline оправдан). Закрывает все три замечания для всех форматов сразу; в dev-кросс-домене тоже работает (заголовок уважается и для кросс-домена). Требует честного versioned-обновления пина `test_doclog4_document_delivery.py:612` (`attachment` становится обязательным) и прогонки doclog-корпуса.
2. **Фронтенд-вариант:** fetch → blob → `anchor.download` (паттерн AdminLogsDashboard/ForecastExportMenu) — не зависит от заголовков, но не чинит «открыть в новой вкладке» для HTML и дублирует механику; для кросс-домена — единственный вариант, если бэкенд не трогать.
3. **Максимально честный UX:** развести подписи/действия — «Предпросмотр» (панель, уже есть) / «Скачать файл» (`attachment`) / опционально «Открыть в новой вкладке» (`target="_blank"` для рендеримых). Спека §12.4 и так требует полных негативных состояний — это тот же класс честности подписей, что C09.
4. Любой вариант не нарушает §15.2: имя файла, nosniff, private,no-store сохраняются; CSRF не применим (GET read-only), авторизация R09 не меняется.

## 7. Границы достоверности

- Динамика: TestClient + Memory-бекенды (паттерн DOCLOG-4), D02/`owner-v1`; heavy-форматы проверены на постановку в очередь (zip `queued` — worker в TestClient-среде не тикал; их фактическая отдача `inline` подтверждается кодом того же маршрута).
- Живой браузер (Chrome/Firefox/Safari), Vercel-прокси и Render не прогонялись; выводы о поведении браузера — стандартная семантика Content-Disposition/nosniff для top-level перехода (матрица §3 — Chrome-ориентированная; Firefox/Safari могут отличаться в деталях для jsonl/csv).
- Продуктовый код не менялся; пины не переписывались; реализация фикса — отдельная задача по AGENTS.md (TDD: сначала инверсия пина как RED).

---

*Репродукция: `scripts/doclog_dl_repro/reproduce_download_behavior.py` (namespace RUN-DLR*/dlr-*, дизъюнктен repo-корпусу), протокол `protocols/repro_result.json`. Запуск из корня репозитория: `python3 scripts/doclog_dl_repro/reproduce_download_behavior.py`.*
