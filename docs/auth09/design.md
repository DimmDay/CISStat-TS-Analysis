# AUTH-09 — Object ownership bridge и legacy migration

База c2217ec5ba38116e9da6413dc2c56794aefb89b5. Восстановление утраченной поставки; все результаты проверяются заново. Commit/push и VM этой задачей не меняются.

## Решение

owner_account_id у run/session задаёт владельца Account; owner_subject сохраняет первоначального автора/provenance, включая неизвестное значение. Account/tenant проверяются раньше ADMIN/dev/creator cookie. Действующий MEMBER имеет доступ к account-owned объектам через существующий authorize_run_access, используемый также DOCLOG snapshots/artifacts/jobs/revisions/lifecycle. Неизвестные действия запрещены. Legacy не присваивается командному Account молча: named субъект читает своё доказанное private legacy, но write/restore требует миграции.

Центральный session pointer guard сначала получает текущую AuthN, затем проверяет session/run. Cookie исследования не credential. Новая named session получает случайный server ID и Account binding, неизвестный/пустой legacy pointer заменяется. Содержательный legacy pointer без миграции — 404. Неверный/revoked credential не переходит к cookie; недоступный authority — 503. Login/logout/account switch уже удаляют pointer и ротируют auth SID.

POST /v1/progress/runs/{run_id}/restore использует существующие Origin/CSRF и BFF. Старый GET остаётся для legacy совместимости, named cookie на нём блокируется. Restore наследует Account/tenant/автора (включая None), не передаёт собственность. Чужой pointer не может использоваться для abandonment чужого run. Общий клиентский helper подготовлен для history UI; нового экрана истории здесь нет.

Legacy migration — только доверенный интерактивный оператор, без HTTP claim. Основание/evidence и причина, ожидаемые owner/tenant/ownership_version=0 и актуальная версия target Account обязательны. PostgreSQL UoW блокирует Account→run→текущую session, проверяет active target, сохраняет автора, создаёт immutable receipt и mandatory audit intent в существующем auth_audit_outbox атомарно с binding. Живая persisted session получает metadata/schema/CAS revision в той же транзакции. Scientific bytes, events, подписи и старый audit не переписываются. Повтор, конкурентные target и обычный UPSERT не передают ownership. Сбой audit INSERT откатывает всё.

Миграция 0023 аддитивная, без массового backfill: owner_account_id UUID, ownership_version, индекс, receipt, SQL guards. Auth migrations 0019–0021 не меняются. Session JSON 4→5, старые JSON остаются legacy. Memory UPSERT запрещает перенос так же, как PostgreSQL.

## Риски и проверки

TDD: same subject/different Account; foreign tenant ADMIN/dev; surrogate/creator cookie; invalid/revoked credentials; malformed binding; CSRF restore; unknown author; concurrent CAS; immutable metadata/receipt; audit rollback; stale session CAS; fresh process; DOCLOG/visual caller. Native PostgreSQL и реальные HTTP routers, не SQLite/mock durable. Неподдерживаемые Redis/Memory/advisory/разные DSN/schema не объявляются атомарной миграцией. Проверяется explicit postgres/required и одинаковые relation OID без прогрева lazy stores/DDL.

Граница: comprehensive entitlement/budget admission — AUTH-11/12, worker fencing — AUTH-13, self-service/invitations — AUTH-17. Основания: spec_auth_architecture.md §4/5/8/9; spec_auth.md AUTH-AC21; RP-06/12. Проверки и установка дополняются после исполнения.

## Установка и operator runbook

Восстановленная поставка проверяется заново, старые логи утраченного контейнера не используются. Обновляются API и web images. После применения ZIP, локального commit тимлида, зелёного CI и push, из корня checkout на VM:

```bash
git pull --ff-only
cd deployment/cisstat-stack
docker compose build api web
env -u CISSTAT_AUTH_MFA_KEYS -u CISSTAT_AUTH_MFA_ACTIVE_KEY docker compose up -d
docker compose ps
```

Новых env нет: VM stack уже содержит CISSTAT_SESSION_BACKEND=postgres и CISSTAT_STORAGE_MODE=required. 0023 применяется scientific store автоматически вместе с прежним каталогом. Auth migrations 0019–0021 не меняются. Старые данные не получают Account массово. Старый содержательный research pointer named пользователя после обновления даст 404: выход/вход очищает pointer для нового исследования; продолжение старого требует проверенного operator transfer.

Из deployment/cisstat-stack, подставить реальные run и UUID Account:

```bash
docker compose exec api python scripts/auth09/migrate_ownership.py inspect RUN-XXXXXXXX --account-id UUID
# Из inspect взять source owner_subject/tenant_id, ownership_version=0,
# и актуальный target_account.entitlement_version. Unknown = literal null.
docker compose exec api python scripts/auth09/migrate_ownership.py apply RUN-XXXXXXXX \
  --account-id UUID --expected-version 0 --expected-account-version VERSION \
  --expected-owner-subject SOURCE_OWNER --expected-tenant-id SOURCE_TENANT \
  --evidence TICKET-ID --reason 'Reviewed ownership evidence'
```

apply требует TTY и подтверждение run ID. Raw research cookie не нужен оператору и не хранится в receipt/audit. Основание владения проверяется вне HTTP; это не команда «присвоить найденное». Уже назначенный Account нельзя менять. Перед записью проверяются общий разобранный auth/scientific DSN и совпадение relation OID в auth/scientific schema. Неподдерживаемая топология отказывает до transfer; прогрев factories/DDL не запускается.

Mandatory intent публикуется существующим AUTH-04 consumer, отдельного security journal нет:

```bash
docker compose exec api python -c 'from apps.api.authentication.audit_outbox import publish_pending; print(publish_pending(limit=100))'
```

Нельзя откатывать production к старому runtime, пишущему в обход нового object gate. Миграционный rollout/consumer service — AUTH-20. Пользовательский экран истории не добавлен: общий restoreResearchRun helper подготовлен, сам transport/route/CSRF покрыт тестами.

## Проверки и маршруты

scripts/auth09/verify_postgres.py требует disposable CISSTAT_AUTH_TEST_DSN: отсутствие DSN возвращает 2, skips не PASS. CI auth09.yml: минимальный unit на Ubuntu/Windows, native с полными scientific API requirements на PostgreSQL16/18. Здесь выполняются Linux и native PostgreSQL16.2; Windows/PG18 — будущий CI пользователя.

AUTH-09 включает unit по умолчанию в local_gates.py и отдельный --with-auth09-postgres. Default не объявляет SQL долговечность проверенной без opt-in. Полные API-прогоны сравниваются с чистым c2217ec в том же окружении. Результаты — scripts/auth09/protocols/ и worklog/worklog11.md.

Ровно один новый HTTP method/path: POST /v1/progress/runs/{run_id}/restore. Discovery 540→541; full reviewed inventory 565→567 (+operator boundary); registry 238→239; API 234→235. Карту inventory, OpenAPI/TS и proxy allowlist генерировать явно; inventory --write последним после генерации производных источников. AUTH-09-HOTFIX01: до коммита после явного git add local_gates проверяет INDEX; после коммита перед push --auth00-target head. Проверяется полный reviewed report, ignored/untracked paths не пропускаются. Агент commit/push не делает; см. docs/auth09/hotfix01.md.


Свежие результаты восстановления: 12 unit в минимальном venv, 20 AUTH-09 native и 137 общей native регрессии; 175 targeted API после установки dev fakeredis; 2833 Jest tests; renderer/typecheck/Next embedded+standalone PASS. Полный API: 3340 PASS/52 skipped/12 FAIL против 3338 PASS/52 skipped/тех же 12 FAIL чистой базы, added failures=0. Полные логи приложены; это не утверждение, что весь API suite зелёный. Из 12 один одинаковый Redis CAS failure вызван отсутствовавшим dev fakeredis и проходит в targeted прогоне после установки.

При проектировании сверены [OWASP Authorization Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Authorization_Cheat_Sheet.html) и [PostgreSQL16 Explicit Locking](https://www.postgresql.org/docs/16/explicit-locking.html). Собственные правила доступа и доказательства — спецификации проекта и исполняемые отрицательные/конкурентные тесты этой поставки.
