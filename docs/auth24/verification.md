# AUTH-24 — верификация

## TDD

RED: unit 15 контрактов на отсутствующем модуле `apps/api/billing/wallet_views.py` (12 ImportError suite-level + 1 failure «маршруты не зарегистрированы»); UI RED — suite-level «Cannot find module './WalletPanel'». GREEN после реализации.

## Unit-регресс

auth24 15/15; полный auth-регресс auth00…auth24 — **365/365 OK** (было 350 + 15 новых). Включая auth00 inventory/precommit/local_output 59/59 после финальной перегенерации inventory ПОСЛЕ всех правок исходников (порядок «производные → inventory» соблюдён; первый прогон поймал дрейф отпечатков AccountScreen.tsx/billing.ts — правомерно, --write перезапущен).

## Native PostgreSQL 16.2 (pgserver, disposable DB, 0 skips) — 48/48

11 новых AUTH-24 оракулов + 37 унаследованных регрессий AUTH-21/22 (WalletFixture→TopupSQLTests) в том же прогоне:

- admission: OWNER-чтение полное; MEMBER — usage-проекция без источников/истории/денег; чужая identity → 404 `account_not_found`; аккаунт без кошелька → 403 `wallet_required`; ledger MEMBER → 403 `owner_required`.
- privacy: у MEMBER-проекции нет ключей sources/locked_reason/issued/spent/expired/refund_*/amount/currency/price/terms/origin_order; totals (available/reserved/next_expiry) совпадают с OWNER.
- parity: sources/reserved/next_expiry/status OWNER-чтения == `WalletService.summary()` того же аккаунта (после refund_hold).
- lifecycle (критерий приёмки AUTH-24): seat churn (invite→accept→remove) — READ и лоты байт-в-байт неизменны, удалённый MEMBER теряет доступ (401); OWNER transfer — wallet_id/лоты сохранены, прежний OWNER повторным входом получает usage-проекцию (`can_purchase_cu=false`), новый OWNER (свежий select) — полную проекцию, `can_purchase_cu=true`; MONO↔MULTI — кошелёк/лоты неизменны (`can_purchase_cu` false на mono, true на multi); cycle rollover (второй issuance basis) — новый included-лот, purchased available/spent не тронуты (E1); expiry sweep — included→expired, purchased 700k доступен, next_expiry=null; expired plan — сессия 403 `account_expired` (AUTH-08 слоем сессий), под ней лоты сохранены (ledger-вид), восстановление entitlement возвращает прежнее чтение; повторный вход — тот же wallet_id, `auth_wallets` == 1 строка.
- refund-видимость: refund_hold AUTH-21 виден в OWNER-проекции (`refund_pending`=200k, available=0) и в MEMBER-агрегате (available=0, без ключа refund_pending).
- ledger: bounded-проекции; refund/dispute строки засеяны на реальном credited-заказе саги AUTH-22 (honest path); в проекциях нет lease_until/fence/owner_id; postings — целочисленные дельты.

## Роуты и производные

`check_routes`: actual 281 == inventory 281, bindings 285 (+2 `billing.wallet`), added=[] missing=[]; OpenAPI/TS (auth01 generate --check), proxy allowlist (281), inventory 656→658 (api 279→281), policy_review (+политика `billing.wallet`, threats T02/T09/T13/T15/T20, +2 классификации) — порядок «производные → inventory».

## Jest/сборки

Полный Jest: **2882 passed / 2 штатных skipped / 0 failed assertions** (262 сюиты passed; 2 сюиты получили SIGKILL воркера песочницы — OOM-класс, зафиксированный ещё в UI-DEVNOTICE-1; изолированный --runInBand прогон обеих — PASS; паритет с историей флейков). Целевые UI-оракулы auth24 7/7 + регресс auth22-topup 3/3. Renderer build PASS; typecheck:all обеих оболочек PASS; production builds embedded+standalone PASS. Deployment-пины: `test_cisstat_stack_deployment` + `test_run_report` PASS; единственное падение `test_doclog8_monitoring::test_routes_registered` воспроизводится на чистом 32e0f50 (git stash-проверка) — предсуществующий средовой класс, к AUTH-24 не относится.

## Границы честности

Реальная сеть/магазин/IdP не вызывались; native — disposable PG16.2 локально (PG18/Windows — remote CI auth24.yml); Docker engine в сессии отсутствует — образы собираются на VM (deploy.md); полный scientific pytest и browser E2E не заявляются; `can_purchase_cu`/`can_spend_cu` — справочные READ-флаги, admission к расходу остаётся у координатора AUTH-12; READ поверх expired-плана через живую сессию недостижим (AUTH-08 отказывает сессию раньше) — инвариант сохранения purchased зафиксирован на ledger-уровне и при восстановлении entitlement; AUTH-25/AUTH-CERT не объявляются.
