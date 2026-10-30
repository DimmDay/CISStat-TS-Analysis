# PGV-10 — Export upload/validation/preprocessing (2026-10-30)

**Спецификация:** `spec_passport_graphics_visual.md` §10.1/§11/§13, строка PGV-10
(зависимости PGV-03 + PGV-09 — выполнены). **База:** `main@09c79aa` (PGV-09).
**Критерий завершения §13:** «Верный PNG каждого view, before/after/sampling,
не первый SVG».

Поставка следует AGENTS.md: проектирование → точки изменения → риски →
TDD (RED → GREEN) → затронутый регресс + дельта-0 → сборка → worklog/ZIP.
Commit/push не выполнялись.

## 1. Постановка и результат

«Скачать PNG» появилось на **всех 38 render sites** остановок
Загрузка/Валидация/Предобработка (pgv-03 research view реестра PGV-00:
10 upload + 10 validation + 18 preprocessing; паспорта pgv-04/13 и
static_demo вне скоупа — честные отказы с добирающей задачей). Экспорт
строит печатный PNG из **durable frozen inputs** через печатный конвейер
PGV-09 (V01 revision → document job → renderer-контейнер PGV-08), не
запуская науку (AC06).

## 2. Ключевые решения

1. **Экспорт из durable-слоя без науки (AC06).** Источник —
   `visual_result` артефакт, замороженный `notify_visual_result` в момент
   фактического ответа (PGV-03). Пересчёт/GET запрещены; кэш сохранённых
   ответов (`freeze_saved_visual`, producer_first_export, CAS ВСЕГДА) —
   fallback lazy transfer (§6) только для результата, не попавшего в
   durable слой. Ревизия/цель/дата — обязательные refs research-снапшота
   (run.target_column + сессия/запрос; отсутствие — честный
   `source_unavailable`, refs не фабрикуются).
2. **Не «первый SVG» (критерий §13).** Recharts-геометрия — сериализация
   СВОЕГО chart-узла (`packages/ui/lib/serializeChartSvg.ts`: ref на
   контейнер конкретного view, `container.querySelector("svg")`;
   `document.*` сканы запрещены coverage-гвардом). Legacy-паттерн
   ForecastExportMenu («первый SVG контейнера») не воспроизводится.
3. **Frozen print input с геометрией (AC08).** `screen_svg`
   замораживается в recharts-секции снапшота с sha256; identity снапшота
   аддитивно расширена
   `pgv.print_snapshot:{view_id}:{result_digest}[:svg16]` — иной frozen
   print input (другая геометрия того же результата) — ДРУГОЙ immutable
   снапшот (§8 «старые snapshots не переписываются»), а не конфликт
   ключа. Данные авторитетны из visual_result; SVG — rendering-asset,
   санитайзер контейнера (AC19) — второй слой.
4. **Идемпотентность (§11/AC09/§12.2).** Identity снапшота вычисляется
   ДО сборки payload; существующий frozen input переиспользуется (его
   время фиксации не переписывается) → та же V01 ревизия (basis_
   fingerprint включает профиль, F-P2C3) → тот же активный/ready job.
   Иной профиль — новая ревизия того же печатного документа.
5. **before/after/sampling.** sampling frozen результата
   (full/windowed/downsampled/truncated) переносится в снапшот;
   `display.detail_level = "sampling"` при неполном показе;
   `detail_level=compact` декомпозиции/спектра — честный truncated с
   фактическим cap (Task 97.3: расчёт полный, показ ограничен). Пары
   «до/после» — состав frozen data (обе серии в печати); смена данных
   между показом и экспортом — 409 context_changed (PGV-AC07).
6. **Mixed-сайты (6 view Предобработки).** Печатная композиция ≥2 секций
   разных kinds из ОДНОГО frozen data (chart — из screen_svg, таблица —
   из `{columns, rows}` того же среза). Мост `section_content_from_
   visual_result` строит каждую секцию СВОИМ строителем по renderer_kind
   секции; `{columns, matrix}` корреляционных срезов разворачивается в
   таблицу с row-headers. Отсутствие формы — терминальный
   `missing_section_content` (§3.6, не фабрикуется).
7. **Честные preflight-отказы.** `screen_svg_required` (chart-секция без
   frozen геометрии — до постановки job'а, а не заглушка контейнера),
   `invalid_screen_svg` (не SVG/<script>/foreignObject/on* — защита в
   глубину до санитайзера AC19), `invalid_profile`,
   `source_unavailable` (409), `context_changed` (409), uniform 404
   чужого run (AC18), 429 лимиты очереди (§18). Тела ошибок — плоские
   `{code, message, request_id}` (паритет routers/logs.py).

## 3. Точки изменения (файлы)

**Новые:**
- `apps/api/visual_exports.py` — скоуп/спеки печати (38 view: заголовки,
  оси, заголовки таблиц, композиции mixed), сборка
  VisualPrintSnapshot/1, резолв frozen результата, `list_visual_sources`,
  `request_visual_export` (freeze → snapshot → V01 → job);
- `packages/ui/lib/serializeChartSvg.ts` (+ тест) — scoped сериализация;
- `packages/ui/lib/visualExports.ts` — клиент (run_id — единый источник
  /trace, паритет resolveCurrentRun; плоские ошибки);
- `packages/ui/components/VisualExportButton.tsx` (+ тест) — общее
  действие «Скачать PNG» (§10.1: accessible название, честные
  idle/queued/error/disabled) + `VisualExportChartScope` (ref-скоуп
  chart-ячейки);
- `packages/ui/lib/visualExportRegistry.pg10coverage.test.ts` —
  coverage-гвард: каждый из 38 сайтов монтирует кнопку; viewId кнопок —
  только скоуп; chart-сайты сериализуют scoped; unknown site блокирует;
- `tests/api/test_pgv10_visual_exports.py` — 46 оракулов;
- `docs/pgv10_visual_exports.md`, `scripts/pgv10/check_documents.py`.

**Изменённые:**
- `apps/api/visual_producers.py` — 12 адаптеров добора «Предобработки»
  (regularity overview/gap_map, decomposition, variance×5, stationarity,
  spectral, feature_eng, scaling) + аддитивные формы двух wired
  (coverage_matrix → каноническая теплокарта из фактических bins;
  outliers.series_profile → табличная форма границ); UNWIRED_PGV03_VIEWS
  сужен честно (остались modeling/forecasting → PGV-12);
- `apps/api/routers/session.py` — wiring 8 GET-эндпоинтов Предобработки
  (best-effort freeze, X-Visual-* — паритет PGV-03);
- `apps/api/visual_artifacts.py` — `print_snapshot_producer_key`:
  аддитивный svg-член identity (см. решение 3);
- `apps/api/print_render_payload.py` — мост: секции по renderer_kind
  секции, screen_svg снапшота — первичный источник recharts-контента,
  `{columns, matrix}` → таблица;
- `apps/api/routers/documentation.py` — `GET /runs/{run_id}/visual-sources`,
  `POST /runs/{run_id}/visuals` (202 + status_url; плоские ошибки);
- 19 поверхностей UI — вмонтирована кнопка (полный перечень — coverage-
  гвард); `packages/ui/components/PreprocessingDecompositionOverview.
  test.tsx` — селектор пина Task 97.3 обновлён (`section > .absolute` →
  `section .absolute`): PGV-10 добавил контейнер frozen-геометрии между
  section и панелью раскрытия; смысл пина («раскрытие не дозагружает
  данные; loading bar виден») сохранён.

## 4. TDD

- **RED:** 43 failed / 3 passed на базе 09c79aa
  (`scripts/pgv10/protocols/red_protocol.txt`) — корпус на своих данных
  (RUN-PGV10A01, pgv10-*), дизъюнктен repo и PGV-02/03/08/09.
- **GREEN:** 46/46; в процессе пойманы и исправлены дефекты реализации
  (hooks-порядок useRef после ранних возвратов — «Rendered more hooks»,
  cookie-имя в TestClient-хелперах, якорь timeline-графика) и оракулов
  (честная форма coverage-данных, allowlist-контракт selection).
- **Регресс:** pgv01/02/03/04/05/06/09 + doclog4/5/recheck + upload/
  missing — 442 passed, 0 failed. Полный `tests/api`: **дельта-0** —
  FAILED-ID байт-идентичны чистой базе 09c79aa (git stash, одна среда):
  28F/3285P/42S vs 28F/3239P/42S, +46 = ровно корпус поставки.
- **Jest полный:** **2766/2766, 0 failed** (было 2760: +15 новых PGV-10,
  -4 отказа после фикса hooks/пина — предсуществующие от вайринга не
  остались). `typecheck:all` (embedded+standalone) PASS; `tsc -p
  packages/ui` PASS.

## 5. Честные границы

1. **Контейнер PGV-08/Chromium/Docker в среде недоступны** (унаследовано
   от PGV-08): контейнерная E2E и финальный image smoke не
   пересертифицируются; полный путь job'а покрыт инъекцией
   fake-renderer'а (паттерн класса D PGV-09), HTTP-контракт клиента —
   PGV-09 (реальный TCP-раундтрип).
2. **Составные панели экрана** (два графика рядом: стационарность
   до/после, скейлинг-распределения): chart-секция печати несёт СВОЙ
   главный SVG вида (первый svg внутри контейнера ЭТОГО view — чужой
   график невозможен); печатная композиция обеих панелей — зона
   пагинации/page-set PGV-14 (граница документирована).
3. **screen_svg замораживается на экспорте** — пересчёт recharts-геометрии
   на бэкенде отсутствует по построению (§4.1: единственная реализация —
   общий print-бандл); между разными окнами клиента — разные frozen
   print inputs (новые снапшоты, AC08-честность).
4. **date_column** — обязательный ref: берётся из структуры сессии
   запуска либо явного поля запроса; при утраченной сессии экспорт
   честно отказывает (source_unavailable) до восстановления структуры —
   V01 научных остановок сессионно-привязан (Path B — паспорта, PGV-13).
5. Живой PostgreSQL/docker/Render не проверялись (Memory-сторы; контур
   durable-зеркал наследуется от PGV-02/09). Манифест sha256 не ведётся
   (конвенция серии).
6. coverage-гвард — статический оракул исходников (паттерн PGV-00);
   живая браузерная приёмка кнопок — вне среды (граница PGV-08).

## 6. Deliverable

ZIP `cisstat-pgv10-visual-exports.zip` → открытый контейнер сессии
(download/) и веб-приложение :3000 (страница поставки с кнопкой
скачивания); только файлы текущей задачи. Без commit/push (AGENTS.md).
