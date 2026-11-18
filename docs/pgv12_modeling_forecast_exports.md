# PGV-12: Export modeling/forecast/panel (spec_passport_graphics_visual.md §13)

**База:** 1cc4022 (origin/main). **Статус:** реализация по спеке, commit/push не выполнялись (AGENTS.md).

## Скоуп (13 view: modeling 6 + forecasting 7 pgv-03)
modeling.workflow.overview, modeling.traceability.cards, modeling.backtest.comparison, modeling.backtest.oof, modeling.panel.metrics, modeling.diagnostics.residuals; forecasting.forecast.chart, forecasting.forecast.panel_chart, forecasting.forecast.panel_table, forecasting.forecast.comparison, forecasting.forecast.sensitivity, forecasting.accuracy.metrics, forecasting.monitoring.d12. Паспорта pgv-04/13 и static_demo -- вне (честный отказ). `forecasting.forecast.legacy_png` СНЯТ С УЧЁТА: клиентский canvas-PNG ForecastExportMenu переехал на общий pipeline (view forecasting.forecast.chart, serializeChartSvgSafe СВОЕГО узла); CSV/JSON и recordClientExport audit сохранены (§10.1, критерий §13).

## Ключевые решения
1. **Честные недоборы PGV-03 закрыты** (8 адаптеров добавлено: workflow/traceability/panel.metrics/diagnostics + comparison/sensitivity/accuracy/d12; UNWIRED_PGV03_VIEWS пуст). Экстракторы строят канонические печатные формы ({columns,rows}/{cards}) ИЗ ТЕХ ЖЕ frozen данных; экранная форма не меняется (паритет PGV-10/11).
2. **Wiring freeze** (без новых роутов): GET /modeling/state -> workflow; GET /modeling/context -> traceability; POST /panel/backtest -> panel.metrics; POST /diagnostics -> diagnostics.residuals; POST /forecast (+accuracy в один notify), GET /forecast/{id} (lazy §6) -> chart+accuracy; POST /forecast/compare -> comparison; POST /forecast/{id}/sensitivity -> sensitivity; POST/GET /monitoring/comparisons -> d12 (direct freeze_visual_from_response, best-effort).
3. **AC14 (панельные dimensions)**: dimensions.mode="panel" + entity_ids из frozen данных; entity_column -- имя колонки из ЗАФИКСИРОВАННЫХ panel_columns сессии (refs.entity_column -- требование валидатора PGV-02, honest-источник: без panel_columns панельный бэктест не выполняется). Отсутствие -- честный отказ, не фабрикация.
4. **Честные коррекции реестра** (документированы в комментариях записей): refs modeling-видов -- без modeling_artifact_ref (в ответах отсутствует, артефактный ref -- execution.result_ref); diagnostics -- backtest_run_id; traceability -- checkpoint_id (snapshot_id -- в frozen data, вид -- research-поверхность; паспортный scope -- PGV-13); comparison -- forecast_artifact_refs (наложение НЕСКОЛЬКИХ артефактов, sorted join); render_site diagnostics -- смонтированная поверхность ModelingWorkflowOverview#diagnostics-report (standalone ResidualDiagnosticsPanel не смонтирован -- исключение реестра №10 с причиной).
5. **Не фабрикуется** (§3.6/§6): отсутствующие метрики accuracy -- None; отсутствующие интервалы панельной таблицы -- None; нет entity_columns/checkpoint/comparison-refs -- честный отказ экспорта.

## Верификация
- TDD: RED-корпус python 38F/3P (scripts/pgv12/protocols/red_protocol.txt), TS-гвард 6F/2P. GREEN: tests/api/test_pgv12_visual_exports.py **41/41** (скоуп/адаптеры/снапшот-refs/dimensions/HTTP 202+ready/идемпотентность/CAS-409/wiring-гвардия/CSV-JSON-сохранение); TS-гвард pgv12coverage **8/8**; все гварды реестра PGV-00/10/11/12 **43/43**; затронутые сьюты (Modeling/Forecasting/Workflow/Traceability/Backtest*/Accuracy/doclog8-monitoring/vars) зелёные.
- check_routes (scripts/pgv12/check_routes_auth00.py): **PASS -- added=[] (новых HTTP-маршрутов НЕТ)**; 13 view проходят resolve; legacy_png -- честный отказ с подсказкой.
- Реестр: config/visual_registry.json регенерирован (92 сайта, forecasting 7, исключений 10); экспортный union 68 view (38+17+13).
- py_compile PASS.

## Границы (честные)
- Полный tests/api прогон и полный jest: в песочнице выполнен затронутый регресс; полный корпус (3387P/20F предсуществующих средовых, дельта-0 по методике PGV-11) -- за тимлидом через local_gates на своей машине.
- Контейнер PGV-08/Chromium/Docker и живой PostgreSQL в песочнице недоступны (унаследовано): job доводится до ready штатным worker'ом с fake-renderer'ом.
- native Windows не исполнялся; вычисляемый viewId скан-гвара допускает цифры (d12).
- inventory --check в песочнице падает на предсуществующем CRLF-классе (page:*/upload fingerprints) -- не поставка PGV-12; маршрутная карта не менялась.

## Поставка
ZIP: download/cisstat-pgv12-modeling-forecast-exports.zip (файлы только текущей задачи + files.txt). Применение: распаковать поверх чекаута 1cc4022 -> git add <files.txt> -> commit -> push; VM: git pull --ff-only; пересборка образов НЕ требуется... НО: изменены python-файлы внутри образа api и UI-бандл web -- **docker compose build api web && env -u CISSTAT_AUTH_MFA_KEYS -u CISSTAT_AUTH_MFA_ACTIVE_KEY docker compose up -d** (паритет практик AUTH-07-HOTFIX1/AUTH-KABINET-DEMO).

## Дополнение после локального прогона local_gates (тимлид)

**auth00 FAIL (check_committed --target index)** — ожидаемо: поставка меняет 8 reviewed-источников
(3 роутера, visual_exports/visual_producers, 3 UI-компонента), а карта `docs/auth00/inventory.json`
в ZIP не входила. Выполнен честный review-шаг (`scripts/auth00/inventory.py --write` после review
диффа), верификация диффа: **counts идентичны** (api 282, всего 661), **added/removed ids: нет**,
**non-evidence field diffs: нет** (method/path/operation/классификация не тронуты), evidence —
**41 запись, только сдвиг line** (source/symbol прежние), fingerprints — ровно 8 доставленных
файлов. Карта включена в поставку (inventory.json + inventory.md). Коммитить map+sources вместе.

**jest FAIL** — причина: применён ПЕРВЫЙ ZIP (09:05), где `TsAnalysisModeling.tsx` содержал
сломанный JSX-комментарий (TS2304 → сьютет не компилировался); в финальном ZIP (09:10+) файл
исправлен и сьютет зелёный (53/53 локально). Применить финальный ZIP целиком.

**Попутно**: в worktree-клоне песочницы отсутствовали `apps/{embedded,standalone}/app/upload/page.tsx`
(предсуществующая порча клона — блокировала `inventory.py build`); восстановлены из HEAD
(`git checkout HEAD -- ...`), в поставку не входят (у тимлида они в HEAD без изменений).

## Дополнение 2: второй прогон local_gates — jest FAIL (3 устаревших source-scan пина)

Полный jest у тимлида: 3 failed теста в 2 сьютетах — source-scan пины, не учтённые PGV-12:

1. `packages/ui/dkt5-open-questions.test.ts` (§10.1 «всегда светлый» PNG): требовал клиентские
   canvas-паттерны (`resolveSvgVarsLight(clone)`, `context.fillStyle="#FFFFFF")`, которые PGV-12
   законно удалил. Инвариант «светлый артефакт» переведён на новый источник: клиентский
   canvas-рендер отсутствует (`not.toMatch(/toBlob|fillStyle|resolveSvgVarsLight/)`), экспорт уходит
   в `requestVisualExport` с view `forecasting.forecast.chart`; светлость гарантирует серверная
   печать — `print.theme === "light-print"` обязателен схемой снапшота (`theme_not_light_print`,
   spec §3.4), белый фон — `printTheme.ts: page_background: "#FFFFFF"`.
2. `packages/ui/print/printSchema.test.ts:577`: пин `VISUAL_SITE_REGISTRY.length == 93` → 92
   (TS-двойник Python-пина PGV-01; legacy_png снят с учёта, forecasting 7). Обновлены также
   комментарии/имена («93 sites» → 92).

Оба сьютета зелёные (54/54), полный jest: 2913 passed; 2 «failed suites» в песочнице — SIGKILL
jest-воркеров (OOM клона), на их машине воспроизведения нет — подтверждено отдельным прогоном
(5/5). Python-пиновые тесты (pgv01/03/10/11) впервые включены в поставку (packager +6 файлов):
после пересоздания песочницы их правки не восстановились из ZIP, т.к. файлы в него не входили;
применены заново (226 passed).
