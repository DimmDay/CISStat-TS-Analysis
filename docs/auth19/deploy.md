# AUTH-19 — установка поверх 8ec771d

ZIP содержит только новые/обновлённые файлы задачи. Репозиторий/VM эта сессия не изменяет. Перед переносом — штатный backup PostgreSQL/.env и volumes. AUTH-19 добавляет 0031; 0019…0030/checksums не меняются. Нужна пересборка api и web (изменились backend и BFF allowlist/generated TS). Научные kernels/compute*.py не менялись, перекалибровка CU не требуется.

## Локальная машина

Распаковать в корень checkout на 8ec771d. Сверить scripts/auth19/files.txt, затем:

```powershell
git add --pathspec-from-file=scripts/auth19/files.txt
python scripts/local_gates.py --skip-install
# При установленном disposable PostgreSQL и CISSTAT_AUTH_TEST_DSN:
python scripts/local_gates.py --only auth19,auth19-postgres --skip-install
npm run build:all
# После собственного commit, до push:
python scripts/local_gates.py --auth00-target head --skip-install
```

## VM — безопасная установка с выключенными контурами

После собственного push и зелёного CI, из checkout VM:

```bash
set -euo pipefail
git pull --ff-only
cd deployment/cisstat-stack
docker compose build api web
docker compose run --rm --no-deps -T api python scripts/auth19/migrate.py --apply
docker compose run --rm --no-deps -T api python scripts/auth19/migrate.py --check
env -u CISSTAT_AUTH_MFA_KEYS -u CISSTAT_AUTH_MFA_ACTIVE_KEY \
    -u CISSTAT_WORKER_KEY -u CISSTAT_CU_PROFILE -u CISSTAT_CU_PROFILE_SHA256 \
    docker compose up -d --no-deps api web
docker compose exec -T api python scripts/auth19/migrate.py --check
docker compose exec -T api curl -fsS http://127.0.0.1:8000/health/ops
docker compose ps
```

По умолчанию оба новых контура ВЫКЛЮЧЕНЫ: без `CISSTAT_AUTH_OIDC_ISSUER`/`CLIENT_ID` и без `CISSTAT_AUTH_EMAIL_KEY`+`CISSTAT_AUTH_SMTP_HOST` новые endpoints отвечают 503, `GET /v1/auth/csrf` показывает `oidc:false, email_trial:false`. Миграция 0031 ничего не переносит и не создаёт учётных записей: только nullable `credential_version`, расширение `auth15_session_family` (третий тип сессии: credential NULL + grant NULL) и две новые таблицы. Existing sessions/users/accounts/reservations/платежи не затрагиваются; парольные и demo-сессии живут по прежним правилам.

## Включение email-входа (personal trial / bind)

1. Сгенерировать ключ: `openssl rand -base64 32` → `CISSTAT_AUTH_EMAIL_KEY` (≥32 байт; без него контур закрыт).
2. SMTP-учётная запись: `CISSTAT_AUTH_SMTP_HOST/PORT/USER/PASSWORD/FROM/TLS`. Порты провайдера и лимиты подтверждает оператор; сбой доставки честно возвращает 503 и не открывает вход.
3. Пересоздать api с новыми env (`docker compose up -d --no-deps api`), проверить `GET https://api.datasetup.ru/v1/auth/csrf` → `email_trial:true`.
4. Опционально `CISSTAT_AUTH_TRIAL_PLAN_DAYS=N` (1..3650) — срок личного starter-аккаунта; без переменной — бессрочный starter (потолки caps серверные).

Сценарий: «Вход по email» на /login → письмо со ссылкой и 8-значным кодом → переход по ссылке ведёт на страницу входа (`/login?email_challenge=…`), подтверждение — ТОЛЬКО кнопкой (POST); GET по ссылке ничего не погашает. Первый вход создаёт личный MONO starter Account (владелец — этот субъект). Повторный вход — та же учётная запись. Привязка email к существующей учётной записи: POST `/v1/auth/email/start` с `purpose:"email_bind"` из активной сессии. Ответы start не раскрывают существование адреса.

## Включение корпоративного OIDC

1. В IdP зарегистрировать client c redirect_uri = `https://<origin>/login` для КАЖДОЙ оболочки (datasetup.ru и embedded origin), подпись токенов RS256, scope `openid` обязателен (по умолчанию `openid profile email`).
2. В .env VM: `CISSTAT_AUTH_OIDC_ISSUER=https://idp.example.com`, `CISSTAT_AUTH_OIDC_CLIENT_ID=…`, при confidential client — `CISSTAT_AUTH_OIDC_CLIENT_SECRET` (HTTP Basic). Проверить discovery: `CISSTAT_AUTH_OIDC_SCOPES` при нестандартном наборе.
3. Пересоздать api, проверить `GET /v1/auth/csrf` → `oidc:true` и что `POST /v1/auth/oidc/start` возвращает authorize_url с `code_challenge_method=S256`.

Первый вход под неизвестным (issuer, subject) ОТКЛОНЯЕТСЯ (без регистрации, без merge по email). Связывание существующей учётной записи: на странице /login под активной сессией `POST /v1/auth/oidc/start` с `purpose:"link"` → подтверждение в IdP → `POST /v1/auth/oidc/callback` привязывает (issuer, subject) к текущему субъекту (409, если binding уже у другого). ADMIN через OIDC: 403 `mfa_required` — административный вход остаётся на локальном password+MFA (AUTH-05), контракт IdP-MFA — отдельная поставка. PKCE verifier/nonce/state живут только на сервере; state одноразовый, TTL 10 мин, origin-bound.

## Откат контура (без даунгрейда схемы)

Выключить email: очистить `CISSTAT_AUTH_EMAIL_KEY`/`CISSTAT_AUTH_SMTP_HOST` и пересоздать api — новые challenge не выпускаются, уже выпущенные истекают по TTL (15 мин) и consume закрывается. Выключить OIDC: очистить ISSUER/CLIENT_ID — выданные OIDC-сессии живут до обычного 8h/15m/отзыва. `docker compose down -v` и обратная DDL миграция запрещены: 0031 сохраняется, rollback означает только отключение env-контуров.
