# AUTH-CERT — матрица приёмки AC01…AC30 и границы акта

Дата: 12.11.2026. База: 3c3e8b7. Объект: полный `apps.api.main` (production-like деплой на
disposable PostgreSQL 16.2: цепочка 0019→0035, required-режим хранения, полный middleware-стек
CORS/Telemetry/TraceHook/AUTH-06). Транспорт — настоящий HTTP (first-party cookies
`__Host-cisstat_auth`/`__Host-cisstat_csrf`, CSRF-доказательства, Origin, MFA-челленджи,
адмиссионные коды). Состав suite'ов: `test_authcert_api` (10), `test_authcert_demo` (6),
`test_authcert_concurrency` (5), `test_authcert_failures` (5), `test_authcert_billing` (4),
`test_authcert_browser` (4, без DSN). Harness: `tests/integration/authcert_harness.py`
(design D2/D3/D6 — docs/authcert/design.md).

Обозначения: **CERT** — оракул реализован в suite'ах AUTH-CERT; **TASK(n)** — покрыто native-гейтом
задачи n (ссылка на файл в скобках); **ACT-граница** — вне достижимости среды, зафиксировано ниже.

## §17 spec_auth — приёмочные сценарии

| AC | Покрытие | Где |
|---|---|---|
| AC01 | CERT: named ADMIN проходит MFA-логин (challenge→enroll/verify) и открывает реальные admin-API; админ-сессия origin-bound — embedded обслуживается собственным входом | api::test_ac01_ac02_admin_mfa_login_both_origins |
| AC02 | CERT: тот же ADMIN из standalone: GET /v1/admin/demo-campaigns 200, /v1/auth/me role=admin, флаги /v1/auth/csrf | api (тот же тест) |
| AC03 | CERT: external_user, internal_analyst и Account OWNER получают 403 на admin-API; tamper role-полем/заголовком X-Role не помогает | api::test_ac03_owner_and_analyst_rejected_on_admin_apis |
| AC04 | CERT: challenge-токен не годится как auth-сессия (cookie→/me 401); смена пароля без свежего step-up отказана (401 invalid_credential от consume_step_up); с fresh step-up (password+MFA-код→proof) — 200, сессии отозваны | api::test_ac04_challenge_not_session_and_fresh_stepup_required |
| AC05 | CERT: logout закрывает следующий запрос (401); снятие ADMIN (version-bump) отзывает сессию немедленно, admin-поверхность закрыта; восстановление роли возвращает поверхность (fixture) | api::test_ac05_logout_and_role_removal_close_next_request |
| AC06 | CERT: одна пара допускает двух участников одновременно — разные grant/account; разные upload→разные dataset_id/run_id; действие A не затрагивает сессию B | demo::test_ac06_ac07_two_participants_one_credential_isolated |
| AC07 | CERT: научная сессия привязана к гранту, не к bare ID: A не видит и не меняет состояние B (session-scoped трасса, изоляция датасетов); addressability run_id по построению отсутствует | demo (тот же тест) |
| AC08 | CERT: shared-credential участник не получает admin-API (403 в demo::…closed_endpoints), роль/приглашения/billing недостижимы (403 admin_role_required); rotation кампании меняет секрет (failures::s10_credential_rotation) | demo::test_s10_demo_pipeline_end_to_end_and_closed_endpoints, failures::test_s10_credential_rotation_kills_old_secret |
| AC09 | CERT: повторный login/logout/resume известного гранта сохраняет grant_id и expires_at, не создаёт новый расход | api::test_ac09_relogin_keeps_grant_expiry_and_usage |
| AC10 | CERT: кампания с ends_at «+2 сек» после границы отказывает enter (403 demo_expired); точная миллисекундная граница `now >= expires_at` — native-оракул AUTH-15 (clock injection, test_auth15_demo) | api::test_ac10_expired_campaign_boundary_rejects_enter; TASK(auth15) |
| AC11 | CERT: новый браузер = новый грант (soft-режим), но жёсткий потолок max_grants — третий вход 429 campaign_capacity_exhausted; тест не заявляет распознавание человека | demo::test_ac11_new_browser_new_grant_but_hard_limits |
| AC12 | CERT: один admission code при ПАРАЛЛЕЛЬНЫХ enter (4 потока) погашается ровно один раз (1×200, 3×401; auth_demo_admissions redeemed=1, grants=1); replay не выдаёт грант/куки; отдельный неиспользованный код допускает второго участника | concurrency::test_ac12_admission_code_parallel_enter_single_redemption; demo::test_ac12_admission_code_redeemed_once_no_foreign_resume |
| AC13 | CERT: гонка за последние CU (2×80k против 100k на реальных PG-транзакциях) — ровно один победитель, ровно одна резервация; уровень координатора AUTH-12 (admission/session/CU атомарность) — native-оракулы auth12 | concurrency::test_ac13_last_units_race_exactly_one_winner; TASK(auth12) |
| AC14 | CERT: идемпотентный retry (Idempotency-Key) возвращает тот же ответ; другой payload с тем же ключом — 409; дубли-начисления/кредиты — native auth22/23 | concurrency::test_ac14_idempotent_retry_same_result_conflict_on_payload; TASK(auth22, auth23) |
| AC15 | CERT: pause кампании закрывает upload/polling/resume участника немедленно (401/403) без ожидания TTL; revoke/expiry — native-оракулы AUTH-15/16 (expiry fences late publication, revoke закрывает polling/internal) | demo::test_ac15_pause_and_revoke_close_live_operations; TASK(auth15, auth16) |
| AC16 | CERT: bounded modeling идёт через AUTH-13 worker authority (реальный supervised child, worker_jobs completed); queued/running/late-completion/fencing — native auth13/auth16 | demo::test_s10_demo_pipeline_end_to_end_and_closed_endpoints; TASK(auth13, auth16) |
| AC17 | CERT: re-enter того же браузера не выпускает второй грант; новый браузер — новый грант при том же кампанном бюджете (issued_grants монотонны, счётчики не сбрасываются) | api::test_ac17_second_session_no_new_budget_no_usage_reset |
| AC18 | CERT: демо проходит только bounded-путь; прямой tuning/start и tuning/skip закрыты (403/422), admin API 403, public API 401/403, bare internal backtest 401/403/422; GPU/тяжёлый fit недостижимы по каталогу | demo::test_s10_…closed_endpoints, demo::test_ac18_public_api_and_internal_guard_for_demo |
| AC19 | CERT: при недоступном authority store — 503 auth_authority_unavailable для аутентифицированного запроса; anonymous — 401 без fallback-успеха; восстановление — 200 | failures::test_ac19_unavailable_authority_503_no_anonymous_fallback |
| AC20 | CERT: fault обязательного аудита откатывает команду кампании целиком (503, строка не создана); повтор после сбоя согласован (успех); native-паттерн audit-fault→rollback — auth15/16/23 | failures::test_ac20_audit_fault_leaves_no_unaccounted_change; TASK(auth16, auth23) |
| AC21 | CERT: login-ротация отзывает прежний токен (fixation закрыт); auth-cookie и research-pointer — разные имена; legacy claim не присваивает чужой ResearchRun — ownership-receipts AUTH-09 (native) | api::test_ac21_fixation_rotates_and_cookies_differ; browser::ac22; TASK(auth09) |
| AC22 | CERT(browser): __Host-куки host-only (без Domain=), Secure/HttpOnly/SameSite=lax (HTTP-проверка в api::test_ac21); отсутствие credentials в URL (replaceState в LoginScreen, redirect:error, no location.href); отсутствие токенов в browser storage (authClient без localStorage/sessionStorage) | browser::test_ac22_*, api::test_ac21 |
| AC23 | CERT: mutation без CSRF 403; неверный Origin 403; Sec-Fetch-Site: cross-site 403; недопущенный Origin не получает CORS-заголовков открытия | api::test_ac22_ac23_csrf_origin_and_no_cors_bypass |
| AC24 | CERT: rate-лимиты логина/OTP/челленджей — native-оракулы AUTH-04/05/19 (429, per-email/per-peer/global); один пользователь не блокирует общую учётку кампании (общий login барьеры Argon2 throttle — auth15 native) | TASK(auth04, auth05, auth19); ACT-граница: NAT-профиль форума — нагрузочная эксплуатационная приёмка |
| AC25 | CERT: две конкурентные admin-правки с одной expected_version — ровно один 200 (CAS), второй 409; ослабление лимита не сбрасывает usage (issued_grants сохранены) | api::test_ac25_policy_cas_one_winner_usage_not_reset |
| AC26 | CERT: replay приглашения не создаёт второе membership (accept идемпотентен, повтор отказан; members=2 после одного гостя); гонка за последнее место — native-оракул AUTH-17 (last-seat race) | concurrency::test_ac26_invitation_replay_creates_no_second_membership; TASK(auth17) |
| AC27 | CERT: «рестарт» (полное переоткрытие durable-хранилищ новым HTTP-контекстом) не воскрешает logout-сессию и потреблённый admission-код; restore/marks/watermark — native-оракулы AUTH-20/25 (reconcile re-apply, идемпотентность, resurrection доказана/закрыта) | failures::test_ac27_restart_does_not_resurrect_revocations; TASK(auth20, auth25) |
| AC28 | CERT: cleanup сохраняет минимальный usage/audit (native auth16: retention сохраняет identity/grant/admission/usage/ledger/audit); plaintext secrets отсутствуют в строках/ошибках (native auth04 hash-only + cert: refusal bodies без пароля) | TASK(auth16, auth04); CERT-наблюдение в refusal-оракурах api/demo |
| AC29 | CERT(browser): обе оболочки несут surfaces login/admin/demo/account/upload; транспорт — общий authClient; 503 авторитет-недоступность маппится в явное сообщение без ложного «вход выполнен» (пин authClient.test); loading/forbidden/expired/quota/offline — полный Jest 2882/2 (AUTH-24 запись) | browser::test_ac29_*; ACT-граница: реальный браузер/клавиатура/мобильный экран не прогонялись |
| AC30 | ACT-граница: нагрузочный профиль (участники/NAT/очередь/budget) опирается на measured AUTH-14 reference (90/90 checks; CU-конверт) и эксплуатационную приёмку запуска на VM; новый замер в этой среде не выполнялся | TASK(auth14); docs/auth25 (launch runbook) |

## §10 spec_auth_architecture — явные оракулы

| Оракул | Покрытие |
|---|---|
| Один User в двух Account не переносит данные/кэши/ключи; MONO→MULTI сохраняет run IDs | native-оракулы AUTH-17 (17/17: account switch, MONO↔MULTI, сессии инвалидируются); CERT: повторный вход/смена браузера не создаёт новый бюджет (api::ac17) |
| OWNER не ADMIN; internal entitlement не отменяет tenant/object policy; SupportGrant не открывает чужой tenant/run | CERT: OWNER→admin-API 403 (api::ac03); tenant/object policy — native auth09 (ownership receipts, uniform-404) |
| Demo проходит upload→validation→preprocessing→EDA→bounded modeling→forecast; прямые tuning/custom/прикладные закрыты | CERT: demo::test_s10_demo_pipeline_end_to_end_and_closed_endpoints (реальный supervised child + export.csv) |
| Одновременные invite/seat/CU admission, crash после reserve/до queue и после execute/до settle — без двойного расхода/бесплатного результата | CERT: concurrency::ac12/ac13/s10; crash/replay — native auth12/13/22/23 |
| Downgrade, campaign pause, identity revoke действуют на polling/restore/render/download/job start | CERT: demo::ac15 (pause→upload/polling/resume закрыты); revoke/expiry — native auth15/16; render/download — AUTH-13 delivery recovery (native) |
| ENV removal / key rotation / salt migration / backup restore сохраняют владение, не воскрешают отзыв | CERT: failures::s10 (rotation старый секрет 401/новый 200; CISSTAT_AUTH_LOCKDOWN; CSRF-key removal fail-closed), ac27 (restart); backup restore — native auth20 (marks/reconcile) и auth25 (watermark) |

## §12.5 — сертификационный объём billing

| Сценарий | Покрытие |
|---|---|
| Callback spoof / повтор / out-of-order webhook / два event IDs / не тот merchant/env/currency/amount | native auth22 (18/18) — CERT не дублирует |
| Refund-versus-spend race; неизвестный исход refund держит hold | CERT: billing::test_refund_hold_blocks_spend_and_release_paths_are_exclusive; native auth23 |
| Chargeback после settle; wallet_locked закрывает новые admissions | native auth23 (12/12: dispute lost/won, exposure) |
| Purchased на смене цикла; expiry included во время job; rollover без потери средств | CERT: billing::test_expiry_sweep_honest_and_no_revival, test_integer_split_exactness_at_giant_scale (1e12); E1…E6 — native auth21/22/23 |
| Seat churn без бесплатного кредита; финансовая приватность MEMBER | CERT: billing::test_seat_churn_never_creates_credit_and_privacy_holds (HTTP: MEMBER без источников/журнала, ledger 403) |
| Integer overflow/rounding | CERT: integer_split_exactness_at_giant_scale; native auth21 (сплиты без потерь) |

## Границы акта (честно)

1. **Реальный браузер не запускался** — UI-слой: статические оракулы `test_authcert_browser` + полный Jest (2882/2skips, AUTH-24) + production builds (AUTH-24). Keyboard/mobile/theme E2E не выполнялись.
2. **Redis отсутствует в auth-контуре проекта** (AUTH-20): требование «реальный PG/Redis» выполняется как «реальный PostgreSQL 16.2»; Redis-N/A зафиксировано, не скрыто.
3. **IdP/SMTP/провайдер-магазин не вызывались** — контрактные границы OIDC/email/OIDC-MFA проверены их собственными native-гейтами (auth19); money-путь — только trusted-провижининг, адаптер не тронут.
4. **AC30 (ёмкость) не замерялась заново** — опирается на AUTH-14 measured reference; «production certified» не заявляется: операционная приёмка на VM (launch runbook AUTH-25) остаётся открытым пунктом.
5. **PG18/Windows** — удалённая CI-матрица authcert.yml; локально PG16.2 (pgserver).
6. **Находки приёмки** (не блокеры, в существующих контрактах): F-CERT-B1 — legacy-заглушка `useAuth` (dev-переключатель) живёт только в StandaloneHome и не участвует в auth-поверхностях (задокументирована в коде как «ЗАМЕНИТЬ»); F-CERT-H1 — lazy-миграция аудит-sink'а внутри первого запроса может самодедлочиться на trace_events при переиспользовании соединений — в деплоях устраняется порядком «миграция до старта api» (harness воспроизводит этот порядок; кандидат в runbook-чеклист).
