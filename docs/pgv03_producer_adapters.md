# PGV-03 — Producer adapters (документ поставки)

**Дата:** 28 октября 2026. **База:** `main@2f412d6` (PGV-02; клон, рабочее дерево синхронизировано до HEAD). **Статус:** producer-адаптеры — фиксация print-input (VisualResult/1) в момент выдачи фактического ответа научной остановки; reader/renderer/jobs/UI не реализованы. **Родительский контракт:** `spec_documentation_logging.md` §19 (аддитивная строка PGV-03). **Проектная спека:** `spec_passport_graphics_visual.md` §6/§13 (строка PGV-03), §14 (приёмочные сценарии).

---

## 1. Назначение и границы

PGV-03 замыкает durable-слой PGV-02 на **producer'ов**: научные остановки фиксируют print-input (VisualResult/1) в момент выдачи фактического ответа. Критерий готовности по spec §13 — «**Freeze сохранённого реального response, CAS версии, export не пересчитывает science**».

Два момента фиксации (§6):

1. **producer_freeze** — в момент выдачи ответа обработчиком (тот же контракт best-effort, что у `notify_validation_result`, прецедент C03): 48 research-view во всех семи остановках.
2. **producer_first_export** — первый explicit export ещё доступного проверенного результата (`freeze_saved_visual`): морозится **СОХРАНЁННЫЙ** ответ по result_ref из кэша, без пересчёта науки (renderer не вызывает GET для повторной науки), с обязательным CAS против текущего состояния запуска.

**Границы поставки (честно):** (1) 20 pgv-03 view из 68 — честный недобор `UNWIRED_PGV03_VIEWS` (preprocessing variance/spectral/feature_eng/scaling/stationarity/regularity/decomposition, modeling workflow/traceability/panel/diagnostics, forecasting comparison/sensitivity/accuracy/monitoring) — добираются PGV-10/11/12 вместе с UI-вэндингом; (2) navigator/static_demo (16 сайтов) — «статическое демо маркируется и не становится результатом исследования» (§1) — отдельная честная категория без freeze; (3) passport.panel/comparison — PGV-04/13, legacy_png — PGV-12; (4) POST /visuals-роутеры (§11) — PGV-13/15; API-слой экспорта здесь — `freeze_saved_visual` как субстрат; (5) PrintSnapshot/чекпоинты — PGV-04/13.

## 2. Состав поставки (файлы)

| Файл | Роль |
|---|---|
| `apps/api/visual_producers.py` | **НОВЫЙ** (~1400 строк): единый слой producer-адаптеров — резолв сайтов реестра PGV-00 по `source_adapter pgv-03/*` с честными guard'ами скоупа; 48 `ADAPTER_SPECS` (срез ответа → payload.data, units, sampling); `UNWIRED_PGV03_VIEWS` (честный недобор) + `static_demo_view_ids` (демо-категория); детерминированный `visual_result_ref(params, response)`; кэш сохранённых ответов (LRU 256, process-local) `save/get_visual_response`; `build_visual_result_payload` (зеркало правил PGV-01); `freeze_visual_from_response` (CAS по явным expected_*) и `freeze_saved_visual` (producer_first_export, CAS против текущего run-состояния) |
| `apps/api/promotion_integration.py` | `notify_visual_result` — единая best-effort точка (save → per-view freeze → X-Visual-* заголовки; сбой → durable-receipt, ответ не ломается); `freeze_visual_result_best_effort`; `_sweep_modeling_visuals` — добор visual_result бэктестов в существующей sweep-точке `notify_modeling_artifacts_updated` (counts + `visual_result`) |
| `apps/api/routers/session.py` | Wiring 23 обработчиков: upload (dataset/timeseries/decomposition ×2/distribution/structure/stats), validation (validate → 10 видов), preprocessing (missing ×3, outlier ×2, smoothing), EDA (correlation/IH ×3/seasonality/stationarity/distribution/breaks/features ×2/strategy/matrix); пустой distribution честно морозится (§10.1 «meaningful empty result») |
| `apps/api/routers/tasks_session.py` | Wiring GET /causes: fold_importance морозится ТОЛЬКО при available-методе (not_computed не фабрикуется — §9.1); + импорт `_promotion` |
| `apps/api/routers/forecasting_session.py` | Wiring POST /forecast → forecasting.forecast.chart (origin/horizon/alpha — trusted параметры) |
| `apps/api/routers/modeling_session.py` | Wiring POST /panel/forecast → panel_chart + panel_table (панели отдельно от single-series, AC14) |
| `tests/api/test_pgv03_producer_adapters.py` | **НОВЫЙ**: 63 теста (7 классов) — реестр/паритет, result_ref/кэш, payload из реальных ответов, freeze/CAS/идемпотентность, export из кэша после утраты сессии, wiring штатным HTTP-потоком (TestClient), sweep/Tasks |
| `tests/api/test_doclog3_telemetry_audit.py`, `test_doclog7_logs_support.py`, `test_doclog9_profiles.py` | Честное обновление устаревших пинов миграций (15→16 файлов, 93→96 statements, последний 0016) — пины остались от PGV-02 на 2f412d6, прецедент DOCLOG-9 |
| `spec_documentation_logging.md` | §19: аддитивная строка PGV-03 |
| `docs/pgv03_producer_adapters.md` | Этот документ |
| `worklog/worklog12.md` | Запись Task ID: PGV-03 |

## 3. Проектные решения

### 3.1. Один слой адаптеров; реестр — источник истины

`producer_view_ids()` выводится из реестра PGV-00 (source_adapter `pgv-03/*` И applicability ≠ static_demo): 68 research-сайтов. Каждый — либо wired (48, `ADAPTER_SPECS`), либо в `UNWIRED_PGV03_VIEWS` (20, добирающая задача PGV-10/11/12 в тексте ошибки). Тест-паритет гарантирует: wired ∪ unwired = все, пересечение пусто, молчаливых пропусков нет (§3.6 «неполнота маркируется»). Спеки соответствуют реестру по module_id/renderer_kind (mixed → первичный kind — явный выбор адаптера; validator VisualResult принимает только базовые kinds).

### 3.2. result_ref и кэш сохранённых ответов (lazy transfer §6)

`visual_result_ref = vr-<sha256[:32]>{params, response}` — детерминированный токен результата: те же данные+selection → тот же ref (идемпотентность §11); zoom/окно/новая ревизия данных → другой ref → НОВЫЙ immutable артефакт (AC08: sampling/aggregation/zoom различаются явно; §8: старые не переписываются). Ответ сохраняется в LRU-кэш (256 записей, process-local) с контекстом момента (run/session/context_id/data_revision/computed_at) — субстрат переноса «из фактического response в durable слой» (§6). Снимок изолируется ГЛУБОКОЙ копией (PGV-03-FIX, F-P3C3): пост-мутация источника не меняет сохранённое и замороженное. Вытеснение — честная `VisualSourceUnavailable` (§11 source_unavailable), пересчёт науки запрещён.

### 3.3. Payload по зеркалу PGV-01 — честность данных

`build_visual_result_payload`: payload.data — явный срез ответа (серия/таблица/матрица/карточки); digest = sha256(canonical(data)) — не выдумывается; неканонический срез (NaN) — честный отказ, ничего не регистрируется. Units — value XOR явная причина: сырые ряды → `legacy_unknown`, counts/статистики → `dimensionless`, rates → `percent`, ACF (лаги + коэффициенты) → две декларации. Sampling — из РЕАЛЬНЫХ полей ответа: `scatter_sampled`/LTTB → downsampled+point_cap=len(series), start/end → windowed+point_cap, таблицы → full. Trusted-параметры — только allowlisted view_params реестра (start/end влияют на sampling, но не попадают в параметры scatter-вида — честное следствие allowlist). `computed_at` — от обработчика; None → `producer_not_reported` (время вызова не подставляется — missing_date-семантика). Wiring-канал (`notify_visual_result`) передаёт время КАК ЕСТЬ (PGV-03-FIX, F-P3C2): None честно доходит и до кэш-записи, и до payload — один ответ несёт одно время фиксации; сообщённое время едино для обеих записей.

### 3.4. CAS: где какой (AC07)

- **producer_freeze** (в обработчике): фиксация текущего durable-состояния — сессия и запуск согласованы в момент ответа; явные expected_* проверяются против run (расхождение → `PrintContextConflict` → 409, НИЧЕГО не зарегистрировано).
- **producer_first_export** (`freeze_saved_visual`): CAS ВСЕГДА сверяет контекст сохранённого ответа с текущим run-состоянием — смена данных между показом и export → 409 context_changed; клиент выбирает обновление или уже сохранённую (замороженную при фиксации) версию. Именно здесь «CAS версии» критерия. «ВСЕГДА» ENFORCED (PGV-03-FIX, F-P3C1): сверка возможна только при ПОЛНОМ снимке контекста момента — деградировавший снимок не даёт доказательства неизменности durable-состояния и отвергается fail-closed (НЕ тихий пропуск сверки, класс F-P2C2, прецедент PGV-02-FIX): пустой снимок (оба измерения неизвестны) → честный `VisualSourceUnavailable`; частичный → `PrintContextConflict` (409); НИЧЕГО не регистрируется.

### 3.5. «Наука первична» — best-effort с durable-receipt

`notify_visual_result` — прецедент `notify_validation_result` (C03): ответ сохраняется, каждый view морозится независимо; ЛЮБОЙ сбой — `artifact_promotion_failed`-receipt (класс стандартного аудита), HTTP-ответ не меняется. Тест-оракул: monkeypatch-сбой freeze → ответ жив. Сессия без run_id — честный пропуск без артефактов. Ответ несёт `X-Visual-Result-Ref/Context-Id/Data-Revision` (§6 «Response содержит result_ref/context/version token»).

### 3.6. Sweep modeling: добор без науки

`_sweep_modeling_visuals` встроен в существующую точку `notify_modeling_artifacts_updated` (6 call-сайтов): visual_result comparison/oof строятся из УЖЕ зафиксированных `session.modeling_artifacts['backtests']` (форма BacktestResponse.model_dump — та же, что продвигает DOCLOG-1). Идемпотентность producer_key — повтор sweep no-op.

## 4. Приёмочные сценарии (покрытие поставки)

| AC | Покрытие |
|---|---|
| PGV-AC01 | 6 видов distribution из одного ответа — раздельные срезы (scatter ≠ histogram ≠ kde; upload == eda.descriptive общий срез) — тест `test_distribution_freezes_six_views` |
| PGV-AC05 | Метаданные не теряются: units/sampling/method/context/revision в payload; знаменатели validation/missing — тесты `test_validation_table_*`, `test_validate_freezes_ten_check_views` |
| PGV-AC06 | Export из кэша после `reset_session_store` — без DataFrame/SessionStore; сбои freeze не ломают ответ; тесты `test_export_freezes_saved_response_after_session_loss`, `test_promotion_failure_does_not_break_response` |
| PGV-AC07 | CAS: явные expected_* при producer_freeze; обязательный CAS при export из кэша (смена ревизии → 409, ничего не зарегистрировано) — тесты `test_cas_*`, `test_export_cas_conflict_after_data_change` |
| PGV-AC08 | LTTB → downsampled+point_cap; zoom → windowed; смена params → другой result_ref; скрытого detail upgrade нет — тесты `test_scatter_payload_*`, `test_zoom_params_*`, `test_result_ref_differs_by_params` |
| PGV-AC14 | Панельные виды отдельно (panel_chart/panel_table из panel-выпуска; entity None в параметрах) — wiring modeling_session |
| PGV-AC22 | Наука не вызывалась из freeze: адаптеры — чистые срезы; science runtime не менялся (221 маршрут, index.ts не тронут) |
| PGV-AC11/12 (частично) | not_computed fold_importance не фабрикуется — тест `test_tasks_causes_not_computed_is_not_fabricated` |

## 5. TDD-протокол

**RED:** 61 тест собран, честный import-RED (модуля нет). **GREEN:** в процессе пойманы и честно исправлены: (1) реестр — navigator-сайты несут `pgv-03/navigator_demo` → введена третья честная категория `static_demo_view_ids` (исключены из research-скоупа, freeze запрещён); (2) `_units_unknown` без аргумента (receipt показал сигнал); (3) контекст сессии — вычисляемый `current_context_id()`, а не константа → добавлен `_sync_run_to_session` (зеркалирование, контракт record_run_event); (4) семантика ошибок export — резолв view до lookup кэша; (5) computed_at сохранённого ответа — момент фиксации. Три оракула уточнены по факту честной семантики (units ACF — две декларации; trusted-параметры без start/end; items вместо rows). **Регресс:** pgv02+recheck 69 passed; doclog1/2/4/5/6/8/9+research_runs — устранены 3 устаревших пина миграций (предсуществующие на 2f412d6, честное обновление); upload/EDA/tasks 107 passed; doclog0/3/7+session_store 376 passed.

## 6. Верификация

Сюита PGV-03: **63/63 GREEN**. `py_compile` 10 файлов OK; `import apps.api.main` OK — 221 маршрут (наука не менялась); `git diff --check` PASS. Предсуществующие lacуны окружения (зафиксированы на чистом 2f412d6): 2 падения EDA (нет `psycopg`), 20 падений heavy modeling/forecasting — идентичны до и после диффа. Jest не гонялся: дифф не трогает packages/ui. Браузерная/docker приёмка неприменима (runtime UI/контейнеров не менялся).

## 7. Честные границы

(1) 20 pgv-03 view — честный недобор PGV-10/11/12 (заявлены `UNWIRED_PGV03_VIEWS`, resolve даёт ошибку с именем добирающей задачи). (2) Кэш сохранённых ответов process-local: после рестарта процесса export по старому ref — честный `source_unavailable`; повторный GET пересоздаёт фиксацию идемпотентно; durable-альтернатива — артефакт, замороженный при фиксации. (3) POST /visuals / GET /visual-sources-роутеры (§11) — PGV-13/15; `freeze_saved_visual` — их субстрат. (4) PrintSnapshot-сборка (зависимость от visual_result) — PGV-13. (5) PassportCheckpoint-фиксация в handoff-точках — PGV-04 (модуль-валидатор готов). (6) Postgres-путь паритетен Memory (тот же registry-контракт); живой Postgres-прогон — в контуре CERT.

## 8. PGV-03-FIX — исправление находок сертификации (2026-10-28)

Закрытие находок акта `docs/cert_pgv03_2026-10-28.md` (§7) по плану §8; Class B оракулы корпуса сертификации стали GREEN без правки их смысла.

| Находка | Исправление | Ключевые тесты |
|---|---|---|
| **F-P3C1** (средняя; класс F-P2C2) — «CAS ВСЕГДА» экспорта не enforced: деградировавший снимок контекста отключал сверку целиком | `freeze_saved_visual` отвергает неполный снимок fail-closed ДО обращения к durable-слою: пустой снимок (context_id и data_revision неизвестны) → честный `VisualSourceUnavailable`; частичный → `PrintContextConflict` (409 context_changed); НИЧЕГО не регистрируется. Полный снимок — штатная сверка PGV-02 по обоим измерениям | Class B ×2; repo-сюита: `test_partial_snapshot_context_degraded_conflicts`, `test_partial_snapshot_revision_degraded_conflicts`, `test_empty_snapshot_is_source_unavailable`, `test_full_snapshot_context_move_still_conflicts` (пин ORACLE-ONLY M01 поднят в repo-канал) |
| **F-P3C2** (средняя) — wiring-канал подставлял wall-clock (`computed_at or _now_iso()` ×2) вместо честной `producer_not_reported`, now₁ ≠ now₂ | `notify_visual_result` передаёт `computed_at` КАК ЕСТЬ и в кэш, и в freeze (двойная подстановка устранена, время едино); контракт `save_visual_response` разведён честно: аргумент не передан (прямой вызов кэша) → момент сохранения; явный None → запись хранит None без подстановки | Class B ×2; repo-сюита: `test_notify_without_handler_time_reports_honest_reason`, `test_notify_with_reported_time_carries_it_everywhere`, `test_direct_cache_save_without_time_keeps_save_moment` |
| **F-P3C3** (низкая) — кэш хранил поверхностную копию (`dict(response)`) | Глубокая копия снимка (`copy.deepcopy`) для response и params до вычисления ref; сбой изоляции — честный пропуск кэша (в классе неканоничного содержимого) | Class B; repo-сюита: `test_post_save_mutation_does_not_change_saved_or_frozen` (ответ+params, кэш+заморозка+ref) |

Обновлены контрактные докстринги (`visual_producers.py` §3/§5 модуля, `save_visual_response`, `freeze_saved_visual`, `notify_visual_result`). Наблюдения акта N-P3C1–N-P3C4 остаются вне скоупа фикса (задокументированы в акте; ref-семантика — PGV-13).

**Верификация фикса:** Class B корпуса сертификации 5/5 GREEN (смысл оракулов не правился); Class A 315 GREEN ×2 (детерминизм); repo-сюита 71/71 (63 + 8 новых); полный `tests/api` — дельта-0 против 857a516: FAILED-множество идентично (62, средовой класс «живой PostgreSQL»; единственное колебание ±1 — `test_doclog9_profiles::test_pdfa_render_markers_and_determinism` — проходит 3/3 изолированно на обеих сторонах, вне диффа); passed 2982 = 2956 (базлайн) + 18 (секция 9 PGV-02-FIX в дереве) + 8 (секция 8 этой поставки); `build_check.py` — py_compile OK, `import main` 221 маршрут (граница §13), doc-гварды GREEN; `git diff --check` PASS. Дифф вне packages/ui — Jest/typecheck не требуются (прецедент PGV-02-FIX/PGV-03-CERT).
