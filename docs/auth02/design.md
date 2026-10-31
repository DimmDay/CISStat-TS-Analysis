# AUTH-02 — Durable identity/account schema и repositories

База: `649027ee3e97c46bb64cb0e7319790c022a0c3bc`, 31 октября 2026, Москва.
Прочитаны AGENTS.md, spec_auth.md, spec_auth_architecture.md §2–5/8–9,
Role/Plan RP-01/03/05/06/07/12/14, billing Accounts и worklog11 (AUTH-00/01,
Windows encoding/CRLF, документные миграции). SHA подтверждён GitHub и локально.
Работа в отдельном detached worktree; прежние файлы сохранены; commit/push нет.
Исторические blockers 21946a7/ad7dd4b не относятся к доступной текущей базе.

## Граница и процесс

Результат — PostgreSQL foundation четырёх сущностей: Identity, ExternalIdentity,
Account, Membership. Их persistence не является входом/выдачей прав пользователю.
Credentials/AuthSession/challenges/MFA/APIKey lifecycle — AUTH-04/05/10;
актуальный request context — AUTH-03, account entitlement policy — AUTH-08,
legacy ownership bridge — AUTH-09, invitation/seats billing — AUTH-17/18.
Forum grants и CU/wallet не вводятся этим срезом.

Процесс: исходники/инварианты → тесты и RED отсутствующего storage → SQL +
repositories → PostgreSQL SQL engine проверки → отдельный RED unsafe DSN error
и SQL/CRLF fingerprint → GREEN → source/policy review AUTH-00 → gates/build/ZIP.
Риски: identity merge по email, ранний commit в одном repository, write skew
membership, последний OWNER, потеря tenant при MONO→MULTI, stale version,
расхождение ops SQL/runtime DDL, silent memory fallback, секрет в driver error,
нечестный PASS при пропуске PostgreSQL-тестов. Проверки ниже адресуют эти риски.

## Схема

`apps/api/migrations/0019_auth02_identity_accounts.sql` — следующий свободный
номер после существующих 0001…0018. Четыре новые таблицы; пятая служебная
`auth_schema_versions` создаётся мигратором. Старые таблицы, их строки,
owner_subject, scientific artifacts и исторический audit не переписываются.

| Таблица | Ключевые свойства |
|---|---|
| auth_identities | UUID subject_id, person/service, platform_role, active/suspended, subject_version, UTC timestamps |
| auth_external_identities | PRIMARY KEY (issuer, external_subject), FK subject; exact C collation; email/verified metadata без UNIQUE email |
| auth_accounts | UUID account_id, отдельный UNIQUE tenant_id, mono/multi, plan/status/seats, entitlement_version, optional plan expiry |
| auth_memberships | PRIMARY KEY (account_id, subject_id), FK, owner/member, active/revoked, joined_at |
| auth_schema_versions | version + normalized SQL checksum + applied_at; один источник DDL |

UUID создаются сервером, create Account не принимает tenant/account ID из
клиентского тела. Один User может иметь несколько Account. Account OWNER не
меняет platform_role; service/internal — отдельный persistence plan, не выбор
в pricing UI и не автоматическое следствие ADMIN. Политика назначения internal
и effective caps относится к AUTH-08; коммерческий PlanName/TS не расширен.
Поля финансового кошелька/фиктивный CU balance не создаются до соответствующих
AUTH-задач. Private participant — будущий отдельный flow, не shared OWNER.

Subject, external issuer+sub→subject, Account ID/tenant и membership keys
неизменяемы через UPDATE triggers. FK используют RESTRICT, не каскадное удаление
identity/ownership. Email не является ключом автоматического merge; один
verified email может встретиться у разных subjects. Никаких raw keys/passwords,
AuthSession tokens или их фиктивных plaintext колонок здесь нет.

## Membership, concurrency и версии

Для любого сохранённого Account в момент COMMIT:

- минимум один active OWNER;
- число active memberships не превышает seats;
- MONO имеет seats=1 и ровно одно active membership (следовательно OWNER).

Closed status не позволяет удалить последнего OWNER; для полного purge нужна
отдельная атомарная политика удаления Account с зависимостями. Доступ по статусу
ещё обязан закрывать будущий context coordinator. INSERT Account + OWNER одной
транзакцией необходим: промежуточное пустое состояние допустимо только до COMMIT.

BEFORE membership INSERT/UPDATE/DELETE делает настоящую UPDATE parent Account,
увеличивает entitlement_version и получает row lock. Constraint triggers на
Account и Membership — DEFERRABLE INITIALLY DEFERRED — проверяют итоговую картину.
Это не cross-table CHECK с гонкой. Прямые SQL писатели тоже проходят ограничения.
Parent write дополнительно исключает тихий write skew при более строгой snapshot
изоляции (serialization failure). Repository соединения явно READ COMMITTED.
Несколько Account в общей команде следует блокировать в стабильном порядке;
deadlock/serialization failure возвращается как безопасный VersionConflict.

Opaque versions строго возрастают: subject update +1; Account update +1;
каждая membership mutation автоматически +1 у Account, включая прямой SQL.
Поэтому созданный Account с OWNER уже имеет version=2; клиент не должен
предполагать «первая версия всегда 1». Это не счётчик тарифной квоты.
CAS update/add/update_member требует expected_version и блокирует parent row;
stale writer не затирает downgrade/состав/тип. MONO→MULTI сохраняет Account/tenant.
Обратный переход с лишними active members и снятие последнего OWNER отклоняются
на COMMIT. Разрешённая передача OWNER может временно менять оба membership в
одной транзакции; итоговый OWNER обязателен. Новые API для этого не созданы.

Primitive add_member/update(seats/plan) — внутренние trusted persistence методы.
Их нельзя выдавать напрямую в HTTP без AUTH-08/17/18 permission, paid seat
capacity, idempotency, quote/provider и аудита. Они не реализуют оплату, invitations,
self-service или server request membership resolution сами по себе.

## Repository / Unit of Work

`authentication.storage.PostgresAccessStore.transaction()` даёт один connection
и связанные `tx.identities`/`tx.accounts`. Методы repositories не открывают вторые
соединения, не commit, не создают schema. Исключение, deferred constraint failure
или сбой приложения откатывает всю команду. Commit выполняет внешний context.
Новый Python-процесс читает committed records, без модульного authority cache.

```python
store = PostgresAccessStore.from_env()
with store.transaction() as tx:
    identity = tx.identities.create()
    tx.identities.link_external(identity.subject_id, issuer, external_sub)
    account = tx.accounts.create(identity.subject_id)
```

Пример — внутренний вызов после проверки источника identity. Он не означает,
что доверять issuer/sub из browser body допустимо; OIDC signature/issuer/nonce
проверяет будущий provider adapter AUTH-19.

Connection DSN — `CISSTAT_AUTH_DATABASE_URL`, иначе `DATABASE_URL`. Нет memory/
SQLite fallback. Пустая конфигурация, недоступная БД и malformed DSN дают
AuthStoreUnavailable; schema/checksum не готовы — AuthSchemaNotReady;
constraint/data violation — RepositoryConflict; stale version — VersionConflict.
Driver messages/DSN не попадают в repr/доменные сообщения. connect timeout 3 s,
statement timeout 5 s, lock timeout 3 s, timezone UTC. HTTP status mapping — AUTH-03.
Readiness не выполняет DDL и проверяет ledger/checksum и наличие четырёх таблиц.

Дальнейшие policy changes обязаны дописывать mandatory audit intent/outbox в ту
же транзакцию с использованием существующего security_audit каталога. Нельзя
вызвать нынешний отдельно коммитящий sink после update и считать это атомарным
аудитом. Общий connection предоставлен для этого; отдельный независимый auth
журнал не создан. Новые privileged HTTP commands пока не экспонированы.

## Миграция и rollback

Миграция явная, reader-first; приложение не выполняет DDL при import/readiness.

```sh
python scripts/auth02/migrate.py --apply
python scripts/auth02/migrate.py --check
```

Передать DSN через окружение, не CLI аргумент или URL в логе. Schema production
по умолчанию public, не создаётся неявно; миграцию выполняет отдельная роль с
DDL privileges. Рабочему сервису нужны только целевые DML/SELECT права; ledger
и DDL оставить deployment owner. Тесты используют случайный изолированный schema.

Мигратор: transaction advisory lock на schema → ledger → checksum guard →
единственный SQL-файл → запись версии в той же транзакции. Повтор — no-op только
при совпадающем checksum, дрейф закрывает доступ. CRLF/BOM SQL нормализуются для
checksum; AUTH-00 fingerprints .sql также нормализуют CRLF. Научный research_runs
migration catalogue 0001…0018 не расширяется вторым владельцем auth schema и
сохраняет прежнее поведение. Ops должны применить отдельный auth migration step.

Проверены rollback identity+external+account/member команды и transactional DDL
rollback. `scripts/auth02/rollback_0019.sql` — только репетиция EMPTY dev schema:
при любых identity/account данных или следующих auth migrations отказывает;
DROP без CASCADE. Production rollback сохраняет эти таблицы и отключает новых
писателей, legacy readers остаются совместимыми. Это не разрешение удалять
накопленные identity данные. Replay/reconciliation backup credentials/grants/
wallet относится к AUTH-20/25, такие сущности этим срезом не создавались.

## AUTH-00 и проверки

API paths/methods и четыре task aliases не изменены: API 220; AUTH-01 bindings 224
сохраняются. В полную AUTH-00 карту добавлены только три явных non-HTTP entry:
identity storage, account storage и schema apply. Всего **537** записей вместо 534.
Policy auth.storage отражает trusted coordinator boundary. Новых public endpoints,
background workers и смены текущего browser/API resolver нет.

Тесты:

- unit factory/config/error contracts, missing DSN fail closed;
- live SQL unique subject/issuer+sub/member, FK, no email merge, immutable IDs/tenant;
- cross-repository rollback, deferred MONO/OWNER checks, CAS и две competing writes;
- idempotent/checksum migration, rollback DDL, empty-only down/reapply;
- совместимость всех старых 0001…0018 SQL и legacy research row;
- fresh Python process и отдельный seed→DB process stop/start→verify;
- четыре deliberate constraint mutants (issuer PK, membership PK, tenant immutability,
  membership guards) должны падать assertion'ами, не infrastructure errors;
- AUTH-00 SQL CRLF RED→GREEN, обычные AUTH-00/01 gates, typechecks/renderer/Jest.

```sh
python -m pip install -r scripts/auth02/requirements.txt
python scripts/local_gates.py --only auth02,auth01,auth00
# Disposable PostgreSQL; тесты создают/удаляют только свои случайные schemas:
python scripts/auth02/verify_postgres.py
python scripts/auth02/mutation_rehearsal.py
python scripts/local_gates.py --only auth02-postgres
```

Live runner требует CISSTAT_AUTH_TEST_DSN: без него exit=2, skipped suite никогда
не становится PASS. Обычный local auth02 — только unit (явно указан в label);
`--with-auth02-postgres` добавляет SQL/negative-oracle gate. Без него итог
local_gates явно сообщает, что live PostgreSQL не проверен, вместо общего
разрешения push. В CI auth02.yml PostgreSQL 16/18 services,
SQL/negative oracles и restart service обязательны; unit также Linux/Windows.

## Граница фактического локального доказательства

Нативный PostgreSQL 16.2 binary доступен, но песочница не реализует смену OS UID/
chown (EINVAL); штатный сервер запрещает root. Root guard не отключался, бинарники
не патчились, системные users/permissions не изменялись. Нативный сервер и его
multi-backend scheduling локально не проверены; удалённый CI не запускался.

Дополнительный local SQL proof выполнен на **PostgreSQL 18.6 / PGlite 0.5.14 WASM**,
через настоящий psycopg/wire protocol. 18/18 SQL tests, 4/4 mutants detected,
DDL/application rollback и DB process restart с повторным чтением сохранённых
identity/external/account/member/versions прошли. WASM transport serializes
transactions между connections: это полезная SQL/DDL/persistence проверка,
**не доказательство нативных lock races/процессов Postgres 16/18**. Нативная часть
критерия приёмки AUTH-02 требует подготовленного CI/live PG прогона. Нет заявления
о production rollout, completed AuthN или сквозной AUTH-CERT.

Опциональная репетиция воспроизводится pglite_check.py с npm tooling отдельно от
API dependencies; это не альтернативный production backend. PostgreSQL сервис
для native verification должен быть disposable, не пользовательская production DB.

Первичные источники: [PostgreSQL constraint triggers](https://www.postgresql.org/docs/16/sql-createtrigger.html),
[constraints](https://www.postgresql.org/docs/16/ddl-constraints.html),
[psycopg transactions](https://www.psycopg.org/psycopg3/docs/basic/transactions.html),
[PGlite socket limitations](https://github.com/electric-sql/pglite/blob/main/packages/pglite-socket/README.md).

## Итог локальных checks

AUTH-02 unit 4/4; SQL engine corpus 18/18; negative mutants 4/4; fresh client
process + WASM DB stop/start PASS. AUTH-00 28/28 (включая новый SQL/CRLF),
AUTH-01 26/26 и обе locale-эмуляции PASS; generated parity PASS. Full Jest
245 suites / 2791 tests, 0 failures; renderer build/typecheck обеих оболочек PASS.
Rules gate PASS. Python compile и ZIP byte/CRC checks выполнены при поставке.
Next production build попытка снова BLOCKED средой: ENOENT uv_resident_set_memory;
успешная Next production сборка не заявляется. Полный scientific pytest/main
startup, real browser/SSO и native PostgreSQL не выполнялись. См. protocol summary.
