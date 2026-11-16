# PERSONAL-DEMO — два сценария /demo и автоматический старт MONO

База da6cd8cd5a21e613acf4d84df377ab9977d2f7d9. AGENTS: TDD, gates/map/build, task-only ZIP; без commit/push/VM.

Решение: колонка кампании организатора (общая пара/код, частные существующие AUTH15/16 grants) и колонка личного MONO через подтверждённый email. Общая кампания не становится shared MULTI tenant. Старый public-entry остаётся совместимым, но в campaign-only виджете не показывается disabled кнопка при отсутствующей публичной паре.

Личный trial — существующий starter:14 дней,100 CU (100000000 integer micro-CU),10 исследований,1 concurrent job,50k rows по текущему starter caps. API/history — штатные starter permissions;1000 API/month сохраняются. Дополнительный grant budget ограничивает10 lifetime analyses независимо от caps.max_analyses_total=None. Код/caps не ослабляются.

Atomic verified-email consume → identity+MONO+scope hierarchy+wallet promotional lot+immutable issuance receipt+audit+session. Перепользуется bind_connection и AUTH12/21, никакого второго CU счётчика. Pool sponsor→account→grant, всегда конечные сроки. Рекомендуемый пилот:100 issued personal trials/30d signup window, общий10000CU/1000 analyses,2 concurrent jobs. Monthly API budgets заранее покрывают окно всех выданных trial. Отзыв/expiry/нет ресурсов закрывают запрос штатным coordinator; worker profile/stop/fencing не меняем.

Повторный вход не пополняет бюджет, не продлевает expiry. Receipt UNIQUE subject/account/email hash; spend/hold/history остаются. Старые пустые MONO starter verified-email accounts можно включить при первом входе только если у субъекта ровно один свой Account и НЕТ wallet/budget scope/reservations; funded/paid/multi/operator accounts не меняем. Несколько email одного человека не распознаём; верхняя граница — finite pool и существующий email/peer/global throttle. Окончание окна/исчерпание pool требует явного операторского нового решения, не silent reset.

Миграция0036 additive после0035, старые SQL/checksums immutable; provision pilot pool однократно migration transaction с mandatory audit. Включение автоматического trial явным CISSTAT_PERSONAL_DEMO_ENABLED=1 в Compose; без него AUTH19 legacy поведение сохраняется. Новый public metadata GET /v1/auth/personal-demo сообщает реальную availability и лимиты без адресов/секретов. SMTP mode/host/from/key проверяются до рекламы email. Письмо trial в новом режиме возвращает на /login?email_challenge=...&return_to=/upload; target fixed/server-side.

SMTP только операторские secrets в api env; никаких реальных credentials в ZIP. CLI check/send-test использует штатный SMTP adapter, не пишет secret/token в лог. Реальная отправка/пересоздание VM возможны только после заполнения SMTP оператором. Тестируем controlled SMTP и SQL; конфигурация отсутствующего провайдера не выдумывается.
