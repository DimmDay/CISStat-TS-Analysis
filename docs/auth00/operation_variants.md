# AUTH-00 — семантика aliases и параметризованных операций

База `962ccda`. Этот реестр уточняет HTTP-карту; он не является capability
allowlist AUTH-01 и не разрешает операции пользователям. Полные пути и evidence
даны в [inventory.json](inventory.json). В HTTP-методе и имени path недостаточно
сведений о вычислительной стоимости, виде данных или требуемом праве.

| Входы / selector | Canonical operation / существенная семантика | Требование будущего admission |
|---|---|---|
| POST models/backtest, internal/models/backtest, session/modeling/backtest | modeling.backtest; submitted/synthetic/session data отличаются; model_id задаёт baseline/advanced вариант | Model allowlist + точный BacktestPlan/folds/horizon/rows; один capability/budget coordinator для всех mirrors |
| POST models/candidates, internal/models/candidates, session/modeling/candidates | modeling.candidates; не автоматически «custom train» | Прозрачный baseline vs advanced permission; не открывать чужую session |
| POST models/diagnostics, internal/models/diagnostics, session/modeling/diagnostics | modeling.diagnostics; existing backtest/card freshness и variant context | Та же object/version/capability authority; `ensure` также может создавать результат |
| POST models/tune, session/modeling/tune | modeling.tune; grid/trials и folds определяют стоимость | Demo/starter не получают tuning через baseline permission |
| POST session/modeling/jobs/start | modeling.tune.start; ModelingJobStartRequest.operation = Literal["tuning"] | Это tuning, а не generic baseline job; reserve до создания work plan/job |
| POST jobs/{job_id}/step, GET jobs/{job_id}, POST jobs/{job_id}/cancel | modeling.tune.step/status/cancel на сохранённой tuning operation | Session ownership недостаточно: текущий grant/capability/revoke, fencing и разрешение polling/result |
| POST session/modeling/tuning/start и /step | Совместимый persisted tuning path, тот же semantic family | Нельзя закрыть только новый /jobs и оставить старый /tuning |
| POST /v1/models/train | modeling.train.placeholder; реального fit нет, только accepted response; body отражает сырой principal_id ENV key | Не выдавать за реализованный custom training; убрать secret из DTO в AUTH-03 |
| GET session/modeling/context/state/feature-regressors/card; POST card/select/compare | Сессионные scientific artifacts и решения, часть GET может подготавливать/мигрировать state | Account object/version + stage; решение аналитика не равно выполнению науки |
| POST forecast, panel/forecast, forecast/{id}/sensitivity | forecasting create/panel/sensitivity — разные compute bounds | Horizon/series/model/returns/ensemble normalizing, fitting/revoke и reservation, не только просмотр карты |
| GET forecast/{id}/export.csv и export.json, POST forecast/{id}/trace | Output и observation, формат не новое право на чужой прогноз | Re-authorize saved object; trace POST не доказывает реальную доставку/право |
| POST public/internal upload/db/test и /load | upload.db.probe/load; remote DB и local SQLite/DuckDB — разные trust inputs | AuthN и egress/local-file policy **до probe**, а для load ещё размер/analysis/reservation |
| POST public/internal upload; POST session/demo | upload.file.load / upload.demo_dataset.load; demo path загружает dataset, не выполняет forum enter | Общий upload/analysis context; Auth DemoGrant выдаётся будущим AuthN сервисом |
| GET session/dataset/eda-* и preprocessing/*profile | Наука/ресурсные операции могут выполняться в GET и создавать frozen visual result | Не трактовать GET как бесплатную read-only операцию; учитывать method/algorithm/params и существующие bounds |
| GET progress/runs/{id}/restore | Новая session, cookie, чтение сохранённого файла и наследование доказанного owner | Mutating command + CSRF; не auto-claim по ID; отдельно сохранять uniform object deny |
| POST documentation/revisions/{id}/renditions с format/org_profile_id | Один HTTP endpoint: P0 sync и heavy queued rendering, org profile/signature variants | Format/profile permission, snapshot/object gate и atomic admission до queue; повторный guard worker/output |
| GET/POST documentation monitoring | Служебные actuals/comparisons/decisions в документировании | Не application `monitoring` из restricted_stage_ids; сохранить run policy |
| GET session/tasks/causes и UI /tasks/causes | application.causes.inspect, stage_namespace=application, stage=causal; fold importance available, SHAP/PDP/Granger могут быть not_computed | Application entitlement по canonical stage; EDA Granger остаётся scientific `eda` |
| UI /tasks/scenarios, /tasks/decisions, /tasks/monitoring | Canonical restricted stages scenario/decision/monitoring; сейчас placeholder pages | Навигационный href не доказывает доступность вычисления; future API получает тот же stage gate |
| POST session/stage/{stage}, progress/*-checks, forecast trace | Смена статуса/наблюдение, не доказательство аутентификации или научного результата | Валидировать известный stage/operation и право записи; клиент не выпускает себе permission/usage credit |
| Public/internal PATCH rules/update | Module-global in-memory override по template_id, не Account-scoped state | Scope данных/права до миграции; не путать с записью YAML или личной настройкой Account |

Идентификаторы источников: `modeling_session.ModelingJobStartRequest`,
`modeling_session.start_modeling_job/step_modeling_job/start_modeling_tuning`,
`models.train_model`, `forecasting_session`, `document_jobs.request_rendition`,
`tasks_session.get_tasks_causes`, `session.set_stage`, `public.update_rules`.
SHA fingerprints этих исходников уже входят в inventory. Версии моделей,
runtime readiness и конечные compute coefficients определяются AUTH-01/14,
не подставляются в AUTH-00 из названия метода.
