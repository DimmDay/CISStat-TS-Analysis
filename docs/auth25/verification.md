# AUTH-25 — Верификация

Дата: 12.11.2026. База: `main@f6dbec9`. Всё выполнено в сессии на disposable-инфраструктуре; commit/push из сессии не выполняются (AGENTS.md).

## Гейты

| Проверка | Результат |
|---|---|
| Юнит auth25 (`tests/unit/test_auth25_reconciliation.py`) | 32/32 OK: словарь находок/severity/bounding, watermark-конверт (формат/лимит/типы/поля), режимы провайдера (not_configured/sandbox/blocked), окно возврата (паритет с AUTH-23 `window_days`), restore-подсказки trusted-команд, сборка вердикта launch-check (в т.ч. `--allow-empty-catalog` → warn), prefix карантина |
| Native PG16.2 (`pgserver`, 0 skips) | **105/105 OK**: 16 новых AUTH-25 оракулов + 89 регрессий унаследованной цепочки AUTH-21/22/23 (кошельки/сага/возвраты/споры). Новые: честная сага → чистый отчёт; hold возврата и lock спора — легитимны; paid_review — info; provider replay: повтор step() не дублирует lot, payment_id второго заказа → unique violation; orphan credit и credited-без-лота ловятся; refund-регресс buckets ловится; спор при разлоченном кошельке ловится; фантомный expiry (артефакт с отключённым guard-триггером) → lot_projection_drift; watermark: атомарная запись 0600/формат, reconcile находит регрессию refund и НЕ чинит деньги, идемпотентен, аудируется; lock_flagged бьёт только виновных; launch_check ok/blocked по каталогу/environ/находкам |
| check_routes / inventory | `python scripts/auth00/inventory.py --check` → `{"status":"ok","counts":{"api":281,...},"entries":658}` — Роуты НЕ затронуты (ops-CLI без HTTP), access_registry/OpenAPI/TS/proxy не менялись |
| Гейт-фреймворк | `local_gates.py --list` — auth25 первым в default; `--only auth25` PASS; `auth25-postgres` добавлен в одном изменении с `--with-auth25-postgres`/`excluded.add` (урок AUTH-22-HOTFIX-01) |

## Приёмка критерия AUTH-25

- **«Crash/backup/provider replay не создают дубликаты»** — уникальные основания схемы (credit-per-order, payment_id UNIQUE, provider_refund_id UNIQUE, inbox PK) доказаны native-оракулами; одна транзакция credit+state сохраняется (регресс AUTH-22 audit-fault/rollback); restore-регрессия против watermark вне pgdata детектируется и не переносится автоматически (E6).
- **«Terms/catalog подтверждены до real checkout»** — `launch_check` требует versioned price/terms на каждом enabled-пакете, явного режима провайдера и чистого reconciliation; пустой каталог = blocked (осознанно выключенный checkout), live-env = blocked. Терминальное включение live-платежей остаётся отдельной поставкой (§13.9); провайдер по-прежнему конструирует только test-shop.

## Границы (честные)

Реальная сеть/магазин/IdP не вызывались (MockTransport; PG16.2 локально, PG18/Windows — remote CI auth25.yml); Docker-сборка — на VM тимлидом по `docs/auth25/deploy.md`; полный scientific pytest и browser E2E не заявляются; watermark-сравнение возможно только при наличии экспорта, сделанного ДО backup; блокировка только flagged-кошельков не заменяет FULL quarantine AUTH-20 (при сомнении в не-финансовых данных использовать `scripts/auth20/reconcile.py --quarantine`). AUTH-CERT не объявляется.
