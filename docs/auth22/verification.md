# AUTH-22 — матрица проверки

База `7d233ad`. Native-среда: disposable PostgreSQL 16.2 (pgserver, отдельная схема на тест). Норматив: `spec_billing_accounts.md` §13.3/§13.4/§13.8 (E3/E5/E6), `spec_auth_architecture.md` AUTH-22.

## TDD

- **RED**: `tests/unit/test_auth22_topups.py` — 12 контрактных тестов на отсутствующем модуле `apps/api/billing/topups.py` (suite-level ImportError; дополнительно каталог safe-кодов) — зафиксирован до реализации; попутно уточнён контракт D3 (`paid_review→credited` — единственный операторский переход).
- **GREEN unit**: 12/12 (`auth22` gate): валидация пакета (integer bounds, RUB-only v1, title/versions), state machine + терминальные состояния, снимок только из строки пакета (нет `enabled`, `amount_minor` вместо клиентского `price_minor`), канонический digest, DTO `extra="forbid"` (клиент не может ввести amount/units/currency), digest-паттерн, webhook-словарь = AUTH-18 inbox, safe-коды без секретов.
- **GREEN native** (`tests/integration/test_auth22_topups.py`, `scripts/auth22/verify_postgres.py`): **18/18 PASS, 0 skips**:

| Оракул | Пример/правило |
|---|---|
| Миграция: apply→repeat False→check_schema | цепочка 0019…0033 не тронута, checksum 0034 записан |
| SQL-гварды: quote DELETE / package price UPDATE / package re-enable / order reopen+DELETE | CheckViolation/RaiseException по 0034 (raw-connection) |
| Happy path: create → GET-confirmed → credited | ровно один purchased-лот `origin_order=order_id`, units=100 000 000, purchased бессрочен |
| E3: дубликаты событий и два event id одного платежа | ровно один кредит; повторный notify после credited — no-op |
| Callback spoof: notify(succeeded) без API-GET | ни лота, ни перехода состояния |
| Amount tamper (`bad`-mock 999.00) | `review_required`, лота нет |
| Out-of-order: reopen credited после подтверждения | CheckViolation (гвард) |
| Quote expiry 16 мин | confirm → 409 `topup_quote_expired`; созданный ранее order доводится до credited по снимку |
| Idempotency: повторный confirm того же quote | тот же order; другой payload с тем же key на новом quote → 409 `idempotency_conflict` |
| Допуск: чужой current-account 404, MEMBER-after-select 403 `owner_required` | §13.3 |
| Допуск: MONO без кошелька | каталог виден, checkout → 403 `wallet_required` |
| Wallet locked в момент кредита | `paid_review` (деньги видны), разблокировка → ручной лот → `credit-paid` CAS → credited; повторный issue на тот же origin_order отклонён (E6) |
| Provider outage → retry → credited | один payment (Idempotence-Key=order_id), один лот |
| 15 мин без candidate | `review_required`; reconcile чужого payment_id отклонён, своего — очередь → credited по proof |
| Rate limit 32 quote/24ч | 33-й → 429 `topup_quote_limit` |
| Fault аудита в finish | полный откат (лот+состояние), lease выдерживается, повтор — credited ровно один раз |
| Disable пакета посреди заказа | заказ кредитуется по снимку; новый quote → 404 `topup_package_not_found` |
| `auth_schema_versions` содержит 0034 | checksum зафиксирован |

## Регресс (тот же disposable PG 16.2)

- AUTH-18 `test_auth18_saga`: **16/16** (включая HTTP cookie/CSRF/webhook-границы — wake-up расширён, поведение прежнее).
- AUTH-21 `test_auth21_wallet`: **17/17**.
- AUTH-12 `test_auth12_ledger`: **35/35**.
- AUTH-20 `test_auth20_reconciliation`: **43/43** (цепочка миграций 0019…0034).

## AUTH-00/01 (check_routes)

Роуты **затронуты**: +3 OWNER-маршрута `GET /v1/billing/{account_id}/topups`, `POST /v1/billing/{account_id}/topup-quotes`, `POST /v1/billing/{account_id}/topups`. Гейт: actual 277 == inventory 277, registry bindings 281 (операция `billing.topup`), added/missing=[]; научные пути не переименованы. Производные перегенерированы в порядке «производные → inventory»: OpenAPI/TS (auth01), proxy allowlist (277), `docs/auth00/inventory.json|md` 651→654 (api 274→277). policy_review: политика `billing.topup` + 3 классификации + обновление `billing.wallet` target + webhook admission; reviewed_sources +6 (0034 SQL, design.md, CLI, тесты). Unit auth00 59/59, полный unit-регресс auth-контрактов 333/333; deployment-топология и doclog-пин 43 — 80/80 (compose не менялся).

## UI

`auth22-topup.test.tsx` 3/3 (снимок/подтверждение, серверный статус «Ожидает оплаты или сверки», allowlist `safeCheckout`, честные сообщения пустого каталога и `credited`); auth18-billing 2/2 регресс. `npm run typecheck:all` (embedded+standalone) PASS.

## Границы

Реальный IdP-магазин/сеть не вызывались (MockTransport); PG18/Windows — удалённая CI-матрица auth22.yml; полный `npm run build:all` и browser E2E не заявляются (typecheck+jest пройдены); Docker engine отсутствует — сборка образов и VM-деплой не выполнялись (команды в docs/auth22/deploy.md; пересборка api И web). Live-платежи кодом запрещены; каталог пуст до явных операторских команд.
