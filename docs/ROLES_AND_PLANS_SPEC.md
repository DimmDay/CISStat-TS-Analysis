# Контракт «Роль / План / Возможности»

**Редакция 3, 27 октября 2026 года.** Исходники проверены на `ad7dd4b3bcafcccb64d9f5b2f0a97afac7fc965f`. Статус: частичная реализация; решения раздела 7 — целевой контракт, не реализовано. Общий план: [spec_auth_architecture.md](../spec_auth_architecture.md).

## 1. Независимые оси

Identity — стабильный субъект; Role — платформенные полномочия; AccountMembership — членство и OWNER/MEMBER внутри аккаунта; Account.plan — тариф; Capabilities — аналитические возможности тарифа; scopes и grants — разрешённое действие и область ресурсов. Тип оболочки не назначает права. Аналитический код проверяет capability, административный — административное permission; оба проверяют доступ к объекту.

## 2. Роли

| Role | Целевой смысл | Оболочка | Источник аналитических возможностей |
|---|---|---|---|
| admin | Именованный администратор с MFA | embedded и standalone | Выбранный служебный Account, отдельно от admin permissions |
| internal_analyst | Сотрудник, без административных прав | Обычно embedded; права не выводятся из URL | Служебный Account с internal entitlement |
| external_user | Внешний пользователь, включая участника demo | Обычно standalone | Активный Account и его план |

OWNER не становится ADMIN. Support/reviewer — наборы scopes и ограниченных grants, не новые коммерческие роли.

## 3. Фактически существующие возможности

Источник текущих значений — `apps/api/plans.py::PLAN_DEFINITIONS`. Таблица описывает код базы, а не полноту применения guards.

| Поле | demo | starter | professional | enterprise |
|---|---|---|---|---|
| can_train_models | false | false | true | true |
| can_use_api | false | true | true | true |
| can_save_history | false | true | true | true |
| can_upload_own_data | true | true | true | true |
| max_dataset_rows | 5000 | 50000 | null | null |
| max_api_calls_per_month | 0 | 1000 | 50000 | null |
| max_analyses_total | 10 | null | null | null |
| trial_days | 14 | null | null | null |
| watermark_exports | true | false | false | false |

`null` означает отсутствие тарифного ограничения, но не отсутствие технического потолка. Срок trial требует persisted issued_at/expires_at; само число 14 ничего не отсчитывает. Enterprise custom/SLA пока не представлены отдельными account overrides.

## 4. Демо

Общая пара с флаера — credential кампании. Каждый посетитель получает отдельные subject, DemoGrant и временный MONO Account. Бюджет кампании общий, исследования частные. Личный trial — отдельный сценарий.

`can_use_api=False` запрещает программный продуктовый API и выпуск ключей; браузер продолжает обращаться к backend. Запрет автоматизации нельзя обеспечить названием маршрута или CORS: нужны серверные квоты и контроль вычислений на всех входах.

`can_save_history=False` означает отсутствие постоянной пользовательской истории после временного доступа. Это не запрет необходимых временных артефактов, provenance и обязательного аудита. Campaign/grant могут только сужать entitlement плана; изменение состава demo-функций вводится отдельной версией контракта по §7.8.

## 5. Проверки

Единый контекст запроса → действующие role/scopes/membership → объект и tenant → stage/capability → grant → атомарная квота. Backend является границей доверия. UI показывает эффективные права из `/v1/auth/me`; скрытая кнопка не защищает операцию.

401 — нет действующей аутентификации; 403 — недостаточно функциональных прав; uniform 404 — чужой/несуществующий объект; 402 — тарифный барьер/CU; 429 — частота/конкурентность; 503 — authoritative backend недоступен. Коды причин стабильны и не содержат секретов.

## 6. Что реализовано на базе

| Файл | Факт |
|---|---|
| apps/api/plans.py | Role/PlanName/Capabilities; у ADMIN и INTERNAL_ANALYST аналитические caps полные через условие роли |
| apps/api/auth.py | ENV-реестр ключей; subject_id/tenant/scopes; capability и ADMIN dependencies |
| apps/api/identity.py | SubjectRef, суррогаты cookie, authorize_run_access, legacy continuity и uniform 404 |
| apps/api/routers/models.py | Capability guards на части model API |
| apps/api/routers/internal.py | Нет общей AuthN dependency; используется и standalone |
| apps/api/admin_logs.py | Support grants и log scopes; ADMIN имеет полный доступ |
| packages/ui/lib/plans.ts | Ручное зеркало, camelCase; не серверная защита |
| apps/embedded/app/admin/progress/page.tsx | Существующая admin-страница; standalone аналога нет |

Account/Membership, persisted AuthSession, личный MFA-вход, seats, CU и stage gating ещё не реализованы. DOCLOG object guards уже существуют: их нельзя заменить проверкой одного тарифа.

## 7. Что осталось сделать (не реализовано, требует решения)

Решения ниже выбраны для общей архитектуры; зависимости и приёмка приведены в связанном плане. Они заменяют прежние пять открытых предложений.

| Решение | Оптимальный целевой контракт | Проверка реализации |
|---|---|---|
| RP-01: хранилище | PostgreSQL: Identity/Credential/AuthSession/APIKey, Account/Membership; ключи хешированы, principal_id перестаёт содержать секрет. ENV только управляемая миграция | Ротация ключа сохраняет subject и владение; рестарт не сбрасывает отзыв |
| RP-02: лимиты | Атомарные account/grant/campaign ledger и reservations; счётчики не на ключ или cookie; rate limiter отдельно | Два запроса на последний CU/анализ допускают ровно один |
| RP-03: изменение плана | План Account, versioned entitlements; актуальная проверка на запросе и перед стартом worker | Downgrade/revoke закрывает следующий запуск без перелогина |
| RP-04: Python/TS | Версионированная Pydantic/OpenAPI схема → generated TS; effective caps с сервера; CI drift check | Изменение поля ломает CI при устаревшем generated файле |
| RP-05: admin/staff | Административные permissions отдельно от аналитических caps; ADMIN обеих оболочек с MFA, staff internal entitlement явно | INTERNAL_ANALYST и OWNER не управляют платформой |
| RP-06: Account/tenant | MONO/MULTI, OWNER/MEMBER; явный owner_account_id и серверная привязка tenant; membership не заменяет object grants | Чужой Account не читает объект; переход MONO→MULTI сохраняет IDs |
| RP-07: места | Seats — активные billable memberships; приглашение с atomic consume; последнего OWNER нельзя удалить без передачи | Гонки приглашений и seat update не дают лишний доступ/бесплатную квоту |
| RP-08: demo-моделирование | Новая версия: can_run_baseline_models=true для demo/starter; can_tune_models и can_train_custom_models=false; bounded baseline/backtest/forecast | Demo проходит шесть этапов, прямой tuning/custom-fit запрещён |
| RP-09: этапы | restricted_stage_ids для scenario/causal/decision/monitoring у demo; отдельный registry известных operation/stage; неизвестная операция deny | UI soon не открывает доступ к API; aliases ведут к одной policy |
| RP-10: форум | Общий entry credential → private participant/grant/MONO; fixed campaign end и budget, grant TTL не продлевается входом | Новый браузер не обходит общий бюджет/окончание; уникальность человека не обещается |
| RP-11: cookies | Opaque AuthSession отдельно от cisstat_session_id; first-party proxy, CSRF, logout/revoke; инвалидный credential не ведёт в анонимный fallback | Cookie/key conflict, CSRF и session fixation отклоняются |
| RP-12: объекты/legacy | Расширить существующий SubjectRef/authorize_run_access; перенос только доказанного владения, unresolved не присваивать по run_id | Старые чужие run/document/job остаются закрыты |
| RP-13: CU/цена | Seat pricing линейный; CU pooled на Account; calibrated coefficients и fixed-point ledger; provider adapter/outbox | Retry/webhook/seat churn не создают повторный charge или reset пула |
| RP-14: эксплуатация | Security audit/outbox, fail-closed auth stores, rollout с rollback без возврата к anonymous production | Отказ БД/аудита и восстановление backup не воскрешают доступ |
| RP-15: покупаемые CU | Account wallet с included/purchased/promotional lots, OWNER checkout, integer ledger и атомарные refund holds по CU-WALLET-1 | Webhook/retry не удваивает credit; период не сжигает purchased; купленный CU не повышает тариф |

Для RP-08 старое `can_train_models` не переименовывается механически: оно сейчас закрывает также backtest/candidates/diagnostics. Каждый endpoint классифицируется по операции. Legacy-флаг временно сохраняется для совместимости advanced API; конкретные baseline endpoints переводятся на новый permission с лимитами. В `spec_auth.md` запрет тяжёлого fit сохраняется. Противоречие `spec_billing_accounts.md §5.7/§10.6` разрешается этим разделением, а не трактовкой «False на самом деле True».

Для RP-09 запрет относится к прикладным операциям: включая уже существующий XAI-срез `tasks_session.py`. Он не запрещает научные диагностические вычисления EDA автоматически по совпадению слов. `monitoring` исследования и служебный DOCLOG monitoring — разные пространства операций. Для starter дополнительных stage-ограничений в v1 не вводится.

## 8. Валюта CU и право на самостоятельно покупаемый баланс

**CU-WALLET-1, проект от 27 октября 2026 года.** Полный контракт — [spec_billing_accounts.md §13](../spec_billing_accounts.md#13-валюта-платформы-и-самостоятельно-покупаемый-баланс--cu-wallet-1); интеграция — [spec_auth_architecture.md §12](../spec_auth_architecture.md#12-покупаемый-баланс-cu--cu-wallet-1).

CU — внутренняя неденежная единица потребления услуг. Подписка оплачивает seats/entitlements и начисляет included CU на период. Отдельная покупка начисляет purchased CU в кошелёк того же Account. Included сгорает на границе периода; purchased в v1 бессрочен, не обнуляется и не умножается при смене периода/seats. Promotional имеет собственные условия. Источники раздельны в integer micro-CU ledger.

| Право | Кому и при каких условиях | Чего не даёт |
|---|---|---|
| can_purchase_cu | OWNER активного платного Account, top-ups включены сервером | Права ADMIN, доступ к чужому Account и функции вне тарифа |
| can_spend_cu | Уполномоченный MEMBER/OWNER с действующим entitlement, object access и успешным reservation | Неограниченные вычисления, обход CU/concurrency/grant ceilings |
| refund/manage payments | OWNER в рамках условий исходного заказа; исключения — отдельное support permission | Конвертацию любых CU в деньги или возврат потраченного lot одной кнопкой |

Эти permissions — effective server policy, не новые Role и не баланс внутри API key. У demo и INTERNAL top-up flow в v1 отсутствует. Пополнение не открывает tuning на starter и не возобновляет истёкшую подписку. Заблокированный wallet (`wallet_locked`) запрещает новые CU admissions, но не уничтожает оставшийся баланс. OWNER получает финансовые детали, MEMBER — только разрешённые usage/aggregate данные.

Возврат — whole unused purchased lot по исходному заказу, с атомарным hold до результата provider. CU нельзя передавать между Account, использовать для оплаты seats, выводить по курсу или начислять с browser success redirect. Ротация ключа, повторный вход, смена OWNER/оболочки и MONO→MULTI сохраняют Account wallet. Финансовая история не стирается с membership.
