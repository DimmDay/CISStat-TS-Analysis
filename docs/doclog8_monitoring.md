# DOCLOG-8 — Мониторинг: D12 «Сверка прогноза с фактом»

База: main@3634052 (DOCLOG-0..7 включены; синхронизация по прямому указанию тимлида). Спека: spec_documentation_logging.md §6 D12, §6.1 (мониторинг), §19 строка DOCLOG-8, B07/F11, AC12/AC15/AC17.

## Постановка и граница

§19: «D12: frozen forecast и actual vintages, выравнивание, оценки, revisions/threshold decisions». Критерий завершения: «поздний факт и revise не переписывают старый выпуск/OOF». Зависимости 1–6 выполнены.

Реализовано построчно по §6 D12 и §6.1:

- **Frozen forecast vintage** — сверка читает артефакт kind="forecast" (D08-основа) с проверкой целостности байтов (T8: payload_sha256); прогноз НЕ пересчитывается и НЕ изменяется (§6 D08 «никогда не заменять старый выпуск новым»).
- **Actual vintage** (doclog.actual_vintage/1) — иммутабельная партия факта: target/entity, единицы (обязательны, B07), as_of (дата поступления), источник, значения {period, value}. Пересмотр факта = НОВАЯ партия; append-only (AC15).
- **Выравнивание** — точное по метке периода (strip); незрелые горизонты (прогноз без факта) исключены ЯВНО списком меток — НЕ нулевая ошибка (§6.1); факты вне горизонта — отдельный счётчик со списком.
- **Единицы (AC15)** — as_is / converted (только явно переданный {factor, note}) / unknown (forecast_units не объявлены — честное unknown); несовпадение без конверсии — отказ с причиной (MonitoringUnitsMismatchError, 422), сверка не создаётся.
- **Оценки (AC12)** — по зрелым парам: signed/absolute error, ape (факт-ноль → null + reason «actual_zero»), MAE, bias (mean signed error), MAPE (null + reason + список нулевых периодов при хотя бы одном нуле), MASE (только с явно переданным training-scale > 0; без — null + «mase_scale_required»), покрытие интервала (ci_lower/ci_upper; без границ — null + reason). Агрегаты без зрелых горизонтов — null + «no_matured_horizons».
- **Threshold decisions** — порог {metric ∈ {mae, mape, bias_abs, mase}, operator ∈ {>, >=}, value} — ФАКТ (exceeded / within / not_evaluable с reason); decision_action в сверке всегда null; «Автопереобучение не следует из превышения порога без отдельного решения» (§6.1). Решение — отдельная append-only запись человека (doclog.monitoring_decision/1): action ∈ {none, accept, investigate, retrain_requested} + обязательное основание; «retrain_requested» — ЗАПРОС (запись), не действие.
- **Read-only над научным слоем** (AC05-дух) — реестр артефактов, ledger run и OOF не мутируют свергой/решением; оракул на diff durable-состояния.
- **Идемпотентность** (§10.3/AC09) — UNIQUE(run_id, idempotency_key) для партий и сверок; тот же ключ с другим телом — 409.
- **Доступ** — решающая таблица DOCLOG-0 (§15.1): write для регистрации/сверки/решения, read для списков; чужой run/артефакт — uniform 404 (T7/T15).

## Карта изменений

Новые: `apps/api/monitoring.py` (записи/реестры Memory+Postgres/сервис/чистая функция compute_comparison_result); `apps/api/routers/monitoring.py` (7 маршрутов /v1/documentation/runs/{run_id}/monitoring/*: actuals POST+GET, comparisons POST+GET, comparisons/{id} GET, comparisons/{id}/decisions POST+GET; плоские ошибки {code, message, request_id} — паритет logs.py); `apps/api/migrations/0014_doclog8_monitoring.sql` (3 таблицы + 4 индекса; FK на research_runs ON DELETE CASCADE — научные данные run; UNIQUE(run_id, idempotency_key)); `packages/ui/lib/monitoring.ts`; `packages/ui/components/MonitoringComparisonPanel.tsx`; `packages/ui/components/doclog8-monitoring-ui.test.tsx`; `tests/api/test_doclog8_monitoring.py`; этот документ.

Обновлённые: `apps/api/report_snapshot.py` (D12 «Сверка прогноза с фактом» в DOCUMENT_KINDS, 12 видов); `apps/api/snapshot_builder.py` (адаптер _section_d12 — читает frozen сверки, без пересчёта; пусто — честный unknown-claim); `apps/api/document_lifecycle.py` (publish-политика: partial допустим для D01-D10 и D12); `apps/api/security_audit.py` (AUDIT_ACTIONS 21→24: monitoring_actual_registered / monitoring_comparison_created / monitoring_decision_recorded — standard-класс, §8); `apps/api/research_runs.py` (MIGRATION_STATEMENTS_0014, каталог 14/85); `apps/api/main.py` (include monitoring router); `packages/ui/components/DocumentationWorkspace.tsx` (D12 в левом списке + панель в превью D12; каталог экспортирован); `packages/ui/index.ts` (экспорт панели и типов). Честные обновления пинов: test_doclog2 (kinds-каталог 12, resolve_kinds D12/D99), test_doclog3/4/5/6/7 (миграции 14/85, invalid kind D99, D12 201).

## Ключевые решения (7)

1. Сверка — отдельный durable-контур (monitoring.py + миграция 0014), а не интерпретация «на лету» над live-run: секция D12 снимка читает frozen сверки (§19.1 «отсутствие пересчётов»).
2. Actual vintage = партия (batch), а не построчные апдейты: «поступившая версия факта» (§6 D12) приходит как согласованное множество с общим as_of/units/source.
3. Незрелый горизонт ≠ нулевая ошибка: исключение со списком меток (§6.1 дословно).
4. Единицы — на границе контура: mismatch без явной конверсии = 422 с причиной (AC15 «новая оценка либо отказ с причиной»), unknown без фабрикации.
5. Порог — факт в frozen-результате; решение — отдельная append-only запись с основанием (§6.1), каталог действий фиксирован fail-closed.
6. Аудит monitoring_* — standard (§8: mandatory только публикация/approval/выдача защищённых данных); сбой аудита не ломает научную операцию.
7. UI: панель в DocumentationWorkspace для D12 (таблица + агрегаты + порог + незрелые явным списком; AC17-состояния loading/empty/forbidden/error); ключевые ID сверок — в раскрытии/атрибутах, не мусорят основной текст (§12.2 инспектор).

## Верификация

TDD RED: ImportError monitoring (63 ошибки коллекции) + UI module missing — корпуса не вакуумные. GREEN: test_doclog8_monitoring 63/63 (поверхность 3; валидация партий 7; vintage-семантика 3; единицы 5; зрелость 4; метрики AC12 8; целостность прогноза T8/T7 4; идемпотентность 2; frozen-семантика 3; порог/решения 7; D12-адаптер 4; API 9; статкаталоги 5). doclog0-8 все сюиты 529/529. Полный tests/api дельта-0 vs чистая база 3634052 (git-stash/res): 31F/2725P/42S = 2662P (база) + 63 (ровно корпус DOCLOG-8); FAILED-ID — ровно 31 предсуществующих средовых (forecasting-session 16, progress_audit_5b/psycopg-DSN 7, profile 2, structural-breaks 1, modeling-workflow/neural/candidates 3, progress_panel 1, upload-duckdb 1), doclog в failed отсутствуют. Jest полный 2365/2365 (вкл. doclog8-monitoring-ui 7/7, doclog6-lifecycle-ui 15/15, adminLogs 9/9). typecheck:all ✓. Сборка: import apps.api.main OK — 216 маршрутов (7 /v1/documentation/.../monitoring/*), миграции 14/85, DOCUMENT_KINDS=12, AUDIT_ACTIONS=24.

## Честные границы

- График (chart) для D12 — будущий срез: панель даёт таблицу+агрегаты; ChartSpec-рендер сверок не входит в поставку (§6 D12 «таблица и график» — таблица реализована).
- Регистрация actuals — source_kind="manual" (API с provenance); автоматическая привязка факта из нового upload-артефакта (source_kind="artifact") — интерфейс зарезервирован (source_ref), валидация приёма артефактов — будущий срез.
- Drift-метрики (распределение ошибок по времени/сущностям) — только агрегаты текущего винтажа; продвинутый drift-анализ — будущий срез (§6 D12 упоминает drift и решение: решение реализовано, drift — агрегаты + порог).
- Живой Postgres-прогон миграции 0014 — при следующем durable-срезе (прецедент 0013/AUDIT-6A).
- Метрики ограничены честными базовыми (MAE/bias/MAPE/MASE/coverage); RMSSE/WAPE и сравнение винтажей между собой (revision diff сверок) — будущие срезы; сравнение доступно через diff ревизий D12-документов (DOCLOG-6 diff).
- Экспорт D12 (JSON/CSV/XLSX/PDF) идёт через общий rendition-конвейер DOCLOG-5 (claims-based); построчная таблица пар — в JSON-рендиции через claims и через API сверок.

Без commit/push (AGENTS.md). Манифест sha256 не ведётся (указание тимлида, прецедент DOCLOG-2-FIX/3/4/5/6).
