# AUTH-19 — OIDC / personal trial / email self-service

База: 8ec771d (AUTH-18 + HOTFIX1). Зависимости AUTH-04/AUTH-06/AUTH-08 выполнены и изучены: opaque AuthSessions, Argon2id, CSRF/Origin/first-party proxy, Account entitlements. Задача из spec_auth_architecture.md §9: результат — `authentication/providers/challenges`; критерии — issuer+sub/PKCE/state/nonce; mail scanner не consume; email не auto-merge.

## Процесс и границы

1. **Два независимых способа входа, один транспорт.** OIDC (доверенный IdP) и личный email trial выпускают тот же opaque AuthSession AUTH-04 (`__Host-cisstat_auth`, SameSite=Lax, 8h/15m). Браузерный контракт и first-party proxy не раздваиваются; `/v1/auth/me`, account selection и research-pointer ротация переиспользуются.
2. **OIDC identity связывается только по (issuer, subject).** Существующая immutable-таблица `auth_external_identities` (AUTH-02, триггер `auth02_external_update`) остаётся единственным местом связи. Неизвестный (issuer,sub) → 401 без регистрации, без merge по email, без создания Account. Связывание существующей identity — явная authenticated-команда `POST /v1/auth/oidc/callback` (purpose=link): текущая сессия доказывает владение subject, `(issuer,sub)` не должен принадлежать другому субъекту (409). Verified email от IdP сохраняется как метаданные binding и НЕ является основанием склейки.
3. **Authorization Code + PKCE S256 + state + nonce обязательны.** `state`/`nonce`/`code_verifier` создаёт сервер в `auth_login_states` (hash-only для state, TTL 10 мин, origin-bound, одноразовый атомарный consume). RS256-only allowlist (HS256/none отвергаются), JWKS по `kid`, RSA PKCS1v15+SHA256 через уже пинненный `cryptography`. Проверяются iss (exact), aud (содержит client_id), exp (leeway 60s), nbf, nonce, sub. Discovery/JWKS/token — только HTTPS, bounded ответы 256 KiB, timeout 5s, без redirects. Client secret (опция) — HTTP Basic на token endpoint; для public client достаточно PKCE.
4. **Mail scanner не consume.** Погашение email-challenge — только POST-команда `/v1/auth/email/consume`; GET-маршрута consume нет по построению (route check). Magic token `e1_…` и 8-значный OTP хранятся как keyed HMAC-SHA256 (`CISSTAT_AUTH_EMAIL_KEY` ≥32 байта, обязательна при включении контура), TTL 15 мин, ≤5 попыток на challenge (attempts коммитятся до сверки кода), durable per-email/per-peer/global лимиты в `auth_login_limits`.
5. **email не auto-merge.** Trial consume ищет verified-binding `issuer='cisstat.email/1'`, `external_subject=<email>`: найден и активен → вход той же identity; найден suspended → 403; не найден → НОВАЯ identity + binding + MONO starter Account (OWNER, seats=1) по политике trial. Unverified email от OIDC не создаёт binding и не влияет на lookup. Два субъекта с одним адресом остаются разными; связывание — только явные verified-команды (`email_bind`, `oidc_link`).
6. **Uniform ответы email.** `POST /v1/auth/email/start` отвечает одинаково `{"status":"email_sent"}` для существующих и новых адресов (trial_login). Доставка — SMTP-адаптер, выключен по умолчанию (без `CISSTAT_AUTH_SMTP_HOST`); сбой доставки → 503 `email_delivery_unavailable`, challenge остаётся delivered=failed и не погашается: email outage не открывает вход по построению (consume требует секрет из письма).
7. **Внешняя сессия без пароля.** `auth_sessions.credential_id/credential_version` становятся nullable (additive 0031, `(credential_id IS NULL) = (credential_version IS NULL)`, scopes='[]'). `_load` ветвится: для NULL-credential fencing — identity status/subject_version/epoch/membership/account (binding immutable); парольные сессии проверяются как раньше. Отзыв: suspend/revoke/epoch оператора AUTH-08 работает одинаково.
8. **ADMIN через OIDC → 403 mfa_required (v1).** Контракт «доверенный IdP подтверждает MFA» (acr/amr) требует durable evidence в `auth_session_mfa` (FK на локальный фактор) — отдельная поставка. Локальный password+MFA вход администратора не блокируется (R3: «OIDC не блокирует локальный MFA-вход»). Bootstrap ADMIN остаётся AUTH-05 CLI.
9. **Выбор аккаунта.** Identity с несколькими активными Account (личный MONO + командный MULTI) получает `{"status":"account_required","accounts":[…],"selection_token"}` из callback/consume: одноразовая `auth_login_states` запись purpose `oidc_select`/`email_select` (subject-bound, TTL 5 мин, origin-bound). Выбор — повторный POST того же endpoint с `selection`+`account_id`; membership/entitlement перепроверяются сервером. Логика переиспользует password-login выбор (доступные active-аккаунты, labels «Личный/Командный — план»).
10. **Trial политика.** MONO starter: `plan='starter'`, seats=1, OWNER; `CISSTAT_AUTH_TRIAL_PLAN_DAYS` (опционально, 1..3650) задаёт `plan_expires_at`, без env — бессрочный starter (caps ограничены starter-планом сервером, коммерческие потолки не поднимаются). Audit: `auth_identity_changed` (mandatory, новый каталог 36→37) для trial-identity/email-bind/oidc-link; `auth_session_changed` — для выпущенных сессий; `authn_denied` (standard) для неизвестных OIDC binding.
11. **Deny-by-default конфигурация.** OIDC включён только при `CISSTAT_AUTH_OIDC_ISSUER`+`CISSTAT_AUTH_OIDC_CLIENT_ID`; email — только при `CISSTAT_AUTH_EMAIL_KEY`+`CISSTAT_AUTH_SMTP_HOST`. Не настроено → 503 с безопасным кодом (`oidc_unavailable`/`email_unavailable`); флаги доступности добавлены в существующий `GET /v1/auth/csrf` (additive, без response_model). Redirect URI = `<origin>/login` (обе оболочки, точно https origin из configured_origins).
12. **Права не расширяются.** Внешние сессии: scopes=[], platform.admin не выдаётся, INTERNAL entitlement остаётся AUTH-08, object/tenant/worker guards не затронуты. Форум (AUTH-15/16) не использует email-контур: личный trial и форумная кампания — разные субъекты (spec_auth §5).

## Точки изменения

- `apps/api/migrations/0031_auth19_email_oidc.sql` — nullable sessions credential, `auth_email_challenges`, `auth_login_states` + immutable-триггеры.
- `apps/api/authentication/providers/{__init__,oidc,email_delivery}.py` — OIDC RP adapter (discovery/PKCE/JWKS/RS256) и bounded SMTP delivery, без сети по умолчанию.
- `apps/api/authentication/{oidc,email_challenges}.py` — сервисы входа (SessionService подклассы, как MfaService).
- `apps/api/authentication/auth19_migrations.py` — explicit chain 0019→…→0031, checksums прежних не меняются.
- `apps/api/authentication/sessions.py` — `_load` NULL-credential ветка, `issue_external_session`, общий выбор аккаунтов.
- `apps/api/authentication/context.py` — новые safe-коды ошибок.
- `apps/api/security_audit.py` — `auth_identity_changed` (mandatory).
- `apps/api/routers/authentication.py` — 4 новых POST + flags в /csrf.
- `apps/api/access_registry.v1.json` — операции `auth.oidc.start/callback`, `auth.email.start/consume` (authority external).
- `docs/auth00/policy_review.json` + inventory --write; `docs/auth01/openapi.json`/generated TS; proxy allowlist.
- UI: `packages/ui/lib/authClient.ts` (4 команды), `LoginScreen.tsx` (OIDC-кнопка, email trial, consume по ссылке), Jest.
- `apps/api/Dockerfile` — guard `scripts/auth19/migrate.py`; `.env.example` — выключенные по умолчанию настройки.

## Риски и проверки

- **alg confusion / подделка id_token** — RS256-only, JWKS `kid` match, PKCS1v15 verify, полная claims-валидация; негативные оракулы (wrong sig/nonce/aud/iss/exp, unknown kid, `alg:none`).
- **state replay/fixation** — hash-only одноразовый consume в транзакции, origin-bound, TTL; replay → 401.
- **OTP brute force** — 8 цифр, ≤5 попыток (durable), rate limits, keyed HMAC.
- **email enumeration** — uniform start-ответ; consume не раскрывает существование адреса.
- **merge по email** — негативный оракул: OIDC identity с email существующей учётной записи → отказ, второй субъект остаётся собой.
- **account selection races** — одноразовый selection token, membership re-check, CAS epoch.
- **audit rollback** — mandatory `auth_identity_changed` в одной транзакции с mutation (fail-closed).
- **ошибка миграции** — additive 0031, checksums 0019–0030 immutable; явные `--apply/--check`.
- Не входит: WebAuthn, IdP-MFA контракт (acr), email-based password reset, invitations по email (AUTH-17 покрывает их через account invite), forum campaign (AUTH-15/16), отправка писем вне SMTP-адаптера, реальный IdP/SMTP в сессии (тесты — controlled MockTransport/fake delivery + native PostgreSQL 16).

## Операционные входы до activation (не поставка кода)

IdP: registration redirect_uri `https://<origin>/login` для каждой оболочки, RS256 JWKS, scope `openid` обязателен. SMTP: учётная запись/лимиты провайдера. Секреты: `CISSTAT_AUTH_EMAIL_KEY` (генерация ≥32 байт), при необходимости `CISSTAT_AUTH_OIDC_CLIENT_SECRET`. Команды включения — docs/auth19/deploy.md.
