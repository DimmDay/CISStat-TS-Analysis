# EMAIL-CONSUME-FIX — 17.11.2026, база 124a4ee

## Причина и исправление

На VM email/consume возвращал503; безопасный журнал показал operation=consume category=AttributeError. Доставка Gmail к этому моменту восстановлена настройкой SPF/DKIM.

В production router создаёт EmailChallengeService без явного store. SessionService._tx корректно получает PostgresAccessStore.from_env(), однако personal_demo.enroll получал всё ещё None из self.store. BudgetPolicy(None) сам разрешал хранилище, но следующий bind_connection(c, None) обращался к store._dsn/store.schema и падал. Прежние native-тесты всегда передавали store явно, поэтому пропустили этот путь.

Исправление: перед созданием BudgetPolicy и bind_connection разрешаем отсутствующий store через существующую factory. BudgetPolicy/WalletService используют текущую SQL connection через существующий bind_connection. Сессия, proof consume, identity и ресурсы по-прежнему атомарны, без обхода email proof или повторного бюджета.

TDD: два новых native-теста с EmailChallengeService(store=None) и реальным PostgreSQL воспроизвели тот же503/AttributeError до правки. Factory направлена в изолированную тестовую схему, никакого production DSN. После правки проходят ссылка и OTP, verify, защита повторного consume, повторный вход без изменения receipt/expiry/100CU. Отдельный HTTP-тест с FastAPI router без app.state.auth_access_store/auth_email_service подтверждает CSRF → consume200 → secure session cookie → me200/MONO. SMTP в native-тестах заменён fake, реальная доставка здесь не заявляется.

## Ввод кода

После «Отправить письмо для входа» появится поле «Код из письма» и кнопка «Подтвердить код». Восемь цифр, включая начальный ноль, передаются POST email/consume с тем email, на который пользователь запросил письмо. Неполный код не отправляется; после попытки поле очищается. Ошибочный/использованный/истёкший код имеет понятное сообщение, доступен новый ввод. «Другой email или новое письмо» возвращает к форме без автоматической отправки. Ссылка остаётся альтернативой с явной кнопкой подтверждения; код/ссылка живут15 минут и одноразовые. Оба пути используют прежнюю обработку account selection и safeReturnTo.

Код и email хранятся только в памяти компонента, не записываются в URL/localStorage/логи. Серверные ограничения попыток и одноразовость не меняются. Сам входящий GET ссылки по-прежнему не потребляет credential. Новых маршрутов, SQL-миграций или параметров .env нет. Копия письма администратору не добавляется: admin@datasetup.ru является отправителем, а получателем — введённый email.

## Применение

ZIP накладывается на checkout124a4ee; в нём только изменения этой задачи. Commit/push делает тимлид. Перед commit обновлённые reviewed sources нужно включить в INDEX вместе с inventory, например через scripts/email_consume_fix/files.txt. После локальных гейтов и зелёного CI на VM:

```bash
cd /opt/cisstat/CISStat-TS-Analysis
git pull --ff-only
cd deployment/cisstat-stack
docker compose build api web
docker compose up -d --no-deps --force-recreate api web
docker compose ps api web
```

Существующий .env и CISSTAT_AUTH_EMAIL_KEY сохранить. Если shell содержит экспортированные старые значения, использовать dc() из docs/personal_demo/deploy.md. Миграции не применять повторно ради этого фикса; не сбрасывать БД/кошельки/volumes. Нужны новые api и web образы, restart старых образов недостаточен.

Проверка получателем после deploy:

1. Запросить новое письмо, в ожидающей форме ввести8 цифр → /upload.
2. Для проверки ссылки запросить ещё одно письмо, открыть свежую ссылку и нажать «Подтвердить вход» → /upload. Использованная ссылка/код не должны повторно авторизовывать.
3. Повторный вход сохраняет ранее выданный trial, не выдаёт ещё100CU/14 дней.
4. Если возникнет новый503: docker compose logs --since=10m api | grep -F 'Auth operation failed'. Прислать только category/operation и HTTP status/detail.code, без cookies/токенов/кодa.

Доступ к VM в сессии отсутствует: обновление контейнеров и браузерная приёмка на реальном сайте выполняются оператором. Проверенные локальные результаты записаны ниже и в scripts/email_consume_fix/protocols.

Приёмка EMAIL-CONSUME-FIX: native PostgreSQL10/10 SQL +1/1 HTTP, zero skips; unit33/33; Jest32/32 (4 suites); AUTH00 unit38/38; strict temporary INDEX parity598 PASS; actual check_routes282 API/286 bindings/661 entries, added=[]/missing=[], все entries идентичны124a4ee. Обе Next production builds PASS, whitespace PASS. Full32-gate/native всей платформы/Docker image builds и реальная VM не заявляются. Реальный INDEX/HEAD/GitHub не менялись. ZIP содержит только файлы текущей задачи; CRC/manifest/each-byte сверяются при упаковке.
