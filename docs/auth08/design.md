# AUTH-08 — Account entitlements и membership lifecycle

База: `main@76eb8dba1773442794b30eb5907ff0f837b01d5d`. Сервер, по сообщению тимлида, на той же базе. Работа без commit/push. Журнал: `worklog/worklog11.md`.

## Контракт и граница

Account из PostgreSQL — источник плана, статуса, абсолютного срока и entitlement_version. ADMIN/INTERNAL_ANALYST не повышают аналитические возможности выбранного Account. INTERNAL — явный служебный entitlement Account, не коммерческий PlanName, не административное разрешение. OWNER не ADMIN. Сохраняются конечные baseline ceilings AUTH-01 и отдельные технические ограничения исполнителей; INTERNAL не отменяет object/tenant/scopes guards. Непривязанный ENV adapter остаётся явно legacy до AUTH-10; durable principal без account-effective caps отказывает.

`now >= plan_expires_at` запрещает доступ. Один общий predicate используется context, password account selection, session verification и MFA challenge. Серверное UTC время; никакого продления при login. Контекст обновляется на каждом запросе, межзапросного положительного cache нет. `/v1/auth/me` отдаёт проверенные effective capabilities, account plan/type/expiry/version; frontend сохраняет эту проекцию, а не пересчитывает её из роли. Фокус/refresh обновляют caps без смены SID; entitlement version входит в ключ очистки клиентских caches.

Lifecycle — trusted operator service/CLI: смена plan/status/expiry, MONO→MULTI с прежними account_id/tenant_id и без увеличения оплаченных seats; revoke/restore существующего membership в пределах seats. Последний OWNER, MONO=1 и capacity защищены существующими deferred SQL constraints AUTH-02. `closed` — terminal для lifecycle. Нет создания membership, приглашений, покупки мест, перевода OWNER или автоматической раздачи account-owned исследований: AUTH-09/17/18. CLI не монтируется в HTTP, требует интерактивный операторский терминал для записи, expected_version и причину; credentials не печатает. Repositories остаются trusted low-level API, не публичная policy.

Все lifecycle writers блокируют Account и проверяют CAS до записи. Изменение/отзыв + аннулирование относящихся к Account session/challenges + mandatory audit intent в существующем AUTH-04 outbox — одна транзакция. Membership revoke не отзывает другой Account того же subject. Restore/reactivation не воскрешают отозванные sessions/challenges. Downgrade активного плана не требует перелогина. При смене истёкшего/приостановленного состояния и при закрытии sessions отзываются; история/исследования и credential не удаляются. Без аудита — rollback, без БД — безопасный отказ.

Новых HTTP method/path нет. Изменён contract существующего me и auth guards; AUTH-00 review/fingerprints и AUTH-01 OpenAPI/TS обновляются явно. Новая SQL migration не нужна: 0019/0020/0021 уже содержат все необходимые поля/constraints/outbox. Checksum старых миграций сохраняется.

## Риски и проверки до реализации

1. ADMIN в demo/starter не получает tuning; external_user в INTERNAL не становится ADMIN. Legacy-only adapter проверяется отдельно.
2. Следующий запрос с прежним credential/SID после downgrade видит меньшие caps; ровно на expiry отказ в context/login/session/MFA. Отдельно account selection с несколькими memberships.
3. Suspend/revoke/restore не переносит доступ в другой Account и не оживляет старый SID/challenge. Последний OWNER/MONO/capacity, CAS и конфликт двух writers проверяются на PostgreSQL.
4. Fault на вставке audit intent откатывает Account/membership и session invalidation. Mandatory actions используют действующий каталог, не отдельный журнал.
5. Generated DTO/TS parity; frontend не выводит INTERNAL из роли и обновляет проекцию при прежнем SID. Сохраняются текущие AUTH-03…07/CSRF контракты.
6. CI Linux/Windows, native PostgreSQL 16/18, gate без DSN завершается ошибкой, skip не считается proof. Сборка/реальный ASGI route parity/HEAD parity проверяются отдельно. Недоступные проверки указываются честно.

Основание: spec_auth.md, spec_auth_architecture.md §3–4/9 (AUTH-08), docs/ROLES_AND_PLANS_SPEC.md RP-03…07 и spec_billing_accounts.md §2–3 с архитектурными уточнениями. Проверка каждого запроса: [OWASP](https://cheatsheetseries.owasp.org/cheatsheets/Authorization_Cheat_Sheet.html). Сериализация writers: [PostgreSQL explicit locking](https://www.postgresql.org/docs/16/explicit-locking.html).

## Операторская процедура

После цепочки ZIP → локальная машина → commit/push тимлидом → зелёный CI → pull на VM:

```bash
cd /opt/cisstat/CISStat-TS-Analysis
git pull --ff-only
cd deployment/cisstat-stack
docker compose build api web
env -u CISSTAT_AUTH_MFA_KEYS -u CISSTAT_AUTH_MFA_ACTIVE_KEY docker compose up -d
docker compose exec api python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8000/health/ops').read().decode())"
```

Пересобираются ОБА образа: Python authority и CLI — api; DTO/AuthContext — web. Новых миграций и изменений `.env` нет. Старые 0019/0020/0021 и их checksum не меняются. Слой 1 должен по-прежнему показывать `session_backend configured=postgres, effective=postgres, degraded=false`. Из этой сессии рабочая БД/VM не изменялись.

Account UUID можно взять из безопасного ответа `/api/v1/auth/me` в собственном вошедшем браузере; auth cookie/пароль не копировать. Оператор с SSH/доступом к Docker может прочитать Account и существующие memberships:

```bash
auth08_account_id='UUID-из-me'
docker compose exec api python scripts/auth08/manage_account.py show "$auth08_account_id"
```

Для записи требуется интерактивный терминал (не `exec -T`, не pipe), точная текущая `entitlement_version`, причина и ввод Account UUID для подтверждения. Это полномочие локального оператора, не self-service OWNER и не browser-admin endpoint. Ниже `42` — пример, заменить фактической версией из `show`:

```bash
docker compose exec api python scripts/auth08/manage_account.py apply "$auth08_account_id" \
  --expected-version 42 --change '{"plan":"starter"}' --reason 'Согласованное изменение тарифа'

# Явный срок UTC; null явно снимает срок. Login срок не переписывает.
docker compose exec api python scripts/auth08/manage_account.py apply "$auth08_account_id" \
  --expected-version 42 --change '{"plan_expires_at":"2026-12-01T00:00:00Z"}' --reason 'Согласованный срок'

# MONO→MULTI сохраняет IDs и seats=1. Не выдаёт второе оплачиваемое место.
docker compose exec api python scripts/auth08/manage_account.py apply "$auth08_account_id" \
  --expected-version 42 --change '{"account_type":"multi"}' --reason 'Подготовка командного Account'

# Только существующий участник; статус active — восстановление в пределах seats.
auth08_member_id='UUID-участника-из-show'
docker compose exec api python scripts/auth08/manage_account.py membership "$auth08_account_id" \
  --subject-id "$auth08_member_id" --status revoked --expected-version 42 --reason 'Отзыв доступа'
```

После каждой записи заново читать `show`: версия увеличивается, старую нельзя повторно использовать. Неизменяющий patch — no-op без лишнего аудита/версии. Конфликт версии/последнего OWNER/вместимости откатывает всё. `closed` в lifecycle терминален. Resume/restore требует нового входа для ранее отозванных SID; обычный downgrade активного Account виден следующему запросу без перелогина. Отзыв участника не затрагивает другой Account того же subject. Восстановление также аннулирует исторические SID/challenges, включая оставшиеся от прежних low-level writers.

Каждая изменяющая команда оставляет mandatory intent в `auth_audit_outbox`. Для публикации в действующий audit sink используется существующий операторский `scripts/auth04/publish_audit.py` из checkout (он, как и раньше, не копируется этим изменением в production image). Нет обещания автоматической доставки pending intents: сервис публикации/эксплуатационный rollout — AUTH-20. При необходимости публикации через одноразовый контейнер его файл можно смонтировать read-only из репозитория; отдельный security log не создаётся.

## Проверка и ограничения

RED: unit — реальное повышение capabilities по ADMIN/staff и отсутствие Account-effective DTO; UI — три поведенческих отказа; SQL на чистой базе — отсутствующий lifecycle module (17 errors). Дополнительный native RED доказал воскрешение SID при restore после низкоуровневого revoke; GREEN отзывает обе разновидности переходов membership.

Локально использован настоящий PostgreSQL **16.2** (штатные бинарники, отдельный временный кластер, TCP loopback, без изменения PostgreSQL binary/правил). AF_UNIX в среде запрещён; использована штатная настройка `unix_socket_directories=''`. Это native multi-backend SQL proof; WASM/Memory не используются как authority в этой проверке. Финальный AUTH-08 — 10 unit и 24 SQL/HTTP/fault/concurrency теста. Общая native AUTH-02/03/04/05/06/08 регрессия выполняется отдельно; точные числа и протоколы — worklog11 и `scripts/auth08/protocols/`.

Полный Jest: 2831 passed, 2 предсуществующих skipped (252 passed suites + 1 skipped). Renderer build, обе TypeScript проверки и обе production Next.js сборки завершились успешно. AUTH-00/01 и реальный OpenAPI проверяются после source review: HTTP paths остаются 234, registry bindings 238. Одна новая non-HTTP operator boundary увеличивает общий inventory 564→565. Чистый baseline и изменённое дерево дают одинаковые 2 FAILED-ID в адресном научном/API регрессе (FastAPI 0.162 lazy router introspection в старых static assertions); ни одна новая ошибка задачи там не появилась.

Native PostgreSQL 18 и Windows 2025 остаются обязательными удалёнными заданиями нового `auth08.yml`; из этой сессии CI не запускался. Docker-образ не собирался локально (Docker отсутствует), но его исходники/CLI и сборочный import guard проверены; образы собирает VM после push/pull тимлида. Операционная приёмка на рабочем datasetup.ru остаётся за установкой этой поставки. Comprehensive scientific admission/ownership/worker fencing — AUTH-09/11/13, не заявлены выполненными этой задачей.
