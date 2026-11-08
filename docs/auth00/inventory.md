# AUTH-00 — route/operation inventory

База: `a16b31bd0c3d49586de24d3556a39e43b9cc3321`. Автоматически собранные входы + явная policy review.

**Observed — текущее поведение. Target — требования следующих AUTH-задач, не реализованные guards.**

Проверка: `python3 scripts/auth00/inventory.py --check`. Обновление после review: `--write`.

Источник истины и подробные evidence/dependencies/effects: [inventory.json](inventory.json).
Модель угроз: [threat_model.md](threat_model.md). Процесс и границы: [design.md](design.md).

| Вид | Число |
|---|---:|
| api | 239 |
| framework | 8 |
| internal_operation | 25 |
| legacy_authority | 1 |
| legacy_widget | 250 |
| page | 34 |
| proxy | 2 |
| renderer | 4 |
| static_asset | 1 |
| storage | 13 |
| task_alias | 4 |
| transport | 2 |
| worker | 9 |

## Классификации

| Policy | Observed | Target | Follow-up |
|---|---|---|---|
| admin.key | AUTH-03 shared request context with AUTH-07 migration: named admin session (auth_session) requires platform_role=admin AND mfa_verified_at (403 admin_role_required/mfa_required otherwise); ADMIN API-key stays as programmatic channel until AUTH-10; missing/invalid credential 401, unavailable authority 503. | Named platform-admin permission + fresh MFA + scoped action + mandatory audit where sensitive. | AUTH-03, AUTH-05, AUTH-07, AUTH-20 |
| api.key | AUTH-10 protected durable PostgreSQL verifier; current Identity/Account/membership and can_use_api; explicit programmatic operation/scope ceiling. ENV only dev compatibility, never csk_ fallback. Full scientific object admission and atomic budgets remain AUTH-11/12. AUTH-11 also enforces current operation workload and kernel inputs on all scientific alternatives. | Valid account-bound API credential + scopes + can_use_api + object/stage/atomic budgets. | AUTH-12 |
| api.model_key | AUTH-11 operation-aware baseline/tune/custom admission over AUTH-10 durable key, scope and current Account; kernel fence checks actual inputs. Deprecated can_train_models adapter applies only to unbound dev compatibility. | Operation/model-aware split baseline/tune/custom, API/account scopes, atomic compute reservation. | AUTH-12, AUTH-13 |
| auth.api_keys | AUTH-10 personal self/current Account only; named session + Origin/CSRF mutations; fresh authentication for issue/rotate; hash-only durable keys, immutable history, CAS rotation/revoke and mandatory outbox atomic. Keys cannot manage keys. Interactive trusted CLI for existing service membership. | Preserve stable subject/account across rotation and terminal revoke across lifecycle changes. No scope/admin delegation beyond reviewed programmatic operations. | AUTH-11, AUTH-12, AUTH-17, AUTH-20 |
| auth.entry | AUTH-04 explicit HTTPS cookie entry: CSRF issuance or password proof + account membership. Signed host-only CSRF, rate/hash bounds, no password-only ADMIN session; safe 422/no-store. AUTH-05 named ADMIN password proof yields enrollment/login challenge only; no full session before MFA. AUTH-08 selects only active, unexpired Accounts and rechecks half-open Account expiry in session/MFA verification. | Preserve entry/challenge distinction; MFA AUTH-05, full proxy/UI AUTH-06, OIDC AUTH-19. No caller-supplied identity authority. | AUTH-04, AUTH-05, AUTH-06, AUTH-19 |
| auth.mfa.entry | AUTH-05 CSRF+exact Origin; opaque purpose-bound PostgreSQL single-use challenge, 5m expiry, 5 attempts plus subject-wide limiter; current identity/credential/epoch/account membership checked; TOTP replay fence, recovery revokes all sessions; mandatory audit intent atomic. Challenge never authorizes protected API. Pending recovery login remains a recovery-only challenge; another unused code can resume a lost response; password alone cannot restart enrollment. | First-party proxy/login UX and named browser admin route rollout in AUTH-06/07; WebAuthn UV preferred future adapter; current local fallback TOTP. | AUTH-06, AUTH-07 |
| auth.mfa.session | AUTH-05 online AuthSession+CSRF+Origin; password+TOTP step-up proof scoped to exact session/action, single-use and 5m; replacement/recovery rotation consume proof atomically with mandatory audit. MFA-session password change also requires password.change proof. AUTH-08 enforces Account expiry and current entitlements; me exposes effective capabilities without role-derived upgrade. | Extend action catalogue only alongside guarded sensitive admin APIs in AUTH-07; no client MFA assertions. | AUTH-07 |
| auth.session | AUTH-04 opaque PostgreSQL session, online expiry/credential/subject/epoch/membership checks; self-only session/password commands; CSRF on mutation; audit intent atomic with state. AUTH-05 sessions require current MFA factor for ADMIN; MFA evidence only from confirmed local TOTP. AUTH-06 safe generated me DTO; optional account selection after password proof, no session for account choices. AUTH-08 enforces Account expiry and current entitlements; me exposes effective capabilities without role-derived upgrade. | Effective Account entitlements/ownership, common proxy and named admin rollout remain AUTH-06/07/08/09/11/20. | AUTH-04, AUTH-05, AUTH-06, AUTH-08, AUTH-09, AUTH-20 |
| auth.storage | AUTH-02/04/05 PostgreSQL authority and audit outbox. AUTH-08 operator-only Account/membership lifecycle serializes Account CAS, scoped terminal session/challenge invalidation and mandatory audit intent; no new schema or public seat/plan assignment. No memory auth fallback. AUTH-09 trusted single-run migration locks Account→run→session, requires expected source/version/evidence and common PostgreSQL relations; immutable receipt and existing audit outbox commit together. | Only trusted coordinator may call; verify role/MFA/membership/account and transactional audit before mutations. No public tenant/plan assignment or memory fallback. | AUTH-03, AUTH-08, AUTH-10, AUTH-20 |
| billing.authority | AUTH-12 trusted PostgreSQL coordinator: current Identity/Account/caps, hierarchical budget locks, idempotency, balanced append-only postings and atomic job/audit outbox. No public financial writer, HTTP metering/queue worker adapters or commercial CU launch claimed. Explicit0025; no automatic paid credit. | Authoritative atomic resource admission and terminal ledger transitions; integrate current object gate and real execution through AUTH-13, calibrated CU AUTH-14, source-aware wallet AUTH-21. | AUTH-13, AUTH-14, AUTH-20, AUTH-21 |
| browser.internal | AUTH-11 common scientific/research guard in required/scoped profile; current named Account/object admission, safe preparse refusal, existing CSRF; surrogate only dev compatibility. Service metadata remain object/history protected; actual scientific operations use the functional registry and engine fences. | Unified authenticated context, object/stage/capability/grant checks; CSRF mutations; same direct-API policy. | AUTH-03, AUTH-06, AUTH-12 |
| browser.session | AUTH-11 common scientific/research guard in required/scoped profile; current named Account/object admission, safe preparse refusal, existing CSRF; surrogate only dev compatibility. Service metadata remain object/history protected; actual scientific operations use the functional registry and engine fences. | AuthSession отдельно от research pointer; account object policy + stage/grant/budget на каждом входе. | AUTH-03, AUTH-04, AUTH-06, AUTH-09, AUTH-12 |
| compute.calibrated | AUTH-14 protected PELT/sync/stateless/async tuning use fixed-point attempted-fit quotes, supervised progress before fit, saved tariff, atomic result/settle and current-authority cache/replay. A configured profile must match measured host/dependencies/kernels/domain; no configured profile explicitly preserves unpriced AUTH-13. Independent Linux wall/group-RSS supervisor and PostgreSQL global running+uncertain capacity. Shipped measurements are LOCAL reference only; VM calibration is not claimed. | Measure and explicitly install representative VM profile before calibrated admission; preserve bounds/replay/holds and complete operational, Demo/wallet and certification tasks separately. | AUTH-15, AUTH-16, AUTH-20, AUTH-21, AUTH-CERT |
| cors.transport | AUTH-06 exact explicit HTTPS origins; no wildcard preview or implicit localhost credentials. CORS is not AuthN. | Scientific direct API authority rollout remains AUTH-11. | AUTH-11 |
| document.object | Existing document object/scopes/lifecycle policy consumes AUTH-03 shared context; legacy session surrogate only outside scoped mode. Account ownership bridge remains AUTH-09. AUTH-09 common run gate enforces Account/tenant before role/dev compatibility; original author remains provenance. Lazy visual freeze uses actual caller. | Same unified account-aware object authority for metadata, preview, content, jobs and lifecycle; no ID-as-permission. | AUTH-03, AUTH-09, AUTH-11, AUTH-13 |
| legacy.token | Legacy shared-token entry + session_state.authenticated gate; pre-auth form отдельно отмечена в resource/effects. Не личная Account authority. | Explicit isolation/decommission or migrate to common AuthN/object/capability/budget controls; no paid/demo bypass. | AUTH-03, AUTH-11, AUTH-20 |
| logs.scoped | Manual compatibility adapter now passes the real Request into AUTH-03 coordinator; same invalid-key/ambiguity/authority semantics; scopes/SupportGrant exact-pair policy retained. | Unified AuthN without losing exact tenant/run/action pairs; admin MFA and support scope policy; secret-safe exports. | AUTH-03, AUTH-05, AUTH-07, AUTH-20 |
| ops.diagnostics | /health/ops без AuthN; безопасная проекция технического состояния. | Private ops/service или platform permission; не раскрывать конфигурацию/секреты. | AUTH-03, AUTH-20 |
| profile.policy | AUTH-03 shared context subject + existing OrgProfileService policy.admin/mandatory audit. Named MFA policy remains AUTH-05/07. | Unified context + explicit policy admin permission/MFA; preserve tenant and mandatory transaction semantics. | AUTH-03, AUTH-05, AUTH-07, AUTH-20 |
| progress.session | AUTH-11 common scientific/research guard in required/scoped profile; current named Account/object admission, safe preparse refusal, existing CSRF; surrogate only dev compatibility. Service metadata remain object/history protected; actual scientific operations use the functional registry and engine fences. | Unified account context; сохранить object/mirror проверки, ограничить admission/observations. | AUTH-03, AUTH-09 |
| proxy.transport | AUTH-06 shared force-dynamic Node proxy: fixed TLS target, exact configured Origin/Fetch Metadata/CSRF before forwarding, generated method/path allowlist, identity/forwarded headers stripped, explicit cookie/header forwarding, no redirect/no-store. Backend remains authority. GET restore blocked. | Scientific ownership/enforcement remains AUTH-09/11; maintain reviewed allowlist. | AUTH-09, AUTH-11 |
| public.metadata | Открытые metadata/education endpoints; личная AuthN не заявлена. | Явный public allowlist; безопасная проекция, лимит ответа и throttle для compute. | AUTH-01, AUTH-11 |
| renderer.service | No HTTP credential check; intended isolated sandbox, body/timeout/concurrency and output constraints. | Private service boundary + authenticated authorized caller/operation context; revoke/budget before job start and output. | AUTH-03, AUTH-11, AUTH-13, AUTH-14 |
| run.object | AUTH-03 shared context subject projection + existing authorize_run_access owner/tenant/unresolved continuity; incompatible credentials/research owner rejected before object gate. Legacy ADMIN object bypass remains AUTH-09. AUTH-09: explicit Account/tenant boundary before ADMIN/dev/creator cookie; owner_subject provenance. Named legacy write requires migration. | Authenticated account context + current tenant/object permission; uniform 404; controlled legacy migration. | AUTH-03, AUTH-09, AUTH-11 |
| scientific.operation | AUTH-11 protected required/scoped: named browser session or durable scoped programmatic key, current Account/membership, existing run/session object policy before commercial decision. ScientificRoute before body parsing; router dependency normalizes actual workload; request execution fence rechecks kernel inputs. Baseline allowlist/bounds, actual saved model provenance on scientific result reads, no role-derived plan upgrade. Legacy dev compatibility is not production authority. Global legacy rules PATCH and train placeholder refuse protected execution. | Preserve one identity/object/functional policy path; AUTH-14 PELT/tuning use bounded metering/atomic reservations when protected; extend operational acceptance and other priced operations separately. Service progress/DOCLOG retain existing metadata semantics. | AUTH-12, AUTH-13, AUTH-20 |
| storage.internal | Internal file/object/DB operation; content hash/path/registry checks are not user authentication. | Reach only via authorized object service; trusted roots/keys, no direct filesystem mount or public object ACL. | AUTH-09, AUTH-11, AUTH-13, AUTH-20 |
| task.alias | Four UI application hrefs; causes has live backend data, other task views do not imply ready compute. | Canonical application-stage gate including aliases; scientific EDA Granger/DOCLOG monitoring are distinct. | AUTH-01, AUTH-11 |
| ui.admin | AUTH-07: common admin UI in both shells (/admin, /admin/progress, /admin/logs; AdminGate + session-based dashboards, no browser API-key); named session checked via /api/v1/auth/me, final role/MFA enforcement server-side. | Named ADMIN+MFA and common admin UI in both shells; OWNER/analyst cannot elevate by URL. | AUTH-05, AUTH-06, AUTH-07 |
| ui.login | AUTH-06 shared personal login/MFA/recovery and safe generated me DTO; no token URL/storage, exact local return_to, top-level login for framed context. API authority mandatory. | Named admin pages and account lifecycle remain AUTH-07/08. | AUTH-07, AUTH-08 |
| ui.page | Page component/navigation/redirect, no common personal AuthN gate; UI is not an authority. | UI handles auth/denial/account switch; backend independently enforces operation policy. | AUTH-01, AUTH-06, AUTH-11 |
| worker.authority | AUTH-13/14 protected workers use durable service credentials, current delegated authority, finite subprocess/lease/deadline, fences, transactional projection/settle/audit and positive-stop reconciliation. Optional measured CU quote is pinned at admission; unknown outcomes retain holds. No monetary wallet/automatic commercial launch. | Service credential/context where remote; recheck account/grant/revoke/reservation/deadline, fence settle/publication. | AUTH-03, AUTH-12, AUTH-13, AUTH-16, AUTH-20 |

## api

| ID / метод и путь | Operation / stage | Policy / resource | Источник |
|---|---|---|---|
| api:GET:/health | apps.api.main:health / service:platform | public.metadata / request metadata | apps/api/main.py:261 |
| api:GET:/health/ops | apps.api.main:health_ops / service:platform | ops.diagnostics / safe ops projection | apps/api/main.py:266 |
| api:GET:/v1/api-keys | apps.api.routers.api_keys:list_api_keys / service:platform | auth.api_keys / own API keys in current session Account | apps/api/routers/api_keys.py:33 |
| api:GET:/v1/auth/csrf | apps.api.routers.authentication:csrf / service:platform | auth.entry / self authentication session | apps/api/routers/authentication.py:134 |
| api:GET:/v1/auth/me | apps.api.routers.authentication:me / service:platform | auth.session / self authentication session | apps/api/routers/authentication.py:191 |
| api:GET:/v1/auth/sessions | apps.api.routers.authentication:sessions / service:platform | auth.session / self authentication session | apps/api/routers/authentication.py:220 |
| api:GET:/v1/documentation/documents/{document_id}/revisions | apps.api.routers.documentation:list_document_revisions / service:documentation | document.object / run/document/revision/rendition/job/profile | apps/api/routers/documentation.py:559 |
| api:GET:/v1/documentation/jobs/{job_id} | apps.api.routers.documentation:get_job / service:documentation | document.object / run/document/revision/rendition/job/profile | apps/api/routers/documentation.py:748 |
| api:GET:/v1/documentation/org-profiles | apps.api.routers.doc_profiles:list_org_profiles / service:documentation | document.object / run/document/revision/rendition/job/profile | apps/api/routers/doc_profiles.py:60 |
| api:GET:/v1/documentation/renditions/{rendition_id}/content | apps.api.routers.documentation:get_rendition_content / service:documentation | document.object / run/document/revision/rendition/job/profile | apps/api/routers/documentation.py:780 |
| api:GET:/v1/documentation/renditions/{rendition_id}/validations | apps.api.routers.doc_profiles:list_rendition_validations / service:documentation | document.object / run/document/revision/rendition/job/profile | apps/api/routers/doc_profiles.py:180 |
| api:GET:/v1/documentation/revisions/{revision_id} | apps.api.routers.documentation:get_revision / service:documentation | document.object / run/document/revision/rendition/job/profile | apps/api/routers/documentation.py:581 |
| api:GET:/v1/documentation/revisions/{revision_id}/diff | apps.api.routers.documentation:revision_diff / service:documentation | document.object / run/document/revision/rendition/job/profile | apps/api/routers/documentation.py:1012 |
| api:GET:/v1/documentation/revisions/{revision_id}/lifecycle | apps.api.routers.documentation:revision_lifecycle / service:documentation | document.object / run/document/revision/rendition/job/profile | apps/api/routers/documentation.py:993 |
| api:GET:/v1/documentation/revisions/{revision_id}/preview | apps.api.routers.documentation:get_revision_preview / service:documentation | document.object / run/document/revision/rendition/job/profile | apps/api/routers/documentation.py:604 |
| api:GET:/v1/documentation/runs/{run_id}/documents | apps.api.routers.documentation:list_documents / service:documentation | document.object / run/document/revision/rendition/job/profile | apps/api/routers/documentation.py:411 |
| api:GET:/v1/documentation/runs/{run_id}/monitoring/actuals | apps.api.routers.monitoring:list_actuals / service:documentation | document.object / run/document/revision/rendition/job/profile | apps/api/routers/monitoring.py:145 |
| api:GET:/v1/documentation/runs/{run_id}/monitoring/comparisons | apps.api.routers.monitoring:list_comparisons / service:documentation | document.object / run/document/revision/rendition/job/profile | apps/api/routers/monitoring.py:189 |
| api:GET:/v1/documentation/runs/{run_id}/monitoring/comparisons/{comparison_id} | apps.api.routers.monitoring:get_comparison / service:documentation | document.object / run/document/revision/rendition/job/profile | apps/api/routers/monitoring.py:203 |
| api:GET:/v1/documentation/runs/{run_id}/monitoring/comparisons/{comparison_id}/decisions | apps.api.routers.monitoring:list_decisions / service:documentation | document.object / run/document/revision/rendition/job/profile | apps/api/routers/monitoring.py:246 |
| api:GET:/v1/documentation/runs/{run_id}/visual-sources | apps.api.routers.documentation:list_visual_sources_route / service:documentation | document.object / run/document/revision/rendition/job/profile | apps/api/routers/documentation.py:1116 |
| api:GET:/v1/internal/rules/load/{template_id} | apps.api.routers.internal:load_rules_template / scientific:validation | scientific.operation / server rule template / module-global override (not Account scoped) | apps/api/routers/internal.py:113 |
| api:GET:/v1/internal/rules/templates | apps.api.routers.internal:get_rules_templates / scientific:validation | scientific.operation / server rule template / module-global override (not Account scoped) | apps/api/routers/internal.py:108 |
| api:GET:/v1/knowledge/articles | apps.api.knowledge.router:get_articles / service:education | public.metadata / public knowledge registry | apps/api/knowledge/router.py:143 |
| api:GET:/v1/knowledge/glossary | apps.api.knowledge.router:get_glossary / service:education | public.metadata / public knowledge registry | apps/api/knowledge/router.py:203 |
| api:GET:/v1/logs/access | apps.api.routers.logs:get_log_access / service:observability | logs.scoped / audit/telemetry/delivery/support grant | apps/api/routers/logs.py:148 |
| api:GET:/v1/logs/audit | apps.api.routers.logs:get_audit_logs / service:observability | logs.scoped / audit/telemetry/delivery/support grant | apps/api/routers/logs.py:234 |
| api:GET:/v1/logs/delivery | apps.api.routers.logs:get_delivery_logs / service:observability | logs.scoped / audit/telemetry/delivery/support grant | apps/api/routers/logs.py:276 |
| api:GET:/v1/logs/grants | apps.api.routers.logs:list_grants / service:observability | logs.scoped / audit/telemetry/delivery/support grant | apps/api/routers/logs.py:420 |
| api:GET:/v1/logs/telemetry | apps.api.routers.logs:get_telemetry_logs / service:observability | logs.scoped / audit/telemetry/delivery/support grant | apps/api/routers/logs.py:192 |
| api:GET:/v1/progress/admin/case-bank/candidates | apps.api.routers.progress:get_case_bank_candidates / service:observability | admin.key / admin cross-run projection | apps/api/routers/progress.py:2552 |
| api:GET:/v1/progress/admin/overview | apps.api.routers.progress:get_admin_overview / service:observability | admin.key / admin cross-run projection | apps/api/routers/progress.py:2504 |
| api:GET:/v1/progress/runs/{run_id} | apps.api.routers.progress:get_run_detail / service:platform | scientific.operation / run/checkpoint/delivery/report | apps/api/routers/progress.py:1284 |
| api:GET:/v1/progress/runs/{run_id}/delivery | apps.api.routers.progress:list_run_delivery / service:platform | scientific.operation / run/checkpoint/delivery/report | apps/api/routers/progress.py:1787 |
| api:GET:/v1/progress/runs/{run_id}/delivery/{operation_id} | apps.api.routers.progress:get_operation_delivery / service:platform | scientific.operation / run/checkpoint/delivery/report | apps/api/routers/progress.py:1824 |
| api:GET:/v1/progress/runs/{run_id}/mentor/next-step | apps.api.routers.progress:get_mentor_next_step / service:platform | scientific.operation / run/checkpoint/delivery/report | apps/api/routers/progress.py:2167 |
| api:GET:/v1/progress/runs/{run_id}/report | apps.api.routers.progress:get_run_report / service:platform | scientific.operation / run/checkpoint/delivery/report | apps/api/routers/progress.py:2268 |
| api:GET:/v1/progress/runs/{run_id}/restore | apps.api.routers.progress:restore_run / service:platform | scientific.operation / run/checkpoint/delivery/report | apps/api/routers/progress.py:1509 |
| api:GET:/v1/progress/trace | apps.api.routers.progress:get_progress_trace / service:platform | scientific.operation / session-bound trace/observation | apps/api/routers/progress.py:392 |
| api:GET:/v1/public/rules/load/{template_id} | apps.api.routers.public:load_rules_template / scientific:validation | scientific.operation / server rule template / module-global override (not Account scoped) | apps/api/routers/public.py:106 |
| api:GET:/v1/public/rules/templates | apps.api.routers.public:get_rules_templates / scientific:validation | scientific.operation / server rule template / module-global override (not Account scoped) | apps/api/routers/public.py:100 |
| api:GET:/v1/session/current | apps.api.routers.session:get_current_session / service:platform | scientific.operation / research session and dataset | apps/api/routers/session.py:594 |
| api:GET:/v1/session/dataset | apps.api.routers.session:get_session_dataset / service:platform | scientific.operation / research session and dataset | apps/api/routers/session.py:665 |
| api:GET:/v1/session/dataset/consistency-profile | apps.api.routers.session:get_dataset_consistency_profile / scientific:validation | scientific.operation / research session and dataset | apps/api/routers/session.py:4840 |
| api:GET:/v1/session/dataset/decomposition | apps.api.routers.session:get_dataset_decomposition / scientific:upload | scientific.operation / research session and dataset | apps/api/routers/session.py:1802 |
| api:GET:/v1/session/dataset/decomposition-series | apps.api.routers.session:get_dataset_decomposition_series / scientific:upload | scientific.operation / research session and dataset | apps/api/routers/session.py:1842 |
| api:GET:/v1/session/dataset/derived-columns | apps.api.routers.session:get_dataset_derived_columns / scientific:upload | scientific.operation / research session and dataset | apps/api/routers/session.py:763 |
| api:GET:/v1/session/dataset/distribution | apps.api.routers.session:get_dataset_distribution / scientific:upload | scientific.operation / research session and dataset | apps/api/routers/session.py:1571 |
| api:GET:/v1/session/dataset/eda-correlation | apps.api.routers.session:get_dataset_eda_correlation / scientific:eda | scientific.operation / research session and dataset | apps/api/routers/session.py:958 |
| api:GET:/v1/session/dataset/eda-distribution | apps.api.routers.session:get_dataset_eda_distribution / scientific:eda | scientific.operation / research session and dataset | apps/api/routers/session.py:1107 |
| api:GET:/v1/session/dataset/eda-feature-selection | apps.api.routers.session:get_dataset_eda_feature_selection / scientific:eda | scientific.operation / research session and dataset | apps/api/routers/session.py:1189 |
| api:GET:/v1/session/dataset/eda-ih | apps.api.routers.session:get_dataset_eda_ih / scientific:eda | scientific.operation / research session and dataset | apps/api/routers/session.py:991 |
| api:GET:/v1/session/dataset/eda-model-matrix | apps.api.routers.session:get_dataset_eda_model_matrix / scientific:eda | scientific.operation / research session and dataset | apps/api/routers/session.py:1267 |
| api:GET:/v1/session/dataset/eda-seasonality | apps.api.routers.session:get_dataset_eda_seasonality / scientific:eda | scientific.operation / research session and dataset | apps/api/routers/session.py:1033 |
| api:GET:/v1/session/dataset/eda-stationarity | apps.api.routers.session:get_dataset_eda_stationarity / scientific:eda | scientific.operation / research session and dataset | apps/api/routers/session.py:1070 |
| api:GET:/v1/session/dataset/eda-structural-breaks | apps.api.routers.session:get_dataset_eda_structural_breaks / scientific:eda | scientific.operation / research session and dataset | apps/api/routers/session.py:1144 |
| api:GET:/v1/session/dataset/eda-validation-strategy | apps.api.routers.session:get_dataset_eda_validation_strategy / scientific:eda | scientific.operation / research session and dataset | apps/api/routers/session.py:1221 |
| api:GET:/v1/session/dataset/format-profile | apps.api.routers.session:get_dataset_format_profile / scientific:validation | scientific.operation / research session and dataset | apps/api/routers/session.py:2208 |
| api:GET:/v1/session/dataset/inclusion-profile | apps.api.routers.session:get_dataset_inclusion_profile / scientific:validation | scientific.operation / research session and dataset | apps/api/routers/session.py:3442 |
| api:GET:/v1/session/dataset/missing-correlation | apps.api.routers.session:get_dataset_missing_correlation / scientific:upload | scientific.operation / research session and dataset | apps/api/routers/session.py:2515 |
| api:GET:/v1/session/dataset/missing-distribution | apps.api.routers.session:get_dataset_missing_distribution / scientific:upload | scientific.operation / research session and dataset | apps/api/routers/session.py:2535 |
| api:GET:/v1/session/dataset/missing-editor-rows | apps.api.routers.session:get_dataset_missing_editor_rows / scientific:upload | scientific.operation / research session and dataset | apps/api/routers/session.py:2655 |
| api:GET:/v1/session/dataset/missing-matrix | apps.api.routers.session:get_dataset_missing_matrix / scientific:upload | scientific.operation / research session and dataset | apps/api/routers/session.py:2492 |
| api:GET:/v1/session/dataset/missing-profile | apps.api.routers.session:get_dataset_missing_profile / scientific:validation | scientific.operation / research session and dataset | apps/api/routers/session.py:2385 |
| api:GET:/v1/session/dataset/outlier-boxplot | apps.api.routers.session:get_dataset_outlier_boxplot / scientific:upload | scientific.operation / research session and dataset | apps/api/routers/session.py:3408 |
| api:GET:/v1/session/dataset/outlier-density | apps.api.routers.session:get_dataset_outlier_density / scientific:upload | scientific.operation / research session and dataset | apps/api/routers/session.py:3391 |
| api:GET:/v1/session/dataset/outlier-editor-rows | apps.api.routers.session:get_dataset_outlier_editor_rows / scientific:upload | scientific.operation / research session and dataset | apps/api/routers/session.py:2890 |
| api:GET:/v1/session/dataset/outlier-histogram | apps.api.routers.session:get_dataset_outlier_histogram / scientific:upload | scientific.operation / research session and dataset | apps/api/routers/session.py:3358 |
| api:GET:/v1/session/dataset/outlier-line | apps.api.routers.session:get_dataset_outlier_line / scientific:upload | scientific.operation / research session and dataset | apps/api/routers/session.py:3309 |
| api:GET:/v1/session/dataset/outlier-profile | apps.api.routers.session:get_dataset_outlier_profile / scientific:validation | scientific.operation / research session and dataset | apps/api/routers/session.py:3108 |
| api:GET:/v1/session/dataset/panel-balance | apps.api.routers.session:get_panel_balance / scientific:upload | scientific.operation / research session and dataset | apps/api/routers/session.py:1307 |
| api:GET:/v1/session/dataset/passport/compare | apps.api.routers.session:compare_dataset_passports / scientific:upload | scientific.operation / research session and dataset | apps/api/routers/session.py:5978 |
| api:GET:/v1/session/dataset/passport/status | apps.api.routers.session:get_dataset_passport_status / scientific:upload | scientific.operation / research session and dataset | apps/api/routers/session.py:5934 |
| api:GET:/v1/session/dataset/preprocessing-check-modes | apps.api.routers.session:get_dataset_preprocessing_check_modes / scientific:preprocessing | scientific.operation / research session and dataset | apps/api/routers/session.py:2439 |
| api:GET:/v1/session/dataset/preprocessing/decomposition-profile | apps.api.routers.session:get_dataset_preprocessing_decomposition_profile / scientific:preprocessing | scientific.operation / research session and dataset | apps/api/routers/session.py:3948 |
| api:GET:/v1/session/dataset/preprocessing/feature-generation-profile | apps.api.routers.session:get_dataset_preprocessing_feature_generation_profile / scientific:preprocessing | scientific.operation / research session and dataset | apps/api/routers/session.py:4530 |
| api:GET:/v1/session/dataset/preprocessing/regularity-intervals | apps.api.routers.session:get_dataset_preprocessing_regularity_intervals / scientific:preprocessing | scientific.operation / research session and dataset | apps/api/routers/session.py:3844 |
| api:GET:/v1/session/dataset/preprocessing/regularity-profile | apps.api.routers.session:get_dataset_preprocessing_regularity_profile / scientific:preprocessing | scientific.operation / research session and dataset | apps/api/routers/session.py:3802 |
| api:GET:/v1/session/dataset/preprocessing/regularity-timeline | apps.api.routers.session:get_dataset_preprocessing_regularity_timeline / scientific:preprocessing | scientific.operation / research session and dataset | apps/api/routers/session.py:3863 |
| api:GET:/v1/session/dataset/preprocessing/scaling-profile | apps.api.routers.session:get_dataset_preprocessing_scaling_profile / scientific:preprocessing | scientific.operation / research session and dataset | apps/api/routers/session.py:4654 |
| api:GET:/v1/session/dataset/preprocessing/smoothing-profile | apps.api.routers.session:get_dataset_preprocessing_smoothing_profile / scientific:preprocessing | scientific.operation / research session and dataset | apps/api/routers/session.py:4183 |
| api:GET:/v1/session/dataset/preprocessing/spectral-profile | apps.api.routers.session:get_dataset_preprocessing_spectral_profile / scientific:preprocessing | scientific.operation / research session and dataset | apps/api/routers/session.py:4434 |
| api:GET:/v1/session/dataset/preprocessing/stationarity-profile | apps.api.routers.session:get_dataset_preprocessing_stationarity_profile / scientific:preprocessing | scientific.operation / research session and dataset | apps/api/routers/session.py:4314 |
| api:GET:/v1/session/dataset/preprocessing/variance-profile | apps.api.routers.session:get_dataset_preprocessing_variance_profile / scientific:preprocessing | scientific.operation / research session and dataset | apps/api/routers/session.py:4071 |
| api:GET:/v1/session/dataset/range-profile | apps.api.routers.session:get_dataset_range_profile / scientific:validation | scientific.operation / research session and dataset | apps/api/routers/session.py:2298 |
| api:GET:/v1/session/dataset/referential-profile | apps.api.routers.session:get_dataset_referential_profile / scientific:validation | scientific.operation / research session and dataset | apps/api/routers/session.py:3529 |
| api:GET:/v1/session/dataset/regularity-profile | apps.api.routers.session:get_dataset_regularity_profile / scientific:validation | scientific.operation / research session and dataset | apps/api/routers/session.py:3716 |
| api:GET:/v1/session/dataset/rows | apps.api.routers.session:get_dataset_rows / scientific:upload | scientific.operation / research session and dataset | apps/api/routers/session.py:717 |
| api:GET:/v1/session/dataset/stats | apps.api.routers.session:get_dataset_stats / scientific:upload | scientific.operation / research session and dataset | apps/api/routers/session.py:897 |
| api:GET:/v1/session/dataset/structure-detection | apps.api.routers.session:get_structure_detection / scientific:upload | scientific.operation / research session and dataset | apps/api/routers/session.py:1692 |
| api:GET:/v1/session/dataset/sufficiency-profile | apps.api.routers.session:get_dataset_sufficiency_profile / scientific:validation | scientific.operation / research session and dataset | apps/api/routers/session.py:4737 |
| api:GET:/v1/session/dataset/text-quality-profile | apps.api.routers.session:get_dataset_text_quality_profile / scientific:validation | scientific.operation / research session and dataset | apps/api/routers/session.py:3623 |
| api:GET:/v1/session/dataset/timeseries | apps.api.routers.session:get_dataset_timeseries / scientific:upload | scientific.operation / research session and dataset | apps/api/routers/session.py:1755 |
| api:GET:/v1/session/dataset/uniqueness-profile | apps.api.routers.session:get_dataset_uniqueness_profile / scientific:validation | scientific.operation / research session and dataset | apps/api/routers/session.py:4931 |
| api:GET:/v1/session/dataset/validate | apps.api.routers.session:get_dataset_validate / scientific:upload | scientific.operation / research session and dataset | apps/api/routers/session.py:1924 |
| api:GET:/v1/session/dataset/validation-check-modes | apps.api.routers.session:get_dataset_validation_check_modes / scientific:validation | scientific.operation / research session and dataset | apps/api/routers/session.py:2157 |
| api:GET:/v1/session/dataset/validation-rules | apps.api.routers.session:get_dataset_validation_rules / scientific:validation | scientific.operation / research session and dataset | apps/api/routers/session.py:2146 |
| api:GET:/v1/session/date-column | apps.api.routers.session:get_date_column / service:platform | scientific.operation / research session and dataset | apps/api/routers/session.py:5760 |
| api:GET:/v1/session/modeling/card | apps.api.routers.modeling_session:list_model_cards / scientific:modeling | scientific.operation / session model/job/card/forecast | apps/api/routers/modeling_session.py:3339 |
| api:GET:/v1/session/modeling/card/{card_id} | apps.api.routers.modeling_session:get_model_card / scientific:modeling | scientific.operation / session model/job/card/forecast | apps/api/routers/modeling_session.py:3362 |
| api:GET:/v1/session/modeling/context | apps.api.routers.modeling_session:get_modeling_context / scientific:modeling | scientific.operation / session model/job/card/forecast | apps/api/routers/modeling_session.py:1040 |
| api:GET:/v1/session/modeling/feature-regressors | apps.api.routers.modeling_session:get_modeling_feature_regressors / scientific:modeling | scientific.operation / session model/job/card/forecast | apps/api/routers/modeling_session.py:1110 |
| api:GET:/v1/session/modeling/forecast | apps.api.routers.forecasting_session:list_forecasts / scientific:forecasting | scientific.operation / session model/job/card/forecast | apps/api/routers/forecasting_session.py:376 |
| api:GET:/v1/session/modeling/forecast/{forecast_id} | apps.api.routers.forecasting_session:get_forecast / scientific:forecasting | scientific.operation / session model/job/card/forecast | apps/api/routers/forecasting_session.py:384 |
| api:GET:/v1/session/modeling/forecast/{forecast_id}/export.csv | apps.api.routers.forecasting_session:export_forecast_csv / scientific:forecasting | scientific.operation / session model/job/card/forecast | apps/api/routers/forecasting_session.py:429 |
| api:GET:/v1/session/modeling/forecast/{forecast_id}/export.json | apps.api.routers.forecasting_session:export_forecast_json / scientific:forecasting | scientific.operation / session model/job/card/forecast | apps/api/routers/forecasting_session.py:442 |
| api:GET:/v1/session/modeling/jobs/{job_id} | apps.api.routers.modeling_session:get_modeling_job / scientific:modeling | scientific.operation / persisted tuning job/plan (operation Literal tuning), session context | apps/api/routers/modeling_session.py:2178 |
| api:GET:/v1/session/modeling/panel/candidates | apps.api.routers.modeling_session:panel_candidates / scientific:modeling | scientific.operation / session model/job/card/forecast | apps/api/routers/modeling_session.py:3610 |
| api:GET:/v1/session/modeling/state | apps.api.routers.modeling_session:get_modeling_state / scientific:modeling | scientific.operation / session model/job/card/forecast | apps/api/routers/modeling_session.py:1192 |
| api:GET:/v1/session/target-column | apps.api.routers.session:get_target_column / service:platform | scientific.operation / research session and dataset | apps/api/routers/session.py:5607 |
| api:GET:/v1/session/tasks/causes | apps.api.routers.tasks_session:get_tasks_causes / application:causal | scientific.operation / session Model Card and fold importance | apps/api/routers/tasks_session.py:222 |
| api:PATCH:/v1/internal/rules/update | apps.api.routers.internal:update_rules / scientific:validation | scientific.operation / server rule template / module-global override (not Account scoped) | apps/api/routers/internal.py:167 |
| api:PATCH:/v1/public/rules/update | apps.api.routers.public:update_rules / scientific:validation | scientific.operation / server rule template / module-global override (not Account scoped) | apps/api/routers/public.py:165 |
| api:POST:/v1/api-keys | apps.api.routers.api_keys:issue_api_key / service:platform | auth.api_keys / own API keys in current session Account | apps/api/routers/api_keys.py:39 |
| api:POST:/v1/api-keys/{key_id}/revoke | apps.api.routers.api_keys:revoke_api_key / service:platform | auth.api_keys / own API keys in current session Account | apps/api/routers/api_keys.py:53 |
| api:POST:/v1/api-keys/{key_id}/rotate | apps.api.routers.api_keys:rotate_api_key / service:platform | auth.api_keys / own API keys in current session Account | apps/api/routers/api_keys.py:46 |
| api:POST:/v1/auth/login | apps.api.routers.authentication:login / service:platform | auth.entry / self authentication session | apps/api/routers/authentication.py:150 |
| api:POST:/v1/auth/logout | apps.api.routers.authentication:logout / service:platform | auth.session / self authentication session | apps/api/routers/authentication.py:228 |
| api:POST:/v1/auth/mfa/enroll | apps.api.routers.authentication:mfa_enroll / service:platform | auth.mfa.entry / self MFA credential or scoped challenge | apps/api/routers/authentication.py:286 |
| api:POST:/v1/auth/mfa/replace | apps.api.routers.authentication:mfa_replace / service:platform | auth.mfa.session / self MFA credential or scoped challenge | apps/api/routers/authentication.py:331 |
| api:POST:/v1/auth/mfa/verify | apps.api.routers.authentication:mfa_verify / service:platform | auth.mfa.entry / self MFA credential or scoped challenge | apps/api/routers/authentication.py:299 |
| api:POST:/v1/auth/password | apps.api.routers.authentication:change_password / service:platform | auth.session / self authentication session | apps/api/routers/authentication.py:254 |
| api:POST:/v1/auth/recovery | apps.api.routers.authentication:recovery / service:platform | auth.mfa.entry / self MFA credential or scoped challenge | apps/api/routers/authentication.py:344 |
| api:POST:/v1/auth/recovery/rotate | apps.api.routers.authentication:recovery_rotate / service:platform | auth.mfa.session / self MFA credential or scoped challenge | apps/api/routers/authentication.py:356 |
| api:POST:/v1/auth/sessions/revoke-all | apps.api.routers.authentication:revoke_all / service:platform | auth.session / self authentication session | apps/api/routers/authentication.py:235 |
| api:POST:/v1/auth/sessions/{session_id}/revoke | apps.api.routers.authentication:revoke / service:platform | auth.session / self authentication session | apps/api/routers/authentication.py:244 |
| api:POST:/v1/auth/step-up | apps.api.routers.authentication:step_up / service:platform | auth.mfa.session / self MFA credential or scoped challenge | apps/api/routers/authentication.py:317 |
| api:POST:/v1/documentation/documents/{document_id}/retention | apps.api.routers.documentation:document_retention / service:documentation | document.object / run/document/revision/rendition/job/profile | apps/api/routers/documentation.py:1035 |
| api:POST:/v1/documentation/jobs/{job_id}/cancel | apps.api.routers.documentation:cancel_job / service:documentation | document.object / run/document/revision/rendition/job/profile | apps/api/routers/documentation.py:761 |
| api:POST:/v1/documentation/org-profiles | apps.api.routers.doc_profiles:create_org_profile / service:documentation | profile.policy / run/document/revision/rendition/job/profile | apps/api/routers/doc_profiles.py:86 |
| api:POST:/v1/documentation/org-profiles/{profile_id}/retire | apps.api.routers.doc_profiles:retire_org_profile / service:documentation | profile.policy / run/document/revision/rendition/job/profile | apps/api/routers/doc_profiles.py:134 |
| api:POST:/v1/documentation/print-revisions/{print_revision_id}/renditions | apps.api.routers.documentation:request_print_rendition / service:documentation | document.object / run/document/revision/rendition/job/profile | apps/api/routers/documentation.py:696 |
| api:POST:/v1/documentation/renditions/{rendition_id}/verify-signature | apps.api.routers.doc_profiles:verify_rendition_signature / service:documentation | document.object / run/document/revision/rendition/job/profile | apps/api/routers/doc_profiles.py:220 |
| api:POST:/v1/documentation/revisions/{revision_id}/approvals | apps.api.routers.documentation:revision_approvals / service:documentation | document.object / run/document/revision/rendition/job/profile | apps/api/routers/documentation.py:877 |
| api:POST:/v1/documentation/revisions/{revision_id}/publish | apps.api.routers.documentation:revision_publish / service:documentation | document.object / run/document/revision/rendition/job/profile | apps/api/routers/documentation.py:928 |
| api:POST:/v1/documentation/revisions/{revision_id}/renditions | apps.api.routers.documentation:request_rendition / service:documentation | document.object / run/document/revision/rendition/job/profile | apps/api/routers/documentation.py:642 |
| api:POST:/v1/documentation/revisions/{revision_id}/retract | apps.api.routers.documentation:revision_retract / service:documentation | document.object / run/document/revision/rendition/job/profile | apps/api/routers/documentation.py:961 |
| api:POST:/v1/documentation/runs/{run_id}/archive | apps.api.routers.documentation:archive_run / service:documentation | document.object / run/document/revision/rendition/job/profile | apps/api/routers/documentation.py:1076 |
| api:POST:/v1/documentation/runs/{run_id}/archive/verify | apps.api.routers.documentation:archive_verify / service:documentation | document.object / run/document/revision/rendition/job/profile | apps/api/routers/documentation.py:1092 |
| api:POST:/v1/documentation/runs/{run_id}/documents | apps.api.routers.documentation:create_document_draft / service:documentation | document.object / run/document/revision/rendition/job/profile | apps/api/routers/documentation.py:458 |
| api:POST:/v1/documentation/runs/{run_id}/monitoring/actuals | apps.api.routers.monitoring:register_actuals / service:documentation | document.object / run/document/revision/rendition/job/profile | apps/api/routers/monitoring.py:116 |
| api:POST:/v1/documentation/runs/{run_id}/monitoring/comparisons | apps.api.routers.monitoring:create_comparison / service:documentation | document.object / run/document/revision/rendition/job/profile | apps/api/routers/monitoring.py:162 |
| api:POST:/v1/documentation/runs/{run_id}/monitoring/comparisons/{comparison_id}/decisions | apps.api.routers.monitoring:create_decision / service:documentation | document.object / run/document/revision/rendition/job/profile | apps/api/routers/monitoring.py:219 |
| api:POST:/v1/documentation/runs/{run_id}/retention/sweep | apps.api.routers.documentation:retention_sweep / service:documentation | document.object / run/document/revision/rendition/job/profile | apps/api/routers/documentation.py:1060 |
| api:POST:/v1/documentation/runs/{run_id}/visuals | apps.api.routers.documentation:request_visual_export_route / service:documentation | document.object / run/document/revision/rendition/job/profile | apps/api/routers/documentation.py:1137 |
| api:POST:/v1/internal/models/backtest | apps.api.routers.internal:run_backtest_internal / scientific:modeling | scientific.operation / submitted data / research session / rule namespace | apps/api/routers/internal.py:201 |
| api:POST:/v1/internal/models/candidates | apps.api.routers.internal:get_candidates_internal / scientific:modeling | scientific.operation / submitted data / research session / rule namespace | apps/api/routers/internal.py:309 |
| api:POST:/v1/internal/models/diagnostics | apps.api.routers.diagnostics_internal:run_internal_diagnostics / scientific:modeling | scientific.operation / submitted data / research session / rule namespace | apps/api/routers/diagnostics_internal.py:33 |
| api:POST:/v1/internal/passport | apps.api.routers.internal:get_passport / scientific:validation | scientific.operation / submitted data / research session / rule namespace | apps/api/routers/internal.py:43 |
| api:POST:/v1/internal/regularity | apps.api.routers.internal:get_regularity / scientific:validation | scientific.operation / submitted data / research session / rule namespace | apps/api/routers/internal.py:53 |
| api:POST:/v1/internal/rules/validate | apps.api.routers.internal:validate_with_rules / scientific:validation | scientific.operation / server rule template / module-global override (not Account scoped) | apps/api/routers/internal.py:145 |
| api:POST:/v1/internal/upload | apps.api.routers.internal:upload_file / scientific:upload | scientific.operation / submitted data / research session / rule namespace | apps/api/routers/internal.py:69 |
| api:POST:/v1/internal/upload/db/load | apps.api.routers.upload_db:_register.load_db_dataset / scientific:upload | scientific.operation / submitted data / research session / rule namespace | apps/api/routers/upload_db.py:186 |
| api:POST:/v1/internal/upload/db/test | apps.api.routers.upload_db:_register.test_db_connection / scientific:upload | scientific.operation / submitted data / research session / rule namespace | apps/api/routers/upload_db.py:150 |
| api:POST:/v1/learning/track | apps.api.knowledge.router:build_learning_track / service:education | public.metadata / public knowledge registry | apps/api/knowledge/router.py:228 |
| api:POST:/v1/logs/export | apps.api.routers.logs:export_logs_bundle / service:observability | logs.scoped / audit/telemetry/delivery/support grant | apps/api/routers/logs.py:320 |
| api:POST:/v1/logs/grants | apps.api.routers.logs:create_grant / service:observability | logs.scoped / audit/telemetry/delivery/support grant | apps/api/routers/logs.py:436 |
| api:POST:/v1/logs/grants/{grant_id}/revoke | apps.api.routers.logs:revoke_grant / service:observability | logs.scoped / audit/telemetry/delivery/support grant | apps/api/routers/logs.py:481 |
| api:POST:/v1/models/backtest | apps.api.routers.models:run_backtest / scientific:modeling | scientific.operation / submitted/model dataset and model selection | apps/api/routers/models.py:636 |
| api:POST:/v1/models/candidates | apps.api.routers.models:get_candidates / scientific:modeling | scientific.operation / submitted/model dataset and model selection | apps/api/routers/models.py:101 |
| api:POST:/v1/models/diagnostics | apps.api.routers.diagnostics:run_diagnostics / scientific:modeling | scientific.operation / submitted/model dataset and model selection | apps/api/routers/diagnostics.py:208 |
| api:POST:/v1/models/train | apps.api.routers.models:train_model / scientific:modeling | scientific.operation / placeholder accepted response; reflects raw ENV principal_id/API-key | apps/api/routers/models.py:730 |
| api:POST:/v1/models/tune | apps.api.routers.models:tune_model / scientific:modeling | scientific.operation / submitted/model dataset and model selection | apps/api/routers/models.py:742 |
| api:POST:/v1/progress/eda-checks | apps.api.routers.progress:report_eda_checks / service:platform | scientific.operation / session-bound trace/observation | apps/api/routers/progress.py:947 |
| api:POST:/v1/progress/mentor/sanity-check | apps.api.routers.progress:run_mentor_sanity_check / service:platform | scientific.operation / session-bound trace/observation | apps/api/routers/progress.py:2348 |
| api:POST:/v1/progress/preprocessing-checks | apps.api.routers.progress:report_preprocessing_checks / service:platform | scientific.operation / session-bound trace/observation | apps/api/routers/progress.py:817 |
| api:POST:/v1/progress/runs/{run_id}/checkpoints | apps.api.routers.progress:create_checkpoint / service:platform | scientific.operation / run/checkpoint/delivery/report | apps/api/routers/progress.py:1373 |
| api:POST:/v1/progress/runs/{run_id}/pause | apps.api.routers.progress:pause_run / service:platform | scientific.operation / run/checkpoint/delivery/report | apps/api/routers/progress.py:1312 |
| api:POST:/v1/progress/runs/{run_id}/restore | apps.api.routers.progress:restore_run / service:platform | scientific.operation / run/checkpoint/delivery/report | apps/api/routers/progress.py:1510 |
| api:POST:/v1/progress/runs/{run_id}/resume | apps.api.routers.progress:resume_run / service:platform | scientific.operation / run/checkpoint/delivery/report | apps/api/routers/progress.py:1346 |
| api:POST:/v1/progress/upload-stops | apps.api.routers.progress:report_upload_stops / service:platform | scientific.operation / session-bound trace/observation | apps/api/routers/progress.py:590 |
| api:POST:/v1/progress/validation-checks | apps.api.routers.progress:report_validation_checks / service:platform | scientific.operation / session-bound trace/observation | apps/api/routers/progress.py:700 |
| api:POST:/v1/public/passport | apps.api.routers.public:get_passport / scientific:validation | scientific.operation / submitted data / rule namespace | apps/api/routers/public.py:36 |
| api:POST:/v1/public/regularity | apps.api.routers.public:get_regularity / scientific:validation | scientific.operation / submitted data / rule namespace | apps/api/routers/public.py:46 |
| api:POST:/v1/public/rules/validate | apps.api.routers.public:validate_with_rules / scientific:validation | scientific.operation / server rule template / module-global override (not Account scoped) | apps/api/routers/public.py:141 |
| api:POST:/v1/public/upload | apps.api.routers.public:upload_file / scientific:upload | scientific.operation / submitted data / rule namespace | apps/api/routers/public.py:181 |
| api:POST:/v1/public/upload/db/load | apps.api.routers.upload_db:_register.load_db_dataset / scientific:upload | scientific.operation / submitted data / rule namespace | apps/api/routers/upload_db.py:186 |
| api:POST:/v1/public/upload/db/test | apps.api.routers.upload_db:_register.test_db_connection / scientific:upload | scientific.operation / submitted data / rule namespace | apps/api/routers/upload_db.py:150 |
| api:POST:/v1/session/dataset/consistency-corrections | apps.api.routers.session:correct_dataset_consistency / scientific:validation | scientific.operation / research session and dataset | apps/api/routers/session.py:4860 |
| api:POST:/v1/session/dataset/convert-types | apps.api.routers.session:convert_dataset_types / scientific:validation | scientific.operation / research session and dataset | apps/api/routers/session.py:5450 |
| api:POST:/v1/session/dataset/derived-columns/delete | apps.api.routers.session:delete_dataset_derived_columns / scientific:upload | scientific.operation / research session and dataset | apps/api/routers/session.py:808 |
| api:POST:/v1/session/dataset/entity-filter | apps.api.routers.session:filter_dataset_by_entity / scientific:upload | scientific.operation / research session and dataset | apps/api/routers/session.py:1362 |
| api:POST:/v1/session/dataset/format-corrections | apps.api.routers.session:correct_dataset_formats / scientific:validation | scientific.operation / research session and dataset | apps/api/routers/session.py:2227 |
| api:POST:/v1/session/dataset/inclusion-corrections | apps.api.routers.session:correct_dataset_inclusion / scientific:validation | scientific.operation / research session and dataset | apps/api/routers/session.py:3458 |
| api:POST:/v1/session/dataset/missing-corrections | apps.api.routers.session:correct_dataset_missing / scientific:validation | scientific.operation / research session and dataset | apps/api/routers/session.py:2556 |
| api:POST:/v1/session/dataset/missing-manual-corrections | apps.api.routers.session:apply_dataset_missing_manual_corrections / scientific:validation | scientific.operation / research session and dataset | apps/api/routers/session.py:2728 |
| api:POST:/v1/session/dataset/outlier-corrections | apps.api.routers.session:correct_dataset_outliers / scientific:validation | scientific.operation / research session and dataset | apps/api/routers/session.py:3178 |
| api:POST:/v1/session/dataset/outlier-manual-corrections | apps.api.routers.session:apply_dataset_outlier_manual_corrections / scientific:validation | scientific.operation / research session and dataset | apps/api/routers/session.py:2968 |
| api:POST:/v1/session/dataset/panel-aggregate | apps.api.routers.session:aggregate_dataset_by_date / scientific:upload | scientific.operation / research session and dataset | apps/api/routers/session.py:1476 |
| api:POST:/v1/session/dataset/passport/{stage} | apps.api.routers.session:capture_dataset_passport / scientific:upload | scientific.operation / research session and dataset | apps/api/routers/session.py:6098 |
| api:POST:/v1/session/dataset/preprocessing/decomposition-outputs | apps.api.routers.session:create_dataset_preprocessing_decomposition_outputs / scientific:preprocessing | scientific.operation / research session and dataset | apps/api/routers/session.py:4004 |
| api:POST:/v1/session/dataset/preprocessing/feature-generations | apps.api.routers.session:create_dataset_preprocessing_feature_generation / scientific:preprocessing | scientific.operation / research session and dataset | apps/api/routers/session.py:4575 |
| api:POST:/v1/session/dataset/preprocessing/regularity-corrections | apps.api.routers.session:correct_dataset_preprocessing_regularity / scientific:preprocessing | scientific.operation / research session and dataset | apps/api/routers/session.py:3886 |
| api:POST:/v1/session/dataset/preprocessing/scaling-recipes | apps.api.routers.session:create_dataset_preprocessing_scaling_recipe / scientific:preprocessing | scientific.operation / research session and dataset | apps/api/routers/session.py:4699 |
| api:POST:/v1/session/dataset/preprocessing/smoothing-transformations | apps.api.routers.session:create_dataset_preprocessing_smoothing_transformation / scientific:preprocessing | scientific.operation / research session and dataset | apps/api/routers/session.py:4240 |
| api:POST:/v1/session/dataset/preprocessing/spectral-selections | apps.api.routers.session:save_dataset_preprocessing_spectral_selection / scientific:preprocessing | scientific.operation / research session and dataset | apps/api/routers/session.py:4492 |
| api:POST:/v1/session/dataset/preprocessing/stationarity-transformations | apps.api.routers.session:create_dataset_preprocessing_stationarity_transformation / scientific:preprocessing | scientific.operation / research session and dataset | apps/api/routers/session.py:4368 |
| api:POST:/v1/session/dataset/preprocessing/variance-transformations | apps.api.routers.session:create_dataset_preprocessing_variance_transformation / scientific:preprocessing | scientific.operation / research session and dataset | apps/api/routers/session.py:4124 |
| api:POST:/v1/session/dataset/range-corrections | apps.api.routers.session:correct_dataset_ranges / scientific:validation | scientific.operation / research session and dataset | apps/api/routers/session.py:2317 |
| api:POST:/v1/session/dataset/referential-corrections | apps.api.routers.session:correct_dataset_referential / scientific:validation | scientific.operation / research session and dataset | apps/api/routers/session.py:3552 |
| api:POST:/v1/session/dataset/regularity-corrections | apps.api.routers.session:correct_dataset_regularity / scientific:validation | scientific.operation / research session and dataset | apps/api/routers/session.py:3742 |
| api:POST:/v1/session/dataset/sufficiency-plan | apps.api.routers.session:save_dataset_sufficiency_plan / scientific:validation | scientific.operation / research session and dataset | apps/api/routers/session.py:4767 |
| api:POST:/v1/session/dataset/text-quality-corrections | apps.api.routers.session:correct_dataset_text_quality / scientific:validation | scientific.operation / research session and dataset | apps/api/routers/session.py:3645 |
| api:POST:/v1/session/dataset/uniqueness-corrections | apps.api.routers.session:correct_dataset_uniqueness / scientific:validation | scientific.operation / research session and dataset | apps/api/routers/session.py:4950 |
| api:POST:/v1/session/date-column | apps.api.routers.session:set_date_column / service:platform | scientific.operation / research session and dataset | apps/api/routers/session.py:5768 |
| api:POST:/v1/session/demo | apps.api.routers.session:load_demo_dataset / scientific:upload | scientific.operation / bundled demo dataset; not AuthSession/DemoGrant/campaign entry | apps/api/routers/session.py:604 |
| api:POST:/v1/session/modeling/backtest | apps.api.routers.modeling_session:run_modeling_backtest / scientific:modeling | scientific.operation / session model/job/card/forecast | apps/api/routers/modeling_session.py:1404 |
| api:POST:/v1/session/modeling/backtest/exclude | apps.api.routers.modeling_session:decide_modeling_backtest_scope / scientific:modeling | scientific.operation / session model/job/card/forecast | apps/api/routers/modeling_session.py:1621 |
| api:POST:/v1/session/modeling/baselines | apps.api.routers.modeling_session:bootstrap_modeling_baselines / scientific:modeling | scientific.operation / session model/job/card/forecast | apps/api/routers/modeling_session.py:1292 |
| api:POST:/v1/session/modeling/candidates | apps.api.routers.modeling_session:generate_modeling_candidates / scientific:modeling | scientific.operation / session model/job/card/forecast | apps/api/routers/modeling_session.py:1216 |
| api:POST:/v1/session/modeling/card | apps.api.routers.modeling_session:create_model_card / scientific:modeling | scientific.operation / session model/job/card/forecast | apps/api/routers/modeling_session.py:3161 |
| api:POST:/v1/session/modeling/compare | apps.api.routers.modeling_session:compare_modeling_candidates / scientific:modeling | scientific.operation / session model/job/card/forecast | apps/api/routers/modeling_session.py:2828 |
| api:POST:/v1/session/modeling/diagnostics | apps.api.routers.modeling_session:diagnose_modeling_candidate / scientific:modeling | scientific.operation / session model/job/card/forecast | apps/api/routers/modeling_session.py:2767 |
| api:POST:/v1/session/modeling/diagnostics/ensure | apps.api.routers.modeling_session:ensure_modeling_diagnostics / scientific:modeling | scientific.operation / session model/job/card/forecast | apps/api/routers/modeling_session.py:2787 |
| api:POST:/v1/session/modeling/forecast | apps.api.routers.forecasting_session:create_forecast / scientific:forecasting | scientific.operation / session model/job/card/forecast | apps/api/routers/forecasting_session.py:209 |
| api:POST:/v1/session/modeling/forecast/compare | apps.api.routers.forecasting_session:compare_forecasts / scientific:forecasting | scientific.operation / session model/job/card/forecast | apps/api/routers/forecasting_session.py:466 |
| api:POST:/v1/session/modeling/forecast/{forecast_id}/sensitivity | apps.api.routers.forecasting_session:forecast_sensitivity / scientific:forecasting | scientific.operation / session model/job/card/forecast | apps/api/routers/forecasting_session.py:530 |
| api:POST:/v1/session/modeling/forecast/{forecast_id}/trace | apps.api.routers.forecasting_session:record_client_export_event / scientific:forecasting | scientific.operation / session model/job/card/forecast | apps/api/routers/forecasting_session.py:449 |
| api:POST:/v1/session/modeling/jobs/start | apps.api.routers.modeling_session:start_modeling_job / scientific:modeling | scientific.operation / persisted tuning job/plan (operation Literal tuning), session context | apps/api/routers/modeling_session.py:2085 |
| api:POST:/v1/session/modeling/jobs/{job_id}/cancel | apps.api.routers.modeling_session:cancel_modeling_job / scientific:modeling | scientific.operation / persisted tuning job/plan (operation Literal tuning), session context | apps/api/routers/modeling_session.py:2188 |
| api:POST:/v1/session/modeling/jobs/{job_id}/step | apps.api.routers.modeling_session:step_modeling_job / scientific:modeling | scientific.operation / persisted tuning job/plan (operation Literal tuning), session context | apps/api/routers/modeling_session.py:2223 |
| api:POST:/v1/session/modeling/panel/backtest | apps.api.routers.modeling_session:panel_backtest / scientific:modeling | scientific.operation / session model/job/card/forecast | apps/api/routers/modeling_session.py:3684 |
| api:POST:/v1/session/modeling/panel/forecast | apps.api.routers.modeling_session:panel_forecast / scientific:forecasting | scientific.operation / session model/job/card/forecast | apps/api/routers/modeling_session.py:3742 |
| api:POST:/v1/session/modeling/panel/passport | apps.api.routers.modeling_session:build_panel_passport_for_session / scientific:modeling | scientific.operation / session model/job/card/forecast | apps/api/routers/modeling_session.py:3473 |
| api:POST:/v1/session/modeling/panel/passport/confirm | apps.api.routers.modeling_session:confirm_panel_entry_checkpoint / scientific:modeling | scientific.operation / session model/job/card/forecast | apps/api/routers/modeling_session.py:3546 |
| api:POST:/v1/session/modeling/select | apps.api.routers.modeling_session:select_modeling_candidate / scientific:modeling | scientific.operation / session model/job/card/forecast | apps/api/routers/modeling_session.py:3051 |
| api:POST:/v1/session/modeling/selection/evaluate | apps.api.routers.modeling_session:evaluate_modeling_selection / scientific:modeling | scientific.operation / session model/job/card/forecast | apps/api/routers/modeling_session.py:3011 |
| api:POST:/v1/session/modeling/tune | apps.api.routers.modeling_session:tune_modeling_candidate / scientific:modeling | scientific.operation / session model/job/card/forecast | apps/api/routers/modeling_session.py:1779 |
| api:POST:/v1/session/modeling/tuning/skip | apps.api.routers.modeling_session:skip_modeling_tuning / scientific:modeling | scientific.operation / session model/job/card/forecast | apps/api/routers/modeling_session.py:1661 |
| api:POST:/v1/session/modeling/tuning/skip-pending | apps.api.routers.modeling_session:skip_all_pending_modeling_tuning / scientific:modeling | scientific.operation / session model/job/card/forecast | apps/api/routers/modeling_session.py:1703 |
| api:POST:/v1/session/modeling/tuning/start | apps.api.routers.modeling_session:start_modeling_tuning / scientific:modeling | scientific.operation / persisted tuning job/plan (operation Literal tuning), session context | apps/api/routers/modeling_session.py:2397 |
| api:POST:/v1/session/modeling/tuning/step | apps.api.routers.modeling_session:step_modeling_tuning / scientific:modeling | scientific.operation / persisted tuning job/plan (operation Literal tuning), session context | apps/api/routers/modeling_session.py:2500 |
| api:POST:/v1/session/stage/{stage} | apps.api.routers.session:set_stage / service:platform | scientific.operation / research session and dataset | apps/api/routers/session.py:6237 |
| api:POST:/v1/session/target-column | apps.api.routers.session:set_target_column / service:platform | scientific.operation / research session and dataset | apps/api/routers/session.py:5641 |
| api:PUT:/v1/session/dataset/preprocessing-check-modes | apps.api.routers.session:save_dataset_preprocessing_check_modes / scientific:preprocessing | scientific.operation / research session and dataset | apps/api/routers/session.py:2455 |
| api:PUT:/v1/session/dataset/type-schema | apps.api.routers.session:save_dataset_type_schema / scientific:validation | scientific.operation / research session and dataset | apps/api/routers/session.py:5421 |
| api:PUT:/v1/session/dataset/validation-check-modes | apps.api.routers.session:save_dataset_validation_check_modes / scientific:validation | scientific.operation / research session and dataset | apps/api/routers/session.py:2172 |
| api:PUT:/v1/session/dataset/validation-rules | apps.api.routers.session:save_dataset_validation_rules / scientific:validation | scientific.operation / research session and dataset | apps/api/routers/session.py:5018 |
| api:PUT:/v1/session/modeling/feature-regressors | apps.api.routers.modeling_session:set_modeling_feature_regressors / scientific:modeling | scientific.operation / session model/job/card/forecast | apps/api/routers/modeling_session.py:1120 |

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
| auth.account.operator | accounts.lifecycle.operator / service:platform | auth.storage / Account entitlements / existing memberships / scoped auth sessions and challenges | scripts/auth08/manage_account.py:14 |
| auth.api_keys.operator | auth.api_keys.operator / service:platform | auth.api_keys / existing service Identity/Account membership API keys; emergency revocation | scripts/auth10/manage_keys.py:13 |
| auth.audit.publish | auth.audit.publish / service:platform | auth.storage / auth session authority or audit delivery | apps/api/authentication/audit_outbox.py:12 |
| auth.mfa.bootstrap | auth.mfa.bootstrap / service:platform | auth.storage / MFA durable authority / operator-only singleton bootstrap | scripts/auth05/bootstrap.py:14 |
| auth.mfa.schema.apply | auth.mfa.schema.apply / service:platform | auth.storage / MFA durable authority / operator-only singleton bootstrap | apps/api/authentication/mfa_migrations.py:18 |
| auth.ownership.migrate | auth.ownership.migrate / service:platform | auth.storage / Account entitlements / existing memberships / scoped auth sessions and challenges | scripts/auth09/migrate_ownership.py:17 |
| auth.schema.apply | auth.schema.apply / service:platform | auth.storage / DDL + schema checksum ledger | apps/api/authentication/migrations.py:13 |
| auth.sessions.schema.apply | auth.sessions.schema.apply / service:platform | auth.storage / auth session authority or audit delivery | apps/api/authentication/session_migrations.py:17 |
| billing.policy.operator | billing.policy.operator / service:platform | billing.authority / Account-scoped resource reservation / ledger / transactional job intent | scripts/auth12/manage_budget.py:11 |
| billing.reserve | billing.reserve / service:platform | billing.authority / Account-scoped resource reservation / ledger / transactional job intent | apps/api/billing/coordinator.py:260 |
| billing.schema.apply | billing.schema.apply / service:platform | billing.authority / Account-scoped resource reservation / ledger / transactional job intent | apps/api/billing/migrations.py:18 |
| billing.settle | billing.settle / service:platform | billing.authority / Account-scoped resource reservation / ledger / transactional job intent | apps/api/billing/coordinator.py:578 |
| compute.calibration | compute.calibration / service:platform | compute.calibrated / real CPU/wall/RSS training/holdout/capacity evidence | apps/api/billing/compute_benchmark.py:246 |
| compute.meter | compute.meter / service:platform | compute.calibrated / attempted fold/PELT fit ceiling before start | apps/api/billing/compute_meter.py:53 |
| compute.profile | compute.profile / service:platform | compute.calibrated / pinned compatible measured profile | apps/api/billing/compute_profile.py:152 |
| compute.quote | compute.quote / service:platform | compute.calibrated / measured-domain integer micro-CU quote | apps/api/billing/compute_units.py:73 |
| execution:model.job_step | execution:model.job_step / scientific:modeling | worker.authority / persisted tuning job/plan (operation Literal tuning), session context | apps/api/routers/modeling_session.py:2208 |
| execution:model.registry | execution:model.registry / scientific:modeling | worker.authority / model request; dataset; CPU/GPU | apps/api/model_execution.py:374 |
| execution:model.tuning_step | execution:model.tuning_step / scientific:modeling | worker.authority / persisted tuning job/plan (operation Literal tuning), session context | apps/api/routers/modeling_session.py:2483 |
| execution:worker.authority | execution:worker.authority / service:platform | worker.authority / persisted delegated Account/run/session worker claim | apps/api/workers/authority.py:362 |
| execution:worker.publication | execution:worker.publication / service:platform | worker.authority / atomic current-access result projection, settlement and audit | apps/api/workers/authority.py:585 |
| execution:worker.reconciliation | execution:worker.reconciliation / service:platform | worker.authority / unknown worker outcomes and retained reservation holds | apps/api/workers/authority.py:744 |
| execution:worker.service | execution:worker.service / service:platform | worker.authority / opaque worker service credential and allowed worker kind | apps/api/workers/services.py:23 |
| scientific.admission | scientific.admission / service:platform | scientific.operation / current Account / owned scientific resource / normalized execution inputs | apps/api/scientific.py:186 |
| scientific.execution | scientific.execution / service:platform | scientific.operation / current Account / owned scientific resource / normalized execution inputs | apps/api/scientific.py:379 |

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
| page:embedded:/admin | ui:embedded:/admin / service:admin | ui.admin / UI navigation only | apps/embedded/app/admin/page.tsx:1 |
| page:embedded:/admin/logs | ui:embedded:/admin/logs / service:admin/logs | ui.admin / UI navigation only | apps/embedded/app/admin/logs/page.tsx:1 |
| page:embedded:/admin/progress | ui:embedded:/admin/progress / service:admin/progress | ui.admin / UI navigation only | apps/embedded/app/admin/progress/page.tsx:1 |
| page:embedded:/analytics/ts-analysis | ui:embedded:/analytics/ts-analysis / service:analytics/ts-analysis | ui.page / UI navigation only | apps/embedded/app/analytics/ts-analysis/page.tsx:1 |
| page:embedded:/eda | ui:embedded:/eda / scientific:eda | ui.page / UI navigation only | apps/embedded/app/eda/page.tsx:1 |
| page:embedded:/forecasting | ui:embedded:/forecasting / scientific:forecasting | ui.page / UI navigation only | apps/embedded/app/forecasting/page.tsx:1 |
| page:embedded:/login | ui:embedded:/login / service:platform | ui.login / personal login UI | apps/embedded/app/login/page.tsx:1 |
| page:embedded:/modeling | ui:embedded:/modeling / scientific:modeling | ui.page / UI navigation only | apps/embedded/app/modeling/page.tsx:1 |
| page:embedded:/navigator | ui:embedded:/navigator / service:navigator | ui.page / UI navigation only | apps/embedded/app/navigator/page.tsx:1 |
| page:embedded:/preprocessing | ui:embedded:/preprocessing / scientific:preprocessing | ui.page / UI navigation only | apps/embedded/app/preprocessing/page.tsx:1 |
| page:embedded:/tasks | ui:embedded:/tasks / service:tasks | ui.page / UI navigation only | apps/embedded/app/tasks/page.tsx:1 |
| page:embedded:/upload | ui:embedded:/upload / scientific:upload | ui.page / UI navigation only | apps/embedded/app/upload/page.tsx:1 |
| page:embedded:/validation | ui:embedded:/validation / scientific:validation | ui.page / UI navigation only | apps/embedded/app/validation/page.tsx:1 |
| page:standalone:/ | ui:standalone:/ / service:platform | ui.page / UI navigation only | apps/standalone/app/page.tsx:1 |
| page:standalone:/admin | ui:standalone:/admin / service:admin | ui.admin / UI navigation only | apps/standalone/app/admin/page.tsx:1 |
| page:standalone:/admin/logs | ui:standalone:/admin/logs / service:admin/logs | ui.admin / UI navigation only | apps/standalone/app/admin/logs/page.tsx:1 |
| page:standalone:/admin/progress | ui:standalone:/admin/progress / service:admin/progress | ui.admin / UI navigation only | apps/standalone/app/admin/progress/page.tsx:1 |
| page:standalone:/dashboard/ts-analysis | ui:standalone:/dashboard/ts-analysis / service:dashboard/ts-analysis | ui.page / UI navigation only | apps/standalone/app/dashboard/ts-analysis/page.tsx:1 |
| page:standalone:/documentation | ui:standalone:/documentation / service:documentation | ui.page / UI navigation only | apps/standalone/app/documentation/page.tsx:1 |
| page:standalone:/eda | ui:standalone:/eda / scientific:eda | ui.page / UI navigation only | apps/standalone/app/eda/page.tsx:1 |
| page:standalone:/education | ui:standalone:/education / service:education | ui.page / UI navigation only | apps/standalone/app/education/page.tsx:1 |
| page:standalone:/forecasting | ui:standalone:/forecasting / scientific:forecasting | ui.page / UI navigation only | apps/standalone/app/forecasting/page.tsx:1 |
| page:standalone:/login | ui:standalone:/login / service:platform | ui.login / personal login UI | apps/standalone/app/login/page.tsx:1 |
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
| proxy:embedded:/api/v1/:path* | proxy:embedded / service:transport | proxy.transport / forwarded HTTP request | apps/embedded/app/api/v1/[...path]/route.ts:1 |
| proxy:standalone:/api/v1/:path* | proxy:standalone / service:transport | proxy.transport / forwarded HTTP request | apps/standalone/app/api/v1/[...path]/route.ts:1 |

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
| compute.cache | compute.cache / service:platform | compute.calibrated / current-authority signed content-addressed compute result replay | apps/api/billing/compute_cache.py:46 |
| storage:artifacts | storage:artifacts / service:storage | storage.internal / snapshot/artifact/rendition bytes | apps/api/artifact_store.py:321 |
| storage:auth.accounts | auth.repository.account / service:platform | auth.storage / Account/tenant/membership/versions | apps/api/accounts/repository.py:6 |
| storage:auth.identities | auth.repository.identity / service:platform | auth.storage / Identity/external issuer-sub mapping | apps/api/authentication/repository.py:8 |
| storage:auth.mfa | storage:auth.mfa / service:platform | auth.storage / MFA durable authority / operator-only singleton bootstrap | apps/api/authentication/mfa.py:68 |
| storage:auth.sessions | auth.session.authority / service:platform | auth.storage / auth session authority or audit delivery | apps/api/authentication/sessions.py:68 |
| storage:billing.job_outbox | storage:billing.job_outbox / service:platform | billing.authority / Account-scoped resource reservation / ledger / transactional job intent | apps/api/billing/coordinator.py:260 |
| storage:billing.ledger | storage:billing.ledger / service:platform | billing.authority / Account-scoped resource reservation / ledger / transactional job intent | apps/api/billing/coordinator.py:236 |
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
| compute.runtime | compute.runtime / service:platform | compute.calibrated / protected PELT/tuning isolated runtime | apps/api/billing/compute_runtime.py:183 |
| execution:worker.subprocess | execution:worker.subprocess / service:platform | worker.authority / bounded pure child process; no database or service credential | apps/api/workers/process.py:123 |
| worker:apps/api/delivery_worker.py:182 | apps/api/delivery_worker.py:self._loop / service:platform | worker.authority / queued operation | apps/api/delivery_worker.py:182 |
| worker:apps/api/document_render_worker.py:676 | apps/api/document_render_worker.py:target / service:platform | worker.authority / queued operation | apps/api/document_render_worker.py:676 |
| worker:apps/api/document_render_worker.py:698 | apps/api/document_render_worker.py:self._loop / service:platform | worker.authority / queued operation | apps/api/document_render_worker.py:698 |
| worker:apps/api/workers/process.py:176 | apps/api/workers/process.py:supervise / service:platform | compute.calibrated / independent physical wall deadline and aggregate Linux process-group RSS | apps/api/workers/process.py:176 |
| worker:delivery.run_once | worker:delivery.run_once / service:platform | worker.authority / delivery outbox; research runs; checkpoint files | apps/api/delivery_worker.py:118 |
| worker:document.process | worker:document.process / service:documentation | worker.authority / render job; snapshot; rendition | apps/api/document_render_worker.py:384 |
| worker:document.system_snapshot | worker:document.system_snapshot / service:documentation | worker.authority / durable snapshot bytes | apps/api/document_render_worker.py:170 |
