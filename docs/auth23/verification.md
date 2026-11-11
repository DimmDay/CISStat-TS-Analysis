# AUTH-23 — верификация

## TDD

RED: 17 unit-контрактов на отсутствующих модулях (state-машины refund/dispute, окно, валидация provider-refund, DTO forbid, safe-коды, view-проекция, backoff). GREEN unit 17/17 после реализации; попутные уточнения контракта: same-state обновление легально (backoff саги), backoff — timedelta.

## Unit-регресс

auth23 17/17; регресс auth20–22 unit 64/64; полный auth-регресс — см. Гейты.

## Native PostgreSQL 16.2 (pgserver, disposable schema, 0 skips) — 12/12

- миграция 0035: apply/repeat(false)/check; SQL-гварды raw-connection: DELETE refund → 23514, immutable binding (units) → 23514, DELETE dispute → 23514.
- happy path: OWNER POST refunds → hold (available 0 / refund_pending = лот целиком), повторный POST → тот же refund (UNIQUE order_id), сага: POST refunds (Idempotence-Key = refund UUID — проверен) → GET-confirmed → refunded; лот refund_pending→refunded; повторный step не меняет.
- spoof: refund чужого payment → review_required, hold сохранён; reconcile (trusted) → pending → успешное завершение.
- unknown outcome (500): retry с backoff (next_attempt_at > now), hold сохранён; после восстановления — refunded.
- canceled: failed → available восстановлен ровно один раз; повторный step — no-op.
- spend после hold: coordinator reserve → 402 cu_insufficient (refund_pending исключён из FEFO).
- окно: CISSTAT_TOPUP_REFUND_DAYS=0 + 1 с → 403 refund_window; pending-заказ → 409 refund_not_eligible.
- MEMBER выбранного аккаунта → 403 owner_required; чужой/несуществующий refund → 404 refund_not_found.
- audit fault: RuntimeError внутри boundary → безопасный 503, полный откат (hold и refund-запись отсутствуют), повтор → успех.
- chargeback после расхода (через AUTH-12 coordinator: reserve→start→settle): wallet locked, остаток available в refund_pending, exposure spent_units=30M/disputed_units=70M; HTTP refund → 409; двойной спор → ValueError; dispute lost → CU погашены, кошелёк остаётся locked, resolve ровно один раз; dispute won → available восстановлен, кошелёк active, повторный resolve → ValueError.
- взаимная исключённость: pending/refunded refund закрывает спор; failed refund — спор открывается.

## Регресс соседних контуров (тот же disposable PG)

auth18-postgres 16/16, auth21-postgres, auth22-postgres 18/18 — PASS (рефактор wallet.refund_hold/_refund_finish на композабельные in-tx функции сохраняет поведение; provider.py — только аддитивные refund-методы).

## Роуты и производные

`check_routes`: actual 279 == inventory 279, bindings 283 (+2 `billing.refund`), added=[] missing=[]; OpenAPI/TS (auth01), proxy allowlist (279), inventory 654→656 (api 277→279), policy_review (политика billing.refund + 2 классификации + target billing.topup) — в порядке «производные → inventory».

## Границы честности

Реальная сеть/магазин не вызывались (MockTransport); PG18/Windows — remote CI; полный Jest/pytest/production builds в этой сессии не заявляются (UI-код не менялся); Docker-сборка выполняется на VM (deploy.md); AUTH-CERT/24/25 не объявляются.
