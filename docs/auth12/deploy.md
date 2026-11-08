# AUTH-12 — поставка и VM

База ad4fd342eeba39161e69cce736d9d5d25f1cea2f. Распаковать полный ZIP в корень checkout. Единственный manifest текущей задачи scripts/auth12/files.txt; прежние manifests AUTH-09…11 уже в базе.

```powershell
git status --short
git add --pathspec-from-file=scripts/auth12/files.txt
git diff --cached --stat
python scripts/local_gates.py
```

После commit перед push: `python scripts/local_gates.py --auth00-target head --skip-install`. До git add строгий INDEX gate намеренно FAIL; смотреть UTF-8 logs/local_gates/auth00.log. Скрипты сами не stage/commit/push. Native gate отдельно `--with-auth12-postgres`, disposable CISSTAT_AUTH_TEST_DSN, без DSN/skips не PASS.

## VM после собственного push

Нужен только новый api image. API/UI routes, web код и DTO не менялись. Из корня клона:

```bash
set -e
git pull --ff-only
cd deployment/cisstat-stack
unset CISSTAT_AUTH_MFA_KEYS CISSTAT_AUTH_MFA_ACTIVE_KEY
docker compose build api
docker compose run --rm --no-deps -T api python scripts/auth12/migrate.py --apply
docker compose up -d --no-deps api
docker compose exec -T api python scripts/auth12/migrate.py --check
```

0025 additive, идемпотентная explicit authority migration, без request-time DDL. Она создаёт scopes/budgets/reservations/allocations/postings/claims/job outbox и SQL guards. 0019–0024/checksums/scientific migration catalogue неизменны. Новых обязательных env нет, DSN берётся из действующего auth DATABASE_URL. Unset удаляет только shell overrides; Compose использует действующий .env. До migration --check должен отказать, после неё ok=true/schema_version0025. Отказ schema/audit/outbox — safe503, без fallback в memory.

AUTH-12 предоставляет trusted in-process ReservationCoordinator/BudgetPolicy, а не новый публичный billing endpoint. Job intent с reference/digest сохраняется атомарно, но настоящий broker consumer, worker start/settle/fencing/reconciliation ещё AUTH-13. Нельзя объявлять текущие scientific handlers финансово metered. Commercial CU pricing/коэффициенты ещё AUTH-14, paid source-aware wallet/lots ещё AUTH-21. Включение реального CU тарифа не является частью этой migration. Начальные балансы из ENV и выдуманный исторический usage не создаются.

## Trusted API и policy operator

До reserve вызывающий scientific coordinator обязан доказать object access и нормализовать реальные входы AUTH-11. Передаёт current RequestContext и Admission(entry_id,resource kind/id,idempotency_key,payload,cost=Cost(integer micro_cu,version),absolute deadline,workload,stage,analysis_run_id,slots). Deadline сохраняется при первом admission; для retry использовать тот же snapshot запроса/quote. Positive CU требует slot1. Metadata-only counters могут slots0/cost0. Ни budget chain, ни plan/limits не берутся из browser payload.

Reserve возвращает immutable Receipt: server reservation UUID, state/version, held/actual, quote version/deadline/lease, безопасный result_ref. Повтор того же Account/actor/canonical operation/key+input возвращает тот же receipt, другой input409. Credential ID не часть usage identity. Start(ctx,id,expected_version) повторно проверяет credentials/Account/caps/chain и CAS. Extend(ctx,id,expected_version,additional_cu) требует fresh authority и дополнительный reserve ДО лишней работы. Settle(id,expected_version,actual_cu,result_ref) и release(id,expected_version) — trusted execution/операторские методы, не HTTP handlers; результат должен отдельно пройти object/access/publication gate AUTH-13. Settle после lease/deadline и running release закрыты до reconciler; timeout не refund. API/analysis после admission не возвращаются.

Обычный Account root и API/month + analysis/lifetime counters создаются только при первом успешном coordinator admission, лимиты берутся из текущих Account caps. Для CU/concurrency нужны явные finite server budgets; NULL не денежная бесконечность. Sponsor/campaign/grant chain назначается trusted provisioning, parent/owner неизменны. Account counters нельзя «выдать заново» operator limit reset: они вычисляются по caps, spent/claims сохраняются. Ротация ключей, logout, upgrade/downgrade не обнуляют ledger.

В интерактивном trusted терминале оператора есть scripts/auth12/manage_budget.py: `scope-create`, `budget-set`, `scope-status`; обязательные reason/expected-version, JSON безопасного результата и mandatory audit. Не публиковать этот CLI как browser/admin endpoint. Он задаёт resource ceilings, не начисляет оплаченные CU, не меняет планы/seats/membership. Конкретные суммы не подставляются из примеров: commercial policy требует AUTH-14/18/21.

Smoke: migration --check; прежний named login/upload/baseline; invalid/foreign scientific запросы по-прежнему отказ. Readiness не означает интегрированный worker billing. Native tests только в отдельной disposable БД, никогда production. Откат — согласованный прежний api image без удаления 0025/ledger или выключения AUTH-11 guard. Любая будущая reconciliation неизвестного running outcome отдельно AUTH-13/20; зарезервированные ресурсы не освобождать по одному TTL.
