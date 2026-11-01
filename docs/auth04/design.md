# AUTH-04 — Opaque sessions, password и revoke

База d3f78a79d71a9768dfd4d24c2cad2c1f0764dc57, 31.10.2026 Москва.
Отдельный detached checkout сохраняет AUTH-03. AGENTS.md и спецификации,
журнал AUTH-00…03, repositories/UoW, context, audit, routes изучены.
Ни commit/push, ни реальные credentials/users не создаются.

## Процесс, граница и риски

Дизайн → RED password/service/SQL/HTTP contracts → реализация → fault/negative
проверки → API IDs/policy review AUTH-00 + AUTH-01 bindings → гейты/сборка → ZIP.
Риски: plaintext в БД/422/logs, fixation, idle sliding за absolute, resurrection
после password/revoke/suspend, grant/account substitution, racing logout/login,
DB outage→surrogate, CSRF login/logout, password-only ADMIN, audit-after-write.

PostgreSQL-only authority AUTH-02 + единый context AUTH-03; отдельная миграция
0020 после 0019. Reader/migration прежнего AUTH-02 не меняет свой контракт.
Credentials/session/security epoch/rate buckets/audit outbox — новые auth-owned
таблицы. Identity/Account/Membership и scientific data не переписываются.

Credentials: canonical explicit login, Argon2id (64 MiB, t=3, p=1), version/status,
server scopes ceiling. Длинные passphrases без composition/trim/truncation;
15…1024 UTF-8 bytes bounded, минимум 15 символов; локальный versioned blocklist
и optional deployment blocklist. Начальный список не называется полным breach
corpus. Unknown login проверяется dummy Argon2, generic denial. Durable bounded
rate buckets + process hash concurrency cap; shared forum credential сюда не
подключается (AUTH-15/16), global campaign lockout не вводится.

AuthSession: random 256-bit opaque SID, отдельно safe UUID session/family refs;
в БД только SHA-256 domain-separated verifier. Frozen absolute 8h / idle 15m,
UTC server clock; idle ≤ absolute; expiry inclusive. Snapshot credential/subject
versions + subject session_epoch, online check на каждом запросе. Identity lock
перед session lock, current DB state без межзапросного positive cache.
Revoke individual/family/all terminal, password change/revoke invalidates all;
suspend/role change и повторная активация не оживляют старые версии. Login всегда
новый SID, прежний browser SID отзывается; ни SID, ни family от клиента не берутся.

Обычный password login проверяет account membership; account_id — selector,
не право. OWNER не ADMIN. ADMIN password proof не выдаёт full AuthSession:
ответ mfa_required до AUTH-05, без фиктивного challenge. Key-only admin/API
compatibility AUTH-03 сохраняется до AUTH-07/10; cookie не открывает public API.
Login/logout/password/revoke не claim-ят legacy runs: research pointer удаляется,
серверные scientific данные не удаляются и владельцы не назначаются автоматически.

## HTTP и транспорт

/v1/auth: GET csrf, POST login, GET me, GET sessions, POST logout,
POST sessions/{session_id}/revoke, POST sessions/revoke-all, POST password.
Session secret только __Host-cisstat_auth (Secure/HttpOnly/Path=/, без Domain,
SameSite=Lax). Нет token в URL/JSON/storage. Все ответы auth — private,no-store.
Auth routes sanitise 422 без input/password. Неизвестный/неверный предъявленный
credential не превращается в research surrogate; DB/schema outage — safe 503.

Ограниченная необходимая CSRF foundation уже здесь: exact trusted Origin из
CISSTAT_AUTH_ALLOWED_ORIGINS (или ALLOWED_ORIGINS), Fetch Metadata, double-submit
__Host-cisstat_csrf + X-CSRF-Token с HMAC и привязкой к текущему auth cookie,
TTL 10 минут. CISSTAT_AUTH_CSRF_KEY ≥32 bytes обязателен; default signing key нет.
GET csrf только выпускает CSRF proof, без AuthSession/identity и смены research
состояния. Signed proof не является auth credential. Cookie-auth mutations вне
/auth также проверяет session verifier; GET restore с побочным эффектом закрыт
до защищённого transport AUTH-06. Общий BFF/UI/SSO и CSRF rollout всех открытых
scientific путей — AUTH-06/11; они не объявлены завершёнными.

## Аудит и эксплуатация

Изменения password/session/revoke и audit intent в одной AUTH-02 UoW. Outbox —
обязательство доставки EXISTING security_audit record/catalog, не второй журнал.
Сбой записи outbox откатывает команду. Bounded replay CLI публикует в действующий
sink с тем же audit_id; retry идемпотентен. Publication outage сохраняет pending,
не отменяет уже зафиксированный revoke. Sensitive secrets/verifiers отсутствуют
в audit payload. Никакого отдельно коммитящего sink внутри auth mutation.

Password provisioning — trusted internal method, не public registration или
first-admin bootstrap CLI. Self-service change требует текущий пароль; recovery,
MFA/bootstrap — AUTH-05, email/OIDC — AUTH-19, entitlements/owner bridge — AUTH-08/09.
Нативный PG 16/18 CI обязателен; local WASM SQL proof отдельно от native locks.

## Реализация и эксплуатационная инструкция

HTTP routes перечислены и проверяются по реальному OpenAPI (228 methods),
AUTH-00 (548 entries) и AUTH-01 (232 bindings, из них 4 aliases). Восемь auth
operations имеют external authority, analytical capability не является допуском.
Гейт --check не подменяется регенерацией; review и --write — явные шаги.

Применение (DSN/секреты в окружении, не в argv):

```sh
python -m pip install -r scripts/auth04/requirements.txt
python scripts/auth04/migrate.py --apply
python scripts/auth04/migrate.py --check
python scripts/auth04/publish_audit.py --limit 100
python scripts/local_gates.py --only auth04,auth03,auth02,auth01,auth00,rules
# Disposable native PostgreSQL:
python scripts/auth04/verify_postgres.py
```

`CISSTAT_AUTH_DATABASE_URL` → `DATABASE_URL`, без памяти/SQLite. HTTP transport:
`CISSTAT_AUTH_ALLOWED_ORIGINS=https://ts-standalone.vercel.app,<embedded-origin>`
(или существующий ALLOWED_ORIGINS) и `CISSTAT_AUTH_CSRF_KEY` — отдельный случайный
секрет ≥32 bytes, общий для инстансов. Значения не создавались этим заданием.
Для audit consumer нужны существующие durable настройки security_audit
(`DATABASE_URL`/`CISSTAT_AUDIT_BACKEND=postgres`); auth outbox остаётся pending
при недоступном consumer. CLI не выдаёт dev Memory sink за durable доставку.
Применение 0020 не происходит на import/request. Неверный checksum 0019/0020,
недоступная БД/таблица/драйвер — 503 без смены identity.

Read-only CSRF bootstrap допускает exact Origin; same-origin browser GET без
Origin требует `X-CSRF-Request: 1` + `Sec-Fetch-Site: same-origin`. JSON содержит
только CSRF proof, HttpOnly host-cookie — его double-submit counterpart. После
этого клиент посылает X-CSRF-Token; все unsafe команды всё равно требуют exact
Origin, проверенный сервером, и proof, привязанный к текущему SID. Вход/выход
ротируют/удаляют cookie, поэтому после них proof запрашивается заново. Нет
доверия к X-Forwarded-Host/клиентским identity headers. Origin binding SID
проверяется, если Origin предъявлен; cross-site Fetch Metadata отклоняется и
для чтения. GET legacy restore с side effect при auth cookie закрыт до AUTH-06.

Auth responses no-store/nosniff, 422 не содержит input. POST auth payload
ограничен 16 KiB перед JSON parser, password UTF-8 ограничен отдельно, Cookie
parser ограничен и отклоняет duplicate auth SID. Secrets только в password input
и Set-Cookie; UUID session/family refs пригодны для self-revoke, но не для входа.
Список sessions ограничен последними 100 записями (retention/history — AUTH-20).

Trusted password provisioning — SessionService.set_password(subject, login,
password, expected_version=..., scopes=...). Перед вызовом сервер/оператор
проверяет полномочия; он не доступен как HTTP endpoint. Никакой реальный subject,
пароль, Account или deployment secret не выпускался. Role/status version guard
AUTH-02 уже требует +1 даже для raw SQL; дублирующий trigger в 0020 не добавлен.
Параметры Argon2id self-describing в verifier + PASSWORD_POLICY_VERSION.
При rehash version повышается и прежние sessions закрываются — явная безопасная
политика обновления параметров, не необоснованная периодическая смена пароля.

Rollback: отключить новые входы/писателей, сохранить credentials/revocations и
outbox. Возврат к открытому scoped/surrogate authority запрещён. Приложенный
rollback_0020.sql применим только к EMPTY dev schema и отвергает данные/поздние
миграции; без CASCADE. User research cookie удаляется на login/logout/password/
self-revoke-all, данные и owner остаются на сервере. Account-owned scientific
workflow/миграция legacy IDs не выполнены до AUTH-08/09/11; standalone login UI,
единый BFF и MFA — AUTH-05/06/07. Готовность login/session API не означает
сертификацию полного пользовательского научного пайплайна после входа.

## Проверки и честные границы

20 unit/ASGI/source-route contracts, 42 SQL/HTTP/fault/concurrency contracts.
SQL proof локально: PostgreSQL 18.6 / PGlite 0.5.14, psycopg wire. Для реального
PostgresAuditSink lost-ACK/replay используются отдельные auth/audit SQL engines:
один PGlite multiplexer сериализует транзакции и блокирует nested consumer commit.
Первый однобазовый rehearsal честно остановлен timeout; двухбазовый proof не
выдаётся за native multi-backend scheduling. Native PostgreSQL 16/18 обязательны
в auth04.yml; remote CI не запускался, native locking/restart здесь не доказаны.
Mandatory runner без DSN возвращает 2 и не считает skip PASS.

Нативные цели: expiry inclusive, fixation/old SID invalidation, logout/revoke/
family/all, current password proof, suspend/reactivation/version, concurrent
revoke/touch, outage→503, audit intent rollback + PostgreSQL consumer dedup,
fresh Python process, same self identity/tenant и secret-safe responses.
Дополнительный AUTH-00 RED→GREEN закрепляет CRLF portability .txt blocklist.

Первичные источники (сверены 31.10.2026):
[OWASP Password Storage](https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html),
[OWASP Session Management](https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet.html),
[argon2-cffi API](https://argon2-cffi.readthedocs.io/en/stable/api.html).
Argon2 параметры не называются benchmark/SLA; полная breach corpus и нагрузочная
калибровка задаются deployment policy, не выдумываются по одному локальному тесту.
