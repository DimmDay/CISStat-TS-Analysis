# AUTH-10 — API keys durable lifecycle

База c13a52bd754f753d9a842aa84af8548af3019fed. Отдельный detached worktree; старые рабочие деревья сохранены. Commit/push и VM не меняются.

## Процесс и границы

Изучены AGENTS.md, spec_auth.md §10/13/14/16, spec_auth_architecture.md §3/4/5/8/9, AUTH-02…09/HOTFIX01 в worklog11.md и код context/session/MFA/accounts/identity/public/models/upload_db/BFF. Реализация следует TDD: codec/DTO/scopes RED → SQL/service/HTTP native RED → GREEN → route/INDEX gates → build → task-only ZIP и чистый overlay.

Ключ персонален либо принадлежит существующей service Identity с active AccountMembership. В БД только domain-separated SHA256 verifier высокоэнтропийного random token (csk_ + 43 URL-safe символа), random credential UUID, immutable subject/Account/family/scopes/expiry. Секрет выдаётся только из issue/rotate ответа, никогда не list/audit/repr. Ротация — старый ключ терминально отозван и новый вставлен с теми же subject/Account/family в одном UoW вместе с обязательным существующим audit outbox. Expiry при ротации не продлевается, scopes только сужаются, version CAS. Revoked/expired ключ не восстанавливается ENV fallback или restart.

Четыре новых session-only endpoints: GET/POST /v1/api-keys, POST /v1/api-keys/{key_id}/rotate, POST /v1/api-keys/{key_id}/revoke. Personal self-only, current Account из session, поля чужого subject/account/role запрещены. Cookie mutations через existing Origin/CSRF SafeAuthRoute; issue/rotate требуют auth_time или подтверждённый MFA не старше 15 минут. Повторная session проверка внутри транзакции; lock order identity→Account→session→key. Trusted interactive CLI выдаёт service ключи для уже существующего service subject/member, не создаёт Identity или membership.

Server can_use_api проверяется при issue/rotate/verify на текущем Account, без role bypass. List/revoke доступны активному владельцу собственных ключей даже на API-disabled плане; при inactive Account отзыв возможен trusted operator. SQL cascades терминально отзывают ключи при Identity version change, membership revoke/delete, Account suspension/close/demo/истёкшей реактивации. Каждый запрос reload authority; нет положительного cache между HTTP запросами.

Scope ceiling — только api.read/api.write/api.compute/api.database; wildcard/admin/docs/log scopes не делегируются API-ключом. Явная таблица программных operations из AUTH-01 registry; неизвестный/непрограммный route deny. Публичные upload_db test И load используют тот же gate. Existing global rules PATCH не допускается durable ключом до Account-scoped policy AUTH-11. Admin/browser/session/internal paths не становятся обходом API scope. Legacy ENV adapter остаётся только ограниченным dev compatibility: в required/scoped default durable, explicit legacy_dev там отвергается. csk_ prefix всегда DB, без fallback. Старые production ENV secrets не импортируются автоматически; их заменяют новыми durable ключами на доказанной Identity/Account, legacy objects — по AUTH-09 migration, без переписывания provenance.

Новая explicit auth migration 0024 (не scientific catalogue), checksums 0019–0023 не меняются. CLI apply/check/readiness до запуска нового API image. BFF/registry/OpenAPI/TS генерируются; local gates используют INDEX после явного git add и HEAD после локального commit. Образы api и web обновляются. Новых обязательных env нет на VM с required profile; scope/expiry/rotation API — AUTH-10, atomic quotas/бюджеты — AUTH-12, полное scientific admission — AUTH-11, worker fencing — AUTH-13, self-service seats/роль OWNER — AUTH-17, consumer rollout — AUTH-20.

## Риски/оракулы

Hash-only across DB/audit/telemetry/repr; bounded malformed input; unknown scopes; no browser IDs as authority; cross-subject/Account 404; revoked/expiry/downgrade/current membership; direct public/probe/load before DB connector; rotation race/revoke-versus-rotate; real audit INSERT rollback; native fresh-process/restart; schema checksum/missing authority; ENV removal/no resurrection; CSRF/Origin; CRLF/Windows unit and INDEX overlay parity. Issuance lost response cannot re-reveal secret: revoke and issue again; no secret-bearing idempotency cache. List is bounded (latest 100, active first, truncated flag), max 20 active keys per subject/Account.

Основания: [OWASP REST Security](https://cheatsheetseries.owasp.org/cheatsheets/REST_Security_Cheat_Sheet.html), [Secrets Management](https://cheatsheetseries.owasp.org/cheatsheets/Secrets_Management_Cheat_Sheet.html), [PostgreSQL16 locks](https://www.postgresql.org/docs/16/explicit-locking.html). Установка и границы реализации приведены ниже.

## Установка на VM и consumers

Миграция 0024 additive, без автоматического удаления/переноса legacy ENV. Перед переключением инвентаризировать consumers `CISSTAT_API_KEYS`, сопоставить каждый с существующими stable subject/Account и минимальными scope. Непривязанные legacy objects мигрируются отдельно через AUTH-09 с evidence. Старый секрет не загружается в таблицу и не превращается в пароль личного входа. Новый API в required/scoped не принимает ENV-ключ даже с прежним admin claim. Если consumers ещё не переведены, не переключать production API до согласованного окна замены; это явный разрыв совместимости программных credentials, а не изменение browser login.

Для service automation подготовить существующую service Identity и active membership доверенным контуром AUTH-02/08. CLI не создаёт ни пользователя, ни Account и не назначает роль/план. В новом образе после миграции `docker compose run --rm api python scripts/auth10/manage_keys.py issue-service ...` можно выполнить до переключения работающего API, проверить новые credentials после переключения и обновить consumers. Для персональных ключей нужен личный вход и новая API session; пользовательские UI-страницы управления Account остаются AUTH-17. Секрет из issue/rotate показывается один раз, хранится только у consumer в его secret manager; не помещать в URL, shell history, Git или browser storage.

Из корня репозитория после локальных гейтов, push тимлида и зелёного CI:

```bash
set -e
git pull --ff-only
cd deployment/cisstat-stack
unset CISSTAT_AUTH_MFA_KEYS CISSTAT_AUTH_MFA_ACTIVE_KEY
docker compose build api web
# Используется новый image, старый api пока может работать. БД уже запущена.
docker compose run --rm --no-deps api python scripts/auth10/migrate.py --apply
# Если --apply/ready не ok: остановиться, новый api не запускать.
docker compose up -d
docker compose exec -T api python scripts/auth10/migrate.py --check
docker compose ps
```

`unset` снимает только унаследованные shell overrides: реальные MFA keys по-прежнему читаются Compose из существующего .env; .env не менять/не печатать. Не выполнять `down -v`: durable volumes сохраняются. До migration нужен штатный проверенный backup PostgreSQL. Migration содержит transactional DDL/checksum ledger и повторный --apply idempotent. Новый API требует 0024 при durable key verification/management; отсутствующая/изменённая схема или guards → безопасный 503, без legacy/memory fallback. `--check` проверяет всю auth chain и четыре enabled lifecycle guards. Старые scientific schema/checksums не меняются.

CISSTAT_AUTH_DATABASE_URL, если задан, имеет приоритет над DATABASE_URL; DSN не передавать параметрами команд и не публиковать. У VM required storage profile default durable, новых обязательных env нет. Для тест/dev можно явно CISSTAT_API_KEY_MODE=durable; legacy_dev допустим только при advisory и non-scoped identity. Неверная конфигурация → 503. `health/ops.identity.api_key_authority` отражает выбранный режим, но не заменяет `migrate.py --check` с настоящей БД.

## HTTP и операторские команды

Все personal endpoints получают subject/Account только из валидной named session. Прямой API использует cookie `__Host-cisstat_auth`, точный trusted HTTPS Origin и действующий X-CSRF-Token для POST; first-party BFF пути `/api/v1/api-keys...` уже включены generated map. API key/Bearer на management endpoints не принимается. Смешанные credentials не объединяют права. Пример тела issue (в session клиенте, без X-API-Key):

```json
{"label":"ETL","expires_in_days":30,"scopes":["api.read","api.database"]}
```

GET возвращает только metadata/version. Rotate: `{"expected_version":1}` либо с более узким `scopes`; ответ содержит новый secret/key UUID. Revoke: `{"expected_version":1}`; повтор с актуальной версией терминально отозванного ключа идемпотентен. Stale version → 409, foreign/absent → uniform 404. По истечении 15 минут после auth/MFA для issue/rotate требуется новый личный вход (для ADMIN — с MFA); API key не является таким proof. Лимиты ключей технические (20 активных на subject/Account, list100+truncated), не CU/quota ledger.

Доверенный service CLI (UUID заменить значениями из проверенных server records, команды без сырого секрета):

```bash
docker compose exec api python scripts/auth10/manage_keys.py issue-service \
  --subject-id <SERVICE_UUID> --account-id <ACCOUNT_UUID> \
  --label ETL --expires-in-days 30 --scopes api.read api.database --reason "approved consumer migration"
docker compose exec api python scripts/auth10/manage_keys.py inspect \
  --subject-id <SUBJECT_UUID> --account-id <ACCOUNT_UUID> --key-id <KEY_UUID>
docker compose exec api python scripts/auth10/manage_keys.py rotate-service \
  --subject-id <SERVICE_UUID> --account-id <ACCOUNT_UUID> --key-id <KEY_UUID> \
  --expected-version 1 --reason "scheduled rotation"
docker compose exec api python scripts/auth10/manage_keys.py revoke \
  --subject-id <SUBJECT_UUID> --account-id <ACCOUNT_UUID> --key-id <KEY_UUID> \
  --expected-version 1 --reason "emergency revoke"
```

Mutations require interactive stdin/stdout; не `-T`, не redirect/tee для secret. Inspect безопасно не выдаёт token_hash/secret. Emergency revoke допускает inactive subject/Account, но только trusted local operator с точным owner scope/CAS; HTTP владельцу чужие ключи не открываются. Reason bounded/redacted; mandatory auth_api_key_changed intent atomically в прежнем auth_audit_outbox. Publisher/consumer остаётся действующим AUTH-04 механизмом (AUTH-20 rollout), отдельного журнала нет.

Scope map: api.read — templates/read template; api.write — file load; api.database — public DB test/load; api.compute — passport/regularity/validate и зарегистрированные programmatic modeling operations. Таблица в api_key_policy.py, unknown operation deny. Наличие scope не отменяет существующие object/model gates. Global rules override PATCH, internal/session/admin/docs/logs и browser routes durable key не делегируются. Ключ не получает роль ADMIN или MFA из label/ENV/request. AUTH-11 должен отдельно закрыть все browser/internal scientific альтернативы и общий operation admission; эта поставка не заявляет завершённой изоляции всего scientific API.

## Фактическая проверка

RED unit/diagnostics сохранены. Минимальный runtime11/11 unit; native PostgreSQL16.2 AUTH-02…10 169/169, финальный AUTH-10 с checksum oracle33/33; migration CLI apply/reapply/check PASS. Core local auth10…01/rules PASS; AUTH-00 в изолированном staged candidate44/44 + полный reviewed INDEX parity (545 discovery). Actual ASGI239, registry243, full inventory572;4 additions,0 removals. Generated OpenAPI/TS/BFF parity PASS. Jest2833 PASS, штатные2 skips/1 suite; обе production Next builds, renderer, typecheck и Ruff PASS.

Полный tests/api: 3451 PASS,43 SKIP,11 FAIL. На чистом c13a52b в том же runtime точно те же3451/43/11; добавленных FAILED-ID нет. Ошибки относятся к отсутствующему pwsh, прежней direct-call сигнатуре require_admin_role, старым app.routes assertions при текущем FastAPI, catalog/neural runtime/model message и прежним cert/docs expectations. Они не выдаются за зелёный full scientific suite; точные строки в protocols/api-delta.json. Windows/PG18/Docker engine/VM/browser E2E здесь не проверялись; CI matrix и команды VM приведены выше. Проверка task-only ZIP overlay и состав — protocols/delivery-overlay.txt и scripts/auth10/files.txt.
