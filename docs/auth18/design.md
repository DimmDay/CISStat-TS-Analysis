# AUTH-18 — ЮKassa, seat quotes и durable payment saga

База: 3ca5e4ed0742b5dce6c811f048ed3648817eafa6. AUTH-17 сохраняет membership/invitation authority. AUTH-18 добавляет отдельную provider authority, не выпускает User и не принимает actor/price от браузера.

## Процесс и границы

1. Оператор регистрирует уже оплаченный цикл MULTI и утверждённый прайс/terms; по умолчанию adapter выключен. Тестовый магазин работает только с явно sandbox-циклом. Перед payment POST authenticated /me должен подтвердить enabled test shop; ошибочный live key не создаёт checkout. Live checkout закрыт до отдельного запуска с фискальными условиями. Регистрация не увеличивает места или CU.
2. OWNER текущего Account создаёт immutable quote на pending seat request. Сервер фиксирует Account/CAS, requester, shop/test, cycle, цену в копейках, currency, terms/version, proration, TTL и digest. OWNER подтверждает quote: одна durable order/outbox, ещё без мест.
3. Worker с lease/fence делает POST вне SQL transaction, с постоянным Idempotence-Key. Потерянный ответ повторяется не дольше 23 часов с первого claim; затем review_required, без второго платежа. Возврат браузера ничего не активирует.
4. Уведомление — untrusted wake-up, а не доказательство оплаты. ЮKassa не предоставляет HMAC в описанном протоколе: worker получает актуальный объект фиксированным authenticated GET и проверяет merchant/test/id/metadata/amount/currency. Не доверяем forwarded IP, status или сумме callback. Inbox хранит только semantic payment/event, без платёжных реквизитов. Повторы bounded одной строкой на payment/event.
5. Подтверждённый succeeded/paid применяется одним SQL commit: order + receipt + AUTH-17 seats + audit + included allocation. Старое pending/canceled событие не откатывает applied. Оплата с устаревшим Account/request/cycle остаётся paid_review, не теряется и не активирует места; оператор решает refund/reconcile. Refund API и purchased CreditLot относятся к следующим задачам, автоматических возвратов нет.

## Proration

Время — integer microseconds; деньги — integer minor units, CU — integer micro-CU. Charge = ceil(max(0,deltaSeats)*price*remaining/duration). Included adjustment использует общий denominator цикла и signed cumulative numerator; floor применяется к cumulative total, а не к каждому изменению. Decrease не обнуляет spent/reserved. Источник included фиксируется в adjustment ledger; wallet/source-aware spend AUTH-21 использует эти записи. До AUTH-21 отдельно не увеличиваем общий lifetime CU budget: это смешало бы included с purchased/operator credit. Allocation доступен в subscription projection как entitlement intent, но не как spendable grant. Понижение разрешается только при явно утверждённом zero-refund reduction policy цикла; это нельзя включить из HTTP.

## Риски/проверки

TDD: integer rounding/churn, forged callback, schema migration/replay, duplicate/different notification, HTTP outage/response loss/24h, webhook before POST response, stale OWNER/CAS/TTL, lease fencing, audit rollback, concurrent claims, paid_review. Нет provider I/O под SQL lock; нет callback-triggered внешнего I/O (enqueue only). Все browse commands cookie+Origin+CSRF, personal current OWNER; API key/demo/member не authority. Новые HTTP surfaces подлежат AUTH-00 review. Реальная оплата и merchant secrets не входят в ZIP.

Официальные источники (проверено 2026-11-10):
- https://yookassa.ru/developers/using-api/webhooks (authenticity через current object API)
- https://yookassa.ru/developers/using-api/interaction-format (Basic Auth, Idempotence-Key 24h, unknown 500)
- https://yookassa.ru/developers/payment-acceptance/getting-started/payment-process

- https://yookassa.ru/developers/solutions-for-platforms/partners-api/quick-start (/me shop/test/status)
