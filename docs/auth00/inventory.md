# AUTH-00 — route/operation inventory

База: `962ccda96c15aed5d1a6661364d8c50d8a301cbe`. Автоматически собранные входы + явная policy review.

**Observed — текущее поведение. Target — требования следующих AUTH-задач, не реализованные guards.**

Проверка: `python3 scripts/auth00/inventory.py --check`. Обновление после review: `--write`.

Источник истины и подробные evidence/dependencies/effects: [inventory.json](inventory.json).
Модель угроз: [threat_model.md](threat_model.md). Процесс и границы: [design.md](design.md).

| Вид | Число |
|---|---:|
| api | 217 |
| framework | 8 |
| internal_operation | 3 |
| legacy_authority | 1 |
| legacy_widget | 250 |
| page | 27 |
| proxy | 2 |
| renderer | 4 |
| static_asset | 1 |
| storage | 6 |
| task_alias | 4 |
| transport | 2 |
| worker | 6 |

## Классификации

| Policy | Observed | Target | Follow-up |
|---|---|---|---|
| admin.key | Depends(require_admin_role), ENV API-key ADMIN; MFA browser session отсутствует. | Named platform-admin permission + fresh MFA + scoped action + mandatory audit where sensitive. | AUTH-03, AUTH-05, AUTH-07, AUTH-20 |
| api.key | Router Depends(require_api_key); ENV key registry, без общего can_use_api/CU gate. | Valid account-bound API credential + scopes + can_use_api + object/stage/atomic budgets. | AUTH-01, AUTH-03, AUTH-10, AUTH-11, AUTH-12 |
| api.model_key | get_current_principal + legacy can_train_models; candidates/backtest/diagnostics также под этим флагом. | Operation/model-aware split baseline/tune/custom, API/account scopes, atomic compute reservation. | AUTH-01, AUTH-03, AUTH-10, AUTH-11, AUTH-12 |
| browser.internal | Нет общей AuthN dependency; данные тела/исследовательская cookie не личный вход. | Unified authenticated context, object/stage/capability/grant checks; CSRF mutations; same direct-API policy. | AUTH-03, AUTH-06, AUTH-11, AUTH-12 |
| browser.session | AnalysisSession по cisstat_session_id; общей личной AuthN, Account/CU admission нет. | AuthSession отдельно от research pointer; account object policy + stage/grant/budget на каждом входе. | AUTH-03, AUTH-04, AUTH-06, AUTH-09, AUTH-11, AUTH-12 |
| cors.transport | CORS permits configured/dev origins and regex *.vercel.app with credentials; not access control. | Approved origins + CSRF/Origin/Fetch Metadata; direct API remains subject to AuthN/object gates. | AUTH-06, AUTH-11 |
| document.object | Document services apply subject/tenant/run/scopes/lifecycle decisions; surrogate subject still possible. | Same unified account-aware object authority for metadata, preview, content, jobs and lifecycle; no ID-as-permission. | AUTH-03, AUTH-09, AUTH-11, AUTH-13 |
| legacy.token | Legacy shared-token entry + session_state.authenticated gate; pre-auth form отдельно отмечена в resource/effects. Не личная Account authority. | Explicit isolation/decommission or migrate to common AuthN/object/capability/budget controls; no paid/demo bypass. | AUTH-03, AUTH-11, AUTH-20 |
| logs.scoped | Manual _principal_or_401 adapter + scopes/SupportGrant effective access; export/grants mandatory audit. | Unified AuthN without losing exact tenant/run/action pairs; admin MFA and support scope policy; secret-safe exports. | AUTH-03, AUTH-05, AUTH-07, AUTH-20 |
| ops.diagnostics | /health/ops без AuthN; безопасная проекция технического состояния. | Private ops/service или platform permission; не раскрывать конфигурацию/секреты. | AUTH-03, AUTH-20 |
| profile.policy | Subject resolver + OrgProfileService policy.admin and mandatory audit for create/retire. | Unified context + explicit policy admin permission/MFA; preserve tenant and mandatory transaction semantics. | AUTH-03, AUTH-05, AUTH-07, AUTH-20 |
| progress.session | Research session + существующие trace/delivery/mirror guards; не личная AuthN. | Unified account context; сохранить object/mirror проверки, ограничить admission/observations. | AUTH-03, AUTH-09, AUTH-11 |
| proxy.transport | First-party Next rewrite only; not AuthN, no signed context or CSRF BFF. | Forward allowlisted credentials over TLS; strip spoofed identity headers; server validation + CSRF/Origin. | AUTH-03, AUTH-06 |
| public.metadata | Открытые metadata/education endpoints; личная AuthN не заявлена. | Явный public allowlist; безопасная проекция, лимит ответа и throttle для compute. | AUTH-01, AUTH-11 |
| renderer.service | No HTTP credential check; intended isolated sandbox, body/timeout/concurrency and output constraints. | Private service boundary + authenticated authorized caller/operation context; revoke/budget before job start and output. | AUTH-03, AUTH-11, AUTH-13, AUTH-14 |
| run.object | resolve_request_subject + authorize_run_access; owner/tenant/unresolved continuity, ADMIN bypass. | Authenticated account context + current tenant/object permission; uniform 404; controlled legacy migration. | AUTH-03, AUTH-09, AUTH-11 |
| storage.internal | Internal file/object/DB operation; content hash/path/registry checks are not user authentication. | Reach only via authorized object service; trusted roots/keys, no direct filesystem mount or public object ACL. | AUTH-09, AUTH-11, AUTH-13, AUTH-20 |
| task.alias | Four UI application hrefs; causes has live backend data, other task views do not imply ready compute. | Canonical application-stage gate including aliases; scientific EDA Granger/DOCLOG monitoring are distinct. | AUTH-01, AUTH-11 |
| ui.admin | Only embedded /admin/progress exists; dashboard uses entered API-key in tab memory. | Named ADMIN+MFA and common admin UI in both shells; OWNER/analyst cannot elevate by URL. | AUTH-05, AUTH-06, AUTH-07 |
| ui.page | Page component/navigation/redirect, no common personal AuthN gate; UI is not an authority. | UI handles auth/denial/account switch; backend independently enforces operation policy. | AUTH-01, AUTH-06, AUTH-11 |
| worker.authority | In-process worker trusts queued durable work/admission; not a browser-authenticated request. | Service credential/context where remote; recheck account/grant/revoke/reservation/deadline, fence settle/publication. | AUTH-03, AUTH-12, AUTH-13, AUTH-16, AUTH-20 |

## api

| ID / метод и путь | Operation / stage | Policy / resource | Источник |
|---|---|---|---|
| api:GET:/health | apps.api.main:health / service:platform | public.metadata / request metadata | apps/api/main.py:262 |
| api:GET:/health/ops | apps.api.main:health_ops / service:platform | ops.diagnostics / safe ops projection | apps/api/main.py:267 |
| api:GET:/v1/documentation/documents/{document_id}/revisions | apps.api.routers.documentation:list_document_revisions / service:documentation | document.object / run/document/revision/rendition/job/profile | apps/api/routers/documentation.py:540 |
| api:GET:/v1/documentation/jobs/{job_id} | apps.api.routers.documentation:get_job / service:documentation | document.object / run/document/revision/rendition/job/profile | apps/api/routers/documentation.py:675 |
| api:GET:/v1/documentation/org-profiles | apps.api.routers.doc_profiles:list_org_profiles / service:documentation | document.object / run/document/revision/rendition/job/profile | apps/api/routers/doc_profiles.py:60 |
| api:GET:/v1/documentation/renditions/{rendition_id}/content | apps.api.routers.documentation:get_rendition_content / service:documentation | document.object / run/document/revision/rendition/job/profile | apps/api/routers/documentation.py:707 |
| api:GET:/v1/documentation/renditions/{rendition_id}/validations | apps.api.routers.doc_profiles:list_rendition_validations / service:documentation | document.object / run/document/revision/rendition/job/profile | apps/api/routers/doc_profiles.py:180 |
| api:GET:/v1/documentation/revisions/{revision_id} | apps.api.routers.documentation:get_revision / service:documentation | document.object / run/document/revision/rendition/job/profile | apps/api/routers/documentation.py:562 |
| api:GET:/v1/documentation/revisions/{revision_id}/diff | apps.api.routers.documentation:revision_diff / service:documentation | document.object / run/document/revision/rendition/job/profile | apps/api/routers/documentation.py:939 |
| api:GET:/v1/documentation/revisions/{revision_id}/lifecycle | apps.api.routers.documentation:revision_lifecycle / service:documentation | document.object / run/document/revision/rendition/job/profile | apps/api/routers/documentation.py:920 |
| api:GET:/v1/documentation/revisions/{revision_id}/preview | apps.api.routers.documentation:get_revision_preview / service:documentation | document.object / run/document/revision/rendition/job/profile | apps/api/routers/documentation.py:585 |
| api:GET:/v1/documentation/runs/{run_id}/documents | apps.api.routers.documentation:list_documents / service:documentation | document.object / run/document/revision/rendition/job/profile | apps/api/routers/documentation.py:392 |
| api:GET:/v1/documentation/runs/{run_id}/monitoring/actuals | apps.api.routers.monitoring:list_actuals / service:documentation | document.object / run/document/revision/rendition/job/profile | apps/api/routers/monitoring.py:145 |
| api:GET:/v1/documentation/runs/{run_id}/monitoring/comparisons | apps.api.routers.monitoring:list_comparisons / service:documentation | document.object / run/document/revision/rendition/job/profile | apps/api/routers/monitoring.py:189 |
| api:GET:/v1/documentation/runs/{run_id}/monitoring/comparisons/{comparison_id} | apps.api.routers.monitoring:get_comparison / service:documentation | document.object / run/document/revision/rendition/job/profile | apps/api/routers/monitoring.py:203 |
| api:GET:/v1/documentation/runs/{run_id}/monitoring/comparisons/{comparison_id}/decisions | apps.api.routers.monitoring:list_decisions / service:documentation | document.object / run/document/revision/rendition/job/profile | apps/api/routers/monitoring.py:246 |
| api:GET:/v1/internal/rules/load/{template_id} | apps.api.routers.internal:load_rules_template / scientific:validation | browser.internal / server rule template / module-global override (not Account scoped) | apps/api/routers/internal.py:115 |
| api:GET:/v1/internal/rules/templates | apps.api.routers.internal:get_rules_templates / scientific:validation | browser.internal / server rule template / module-global override (not Account scoped) | apps/api/routers/internal.py:110 |
| api:GET:/v1/knowledge/articles | apps.api.knowledge.router:get_articles / service:education | public.metadata / public knowledge registry | apps/api/knowledge/router.py:143 |
| api:GET:/v1/knowledge/glossary | apps.api.knowledge.router:get_glossary / service:education | public.metadata / public knowledge registry | apps/api/knowledge/router.py:203 |
| api:GET:/v1/logs/access | apps.api.routers.logs:get_log_access / service:observability | logs.scoped / audit/telemetry/delivery/support grant | apps/api/routers/logs.py:154 |
| api:GET:/v1/logs/audit | apps.api.routers.logs:get_audit_logs / service:observability | logs.scoped / audit/telemetry/delivery/support grant | apps/api/routers/logs.py:242 |
| api:GET:/v1/logs/delivery | apps.api.routers.logs:get_delivery_logs / service:observability | logs.scoped / audit/telemetry/delivery/support grant | apps/api/routers/logs.py:284 |
| api:GET:/v1/logs/grants | apps.api.routers.logs:list_grants / service:observability | logs.scoped / audit/telemetry/delivery/support grant | apps/api/routers/logs.py:428 |
| api:GET:/v1/logs/telemetry | apps.api.routers.logs:get_telemetry_logs / service:observability | logs.scoped / audit/telemetry/delivery/support grant | apps/api/routers/logs.py:200 |
| api:GET:/v1/progress/admin/case-bank/candidates | apps.api.routers.progress:get_case_bank_candidates / service:observability | admin.key / admin cross-run projection | apps/api/routers/progress.py:2545 |
| api:GET:/v1/progress/admin/overview | apps.api.routers.progress:get_admin_overview / service:observability | admin.key / admin cross-run projection | apps/api/routers/progress.py:2497 |
| api:GET:/v1/progress/runs/{run_id} | apps.api.routers.progress:get_run_detail / service:platform | run.object / run/checkpoint/delivery/report | apps/api/routers/progress.py:1281 |
| api:GET:/v1/progress/runs/{run_id}/delivery | apps.api.routers.progress:list_run_delivery / service:platform | run.object / run/checkpoint/delivery/report | apps/api/routers/progress.py:1780 |
| api:GET:/v1/progress/runs/{run_id}/delivery/{operation_id} | apps.api.routers.progress:get_operation_delivery / service:platform | run.object / run/checkpoint/delivery/report | apps/api/routers/progress.py:1817 |
| api:GET:/v1/progress/runs/{run_id}/mentor/next-step | apps.api.routers.progress:get_mentor_next_step / service:platform | run.object / run/checkpoint/delivery/report | apps/api/routers/progress.py:2160 |
| api:GET:/v1/progress/runs/{run_id}/report | apps.api.routers.progress:get_run_report / service:platform | run.object / run/checkpoint/delivery/report | apps/api/routers/progress.py:2261 |
| api:GET:/v1/progress/runs/{run_id}/restore | apps.api.routers.progress:restore_run / service:platform | run.object / run/checkpoint/delivery/report | apps/api/routers/progress.py:1506 |
| api:GET:/v1/progress/trace | apps.api.routers.progress:get_progress_trace / service:platform | progress.session / session-bound trace/observation | apps/api/routers/progress.py:391 |
| api:GET:/v1/public/rules/load/{template_id} | apps.api.routers.public:load_rules_template / scientific:validation | api.key / server rule template / module-global override (not Account scoped) | apps/api/routers/public.py:105 |
| api:GET:/v1/public/rules/templates | apps.api.routers.public:get_rules_templates / scientific:validation | api.key / server rule template / module-global override (not Account scoped) | apps/api/routers/public.py:99 |
| api:GET:/v1/session/current | apps.api.routers.session:get_current_session / service:platform | browser.session / research session and dataset | apps/api/routers/session.py:592 |
| api:GET:/v1/session/dataset | apps.api.routers.session:get_session_dataset / service:platform | browser.session / research session and dataset | apps/api/routers/session.py:661 |
| api:GET:/v1/session/dataset/consistency-profile | apps.api.routers.session:get_dataset_consistency_profile / scientific:validation | browser.session / research session and dataset | apps/api/routers/session.py:4746 |
| api:GET:/v1/session/dataset/decomposition | apps.api.routers.session:get_dataset_decomposition / scientific:upload | browser.session / research session and dataset | apps/api/routers/session.py:1797 |
| api:GET:/v1/session/dataset/decomposition-series | apps.api.routers.session:get_dataset_decomposition_series / scientific:upload | browser.session / research session and dataset | apps/api/routers/session.py:1837 |
| api:GET:/v1/session/dataset/derived-columns | apps.api.routers.session:get_dataset_derived_columns / scientific:upload | browser.session / research session and dataset | apps/api/routers/session.py:759 |
| api:GET:/v1/session/dataset/distribution | apps.api.routers.session:get_dataset_distribution / scientific:upload | browser.session / research session and dataset | apps/api/routers/session.py:1566 |
| api:GET:/v1/session/dataset/eda-correlation | apps.api.routers.session:get_dataset_eda_correlation / scientific:eda | browser.session / research session and dataset | apps/api/routers/session.py:954 |
| api:GET:/v1/session/dataset/eda-distribution | apps.api.routers.session:get_dataset_eda_distribution / scientific:eda | browser.session / research session and dataset | apps/api/routers/session.py:1103 |
| api:GET:/v1/session/dataset/eda-feature-selection | apps.api.routers.session:get_dataset_eda_feature_selection / scientific:eda | browser.session / research session and dataset | apps/api/routers/session.py:1184 |
| api:GET:/v1/session/dataset/eda-ih | apps.api.routers.session:get_dataset_eda_ih / scientific:eda | browser.session / research session and dataset | apps/api/routers/session.py:987 |
| api:GET:/v1/session/dataset/eda-model-matrix | apps.api.routers.session:get_dataset_eda_model_matrix / scientific:eda | browser.session / research session and dataset | apps/api/routers/session.py:1262 |
| api:GET:/v1/session/dataset/eda-seasonality | apps.api.routers.session:get_dataset_eda_seasonality / scientific:eda | browser.session / research session and dataset | apps/api/routers/session.py:1029 |
| api:GET:/v1/session/dataset/eda-stationarity | apps.api.routers.session:get_dataset_eda_stationarity / scientific:eda | browser.session / research session and dataset | apps/api/routers/session.py:1066 |
| api:GET:/v1/session/dataset/eda-structural-breaks | apps.api.routers.session:get_dataset_eda_structural_breaks / scientific:eda | browser.session / research session and dataset | apps/api/routers/session.py:1140 |
| api:GET:/v1/session/dataset/eda-validation-strategy | apps.api.routers.session:get_dataset_eda_validation_strategy / scientific:eda | browser.session / research session and dataset | apps/api/routers/session.py:1216 |
| api:GET:/v1/session/dataset/format-profile | apps.api.routers.session:get_dataset_format_profile / scientific:validation | browser.session / research session and dataset | apps/api/routers/session.py:2203 |
| api:GET:/v1/session/dataset/inclusion-profile | apps.api.routers.session:get_dataset_inclusion_profile / scientific:validation | browser.session / research session and dataset | apps/api/routers/session.py:3437 |
| api:GET:/v1/session/dataset/missing-correlation | apps.api.routers.session:get_dataset_missing_correlation / scientific:upload | browser.session / research session and dataset | apps/api/routers/session.py:2510 |
| api:GET:/v1/session/dataset/missing-distribution | apps.api.routers.session:get_dataset_missing_distribution / scientific:upload | browser.session / research session and dataset | apps/api/routers/session.py:2530 |
| api:GET:/v1/session/dataset/missing-editor-rows | apps.api.routers.session:get_dataset_missing_editor_rows / scientific:upload | browser.session / research session and dataset | apps/api/routers/session.py:2650 |
| api:GET:/v1/session/dataset/missing-matrix | apps.api.routers.session:get_dataset_missing_matrix / scientific:upload | browser.session / research session and dataset | apps/api/routers/session.py:2487 |
| api:GET:/v1/session/dataset/missing-profile | apps.api.routers.session:get_dataset_missing_profile / scientific:validation | browser.session / research session and dataset | apps/api/routers/session.py:2380 |
| api:GET:/v1/session/dataset/outlier-boxplot | apps.api.routers.session:get_dataset_outlier_boxplot / scientific:upload | browser.session / research session and dataset | apps/api/routers/session.py:3403 |
| api:GET:/v1/session/dataset/outlier-density | apps.api.routers.session:get_dataset_outlier_density / scientific:upload | browser.session / research session and dataset | apps/api/routers/session.py:3386 |
| api:GET:/v1/session/dataset/outlier-editor-rows | apps.api.routers.session:get_dataset_outlier_editor_rows / scientific:upload | browser.session / research session and dataset | apps/api/routers/session.py:2885 |
| api:GET:/v1/session/dataset/outlier-histogram | apps.api.routers.session:get_dataset_outlier_histogram / scientific:upload | browser.session / research session and dataset | apps/api/routers/session.py:3353 |
| api:GET:/v1/session/dataset/outlier-line | apps.api.routers.session:get_dataset_outlier_line / scientific:upload | browser.session / research session and dataset | apps/api/routers/session.py:3304 |
| api:GET:/v1/session/dataset/outlier-profile | apps.api.routers.session:get_dataset_outlier_profile / scientific:validation | browser.session / research session and dataset | apps/api/routers/session.py:3103 |
| api:GET:/v1/session/dataset/panel-balance | apps.api.routers.session:get_panel_balance / scientific:upload | browser.session / research session and dataset | apps/api/routers/session.py:1302 |
| api:GET:/v1/session/dataset/passport/compare | apps.api.routers.session:compare_dataset_passports / scientific:upload | browser.session / research session and dataset | apps/api/routers/session.py:5884 |
| api:GET:/v1/session/dataset/passport/status | apps.api.routers.session:get_dataset_passport_status / scientific:upload | browser.session / research session and dataset | apps/api/routers/session.py:5840 |
| api:GET:/v1/session/dataset/preprocessing-check-modes | apps.api.routers.session:get_dataset_preprocessing_check_modes / scientific:preprocessing | browser.session / research session and dataset | apps/api/routers/session.py:2434 |
| api:GET:/v1/session/dataset/preprocessing/decomposition-profile | apps.api.routers.session:get_dataset_preprocessing_decomposition_profile / scientific:preprocessing | browser.session / research session and dataset | apps/api/routers/session.py:3927 |
| api:GET:/v1/session/dataset/preprocessing/feature-generation-profile | apps.api.routers.session:get_dataset_preprocessing_feature_generation_profile / scientific:preprocessing | browser.session / research session and dataset | apps/api/routers/session.py:4454 |
| api:GET:/v1/session/dataset/preprocessing/regularity-intervals | apps.api.routers.session:get_dataset_preprocessing_regularity_intervals / scientific:preprocessing | browser.session / research session and dataset | apps/api/routers/session.py:3831 |
| api:GET:/v1/session/dataset/preprocessing/regularity-profile | apps.api.routers.session:get_dataset_preprocessing_regularity_profile / scientific:preprocessing | browser.session / research session and dataset | apps/api/routers/session.py:3797 |
| api:GET:/v1/session/dataset/preprocessing/regularity-timeline | apps.api.routers.session:get_dataset_preprocessing_regularity_timeline / scientific:preprocessing | browser.session / research session and dataset | apps/api/routers/session.py:3850 |
| api:GET:/v1/session/dataset/preprocessing/scaling-profile | apps.api.routers.session:get_dataset_preprocessing_scaling_profile / scientific:preprocessing | browser.session / research session and dataset | apps/api/routers/session.py:4569 |
| api:GET:/v1/session/dataset/preprocessing/smoothing-profile | apps.api.routers.session:get_dataset_preprocessing_smoothing_profile / scientific:preprocessing | browser.session / research session and dataset | apps/api/routers/session.py:4132 |
| api:GET:/v1/session/dataset/preprocessing/spectral-profile | apps.api.routers.session:get_dataset_preprocessing_spectral_profile / scientific:preprocessing | browser.session / research session and dataset | apps/api/routers/session.py:4370 |
| api:GET:/v1/session/dataset/preprocessing/stationarity-profile | apps.api.routers.session:get_dataset_preprocessing_stationarity_profile / scientific:preprocessing | browser.session / research session and dataset | apps/api/routers/session.py:4263 |
| api:GET:/v1/session/dataset/preprocessing/variance-profile | apps.api.routers.session:get_dataset_preprocessing_variance_profile / scientific:preprocessing | browser.session / research session and dataset | apps/api/routers/session.py:4038 |
| api:GET:/v1/session/dataset/range-profile | apps.api.routers.session:get_dataset_range_profile / scientific:validation | browser.session / research session and dataset | apps/api/routers/session.py:2293 |
| api:GET:/v1/session/dataset/referential-profile | apps.api.routers.session:get_dataset_referential_profile / scientific:validation | browser.session / research session and dataset | apps/api/routers/session.py:3524 |
| api:GET:/v1/session/dataset/regularity-profile | apps.api.routers.session:get_dataset_regularity_profile / scientific:validation | browser.session / research session and dataset | apps/api/routers/session.py:3711 |
| api:GET:/v1/session/dataset/rows | apps.api.routers.session:get_dataset_rows / scientific:upload | browser.session / research session and dataset | apps/api/routers/session.py:713 |
| api:GET:/v1/session/dataset/stats | apps.api.routers.session:get_dataset_stats / scientific:upload | browser.session / research session and dataset | apps/api/routers/session.py:893 |
| api:GET:/v1/session/dataset/structure-detection | apps.api.routers.session:get_structure_detection / scientific:upload | browser.session / research session and dataset | apps/api/routers/session.py:1687 |
| api:GET:/v1/session/dataset/sufficiency-profile | apps.api.routers.session:get_dataset_sufficiency_profile / scientific:validation | browser.session / research session and dataset | apps/api/routers/session.py:4643 |
| api:GET:/v1/session/dataset/text-quality-profile | apps.api.routers.session:get_dataset_text_quality_profile / scientific:validation | browser.session / research session and dataset | apps/api/routers/session.py:3618 |
| api:GET:/v1/session/dataset/timeseries | apps.api.routers.session:get_dataset_timeseries / scientific:upload | browser.session / research session and dataset | apps/api/routers/session.py:1750 |
| api:GET:/v1/session/dataset/uniqueness-profile | apps.api.routers.session:get_dataset_uniqueness_profile / scientific:validation | browser.session / research session and dataset | apps/api/routers/session.py:4837 |
| api:GET:/v1/session/dataset/validate | apps.api.routers.session:get_dataset_validate / scientific:upload | browser.session / research session and dataset | apps/api/routers/session.py:1919 |
| api:GET:/v1/session/dataset/validation-check-modes | apps.api.routers.session:get_dataset_validation_check_modes / scientific:validation | browser.session / research session and dataset | apps/api/routers/session.py:2152 |
| api:GET:/v1/session/dataset/validation-rules | apps.api.routers.session:get_dataset_validation_rules / scientific:validation | browser.session / research session and dataset | apps/api/routers/session.py:2141 |
| api:GET:/v1/session/date-column | apps.api.routers.session:get_date_column / service:platform | browser.session / research session and dataset | apps/api/routers/session.py:5666 |
| api:GET:/v1/session/modeling/card | apps.api.routers.modeling_session:list_model_cards / scientific:modeling | browser.session / session model/job/card/forecast | apps/api/routers/modeling_session.py:3320 |
| api:GET:/v1/session/modeling/card/{card_id} | apps.api.routers.modeling_session:get_model_card / scientific:modeling | browser.session / session model/job/card/forecast | apps/api/routers/modeling_session.py:3343 |
| api:GET:/v1/session/modeling/context | apps.api.routers.modeling_session:get_modeling_context / scientific:modeling | browser.session / session model/job/card/forecast | apps/api/routers/modeling_session.py:1032 |
| api:GET:/v1/session/modeling/feature-regressors | apps.api.routers.modeling_session:get_modeling_feature_regressors / scientific:modeling | browser.session / session model/job/card/forecast | apps/api/routers/modeling_session.py:1101 |
| api:GET:/v1/session/modeling/forecast | apps.api.routers.forecasting_session:list_forecasts / scientific:forecasting | browser.session / session model/job/card/forecast | apps/api/routers/forecasting_session.py:374 |
| api:GET:/v1/session/modeling/forecast/{forecast_id} | apps.api.routers.forecasting_session:get_forecast / scientific:forecasting | browser.session / session model/job/card/forecast | apps/api/routers/forecasting_session.py:382 |
| api:GET:/v1/session/modeling/forecast/{forecast_id}/export.csv | apps.api.routers.forecasting_session:export_forecast_csv / scientific:forecasting | browser.session / session model/job/card/forecast | apps/api/routers/forecasting_session.py:427 |
| api:GET:/v1/session/modeling/forecast/{forecast_id}/export.json | apps.api.routers.forecasting_session:export_forecast_json / scientific:forecasting | browser.session / session model/job/card/forecast | apps/api/routers/forecasting_session.py:440 |
| api:GET:/v1/session/modeling/jobs/{job_id} | apps.api.routers.modeling_session:get_modeling_job / scientific:modeling | browser.session / persisted tuning job/plan (operation Literal tuning), session context | apps/api/routers/modeling_session.py:2162 |
| api:GET:/v1/session/modeling/panel/candidates | apps.api.routers.modeling_session:panel_candidates / scientific:modeling | browser.session / session model/job/card/forecast | apps/api/routers/modeling_session.py:3591 |
| api:GET:/v1/session/modeling/state | apps.api.routers.modeling_session:get_modeling_state / scientific:modeling | browser.session / session model/job/card/forecast | apps/api/routers/modeling_session.py:1183 |
| api:GET:/v1/session/target-column | apps.api.routers.session:get_target_column / service:platform | browser.session / research session and dataset | apps/api/routers/session.py:5513 |
| api:GET:/v1/session/tasks/causes | apps.api.routers.tasks_session:get_tasks_causes / application:causal | browser.session / session Model Card and fold importance | apps/api/routers/tasks_session.py:221 |
| api:PATCH:/v1/internal/rules/update | apps.api.routers.internal:update_rules / scientific:validation | browser.internal / server rule template / module-global override (not Account scoped) | apps/api/routers/internal.py:169 |
| api:PATCH:/v1/public/rules/update | apps.api.routers.public:update_rules / scientific:validation | api.key / server rule template / module-global override (not Account scoped) | apps/api/routers/public.py:164 |
| api:POST:/v1/documentation/documents/{document_id}/retention | apps.api.routers.documentation:document_retention / service:documentation | document.object / run/document/revision/rendition/job/profile | apps/api/routers/documentation.py:962 |
| api:POST:/v1/documentation/jobs/{job_id}/cancel | apps.api.routers.documentation:cancel_job / service:documentation | document.object / run/document/revision/rendition/job/profile | apps/api/routers/documentation.py:688 |
| api:POST:/v1/documentation/org-profiles | apps.api.routers.doc_profiles:create_org_profile / service:documentation | profile.policy / run/document/revision/rendition/job/profile | apps/api/routers/doc_profiles.py:86 |
| api:POST:/v1/documentation/org-profiles/{profile_id}/retire | apps.api.routers.doc_profiles:retire_org_profile / service:documentation | profile.policy / run/document/revision/rendition/job/profile | apps/api/routers/doc_profiles.py:134 |
| api:POST:/v1/documentation/renditions/{rendition_id}/verify-signature | apps.api.routers.doc_profiles:verify_rendition_signature / service:documentation | document.object / run/document/revision/rendition/job/profile | apps/api/routers/doc_profiles.py:220 |
| api:POST:/v1/documentation/revisions/{revision_id}/approvals | apps.api.routers.documentation:revision_approvals / service:documentation | document.object / run/document/revision/rendition/job/profile | apps/api/routers/documentation.py:804 |
| api:POST:/v1/documentation/revisions/{revision_id}/publish | apps.api.routers.documentation:revision_publish / service:documentation | document.object / run/document/revision/rendition/job/profile | apps/api/routers/documentation.py:855 |
| api:POST:/v1/documentation/revisions/{revision_id}/renditions | apps.api.routers.documentation:request_rendition / service:documentation | document.object / run/document/revision/rendition/job/profile | apps/api/routers/documentation.py:623 |
| api:POST:/v1/documentation/revisions/{revision_id}/retract | apps.api.routers.documentation:revision_retract / service:documentation | document.object / run/document/revision/rendition/job/profile | apps/api/routers/documentation.py:888 |
| api:POST:/v1/documentation/runs/{run_id}/archive | apps.api.routers.documentation:archive_run / service:documentation | document.object / run/document/revision/rendition/job/profile | apps/api/routers/documentation.py:1003 |
| api:POST:/v1/documentation/runs/{run_id}/archive/verify | apps.api.routers.documentation:archive_verify / service:documentation | document.object / run/document/revision/rendition/job/profile | apps/api/routers/documentation.py:1019 |
| api:POST:/v1/documentation/runs/{run_id}/documents | apps.api.routers.documentation:create_document_draft / service:documentation | document.object / run/document/revision/rendition/job/profile | apps/api/routers/documentation.py:439 |
| api:POST:/v1/documentation/runs/{run_id}/monitoring/actuals | apps.api.routers.monitoring:register_actuals / service:documentation | document.object / run/document/revision/rendition/job/profile | apps/api/routers/monitoring.py:116 |
| api:POST:/v1/documentation/runs/{run_id}/monitoring/comparisons | apps.api.routers.monitoring:create_comparison / service:documentation | document.object / run/document/revision/rendition/job/profile | apps/api/routers/monitoring.py:162 |
| api:POST:/v1/documentation/runs/{run_id}/monitoring/comparisons/{comparison_id}/decisions | apps.api.routers.monitoring:create_decision / service:documentation | document.object / run/document/revision/rendition/job/profile | apps/api/routers/monitoring.py:219 |
| api:POST:/v1/documentation/runs/{run_id}/retention/sweep | apps.api.routers.documentation:retention_sweep / service:documentation | document.object / run/document/revision/rendition/job/profile | apps/api/routers/documentation.py:987 |
| api:POST:/v1/internal/models/backtest | apps.api.routers.internal:run_backtest_internal / scientific:modeling | browser.internal / submitted data / research session / rule namespace | apps/api/routers/internal.py:205 |
| api:POST:/v1/internal/models/candidates | apps.api.routers.internal:get_candidates_internal / scientific:modeling | browser.internal / submitted data / research session / rule namespace | apps/api/routers/internal.py:316 |
| api:POST:/v1/internal/models/diagnostics | apps.api.routers.diagnostics_internal:run_internal_diagnostics / scientific:modeling | browser.internal / submitted data / research session / rule namespace | apps/api/routers/diagnostics_internal.py:32 |
| api:POST:/v1/internal/passport | apps.api.routers.internal:get_passport / scientific:validation | browser.internal / submitted data / research session / rule namespace | apps/api/routers/internal.py:45 |
| api:POST:/v1/internal/regularity | apps.api.routers.internal:get_regularity / scientific:validation | browser.internal / submitted data / research session / rule namespace | apps/api/routers/internal.py:55 |
| api:POST:/v1/internal/rules/validate | apps.api.routers.internal:validate_with_rules / scientific:validation | browser.internal / server rule template / module-global override (not Account scoped) | apps/api/routers/internal.py:147 |
| api:POST:/v1/internal/upload | apps.api.routers.internal:upload_file / scientific:upload | browser.internal / submitted data / research session / rule namespace | apps/api/routers/internal.py:71 |
| api:POST:/v1/internal/upload/db/load | apps.api.routers.upload_db:_register.load_db_dataset / scientific:upload | browser.internal / submitted data / research session / rule namespace | apps/api/routers/upload_db.py:185 |
| api:POST:/v1/internal/upload/db/test | apps.api.routers.upload_db:_register.test_db_connection / scientific:upload | browser.internal / submitted data / research session / rule namespace | apps/api/routers/upload_db.py:149 |
| api:POST:/v1/learning/track | apps.api.knowledge.router:build_learning_track / service:education | public.metadata / public knowledge registry | apps/api/knowledge/router.py:228 |
| api:POST:/v1/logs/export | apps.api.routers.logs:export_logs_bundle / service:observability | logs.scoped / audit/telemetry/delivery/support grant | apps/api/routers/logs.py:328 |
| api:POST:/v1/logs/grants | apps.api.routers.logs:create_grant / service:observability | logs.scoped / audit/telemetry/delivery/support grant | apps/api/routers/logs.py:444 |
| api:POST:/v1/logs/grants/{grant_id}/revoke | apps.api.routers.logs:revoke_grant / service:observability | logs.scoped / audit/telemetry/delivery/support grant | apps/api/routers/logs.py:489 |
| api:POST:/v1/models/backtest | apps.api.routers.models:run_backtest / scientific:modeling | api.model_key / submitted/model dataset and model selection | apps/api/routers/models.py:623 |
| api:POST:/v1/models/candidates | apps.api.routers.models:get_candidates / scientific:modeling | api.model_key / submitted/model dataset and model selection | apps/api/routers/models.py:100 |
| api:POST:/v1/models/diagnostics | apps.api.routers.diagnostics:run_diagnostics / scientific:modeling | api.model_key / submitted/model dataset and model selection | apps/api/routers/diagnostics.py:204 |
| api:POST:/v1/models/train | apps.api.routers.models:train_model / scientific:modeling | api.model_key / placeholder accepted response; reflects raw ENV principal_id/API-key | apps/api/routers/models.py:713 |
| api:POST:/v1/models/tune | apps.api.routers.models:tune_model / scientific:modeling | api.model_key / submitted/model dataset and model selection | apps/api/routers/models.py:725 |
| api:POST:/v1/progress/eda-checks | apps.api.routers.progress:report_eda_checks / service:platform | progress.session / session-bound trace/observation | apps/api/routers/progress.py:946 |
| api:POST:/v1/progress/mentor/sanity-check | apps.api.routers.progress:run_mentor_sanity_check / service:platform | progress.session / session-bound trace/observation | apps/api/routers/progress.py:2341 |
| api:POST:/v1/progress/preprocessing-checks | apps.api.routers.progress:report_preprocessing_checks / service:platform | progress.session / session-bound trace/observation | apps/api/routers/progress.py:816 |
| api:POST:/v1/progress/runs/{run_id}/checkpoints | apps.api.routers.progress:create_checkpoint / service:platform | run.object / run/checkpoint/delivery/report | apps/api/routers/progress.py:1370 |
| api:POST:/v1/progress/runs/{run_id}/pause | apps.api.routers.progress:pause_run / service:platform | run.object / run/checkpoint/delivery/report | apps/api/routers/progress.py:1309 |
| api:POST:/v1/progress/runs/{run_id}/resume | apps.api.routers.progress:resume_run / service:platform | run.object / run/checkpoint/delivery/report | apps/api/routers/progress.py:1343 |
| api:POST:/v1/progress/upload-stops | apps.api.routers.progress:report_upload_stops / service:platform | progress.session / session-bound trace/observation | apps/api/routers/progress.py:589 |
| api:POST:/v1/progress/validation-checks | apps.api.routers.progress:report_validation_checks / service:platform | progress.session / session-bound trace/observation | apps/api/routers/progress.py:699 |
| api:POST:/v1/public/passport | apps.api.routers.public:get_passport / scientific:validation | api.key / submitted data / rule namespace | apps/api/routers/public.py:35 |
| api:POST:/v1/public/regularity | apps.api.routers.public:get_regularity / scientific:validation | api.key / submitted data / rule namespace | apps/api/routers/public.py:45 |
| api:POST:/v1/public/rules/validate | apps.api.routers.public:validate_with_rules / scientific:validation | api.key / server rule template / module-global override (not Account scoped) | apps/api/routers/public.py:140 |
| api:POST:/v1/public/upload | apps.api.routers.public:upload_file / scientific:upload | api.key / submitted data / rule namespace | apps/api/routers/public.py:180 |
| api:POST:/v1/public/upload/db/load | apps.api.routers.upload_db:_register.load_db_dataset / scientific:upload | api.key / submitted data / rule namespace | apps/api/routers/upload_db.py:185 |
| api:POST:/v1/public/upload/db/test | apps.api.routers.upload_db:_register.test_db_connection / scientific:upload | api.key / submitted data / rule namespace | apps/api/routers/upload_db.py:149 |
| api:POST:/v1/session/dataset/consistency-corrections | apps.api.routers.session:correct_dataset_consistency / scientific:validation | browser.session / research session and dataset | apps/api/routers/session.py:4766 |
| api:POST:/v1/session/dataset/convert-types | apps.api.routers.session:convert_dataset_types / scientific:validation | browser.session / research session and dataset | apps/api/routers/session.py:5356 |
| api:POST:/v1/session/dataset/derived-columns/delete | apps.api.routers.session:delete_dataset_derived_columns / scientific:upload | browser.session / research session and dataset | apps/api/routers/session.py:804 |
| api:POST:/v1/session/dataset/entity-filter | apps.api.routers.session:filter_dataset_by_entity / scientific:upload | browser.session / research session and dataset | apps/api/routers/session.py:1357 |
| api:POST:/v1/session/dataset/format-corrections | apps.api.routers.session:correct_dataset_formats / scientific:validation | browser.session / research session and dataset | apps/api/routers/session.py:2222 |
| api:POST:/v1/session/dataset/inclusion-corrections | apps.api.routers.session:correct_dataset_inclusion / scientific:validation | browser.session / research session and dataset | apps/api/routers/session.py:3453 |
| api:POST:/v1/session/dataset/missing-corrections | apps.api.routers.session:correct_dataset_missing / scientific:validation | browser.session / research session and dataset | apps/api/routers/session.py:2551 |
| api:POST:/v1/session/dataset/missing-manual-corrections | apps.api.routers.session:apply_dataset_missing_manual_corrections / scientific:validation | browser.session / research session and dataset | apps/api/routers/session.py:2723 |
| api:POST:/v1/session/dataset/outlier-corrections | apps.api.routers.session:correct_dataset_outliers / scientific:validation | browser.session / research session and dataset | apps/api/routers/session.py:3173 |
| api:POST:/v1/session/dataset/outlier-manual-corrections | apps.api.routers.session:apply_dataset_outlier_manual_corrections / scientific:validation | browser.session / research session and dataset | apps/api/routers/session.py:2963 |
| api:POST:/v1/session/dataset/panel-aggregate | apps.api.routers.session:aggregate_dataset_by_date / scientific:upload | browser.session / research session and dataset | apps/api/routers/session.py:1471 |
| api:POST:/v1/session/dataset/passport/{stage} | apps.api.routers.session:capture_dataset_passport / scientific:upload | browser.session / research session and dataset | apps/api/routers/session.py:6004 |
| api:POST:/v1/session/dataset/preprocessing/decomposition-outputs | apps.api.routers.session:create_dataset_preprocessing_decomposition_outputs / scientific:preprocessing | browser.session / research session and dataset | apps/api/routers/session.py:3971 |
| api:POST:/v1/session/dataset/preprocessing/feature-generations | apps.api.routers.session:create_dataset_preprocessing_feature_generation / scientific:preprocessing | browser.session / research session and dataset | apps/api/routers/session.py:4490 |
| api:POST:/v1/session/dataset/preprocessing/regularity-corrections | apps.api.routers.session:correct_dataset_preprocessing_regularity / scientific:preprocessing | browser.session / research session and dataset | apps/api/routers/session.py:3865 |
| api:POST:/v1/session/dataset/preprocessing/scaling-recipes | apps.api.routers.session:create_dataset_preprocessing_scaling_recipe / scientific:preprocessing | browser.session / research session and dataset | apps/api/routers/session.py:4605 |
| api:POST:/v1/session/dataset/preprocessing/smoothing-transformations | apps.api.routers.session:create_dataset_preprocessing_smoothing_transformation / scientific:preprocessing | browser.session / research session and dataset | apps/api/routers/session.py:4189 |
| api:POST:/v1/session/dataset/preprocessing/spectral-selections | apps.api.routers.session:save_dataset_preprocessing_spectral_selection / scientific:preprocessing | browser.session / research session and dataset | apps/api/routers/session.py:4416 |
| api:POST:/v1/session/dataset/preprocessing/stationarity-transformations | apps.api.routers.session:create_dataset_preprocessing_stationarity_transformation / scientific:preprocessing | browser.session / research session and dataset | apps/api/routers/session.py:4304 |
| api:POST:/v1/session/dataset/preprocessing/variance-transformations | apps.api.routers.session:create_dataset_preprocessing_variance_transformation / scientific:preprocessing | browser.session / research session and dataset | apps/api/routers/session.py:4073 |
| api:POST:/v1/session/dataset/range-corrections | apps.api.routers.session:correct_dataset_ranges / scientific:validation | browser.session / research session and dataset | apps/api/routers/session.py:2312 |
| api:POST:/v1/session/dataset/referential-corrections | apps.api.routers.session:correct_dataset_referential / scientific:validation | browser.session / research session and dataset | apps/api/routers/session.py:3547 |
| api:POST:/v1/session/dataset/regularity-corrections | apps.api.routers.session:correct_dataset_regularity / scientific:validation | browser.session / research session and dataset | apps/api/routers/session.py:3737 |
| api:POST:/v1/session/dataset/sufficiency-plan | apps.api.routers.session:save_dataset_sufficiency_plan / scientific:validation | browser.session / research session and dataset | apps/api/routers/session.py:4673 |
| api:POST:/v1/session/dataset/text-quality-corrections | apps.api.routers.session:correct_dataset_text_quality / scientific:validation | browser.session / research session and dataset | apps/api/routers/session.py:3640 |
| api:POST:/v1/session/dataset/uniqueness-corrections | apps.api.routers.session:correct_dataset_uniqueness / scientific:validation | browser.session / research session and dataset | apps/api/routers/session.py:4856 |
| api:POST:/v1/session/date-column | apps.api.routers.session:set_date_column / service:platform | browser.session / research session and dataset | apps/api/routers/session.py:5674 |
| api:POST:/v1/session/demo | apps.api.routers.session:load_demo_dataset / scientific:upload | browser.session / bundled demo dataset; not AuthSession/DemoGrant/campaign entry | apps/api/routers/session.py:602 |
| api:POST:/v1/session/modeling/backtest | apps.api.routers.modeling_session:run_modeling_backtest / scientific:modeling | browser.session / session model/job/card/forecast | apps/api/routers/modeling_session.py:1389 |
| api:POST:/v1/session/modeling/backtest/exclude | apps.api.routers.modeling_session:decide_modeling_backtest_scope / scientific:modeling | browser.session / session model/job/card/forecast | apps/api/routers/modeling_session.py:1606 |
| api:POST:/v1/session/modeling/baselines | apps.api.routers.modeling_session:bootstrap_modeling_baselines / scientific:modeling | browser.session / session model/job/card/forecast | apps/api/routers/modeling_session.py:1279 |
| api:POST:/v1/session/modeling/candidates | apps.api.routers.modeling_session:generate_modeling_candidates / scientific:modeling | browser.session / session model/job/card/forecast | apps/api/routers/modeling_session.py:1207 |
| api:POST:/v1/session/modeling/card | apps.api.routers.modeling_session:create_model_card / scientific:modeling | browser.session / session model/job/card/forecast | apps/api/routers/modeling_session.py:3142 |
| api:POST:/v1/session/modeling/compare | apps.api.routers.modeling_session:compare_modeling_candidates / scientific:modeling | browser.session / session model/job/card/forecast | apps/api/routers/modeling_session.py:2809 |
| api:POST:/v1/session/modeling/diagnostics | apps.api.routers.modeling_session:diagnose_modeling_candidate / scientific:modeling | browser.session / session model/job/card/forecast | apps/api/routers/modeling_session.py:2748 |
| api:POST:/v1/session/modeling/diagnostics/ensure | apps.api.routers.modeling_session:ensure_modeling_diagnostics / scientific:modeling | browser.session / session model/job/card/forecast | apps/api/routers/modeling_session.py:2768 |
| api:POST:/v1/session/modeling/forecast | apps.api.routers.forecasting_session:create_forecast / scientific:forecasting | browser.session / session model/job/card/forecast | apps/api/routers/forecasting_session.py:208 |
| api:POST:/v1/session/modeling/forecast/compare | apps.api.routers.forecasting_session:compare_forecasts / scientific:forecasting | browser.session / session model/job/card/forecast | apps/api/routers/forecasting_session.py:464 |
| api:POST:/v1/session/modeling/forecast/{forecast_id}/sensitivity | apps.api.routers.forecasting_session:forecast_sensitivity / scientific:forecasting | browser.session / session model/job/card/forecast | apps/api/routers/forecasting_session.py:528 |
| api:POST:/v1/session/modeling/forecast/{forecast_id}/trace | apps.api.routers.forecasting_session:record_client_export_event / scientific:forecasting | browser.session / session model/job/card/forecast | apps/api/routers/forecasting_session.py:447 |
| api:POST:/v1/session/modeling/jobs/start | apps.api.routers.modeling_session:start_modeling_job / scientific:modeling | browser.session / persisted tuning job/plan (operation Literal tuning), session context | apps/api/routers/modeling_session.py:2069 |
| api:POST:/v1/session/modeling/jobs/{job_id}/cancel | apps.api.routers.modeling_session:cancel_modeling_job / scientific:modeling | browser.session / persisted tuning job/plan (operation Literal tuning), session context | apps/api/routers/modeling_session.py:2172 |
| api:POST:/v1/session/modeling/jobs/{job_id}/step | apps.api.routers.modeling_session:step_modeling_job / scientific:modeling | browser.session / persisted tuning job/plan (operation Literal tuning), session context | apps/api/routers/modeling_session.py:2207 |
| api:POST:/v1/session/modeling/panel/backtest | apps.api.routers.modeling_session:panel_backtest / scientific:modeling | browser.session / session model/job/card/forecast | apps/api/routers/modeling_session.py:3665 |
| api:POST:/v1/session/modeling/panel/forecast | apps.api.routers.modeling_session:panel_forecast / scientific:forecasting | browser.session / session model/job/card/forecast | apps/api/routers/modeling_session.py:3723 |
| api:POST:/v1/session/modeling/panel/passport | apps.api.routers.modeling_session:build_panel_passport_for_session / scientific:modeling | browser.session / session model/job/card/forecast | apps/api/routers/modeling_session.py:3454 |
| api:POST:/v1/session/modeling/panel/passport/confirm | apps.api.routers.modeling_session:confirm_panel_entry_checkpoint / scientific:modeling | browser.session / session model/job/card/forecast | apps/api/routers/modeling_session.py:3527 |
| api:POST:/v1/session/modeling/select | apps.api.routers.modeling_session:select_modeling_candidate / scientific:modeling | browser.session / session model/job/card/forecast | apps/api/routers/modeling_session.py:3032 |
| api:POST:/v1/session/modeling/selection/evaluate | apps.api.routers.modeling_session:evaluate_modeling_selection / scientific:modeling | browser.session / session model/job/card/forecast | apps/api/routers/modeling_session.py:2992 |
| api:POST:/v1/session/modeling/tune | apps.api.routers.modeling_session:tune_modeling_candidate / scientific:modeling | browser.session / session model/job/card/forecast | apps/api/routers/modeling_session.py:1764 |
| api:POST:/v1/session/modeling/tuning/skip | apps.api.routers.modeling_session:skip_modeling_tuning / scientific:modeling | browser.session / session model/job/card/forecast | apps/api/routers/modeling_session.py:1646 |
| api:POST:/v1/session/modeling/tuning/skip-pending | apps.api.routers.modeling_session:skip_all_pending_modeling_tuning / scientific:modeling | browser.session / session model/job/card/forecast | apps/api/routers/modeling_session.py:1688 |
| api:POST:/v1/session/modeling/tuning/start | apps.api.routers.modeling_session:start_modeling_tuning / scientific:modeling | browser.session / persisted tuning job/plan (operation Literal tuning), session context | apps/api/routers/modeling_session.py:2380 |
| api:POST:/v1/session/modeling/tuning/step | apps.api.routers.modeling_session:step_modeling_tuning / scientific:modeling | browser.session / persisted tuning job/plan (operation Literal tuning), session context | apps/api/routers/modeling_session.py:2482 |
| api:POST:/v1/session/stage/{stage} | apps.api.routers.session:set_stage / service:platform | browser.session / research session and dataset | apps/api/routers/session.py:6143 |
| api:POST:/v1/session/target-column | apps.api.routers.session:set_target_column / service:platform | browser.session / research session and dataset | apps/api/routers/session.py:5547 |
| api:PUT:/v1/session/dataset/preprocessing-check-modes | apps.api.routers.session:save_dataset_preprocessing_check_modes / scientific:preprocessing | browser.session / research session and dataset | apps/api/routers/session.py:2450 |
| api:PUT:/v1/session/dataset/type-schema | apps.api.routers.session:save_dataset_type_schema / scientific:validation | browser.session / research session and dataset | apps/api/routers/session.py:5327 |
| api:PUT:/v1/session/dataset/validation-check-modes | apps.api.routers.session:save_dataset_validation_check_modes / scientific:validation | browser.session / research session and dataset | apps/api/routers/session.py:2167 |
| api:PUT:/v1/session/dataset/validation-rules | apps.api.routers.session:save_dataset_validation_rules / scientific:validation | browser.session / research session and dataset | apps/api/routers/session.py:4924 |
| api:PUT:/v1/session/modeling/feature-regressors | apps.api.routers.modeling_session:set_modeling_feature_regressors / scientific:modeling | browser.session / session model/job/card/forecast | apps/api/routers/modeling_session.py:1111 |

## framework

| ID / метод и путь | Operation / stage | Policy / resource | Источник |
|---|---|---|---|
| api:GET:/docs | fastapi:docs_url / service:platform | public.metadata / request metadata | apps/api/main.py:166 |
| api:GET:/docs/oauth2-redirect | fastapi:swagger_ui_oauth2_redirect_url / service:platform | public.metadata / request metadata | apps/api/main.py:166 |
| api:GET:/openapi.json | fastapi:openapi_url / service:platform | public.metadata / request metadata | apps/api/main.py:166 |
| api:GET:/redoc | fastapi:redoc_url / service:platform | public.metadata / request metadata | apps/api/main.py:166 |
| api:HEAD:/docs | fastapi:docs_url / service:platform | public.metadata / request metadata | apps/api/main.py:166 |
| api:HEAD:/docs/oauth2-redirect | fastapi:swagger_ui_oauth2_redirect_url / service:platform | public.metadata / request metadata | apps/api/main.py:166 |
| api:HEAD:/openapi.json | fastapi:openapi_url / service:platform | public.metadata / request metadata | apps/api/main.py:166 |
| api:HEAD:/redoc | fastapi:redoc_url / service:platform | public.metadata / request metadata | apps/api/main.py:166 |

## internal_operation

| ID / метод и путь | Operation / stage | Policy / resource | Источник |
|---|---|---|---|
| execution:model.job_step | execution:model.job_step / scientific:modeling | worker.authority / persisted tuning job/plan (operation Literal tuning), session context | apps/api/routers/modeling_session.py:2208 |
| execution:model.registry | execution:model.registry / scientific:modeling | worker.authority / model request; dataset; CPU/GPU | apps/api/model_execution.py:374 |
| execution:model.tuning_step | execution:model.tuning_step / scientific:modeling | worker.authority / persisted tuning job/plan (operation Literal tuning), session context | apps/api/routers/modeling_session.py:2483 |

## legacy_authority

| ID / метод и путь | Operation / stage | Policy / resource | Источник |
|---|---|---|---|
| legacy:token-authority | legacy:token-authority / service:identity | legacy.token / legacy shared token hash | app/core/auth.py:10 |

## legacy_widget

| ID / метод и путь | Operation / stage | Policy / resource | Источник |
|---|---|---|---|
| legacy:app.py:10025:button | legacy:button / service:legacy | legacy.token / Streamlit session data | app.py:10025 |
| legacy:app.py:10092:button | legacy:button / service:legacy | legacy.token / Streamlit session data | app.py:10092 |
| legacy:app.py:10344:selectbox | legacy:selectbox / service:legacy | legacy.token / Streamlit session data | app.py:10344 |
| legacy:app.py:10354:radio | legacy:radio / service:legacy | legacy.token / Streamlit session data | app.py:10354 |
| legacy:app.py:10397:slider | legacy:slider / service:legacy | legacy.token / Streamlit session data | app.py:10397 |
| legacy:app.py:10409:slider | legacy:slider / service:legacy | legacy.token / Streamlit session data | app.py:10409 |
| legacy:app.py:10421:slider | legacy:slider / service:legacy | legacy.token / Streamlit session data | app.py:10421 |
| legacy:app.py:10433:selectbox | legacy:selectbox / service:legacy | legacy.token / Streamlit session data | app.py:10433 |
| legacy:app.py:10455:button | legacy:button / service:legacy | legacy.token / Streamlit session data | app.py:10455 |
| legacy:app.py:10459:button | legacy:button / service:legacy | legacy.token / Streamlit session data | app.py:10459 |
| legacy:app.py:10669:button | legacy:button / service:legacy | legacy.token / Streamlit session data | app.py:10669 |
| legacy:app.py:10732:button | legacy:button / service:legacy | legacy.token / Streamlit session data | app.py:10732 |
| legacy:app.py:10991:selectbox | legacy:selectbox / service:legacy | legacy.token / Streamlit session data | app.py:10991 |
| legacy:app.py:11016:radio | legacy:radio / service:legacy | legacy.token / Streamlit session data | app.py:11016 |
| legacy:app.py:11064:slider | legacy:slider / service:legacy | legacy.token / Streamlit session data | app.py:11064 |
| legacy:app.py:11076:number_input | legacy:number_input / service:legacy | legacy.token / Streamlit session data | app.py:11076 |
| legacy:app.py:11096:slider | legacy:slider / service:legacy | legacy.token / Streamlit session data | app.py:11096 |
| legacy:app.py:11118:slider | legacy:slider / service:legacy | legacy.token / Streamlit session data | app.py:11118 |
| legacy:app.py:11127:number_input | legacy:number_input / service:legacy | legacy.token / Streamlit session data | app.py:11127 |
| legacy:app.py:11140:button | legacy:button / service:legacy | legacy.token / Streamlit session data | app.py:11140 |
| legacy:app.py:11147:button | legacy:button / service:legacy | legacy.token / Streamlit session data | app.py:11147 |
| legacy:app.py:11401:button | legacy:button / service:legacy | legacy.token / Streamlit session data | app.py:11401 |
| legacy:app.py:11469:button | legacy:button / service:legacy | legacy.token / Streamlit session data | app.py:11469 |
| legacy:app.py:11636:selectbox | legacy:selectbox / service:legacy | legacy.token / Streamlit session data | app.py:11636 |
| legacy:app.py:11849:button | legacy:button / service:legacy | legacy.token / Streamlit session data | app.py:11849 |
| legacy:app.py:11889:checkbox | legacy:checkbox / service:legacy | legacy.token / Streamlit session data | app.py:11889 |
| legacy:app.py:11893:checkbox | legacy:checkbox / service:legacy | legacy.token / Streamlit session data | app.py:11893 |
| legacy:app.py:11894:checkbox | legacy:checkbox / service:legacy | legacy.token / Streamlit session data | app.py:11894 |
| legacy:app.py:11896:checkbox | legacy:checkbox / service:legacy | legacy.token / Streamlit session data | app.py:11896 |
| legacy:app.py:11897:checkbox | legacy:checkbox / service:legacy | legacy.token / Streamlit session data | app.py:11897 |
| legacy:app.py:11900:checkbox | legacy:checkbox / service:legacy | legacy.token / Streamlit session data | app.py:11900 |
| legacy:app.py:11913:multiselect | legacy:multiselect / service:legacy | legacy.token / Streamlit session data | app.py:11913 |
| legacy:app.py:11921:checkbox | legacy:checkbox / service:legacy | legacy.token / Streamlit session data | app.py:11921 |
| legacy:app.py:11925:multiselect | legacy:multiselect / service:legacy | legacy.token / Streamlit session data | app.py:11925 |
| legacy:app.py:11931:multiselect | legacy:multiselect / service:legacy | legacy.token / Streamlit session data | app.py:11931 |
| legacy:app.py:11938:checkbox | legacy:checkbox / service:legacy | legacy.token / Streamlit session data | app.py:11938 |
| legacy:app.py:11940:multiselect | legacy:multiselect / service:legacy | legacy.token / Streamlit session data | app.py:11940 |
| legacy:app.py:11950:checkbox | legacy:checkbox / service:legacy | legacy.token / Streamlit session data | app.py:11950 |
| legacy:app.py:11952:multiselect | legacy:multiselect / service:legacy | legacy.token / Streamlit session data | app.py:11952 |
| legacy:app.py:11959:checkbox | legacy:checkbox / service:legacy | legacy.token / Streamlit session data | app.py:11959 |
| legacy:app.py:1195:selectbox | legacy:selectbox / service:legacy | legacy.token / Streamlit session data | app.py:1195 |
| legacy:app.py:11961:multiselect | legacy:multiselect / service:legacy | legacy.token / Streamlit session data | app.py:11961 |
| legacy:app.py:11968:checkbox | legacy:checkbox / service:legacy | legacy.token / Streamlit session data | app.py:11968 |
| legacy:app.py:11970:multiselect | legacy:multiselect / service:legacy | legacy.token / Streamlit session data | app.py:11970 |
| legacy:app.py:11978:button | legacy:button / service:legacy | legacy.token / Streamlit session data | app.py:11978 |
| legacy:app.py:12078:download_button | legacy:download_button / service:legacy | legacy.token / Streamlit session data | app.py:12078 |
| legacy:app.py:12253:multiselect | legacy:multiselect / service:legacy | legacy.token / Streamlit session data | app.py:12253 |
| legacy:app.py:12265:radio | legacy:radio / service:legacy | legacy.token / Streamlit session data | app.py:12265 |
| legacy:app.py:12314:number_input | legacy:number_input / service:legacy | legacy.token / Streamlit session data | app.py:12314 |
| legacy:app.py:12315:number_input | legacy:number_input / service:legacy | legacy.token / Streamlit session data | app.py:12315 |
| legacy:app.py:12319:slider | legacy:slider / service:legacy | legacy.token / Streamlit session data | app.py:12319 |
| legacy:app.py:12340:checkbox | legacy:checkbox / service:legacy | legacy.token / Streamlit session data | app.py:12340 |
| legacy:app.py:12350:button | legacy:button / service:legacy | legacy.token / Streamlit session data | app.py:12350 |
| legacy:app.py:12357:button | legacy:button / service:legacy | legacy.token / Streamlit session data | app.py:12357 |
| legacy:app.py:12580:button | legacy:button / service:legacy | legacy.token / Streamlit session data | app.py:12580 |
| legacy:app.py:12668:button | legacy:button / service:legacy | legacy.token / Streamlit session data | app.py:12668 |
| legacy:app.py:12794:selectbox | legacy:selectbox / service:legacy | legacy.token / Streamlit session data | app.py:12794 |
| legacy:app.py:12964:download_button | legacy:download_button / service:legacy | legacy.token / Streamlit session data | app.py:12964 |
| legacy:app.py:13006:download_button | legacy:download_button / service:legacy | legacy.token / Streamlit session data | app.py:13006 |
| legacy:app.py:13084:selectbox | legacy:selectbox / service:legacy | legacy.token / Streamlit session data | app.py:13084 |
| legacy:app.py:13093:multiselect | legacy:multiselect / service:legacy | legacy.token / Streamlit session data | app.py:13093 |
| legacy:app.py:13106:slider | legacy:slider / service:legacy | legacy.token / Streamlit session data | app.py:13106 |
| legacy:app.py:13113:number_input | legacy:number_input / service:legacy | legacy.token / Streamlit session data | app.py:13113 |
| legacy:app.py:13119:number_input | legacy:number_input / service:legacy | legacy.token / Streamlit session data | app.py:13119 |
| legacy:app.py:13127:button | legacy:button / service:legacy | legacy.token / Streamlit session data | app.py:13127 |
| legacy:app.py:13293:selectbox | legacy:selectbox / service:legacy | legacy.token / Streamlit session data | app.py:13293 |
| legacy:app.py:13357:download_button | legacy:download_button / service:legacy | legacy.token / Streamlit session data | app.py:13357 |
| legacy:app.py:1416:checkbox | legacy:checkbox / service:legacy | legacy.token / Streamlit session data | app.py:1416 |
| legacy:app.py:1453:selectbox | legacy:selectbox / service:legacy | legacy.token / Streamlit session data | app.py:1453 |
| legacy:app.py:1459:selectbox | legacy:selectbox / service:legacy | legacy.token / Streamlit session data | app.py:1459 |
| legacy:app.py:1471:multiselect | legacy:multiselect / service:legacy | legacy.token / Streamlit session data | app.py:1471 |
| legacy:app.py:1483:multiselect | legacy:multiselect / service:legacy | legacy.token / Streamlit session data | app.py:1483 |
| legacy:app.py:1503:selectbox | legacy:selectbox / service:legacy | legacy.token / Streamlit session data | app.py:1503 |
| legacy:app.py:1518:multiselect | legacy:multiselect / service:legacy | legacy.token / Streamlit session data | app.py:1518 |
| legacy:app.py:1623:radio | legacy:radio / service:legacy | legacy.token / Streamlit session data | app.py:1623 |
| legacy:app.py:1635:selectbox | legacy:selectbox / service:legacy | legacy.token / Streamlit session data | app.py:1635 |
| legacy:app.py:1642:selectbox | legacy:selectbox / service:legacy | legacy.token / Streamlit session data | app.py:1642 |
| legacy:app.py:1643:selectbox | legacy:selectbox / service:legacy | legacy.token / Streamlit session data | app.py:1643 |
| legacy:app.py:1645:selectbox | legacy:selectbox / service:legacy | legacy.token / Streamlit session data | app.py:1645 |
| legacy:app.py:1646:selectbox | legacy:selectbox / service:legacy | legacy.token / Streamlit session data | app.py:1646 |
| legacy:app.py:1647:selectbox | legacy:selectbox / service:legacy | legacy.token / Streamlit session data | app.py:1647 |
| legacy:app.py:1649:button | legacy:button / service:legacy | legacy.token / Streamlit session data | app.py:1649 |
| legacy:app.py:1716:selectbox | legacy:selectbox / service:legacy | legacy.token / Streamlit session data | app.py:1716 |
| legacy:app.py:1718:selectbox | legacy:selectbox / service:legacy | legacy.token / Streamlit session data | app.py:1718 |
| legacy:app.py:1726:slider | legacy:slider / service:legacy | legacy.token / Streamlit session data | app.py:1726 |
| legacy:app.py:1728:slider | legacy:slider / service:legacy | legacy.token / Streamlit session data | app.py:1728 |
| legacy:app.py:1738:checkbox | legacy:checkbox / service:legacy | legacy.token / Streamlit session data | app.py:1738 |
| legacy:app.py:1758:checkbox | legacy:checkbox / service:legacy | legacy.token / Streamlit session data | app.py:1758 |
| legacy:app.py:1778:checkbox | legacy:checkbox / service:legacy | legacy.token / Streamlit session data | app.py:1778 |
| legacy:app.py:1797:checkbox | legacy:checkbox / service:legacy | legacy.token / Streamlit session data | app.py:1797 |
| legacy:app.py:1815:button | legacy:button / service:legacy | legacy.token / Streamlit session data | app.py:1815 |
| legacy:app.py:1913:selectbox | legacy:selectbox / service:legacy | legacy.token / Streamlit session data | app.py:1913 |
| legacy:app.py:1914:selectbox | legacy:selectbox / service:legacy | legacy.token / Streamlit session data | app.py:1914 |
| legacy:app.py:1916:checkbox | legacy:checkbox / service:legacy | legacy.token / Streamlit session data | app.py:1916 |
| legacy:app.py:1918:selectbox | legacy:selectbox / service:legacy | legacy.token / Streamlit session data | app.py:1918 |
| legacy:app.py:1920:button | legacy:button / service:legacy | legacy.token / Streamlit session data | app.py:1920 |
| legacy:app.py:2069:selectbox | legacy:selectbox / service:legacy | legacy.token / Streamlit session data | app.py:2069 |
| legacy:app.py:2189:checkbox | legacy:checkbox / service:legacy | legacy.token / Streamlit session data | app.py:2189 |
| legacy:app.py:2618:selectbox | legacy:selectbox / service:legacy | legacy.token / Streamlit session data | app.py:2618 |
| legacy:app.py:2626:button | legacy:button / service:legacy | legacy.token / Streamlit session data | app.py:2626 |
| legacy:app.py:2970:selectbox | legacy:selectbox / service:legacy | legacy.token / Streamlit session data | app.py:2970 |
| legacy:app.py:2978:button | legacy:button / service:legacy | legacy.token / Streamlit session data | app.py:2978 |
| legacy:app.py:3193:download_button | legacy:download_button / service:legacy | legacy.token / Streamlit session data | app.py:3193 |
| legacy:app.py:3222:button | legacy:button / service:legacy | legacy.token / Streamlit session data | app.py:3222 |
| legacy:app.py:3223:download_button | legacy:download_button / service:legacy | legacy.token / Streamlit session data | app.py:3223 |
| legacy:app.py:3322:button | legacy:button / service:legacy | legacy.token / Streamlit session data | app.py:3322 |
| legacy:app.py:3531:button | legacy:button / service:legacy | legacy.token / Streamlit session data | app.py:3531 |
| legacy:app.py:353:text_input | legacy:text_input / service:legacy | legacy.token / legacy pre-auth shared-token entry form | app.py:353 |
| legacy:app.py:354:button | legacy:button / service:legacy | legacy.token / legacy pre-auth shared-token entry form | app.py:354 |
| legacy:app.py:3779:button | legacy:button / service:legacy | legacy.token / Streamlit session data | app.py:3779 |
| legacy:app.py:3882:radio | legacy:radio / service:legacy | legacy.token / Streamlit session data | app.py:3882 |
| legacy:app.py:3909:button | legacy:button / service:legacy | legacy.token / Streamlit session data | app.py:3909 |
| legacy:app.py:3980:button | legacy:button / service:legacy | legacy.token / Streamlit session data | app.py:3980 |
| legacy:app.py:404:radio | legacy:radio / service:legacy | legacy.token / Streamlit session data | app.py:404 |
| legacy:app.py:4110:button | legacy:button / service:legacy | legacy.token / Streamlit session data | app.py:4110 |
| legacy:app.py:4120:download_button | legacy:download_button / service:legacy | legacy.token / Streamlit session data | app.py:4120 |
| legacy:app.py:412:file_uploader | legacy:file_uploader / service:legacy | legacy.token / Streamlit session data | app.py:412 |
| legacy:app.py:4205:radio | legacy:radio / service:legacy | legacy.token / Streamlit session data | app.py:4205 |
| legacy:app.py:4222:data_editor | legacy:data_editor / service:legacy | legacy.token / Streamlit session data | app.py:4222 |
| legacy:app.py:422:button | legacy:button / service:legacy | legacy.token / Streamlit session data | app.py:422 |
| legacy:app.py:4239:button | legacy:button / service:legacy | legacy.token / Streamlit session data | app.py:4239 |
| legacy:app.py:4255:radio | legacy:radio / service:legacy | legacy.token / Streamlit session data | app.py:4255 |
| legacy:app.py:4281:button | legacy:button / service:legacy | legacy.token / Streamlit session data | app.py:4281 |
| legacy:app.py:4364:button | legacy:button / service:legacy | legacy.token / Streamlit session data | app.py:4364 |
| legacy:app.py:4372:button | legacy:button / service:legacy | legacy.token / Streamlit session data | app.py:4372 |
| legacy:app.py:4419:radio | legacy:radio / service:legacy | legacy.token / Streamlit session data | app.py:4419 |
| legacy:app.py:4436:data_editor | legacy:data_editor / service:legacy | legacy.token / Streamlit session data | app.py:4436 |
| legacy:app.py:4453:button | legacy:button / service:legacy | legacy.token / Streamlit session data | app.py:4453 |
| legacy:app.py:4469:radio | legacy:radio / service:legacy | legacy.token / Streamlit session data | app.py:4469 |
| legacy:app.py:4492:button | legacy:button / service:legacy | legacy.token / Streamlit session data | app.py:4492 |
| legacy:app.py:4618:button | legacy:button / service:legacy | legacy.token / Streamlit session data | app.py:4618 |
| legacy:app.py:4696:button | legacy:button / service:legacy | legacy.token / Streamlit session data | app.py:4696 |
| legacy:app.py:4768:radio | legacy:radio / service:legacy | legacy.token / Streamlit session data | app.py:4768 |
| legacy:app.py:4787:data_editor | legacy:data_editor / service:legacy | legacy.token / Streamlit session data | app.py:4787 |
| legacy:app.py:4804:button | legacy:button / service:legacy | legacy.token / Streamlit session data | app.py:4804 |
| legacy:app.py:4836:radio | legacy:radio / service:legacy | legacy.token / Streamlit session data | app.py:4836 |
| legacy:app.py:4856:button | legacy:button / service:legacy | legacy.token / Streamlit session data | app.py:4856 |
| legacy:app.py:4940:button | legacy:button / service:legacy | legacy.token / Streamlit session data | app.py:4940 |
| legacy:app.py:496:selectbox | legacy:selectbox / service:legacy | legacy.token / Streamlit session data | app.py:496 |
| legacy:app.py:5004:button | legacy:button / service:legacy | legacy.token / Streamlit session data | app.py:5004 |
| legacy:app.py:501:text_input | legacy:text_input / service:legacy | legacy.token / Streamlit session data | app.py:501 |
| legacy:app.py:502:number_input | legacy:number_input / service:legacy | legacy.token / Streamlit session data | app.py:502 |
| legacy:app.py:503:text_input | legacy:text_input / service:legacy | legacy.token / Streamlit session data | app.py:503 |
| legacy:app.py:504:text_input | legacy:text_input / service:legacy | legacy.token / Streamlit session data | app.py:504 |
| legacy:app.py:505:text_input | legacy:text_input / service:legacy | legacy.token / Streamlit session data | app.py:505 |
| legacy:app.py:506:text_area | legacy:text_area / service:legacy | legacy.token / Streamlit session data | app.py:506 |
| legacy:app.py:5110:radio | legacy:radio / service:legacy | legacy.token / Streamlit session data | app.py:5110 |
| legacy:app.py:5129:data_editor | legacy:data_editor / service:legacy | legacy.token / Streamlit session data | app.py:5129 |
| legacy:app.py:513:button | legacy:button / service:legacy | legacy.token / Streamlit session data | app.py:513 |
| legacy:app.py:5146:button | legacy:button / service:legacy | legacy.token / Streamlit session data | app.py:5146 |
| legacy:app.py:5173:radio | legacy:radio / service:legacy | legacy.token / Streamlit session data | app.py:5173 |
| legacy:app.py:5196:button | legacy:button / service:legacy | legacy.token / Streamlit session data | app.py:5196 |
| legacy:app.py:5306:button | legacy:button / service:legacy | legacy.token / Streamlit session data | app.py:5306 |
| legacy:app.py:5374:button | legacy:button / service:legacy | legacy.token / Streamlit session data | app.py:5374 |
| legacy:app.py:5439:radio | legacy:radio / service:legacy | legacy.token / Streamlit session data | app.py:5439 |
| legacy:app.py:5458:data_editor | legacy:data_editor / service:legacy | legacy.token / Streamlit session data | app.py:5458 |
| legacy:app.py:5475:button | legacy:button / service:legacy | legacy.token / Streamlit session data | app.py:5475 |
| legacy:app.py:5502:radio | legacy:radio / service:legacy | legacy.token / Streamlit session data | app.py:5502 |
| legacy:app.py:5525:button | legacy:button / service:legacy | legacy.token / Streamlit session data | app.py:5525 |
| legacy:app.py:562:button | legacy:button / service:legacy | legacy.token / Streamlit session data | app.py:562 |
| legacy:app.py:5632:button | legacy:button / service:legacy | legacy.token / Streamlit session data | app.py:5632 |
| legacy:app.py:5671:button | legacy:button / service:legacy | legacy.token / Streamlit session data | app.py:5671 |
| legacy:app.py:5753:radio | legacy:radio / service:legacy | legacy.token / Streamlit session data | app.py:5753 |
| legacy:app.py:5772:data_editor | legacy:data_editor / service:legacy | legacy.token / Streamlit session data | app.py:5772 |
| legacy:app.py:5789:button | legacy:button / service:legacy | legacy.token / Streamlit session data | app.py:5789 |
| legacy:app.py:5813:radio | legacy:radio / service:legacy | legacy.token / Streamlit session data | app.py:5813 |
| legacy:app.py:5839:button | legacy:button / service:legacy | legacy.token / Streamlit session data | app.py:5839 |
| legacy:app.py:5918:button | legacy:button / service:legacy | legacy.token / Streamlit session data | app.py:5918 |
| legacy:app.py:5957:button | legacy:button / service:legacy | legacy.token / Streamlit session data | app.py:5957 |
| legacy:app.py:6003:button | legacy:button / service:legacy | legacy.token / Streamlit session data | app.py:6003 |
| legacy:app.py:6157:radio | legacy:radio / service:legacy | legacy.token / Streamlit session data | app.py:6157 |
| legacy:app.py:6176:data_editor | legacy:data_editor / service:legacy | legacy.token / Streamlit session data | app.py:6176 |
| legacy:app.py:6193:button | legacy:button / service:legacy | legacy.token / Streamlit session data | app.py:6193 |
| legacy:app.py:6225:radio | legacy:radio / service:legacy | legacy.token / Streamlit session data | app.py:6225 |
| legacy:app.py:6251:button | legacy:button / service:legacy | legacy.token / Streamlit session data | app.py:6251 |
| legacy:app.py:6319:button | legacy:button / service:legacy | legacy.token / Streamlit session data | app.py:6319 |
| legacy:app.py:6369:button | legacy:button / service:legacy | legacy.token / Streamlit session data | app.py:6369 |
| legacy:app.py:6409:radio | legacy:radio / service:legacy | legacy.token / Streamlit session data | app.py:6409 |
| legacy:app.py:6468:radio | legacy:radio / service:legacy | legacy.token / Streamlit session data | app.py:6468 |
| legacy:app.py:6490:button | legacy:button / service:legacy | legacy.token / Streamlit session data | app.py:6490 |
| legacy:app.py:651:selectbox | legacy:selectbox / service:legacy | legacy.token / Streamlit session data | app.py:651 |
| legacy:app.py:6713:button | legacy:button / service:legacy | legacy.token / Streamlit session data | app.py:6713 |
| legacy:app.py:6726:download_button | legacy:download_button / service:legacy | legacy.token / Streamlit session data | app.py:6726 |
| legacy:app.py:6735:button | legacy:button / service:legacy | legacy.token / Streamlit session data | app.py:6735 |
| legacy:app.py:6886:download_button | legacy:download_button / service:legacy | legacy.token / Streamlit session data | app.py:6886 |
| legacy:app.py:6973:selectbox | legacy:selectbox / service:legacy | legacy.token / Streamlit session data | app.py:6973 |
| legacy:app.py:713:number_input | legacy:number_input / service:legacy | legacy.token / Streamlit session data | app.py:713 |
| legacy:app.py:720:number_input | legacy:number_input / service:legacy | legacy.token / Streamlit session data | app.py:720 |
| legacy:app.py:7327:button | legacy:button / service:legacy | legacy.token / Streamlit session data | app.py:7327 |
| legacy:app.py:7329:download_button | legacy:download_button / service:legacy | legacy.token / Streamlit session data | app.py:7329 |
| legacy:app.py:732:button | legacy:button / service:legacy | legacy.token / Streamlit session data | app.py:732 |
| legacy:app.py:7338:button | legacy:button / service:legacy | legacy.token / Streamlit session data | app.py:7338 |
| legacy:app.py:7367:download_button | legacy:download_button / service:legacy | legacy.token / Streamlit session data | app.py:7367 |
| legacy:app.py:739:button | legacy:button / service:legacy | legacy.token / Streamlit session data | app.py:739 |
| legacy:app.py:762:button | legacy:button / service:legacy | legacy.token / Streamlit session data | app.py:762 |
| legacy:app.py:7845:selectbox | legacy:selectbox / service:legacy | legacy.token / Streamlit session data | app.py:7845 |
| legacy:app.py:7858:selectbox | legacy:selectbox / service:legacy | legacy.token / Streamlit session data | app.py:7858 |
| legacy:app.py:7859:selectbox | legacy:selectbox / service:legacy | legacy.token / Streamlit session data | app.py:7859 |
| legacy:app.py:7872:radio | legacy:radio / service:legacy | legacy.token / Streamlit session data | app.py:7872 |
| legacy:app.py:7901:data_editor | legacy:data_editor / service:legacy | legacy.token / Streamlit session data | app.py:7901 |
| legacy:app.py:7918:button | legacy:button / service:legacy | legacy.token / Streamlit session data | app.py:7918 |
| legacy:app.py:7934:radio | legacy:radio / service:legacy | legacy.token / Streamlit session data | app.py:7934 |
| legacy:app.py:7960:button | legacy:button / service:legacy | legacy.token / Streamlit session data | app.py:7960 |
| legacy:app.py:8034:button | legacy:button / service:legacy | legacy.token / Streamlit session data | app.py:8034 |
| legacy:app.py:8058:button | legacy:button / service:legacy | legacy.token / Streamlit session data | app.py:8058 |
| legacy:app.py:8065:button | legacy:button / service:legacy | legacy.token / Streamlit session data | app.py:8065 |
| legacy:app.py:8126:multiselect | legacy:multiselect / service:legacy | legacy.token / Streamlit session data | app.py:8126 |
| legacy:app.py:8160:radio | legacy:radio / service:legacy | legacy.token / Streamlit session data | app.py:8160 |
| legacy:app.py:8186:number_input | legacy:number_input / service:legacy | legacy.token / Streamlit session data | app.py:8186 |
| legacy:app.py:8190:number_input | legacy:number_input / service:legacy | legacy.token / Streamlit session data | app.py:8190 |
| legacy:app.py:8194:number_input | legacy:number_input / service:legacy | legacy.token / Streamlit session data | app.py:8194 |
| legacy:app.py:8198:number_input | legacy:number_input / service:legacy | legacy.token / Streamlit session data | app.py:8198 |
| legacy:app.py:8200:number_input | legacy:number_input / service:legacy | legacy.token / Streamlit session data | app.py:8200 |
| legacy:app.py:8205:button | legacy:button / service:legacy | legacy.token / Streamlit session data | app.py:8205 |
| legacy:app.py:8245:selectbox | legacy:selectbox / service:legacy | legacy.token / Streamlit session data | app.py:8245 |
| legacy:app.py:8266:radio | legacy:radio / service:legacy | legacy.token / Streamlit session data | app.py:8266 |
| legacy:app.py:8290:data_editor | legacy:data_editor / service:legacy | legacy.token / Streamlit session data | app.py:8290 |
| legacy:app.py:8308:button | legacy:button / service:legacy | legacy.token / Streamlit session data | app.py:8308 |
| legacy:app.py:8323:radio | legacy:radio / service:legacy | legacy.token / Streamlit session data | app.py:8323 |
| legacy:app.py:8343:button | legacy:button / service:legacy | legacy.token / Streamlit session data | app.py:8343 |
| legacy:app.py:8393:button | legacy:button / service:legacy | legacy.token / Streamlit session data | app.py:8393 |
| legacy:app.py:8444:button | legacy:button / service:legacy | legacy.token / Streamlit session data | app.py:8444 |
| legacy:app.py:8449:button | legacy:button / service:legacy | legacy.token / Streamlit session data | app.py:8449 |
| legacy:app.py:8514:button | legacy:button / service:legacy | legacy.token / Streamlit session data | app.py:8514 |
| legacy:app.py:8696:selectbox | legacy:selectbox / service:legacy | legacy.token / Streamlit session data | app.py:8696 |
| legacy:app.py:8704:radio | legacy:radio / service:legacy | legacy.token / Streamlit session data | app.py:8704 |
| legacy:app.py:8725:selectbox | legacy:selectbox / service:legacy | legacy.token / Streamlit session data | app.py:8725 |
| legacy:app.py:8737:selectbox | legacy:selectbox / service:legacy | legacy.token / Streamlit session data | app.py:8737 |
| legacy:app.py:8744:slider | legacy:slider / service:legacy | legacy.token / Streamlit session data | app.py:8744 |
| legacy:app.py:8749:button | legacy:button / service:legacy | legacy.token / Streamlit session data | app.py:8749 |
| legacy:app.py:8753:button | legacy:button / service:legacy | legacy.token / Streamlit session data | app.py:8753 |
| legacy:app.py:8758:button | legacy:button / service:legacy | legacy.token / Streamlit session data | app.py:8758 |
| legacy:app.py:8773:selectbox | legacy:selectbox / service:legacy | legacy.token / Streamlit session data | app.py:8773 |
| legacy:app.py:8886:button | legacy:button / service:legacy | legacy.token / Streamlit session data | app.py:8886 |
| legacy:app.py:9005:button | legacy:button / service:legacy | legacy.token / Streamlit session data | app.py:9005 |
| legacy:app.py:9189:selectbox | legacy:selectbox / service:legacy | legacy.token / Streamlit session data | app.py:9189 |
| legacy:app.py:9197:radio | legacy:radio / service:legacy | legacy.token / Streamlit session data | app.py:9197 |
| legacy:app.py:9223:number_input | legacy:number_input / service:legacy | legacy.token / Streamlit session data | app.py:9223 |
| legacy:app.py:9234:checkbox | legacy:checkbox / service:legacy | legacy.token / Streamlit session data | app.py:9234 |
| legacy:app.py:9237:selectbox | legacy:selectbox / service:legacy | legacy.token / Streamlit session data | app.py:9237 |
| legacy:app.py:9246:selectbox | legacy:selectbox / service:legacy | legacy.token / Streamlit session data | app.py:9246 |
| legacy:app.py:9272:number_input | legacy:number_input / service:legacy | legacy.token / Streamlit session data | app.py:9272 |
| legacy:app.py:9284:button | legacy:button / service:legacy | legacy.token / Streamlit session data | app.py:9284 |
| legacy:app.py:9288:button | legacy:button / service:legacy | legacy.token / Streamlit session data | app.py:9288 |
| legacy:app.py:9728:selectbox | legacy:selectbox / service:legacy | legacy.token / Streamlit session data | app.py:9728 |
| legacy:app.py:9779:radio | legacy:radio / service:legacy | legacy.token / Streamlit session data | app.py:9779 |
| legacy:app.py:9799:checkbox | legacy:checkbox / service:legacy | legacy.token / Streamlit session data | app.py:9799 |
| legacy:app.py:9801:slider | legacy:slider / service:legacy | legacy.token / Streamlit session data | app.py:9801 |
| legacy:app.py:9816:button | legacy:button / service:legacy | legacy.token / Streamlit session data | app.py:9816 |
| legacy:app.py:9820:button | legacy:button / service:legacy | legacy.token / Streamlit session data | app.py:9820 |

## page

| ID / метод и путь | Operation / stage | Policy / resource | Источник |
|---|---|---|---|
| page:embedded:/ | ui:embedded:/ / service:platform | ui.page / UI navigation only | apps/embedded/app/page.tsx:1 |
| page:embedded:/admin/progress | ui:embedded:/admin/progress / service:admin/progress | ui.admin / UI navigation only | apps/embedded/app/admin/progress/page.tsx:1 |
| page:embedded:/analytics/ts-analysis | ui:embedded:/analytics/ts-analysis / service:analytics/ts-analysis | ui.page / UI navigation only | apps/embedded/app/analytics/ts-analysis/page.tsx:1 |
| page:embedded:/eda | ui:embedded:/eda / scientific:eda | ui.page / UI navigation only | apps/embedded/app/eda/page.tsx:1 |
| page:embedded:/forecasting | ui:embedded:/forecasting / scientific:forecasting | ui.page / UI navigation only | apps/embedded/app/forecasting/page.tsx:1 |
| page:embedded:/modeling | ui:embedded:/modeling / scientific:modeling | ui.page / UI navigation only | apps/embedded/app/modeling/page.tsx:1 |
| page:embedded:/navigator | ui:embedded:/navigator / service:navigator | ui.page / UI navigation only | apps/embedded/app/navigator/page.tsx:1 |
| page:embedded:/preprocessing | ui:embedded:/preprocessing / scientific:preprocessing | ui.page / UI navigation only | apps/embedded/app/preprocessing/page.tsx:1 |
| page:embedded:/tasks | ui:embedded:/tasks / service:tasks | ui.page / UI navigation only | apps/embedded/app/tasks/page.tsx:1 |
| page:embedded:/upload | ui:embedded:/upload / scientific:upload | ui.page / UI navigation only | apps/embedded/app/upload/page.tsx:1 |
| page:embedded:/validation | ui:embedded:/validation / scientific:validation | ui.page / UI navigation only | apps/embedded/app/validation/page.tsx:1 |
| page:standalone:/ | ui:standalone:/ / service:platform | ui.page / UI navigation only | apps/standalone/app/page.tsx:1 |
| page:standalone:/dashboard/ts-analysis | ui:standalone:/dashboard/ts-analysis / service:dashboard/ts-analysis | ui.page / UI navigation only | apps/standalone/app/dashboard/ts-analysis/page.tsx:1 |
| page:standalone:/documentation | ui:standalone:/documentation / service:documentation | ui.page / UI navigation only | apps/standalone/app/documentation/page.tsx:1 |
| page:standalone:/eda | ui:standalone:/eda / scientific:eda | ui.page / UI navigation only | apps/standalone/app/eda/page.tsx:1 |
| page:standalone:/education | ui:standalone:/education / service:education | ui.page / UI navigation only | apps/standalone/app/education/page.tsx:1 |
| page:standalone:/forecasting | ui:standalone:/forecasting / scientific:forecasting | ui.page / UI navigation only | apps/standalone/app/forecasting/page.tsx:1 |
| page:standalone:/modeling | ui:standalone:/modeling / scientific:modeling | ui.page / UI navigation only | apps/standalone/app/modeling/page.tsx:1 |
| page:standalone:/navigator | ui:standalone:/navigator / service:navigator | ui.page / UI navigation only | apps/standalone/app/navigator/page.tsx:1 |
| page:standalone:/preprocessing | ui:standalone:/preprocessing / scientific:preprocessing | ui.page / UI navigation only | apps/standalone/app/preprocessing/page.tsx:1 |
| page:standalone:/tasks | ui:standalone:/tasks / service:tasks | ui.page / UI navigation only | apps/standalone/app/tasks/page.tsx:1 |
| page:standalone:/tasks/causes | ui:standalone:/tasks/causes / application:causal | ui.page / UI navigation only | apps/standalone/app/tasks/causes/page.tsx:1 |
| page:standalone:/tasks/decisions | ui:standalone:/tasks/decisions / application:decision | ui.page / UI navigation only | apps/standalone/app/tasks/decisions/page.tsx:1 |
| page:standalone:/tasks/monitoring | ui:standalone:/tasks/monitoring / application:monitoring | ui.page / UI navigation only | apps/standalone/app/tasks/monitoring/page.tsx:1 |
| page:standalone:/tasks/scenarios | ui:standalone:/tasks/scenarios / application:scenario | ui.page / UI navigation only | apps/standalone/app/tasks/scenarios/page.tsx:1 |
| page:standalone:/upload | ui:standalone:/upload / scientific:upload | ui.page / UI navigation only | apps/standalone/app/upload/page.tsx:1 |
| page:standalone:/validation | ui:standalone:/validation / scientific:validation | ui.page / UI navigation only | apps/standalone/app/validation/page.tsx:1 |

## proxy

| ID / метод и путь | Operation / stage | Policy / resource | Источник |
|---|---|---|---|
| proxy:embedded:/api/v1/:path* | proxy:embedded / service:transport | proxy.transport / forwarded HTTP request | apps/embedded/next.config.mjs:26 |
| proxy:standalone:/api/v1/:path* | proxy:standalone / service:transport | proxy.transport / forwarded HTTP request | apps/standalone/next.config.mjs:63 |

## renderer

| ID / метод и путь | Operation / stage | Policy / resource | Источник |
|---|---|---|---|
| renderer:GET:/healthz | renderer:/healthz / service:documentation | public.metadata / frozen print payload / PNG output | apps/print-renderer/src/server.ts:292 |
| renderer:GET:/readyz | renderer:/readyz / service:documentation | renderer.service / frozen print payload / PNG output | apps/print-renderer/src/server.ts:296 |
| renderer:POST:/v1/render | renderer:/v1/render / service:documentation | renderer.service / frozen print payload / PNG output | apps/print-renderer/src/server.ts:313 |
| renderer:POST:/v1/smoke | renderer:/v1/smoke / service:documentation | renderer.service / frozen print payload / PNG output | apps/print-renderer/src/server.ts:317 |

## static_asset

| ID / метод и путь | Operation / stage | Policy / resource | Источник |
|---|---|---|---|
| asset:standalone:/logo_TS.png | public.asset / service:platform | public.metadata / public static logo | apps/standalone/next.config.mjs:1 |

## storage

| ID / метод и путь | Operation / stage | Policy / resource | Источник |
|---|---|---|---|
| storage:artifacts | storage:artifacts / service:storage | storage.internal / snapshot/artifact/rendition bytes | apps/api/artifact_store.py:321 |
| storage:datasets | storage:datasets / service:storage | storage.internal / uploads + checkpoints | apps/api/research_runs.py:2785 |
| storage:db.load | storage:db.load / scientific:upload | storage.internal / SQL and remote/local DB data | app/data/db_guard.py:352 |
| storage:db.probe | storage:db.probe / scientific:upload | storage.internal / user-supplied DB host/port/path/credentials | app/data/file_loader.py:60 |
| storage:rule_templates | storage:rule_templates / scientific:validation | storage.internal / server rules YAML + shared overrides | apps/api/routers/public.py:81 |
| storage:run.restore | storage:run.restore / service:platform | storage.internal / stored original upload + inherited ownership | apps/api/routers/progress.py:1508 |

## task_alias

| ID / метод и путь | Operation / stage | Policy / resource | Источник |
|---|---|---|---|
| task_alias:/tasks/causes | application:causes / application:causal | task.alias / task route | packages/ui/lib/task-stops.ts:90 |
| task_alias:/tasks/decisions | application:decisions / application:decision | task.alias / task route | packages/ui/lib/task-stops.ts:103 |
| task_alias:/tasks/monitoring | application:monitoring / application:monitoring | task.alias / task route | packages/ui/lib/task-stops.ts:116 |
| task_alias:/tasks/scenarios | application:scenarios / application:scenario | task.alias / task route | packages/ui/lib/task-stops.ts:73 |

## transport

| ID / метод и путь | Operation / stage | Policy / resource | Источник |
|---|---|---|---|
| transport:cors-preflight | transport:cors-preflight / service:transport | cors.transport / CORS preflight metadata | apps/api/main.py:199 |
| transport:streamlit-runtime | transport:streamlit-runtime / service:legacy | legacy.token / Streamlit websocket/uploads/download transport | app.py:1 |

## worker

| ID / метод и путь | Operation / stage | Policy / resource | Источник |
|---|---|---|---|
| worker:apps/api/delivery_worker.py:182 | apps/api/delivery_worker.py:self._loop / service:platform | worker.authority / queued operation | apps/api/delivery_worker.py:182 |
| worker:apps/api/document_render_worker.py:507 | apps/api/document_render_worker.py:_target / service:platform | worker.authority / queued operation | apps/api/document_render_worker.py:507 |
| worker:apps/api/document_render_worker.py:529 | apps/api/document_render_worker.py:self._loop / service:platform | worker.authority / queued operation | apps/api/document_render_worker.py:529 |
| worker:delivery.run_once | worker:delivery.run_once / service:platform | worker.authority / delivery outbox; research runs; checkpoint files | apps/api/delivery_worker.py:118 |
| worker:document.process | worker:document.process / service:documentation | worker.authority / render job; snapshot; rendition | apps/api/document_render_worker.py:384 |
| worker:document.system_snapshot | worker:document.system_snapshot / service:documentation | worker.authority / durable snapshot bytes | apps/api/document_render_worker.py:170 |
