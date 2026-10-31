# AUTH-03 — Unified context и compatibility adapters

База: main@be553b8ff6e6471eb53427822ccd937a3a71433a, 31.10.2026 (Москва).
AGENTS.md, spec_auth.md и spec_auth_architecture.md §2–5/8–9, worklog11,
AUTH-00/01/02 и auth/identity/logs/session/object consumers изучены.
Новая синхронизация, commit и push не выполняются.

## Проектирование и граница

Один immutable RequestContext на HTTP request; auth.py и identity.py — его
совместимые проекции. Никаких новых routes, login, cookies, DDL или пользователей.
AUTH-04 реализует личный session verifier; AUTH-08 — effective entitlements;
AUTH-09 — account-owned resource policy/claim; AUTH-10 — durable API key lifecycle;
AUTH-11 — enforcement на пока открытых scientific/internal paths.

Точки изменения: authentication/context.py (coordinator и verified evidence),
authentication/legacy.py (ENV compatibility), auth.py, identity.py, plans.py
(безопасный principal), routers/logs.py (устранение key-only обхода request
coordinator). Existing authorize_run_access остаётся единственным object policy.

## Trust и выбор credentials

- Явно предъявленный неверный/пустой/дублированный X-API-Key даёт 401/400 ДО
  research cookie и других credentials. Ошибка authority — 503, никогда fallback.
- CredentialVerifier устанавливается только сервером в app.state; возвращает
  VerifiedCredential, а не значения identity headers. По умолчанию работает
  только ENV key adapter. Личная auth cookie без установленного verifier — 401;
  это не фиктивный login. Контракт следующего AUTH-04: verifier проверяет подпись/
  hash, expiry/revoke/challenge и выдаёт только завершённый вход.
- Два verified credentials разных subjects или account bindings — 400
  auth_ambiguous. При совпадении используется ключ с его scopes ceiling, права
  не объединяются; наличие cookie не превращает key в browser authentication.
- cisstat_session_id — research pointer, не AuthSession. В session_scoped/dev
  сохраняется явно маркированный legacy surrogate. Если pointer существует и
  имеет другого server-side owner/tenant относительно предъявленного входа,
  запрос отклоняется auth_ambiguous: он не переназначает владельца. Неизвестный
  pointer не конкурирует с valid key. Scoped-режим не принимает surrogate как
  личный вход; unbound legacy ENV keys не являются durable credentials.
- Неподписанные X-Subject/Tenant/Account/Role/MFA игнорируются. Account берётся
  только из проверенного credential binding, не автоматически из списка Account.

## Authority и проекции

Durable VerifiedCredential указывает UUID subject/account. В одной readonly UoW
AUTH-02 перечитываются Identity, Account и active Membership. Missing/suspended
identity — 401; missing/closed/suspended Account или membership — 403; storage/
schema failure — safe 503. Tenant, role и версии берутся из DB. Выданные scopes
остаются ceiling credential; OWNER не становится ADMIN. Plan expiry и effective
commercial policy дорабатывает AUTH-08; context не выдаёт новый capability engine.
PostgresAccessStore не кешируется между запросами и не выполняет миграций.

ENV keys сохраняют прежние 3/5/6 сегментов в legacy режимах; principal_id теперь
safe subject ID, credential_id — domain-separated HMAC reference. Explicit UUID
subject + седьмой сегмент account UUID дают переходный durable binding: роль,
tenant и plan из ENV НЕ заменяют DB. Это deployment binding до AUTH-10, не
публичное создание API keys. Scoped требует именно durable binding.

RequestContext содержит provenance, subject/credential/auth-session references,
active account/tenant/membership/versions, auth_time/MFA evidence, scopes,
platform permissions и request_id; отсутствующие данные остаются None/empty.
Surrogate никогда не преобразуется в AuthenticatedPrincipal на key-protected
пути. require_api_key сохраняет str-контракт, возвращая safe principal ID.
/models/train сохраняет форму ответа, сырой ключ в него больше не попадает.

## Риски и TDD

RED→GREEN: invalid key + owned cookie; empty/duplicate keys; ambiguous identities
и account bindings; exact scope ceiling; shared resolver/cache; secret-free
repr/serialization/response/audit; missing key 401 вместо 422; outage без
surrogate; restored-owner continuity; scoped no surrogate; unsupported auth
cookie; no client identity trust; DB suspend/revoke/version freshness/tenant;
logs manual adapter; unchanged object uniform-404 и public key requirement.

Далее: AUTH-00 source/policy review (HTTP method/path IDs сравниваются с базой),
AUTH-01 generated parity, Python affected regressions и baseline comparison,
Jest/renderer/typechecks/Next build; границы среды фиксируются отдельно.
ZIP содержит только текущий diff, inventory и byte/CRC проверяются.

## Итоги реализации и миграционные уточнения

Реальный `_authorized_run` в progress.py теперь резолвит контекст ДО поиска
объекта. Иначе новый invalid-key 401 отличался бы от missing-run 404. Отдельный
RED воспроизвёл это различие; GREEN проверяет одинаковый 401 для двух IDs,
а существующий foreign/absent object отказ без входа остаётся uniform-404.
Request ID берётся из действующего telemetry ContextVar: body/header/audit имеют
одну корреляцию. Отдельный RED→GREEN закрепляет это на реальном middleware.

Server verifier выбирается по `is None`, не truthiness: недоступный falsey adapter
не переключается на ENV. Его HTTPException/driver errors нормализуются в safe
401/503 и не передают произвольный detail клиенту. Два собственных RED→GREEN
теста проверяют fallback и утечку detail. Положительный context cache живёт только
в request.state; последующий запрос перечитывает authority.

Versioned compatibility pins: admin missing registry 500→503; scoped surrogate
не получает даже личного субъекта, поэтому object denial 404 вместо прежнего
scope-denial 403. Четыре сценария старых тестов (два согласования, отчёт,
Наставник) теперь явно убирают чужой research pointer при переключении на ADMIN.
Для согласования дополнительно доказан отказ 400 ДО переключения. Эти правки
сохраняют проверки второго лица, lifecycle и фильтрации чужих научных данных.

Важно для потребителей: require_api_key по-прежнему возвращает строку, но это
safe subject ID, НЕ секрет для повторной отправки upstream. Старые 3/5/6-field
ENV entries поддерживаются только в legacy identity modes; canonical UUID subject
с account UUID в седьмом сегменте использует DB authority даже вне scoped.
Пример формы (не действующие credentials):
`<key>:external_user:starter:<subject-uuid>:tenant-legacy:documentation.read:<account-uuid>`.
В durable binding значения ENV role/plan/tenant не задают effective authority.

AUTH-03 не объявляет выполненными AUTH-04/05/07/08/09/10/11: личного входа,
MFA enforcement, account-owned run migration, полного scientific admission и
замены legacy role-based capability facade здесь нет. Protected key dependencies
остаются key-only до AUTH-07; plain research cookie не удовлетворяет им.
DB Account plan уже переносится в context, но effective entitlements (включая
политику INTERNAL и plan expiry) реализует AUTH-08.

## Воспроизводимость

```sh
python -m pip install -r scripts/auth03/requirements.txt
python scripts/local_gates.py --only auth03,auth02,auth01,auth00,rules
python scripts/auth03/verify_postgres.py  # disposable CISSTAT_AUTH_TEST_DSN required
# Optional SQL-engine rehearsal, not a native PostgreSQL certificate:
python scripts/auth03/pglite_check.py --modules /path/to/isolated/npm/tooling
```

`auth03.yml` выполняет contracts на Linux/Windows и обязательный SQL корпус на
native PostgreSQL 16/18. Отсутствие DSN в mandatory runner — exit=2, не PASS/skip.
Локальный SQL proof — PostgreSQL 18.6 / PGlite 0.5.14 через psycopg, шесть проверок
актуальности записей/отзыва/статуса/изоляции. Native PG/remote CI и реальные
Render/Vercel/SSO/browser sessions этим прогоном не сертифицированы.
