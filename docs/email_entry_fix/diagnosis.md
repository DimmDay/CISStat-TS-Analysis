# EMAIL-ENTRY-FIX — 17.11.2026, база 345c9f8

## Что установлено

Исходное письмо содержит правильного получателя и first-party login URL. Возврат отправителю означает, что SMTP relay мог принять сообщение, но последующая доставка отказала. Строки исходного письма не содержат причину отказа. Нужна верхняя диагностическая часть bounce: `Remote-MTA`, `Status`, `Diagnostic-Code` или полный ответ `550 …`/`554 …`. Код подтверждения, URL с email_challenge, пароль и .env повторно присылать не нужно.

В SMTP adapter исходного коммита не формировались Date и Message-ID. Исправлено: текущая UTC-дата и отдельный случайный Message-ID для каждого письма, домен берётся из From, hostname контейнера не раскрывается. Покрыты STARTTLS и SSL. Это подтверждённый дефект формирования сообщения, но без Diagnostic-Code нельзя назвать его доказанной причиной конкретного bounce: relay мог добавить заголовки самостоятельно. Gmail требует RFC5322, SPF либо DKIM; даже правильное письмо не гарантирует доставку при неправильной DNS-аутентификации или политике провайдера.

Официальные требования: https://support.google.com/a/answer/81126?hl=ru

GET ссылки не вызывает consume и не создаёт сессию: нужен явный POST после кнопки «Подтвердить вход». Без HTTP status/detail.code неизвестно, был ли отказ на consume или на последующей проверке /me. Просроченная/использованная/неверная ссылка возвращает 401 invalid_credential; закрытый pilot pool — 403 personal_demo_unavailable; сбой authority — 503 auth_authority_unavailable. Последние два прежде попадали в одинаковую общую фразу интерфейса.

Изменения UI: отдельное объяснение 401 для ссылки, кнопка «Запросить новое письмо» (возвращает к форме, сама письмо не отправляет), понятное сообщение закрытого pilot pool. Настоящий 503 остаётся отказом без выдачи сессии. Новая безопасная запись журнала boundary содержит только имя операции и класс исключения, без repr/args/traceback, SQL, токенов, кодов, email и DSN. Ожидаемые 401/403 не превращаются в 503. Эти изменения не доказывают устранение исходного production-сбоя.

## Операторская проверка на существующей VM

До обновления можно проверить текущее состояние (из deployment/cisstat-stack):

```bash
docker compose exec api python scripts/personal_demo/manage.py status
```

```bash
docker compose exec api python scripts/personal_demo/migrate.py --check
```

`--check` проверяет существующую схему, не применяет миграцию. Не менять ключ email: замена сделает прежние challenge недействительными. Не пересоздавать/пополнять trial вручную и не обходить подтверждение почты.

После применения ZIP в локальном checkout, штатных локальных гейтов, commit/push тимлидом и зелёного CI на VM:

```bash
cd /opt/cisstat/CISStat-TS-Analysis
git pull --ff-only
cd deployment/cisstat-stack
docker compose build api web
docker compose up -d --no-deps --force-recreate api web
docker compose ps api web
```

Новых миграций и новых настроек .env нет. Если в текущем shell экспортированы старые CISSTAT_AUTH_* значения, убрать их переопределения перед recreate по существующему docs/personal_demo/deploy.md.

Получатель запрашивает новое письмо через форму. Успешный SMTP send/test означает принятие relay, а не доставку в Gmail. Если приходит bounce — нужен Diagnostic-Code из нового возврата, чтобы различить формат письма, SPF/DKIM/DMARC и ограничения провайдера. MX меняет входящую маршрутизацию, не устраняет сам по себе отказ исходящего Gmail.

Получатель открывает свежую ссылку в течение 15 минут и нажимает «Подтвердить вход». В DevTools → Network → Fetch/XHR посмотреть только HTTP status и JSON detail.code для email/consume и, если consume=200, последующего me. Не присылать request body, Cookie/Set-Cookie, CSRF, код/URL. Само открытие ссылки не должно отправлять email/consume.

Если после обновления возникает настоящий 503, сразу выполнить:

```bash
docker compose logs --since=10m api | grep -F 'Auth operation failed'
```

Эта новая запись содержит только operation/category. Если строки нет, отказ мог возникнуть до boundary (proxy/CSRF) или на /me — нужен status/code из браузера. Не включать SMTP debug и не пересылать полный журнал запросов с URL. Проверку считать завершённой только после фактического письма в Gmail, успешного consume/me, перехода /upload и отсутствия повторного начисления при повторном входе.

## Проверки поставки

Протоколы — scripts/email_entry_fix/protocols. RED подтверждает отсутствие заголовков/диагностики и одинаковую ошибку закрытого pilot. PASS-сводка дополняется перед упаковкой. Реальная Gmail-доставка и исходный отказ VM пока не воспроизведены: доступа к VM и Diagnostic-Code нет. GitHub/main не изменён, commit/push не выполнялись.

Проверено: Python25/25, AUTH04/AUTH19 regressions22/22, Jest30/30 (4 suites), обе Next production builds PASS, actual check_routes282 API/286 bindings/661 entries без added/missing. Список всех661 entries не изменён. Полный32-gate и native PostgreSQL в этой поставке не запускались.

Финальные AUTH00:38/38 tests PASS, strict temporary INDEX parity PASS (598 discovery surfaces), настоящий INDEX не изменён. Whitespace PASS.
