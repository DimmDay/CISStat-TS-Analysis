# AUTH-25 — Launch runbook: payment reconciliation/restore и pre-launch gate

Статус: runbook операционного контура биллинга (AUTH-25, база `main@f6dbec9`).
Норматив: `spec_auth_architecture.md` §9 (AUTH-25), §12.4/§12.5; `spec_billing_accounts.md` §13.9/§13.10 (E6).
Инструменты: `scripts/auth25/reconcile.py` (CLI, DSN — `CISSTAT_AUTH_DATABASE_URL`/`DATABASE_URL`), trusted-CLI AUTH-21/22/23 (`manage_wallet.py`, `manage_topups.py`, `manage_refunds.py`).

## 0. Что этот runbook НЕ делает

- **Не включает реальные платежи.** Провайдер конструирует только test-shop (`YooKassa(sandbox=True)`, `/me`-проверка `test=true`); терминальный переход к live-checkout — отдельная поставка с правкой провайдера (§13.9 «Необратимый запуск реальных платежей — отдельная поставка»). `launch_check` подтверждает готовность terms/catalog, но ничего не переключает.
- Не ремонтирует деньги автоматически. Все исправления — через существующие audited trusted-команды; AUTH-25 только детектирует и подсказывает.

## 1. Регламент reconciliation (плановый)

1. Ежедневно (или перед каждым рабочим днём): `--report`. Exit 0 = blocking-находок нет. Каждая blocking-находка разбирается в тот же день:
   - `credit_order_mismatch` — сверить заказ и лот: если провайдер подтвердил оплату, а credit потерян — `manage_topups reconcile` (повторная GET-подтверждённая сага) либо, при ручном заведении лота, `manage_wallet issue-purchased` + `manage_topups credit-paid`; если credit без заказа (orphan) — ручной разбор и `manage_wallet adjust` по решению владельца.
   - `refund_state_mismatch` / `dispute_state_mismatch` — сверить с AUTH-23 CLI (`refunds`/`disputes`), восстановить hold через `manage_wallet`/`manage_refunds` по фактическому исходу провайдера.
   - `lot_projection_drift` / `lot_balance_violation` / `payment_id_collision` — деградация схемы/артефакт: остановить записи в кошельки (`--lock-flagged`), разбор с DBA, восстановление через `adjust`-проводки.
   - info-находки (`paid_review_open`, `inbox_unowned_event`, `audit_outbox_pending`) — рабочий список: `manage_topups credit-paid`, очистка inbox спуфов, `scripts/auth20/reconcile.py --drain-audit`.
2. Каждое ручное исправление — с `--reason`; все мутации уже пишут обязательный audit-intent в той же транзакции.

## 2. Backup/restore (E6: рестарт/backup/reconcile не дублируют)

1. **Перед каждым backup**: `--export-watermark /var/lib/cisstat-ops/financial-watermark.json` (атомарная запись 0600; терминальные факты: credited-заказы, возвраты `refunded`, разрешённые споры). Файл хранится ВНЕ pgdata.
2. **После restore из backup**: `--reconcile-watermark --watermark ... --reason "restore-YYYY-MM-DD"`.
   - exit 0 — финансовых регрессий нет.
   - exit 1 — список `restore_regression` (kind/id/expected/actual/detail) и `suggestions` с конкретными trusted-командами. Деньги НЕ перенакладываются автоматически: оператор выполняет подсказки вручную, сверяясь с провайдером (выписка/merchant-portal), затем повторяет `--report` до чистого результата.
   - Идемпотентность: повторный прогон по тому же watermark даёт тот же отчёт; новых артефактов не создаёт.
3. Restore откатывает заказ и его credit одной транзакцией (одна и та же tx в AUTH-22) — внутренне консистентное состояние; регресс виден только против watermark вне pgdata. Отсутствие watermark — warning в runbook, сравнение невозможно: работать только по выписке провайдера.
4. При сомнении до reconciliation: `--lock-flagged --reason "restore in progress"` (finance hold всех flagged-кошельков; разблокировка — существующая audited `manage_wallet.py unlock` после разбора).

## 3. Crash/повтор саги (дубликаты исключены конструкцией)

- Credit заказа и переход состояния — одна PostgreSQL-транзакция; unique credit-per-order (`auth21_lot_order`), `payment_id UNIQUE` на заказах, `provider_refund_id UNIQUE`, inbox `(payment_id,event)` — provider replay/out-of-order/повторный браузерный return не создают второй credit (native-оракулы AUTH-25 доказывают: повтор `step()` после credited → без новых лотов; связать один payment_id с двумя заказами → unique_violation).
- Упадок провайдера между попытками — durable intent сохраняется, повторная попытка GET-подтверждает; неизвестный исход держит hold/paid_review, деньги ждут оператора (§13.7.3).

## 4. Pre-launch gate: terms/catalog подтверждены до real checkout

`--launch-check` собирает шесть фактов: `schema_ready` (0033/0034/0035), `catalog_valid` (каждый enabled-пакет проходит `validate_package`: integer money/units, RUB, versioned price/terms; пустой каталог = blocked с пометкой «checkout выключен» — штатное состояние до провижининга), `refund_window` (0…90, default 14), `provider_mode` (not_configured/sandbox — ok; любое live-значение — blocked), `reconciliation_clean` (нет blocking-находок), `audit_delivery` (warn при pending).

Запуск реального checkout допускается только когда: (а) `--launch-check` зелёный (пустой каталог допустим только с `--allow-empty-catalog` и означает осознанно выключенный checkout), (б) терминальная поставка провайдера выполнена и зафиксирована отдельной записью, (в) операционный регламент разделов 1–2 принят. До этого кнопка покупки остаётся выключенной (AUTH-21/22 каталог пуст по умолчанию).

## 5. Известные границы

- Отчёт bounded (≤500 находок, ≤100000 записей watermark); большие объёмы — сегментировать по периодам.
- Водяной знак не содержит amounts/секретов — только идентификаторы и состояния.
- `lot_balance_violation`/`payment_id_collision` — defense-in-depth: CHECK/UNIQUE обычно предотвращают; находка означает деградацию схемы, а не штатную работу.
- Реальные сети/магазин не вызывались; native-оракулы — disposable PG16/18; Docker-сборка — на VM тимлидом.
