# DOCLOG-DL-FIX-1 — семантика доставки документов «Собрать формат:» (вариант C на ядре A)

**Дата:** 2026-10-27. **База:** `main@b0ef60e` (синхронизация по прямому указанию тимлида). Продуктовые изменения внесены; no commit/push (AGENTS.md).

## 1. Постановка

Сценарий тимлида (срез DOCLOG-DL-REPRO-1, база a4277b9): «Скачать Markdown» даёт не файл .md, а отрисованный документ в текущей вкладке; HTML должен открываться новой вкладкой; «Скачать JSON» не скачивается. Диагноз: бэкенд отдаёт `Content-Disposition: inline` (решение DOCLOG-4, закреплённое пином), фронтовая ссылка — без `download`/`target`; расхождение контракт↔код↔UI (§12.2 «немедленное скачивание», §17 «Скачать уже готовый файл», подпись UI «Скачать X»). Решение по реальной аналитической практике — **вариант C на ядре A** (одобрен тимлидом): «Скачать» = файл для ВСЕХ форматов; просмотр рендера = санитизированный preview в новой вкладке.

## 2. Процесс и точки изменения (TDD: RED → код → GREEN)

1. **RED (pytest):** инверсия пина `tests/api/test_doclog4_document_delivery.py:612` (versioned-комментарий; было `assert "attachment" not in` → стало `assert "attachment" in`) + новый класс `TestRenditionDownloadSemantics` (attachment-матрица всех P0-рендеримых форматов + пин легитимного inline у preview). Прогон на старом коде: **2 failed, 1 passed** — header `inline; filename="document-drend-…​.md"` — RED подтверждён.
2. **Код бэкенда:** `apps/api/routers/documentation.py::get_rendition_content` — `inline` → `attachment` (все форматы); docstring + комментарий с мотивировкой; preview-маршрут НЕ менялся.
3. **RED/GREEN (jest):** новый сюит `packages/ui/components/documentation-new-tab-action.test.tsx` — сначала RED (действие отсутствует + падение на неполной фикстуре), после фикса фикстуры — **2/2 passed**: (а) действие «Открыть в новой вкладке» ведёт на `/v1/documentation/revisions/{id}/preview` с `target="_blank"` + `rel="noopener noreferrer"`; (б) ссылки «Скачать X» — href на content-маршрут, БЕЗ `target`/`download` (семантику скачивания несёт attachment бэкенда — клиентские blob/target-хаки не дублируются); (в) на пустом списке действие отсутствует.
4. **Код фронта:** `packages/ui/components/DocumentationWorkspace.tsx` — действие в шапке панели предпросмотра (видно при `previewPhase === "ready" && revision`); импорт `revisionPreviewUrl`; комментарий с архитектурной мотивировкой (почему preview-маршрут, а не content: при attachment `target="_blank"` на content дал бы скачивание в новой вкладке, а не просмотр).

## 3. Проверки

- `pytest tests/api/test_doclog4_document_delivery.py` → **50 passed** (весь корпус DOCLOG-4).
- `pytest tests/api/ -k "doclog or documentation"` → **604 passed, 1 skipped**.
- Полный `pytest tests/api/` → 48 failed / 2800 passed; отказы — файлы forecasting/modeling/garch/egarch/upload/eda/progress, НЕ тронутые диффом; выборочная верификация на ЧИСТОЙ базе b0ef60e (патч-метод): `test_forecasting_session.py` — те же 16 failed → отказы **предсуществующие env-зависимые** (тот же класс, что зафиксирован в worklog b0ef60e: «отказы побайтово совпадают с чистой базой; psycopg отсутствует и пр.»). Ноль регрессий от диффа.
- Jest: полный прогон в песочнице был заблокирован SIGBUS — диагностирован корень: **обрезанные файлы пакетов** из частичного кэша npm (пример: `csstype/index.d.ts` 515KB вместо 894KB; mmap усечённого файла = SIGBUS). Лечение: чистые `node_modules` + кэш + fresh install → jest работает. Новый сюит 2/2; полный регресс — см. worklog (итог прогона).
- Динамическая репродукция после фикса (`scripts/doclog_dl_repro/reproduce_download_behavior.py`, протокол `protocols/repro_result.json`): md/html/json/csv/jsonl → `attachment; filename="document-{safe_id}.{ext}"`, nosniff, private,no-store; preview → `inline; filename="preview.html"`.

## 4. Спека (контракт приведён в соответствие)

- §15.2: добавлен абзац — семантика Content-Disposition разведена по назначению маршрута (content — всегда attachment; inline — только preview-просмотр).
- §17 таблица: content-маршрут — «Content-Disposition: attachment для ВСЕХ форматов»; preview-маршрут — «inline — просмотр: панель предпросмотра и „Открыть в новой вкладке" с noopener noreferrer».

## 5. Риски и границы

- **Браузеры:** attachment уважается для top-level переходов во всех основных браузерах; в dev-кросс-домене тоже работает (заголовок уважается кросс-доменно). Живой браузер/Vercel/Render не прогонялись (TestClient-репродукция); поведение — стандартная семантика.
- **Безопасность:** §15.2 сохранена (имя/nosniff/no-store); CSRF неприменим (GET read-only); R09 и audit-тройка не менялись; поверхность top-level рендера text/html в API-origin уменьшена по построению (файл вместо рендера); новая вкладка — `noopener noreferrer` + санитизированный preview (AC16).
- **Совместимость UI:** прежние пины DOCLOG-4, кроме честно инвертированного, не менялись; встройки DocumentationWorkspace без пропа — прежний контракт; `preview`-маршрут остаётся источником sandboxed-iframe.
- **Jest-среда:** полный jest-регресс в этой песочнице изначально SIGBUS (обрезанные пакеты из частичного npm-кэша); после чистой переустановки jest исполняется; итог полного прогона зафиксирован в worklog записи DOCLOG-DL-FIX-1.

## 6. Поставка

ZIP в открытый контейнер сессии (download/) + веб-страница поставки :3000 с кнопкой скачивания. Пути изменённых/новых файлов — в worklog11.md (запись DOCLOG-DL-FIX-1). Без commit/push.
