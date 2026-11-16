# PERSONAL-DEMO — поставка и VM

Overlay **da6cd8cd5a21e613acf4d84df377ab9977d2f7d9**. ZIP → распаковка в локальный checkout → собственный commit/push → зелёный CI → pull VM. В сессии нет commit/push или подключения к VM.
Список файлов: `scripts/personal_demo/files.txt`, проектирование: `docs/personal_demo/design.md`, проверки: `verification.md`.

## Профиль и границы

MONO starter: **14 дней, 10 исследований, 100 CU (100000000 micro-CU), 1 concurrent job, 50000 строк**, baseline без tuning/custom. Новая успешная загрузка датасета = новое исследование; неуспешная загрузка не расходует лимит. Повторная загрузка того же файла — новое исследование. Просмотры и продолжение этапов не создают новый trial. Письмо → подтверждение → `/upload`; ручного создания кошелька/бюджетов нет. Подтверждение кода также сохраняет return_to страницы логина. CU расходуются по существующим AUTH14 ценам/профилю, не каждая baseline-операция платная. Существующие тарифные ограничения/history/API permissions starter сохраняются.

Пилот: **100 однократных выдач**, окно регистрации **30 дней от применения0036**, общий sponsor10000 CU/1000 исследований/2 concurrent jobs. Действующие trial доживают свои14 дней. Pool pause закрывает только новые выдачи; существующие не продлеваются/не пополняются. Это ограниченная стартовая программа, не бессрочная неограниченная регистрация. После закрытия окна/исчерпания pool нужно новое операторское решение, не UPDATE/DELETE неизменяемых receipts и не reset spent/reserved. Несколько email одного человека не распознаются; действуют email/peer/global throttles и общий предел100 выдач.

Прежний более короткий срок аккаунта не продлевается: фактический expiry сохраняет меньшую дату.

Пустой прежний verified-email MONO starter единственного OWNER автоматически включается при следующем email-входе, если ещё нет wallet/scopes/reservations и срок не истёк. Ранее управляемые, пополненные, MULTI и иные аккаунты не меняются. Покупка CU сама по себе не продлевает срок trial или анализы; дальнейшие условия/продление — отдельное операторское решение. Персональные данные не получают campaign cleanup: история хранится по текущей политике MONO; по истечении14 дней доступ закрыт. Для кампаний прежние expiry/retention/cleanup без изменений.

## Локально

```powershell
python -m pip install -r scripts/personal_demo/requirements.txt
git add --pathspec-from-file=scripts/personal_demo/files.txt
python scripts/local_gates.py --skip-install --jest-workers 1
# После своего commit перед push:
python scripts/local_gates.py --only auth00 --auth00-target head --skip-install
```

Native на disposable PostgreSQL (не VM production): установить API requirements, задать CISSTAT_AUTH_TEST_DSN, выполнить `python scripts/personal_demo/verify_postgres.py`. Нужны права CREATE DATABASE. Не применять native-тесты к production БД.

## Настройки SMTP на VM

Реальные SMTP параметры и доступ к VM в сессии не предоставлены. Реальная отправка и пересоздание контейнеров — шаги оператора ниже; они не выполнены в сессии. В **существующем** `deployment/cisstat-stack/.env` добавить/заполнить реальные значения имеющегося SMTP (не заменять .env примером!):

```dotenv
CISSTAT_PERSONAL_DEMO_ENABLED=1
CISSTAT_AUTH_EMAIL_KEY=
CISSTAT_AUTH_SMTP_HOST=
CISSTAT_AUTH_SMTP_PORT=587
CISSTAT_AUTH_SMTP_USER=
CISSTAT_AUTH_SMTP_PASSWORD=
CISSTAT_AUTH_SMTP_FROM=
CISSTAT_AUTH_SMTP_TLS=starttls
```

EMAIL_KEY — стойкий секрет минимум32 байта; сохранить существующий, если настроен. Для нового можно сгенерировать `python3 -c 'import secrets; print(secrets.token_urlsafe(48))'` на VM и записать редактором. SMTP_FROM — реальный разрешённый отправитель/домен провайдера. Для порта465 обычно TLS=ssl; порт и TLS берутся из параметров своего SMTP. STARTTLS/SSL проверяют сертификат сервера и hostname. USER/PASSWORD могут быть пустыми только у реально настроенного relay. Пустой key/host/from, неверный port/TLS не рекламируют самостоятельную регистрацию. Наличие конфигурации ещё не доказывает доставку: выполнить smtp-test и проверить входящее письмо, SPF/DKIM/DMARC/политику отправителя своего сервиса. Секреты не коммитить, не публиковать `.env`/compose config с раскрытыми значениями. Если пароль содержит `$`, использовать literal single-quoted dotenv значение по синтаксису Compose.

## Команды VM

Из checkout репозитория, после своего push и зелёного CI. Сначала заполнить .env, затем:

```bash
set -euo pipefail
git pull --ff-only
cd deployment/cisstat-stack
chmod 600 .env
# Не позволить старому shell env перекрыть исправленные значения .env.
dc() {
  env -u CISSTAT_AUTH_MFA_KEYS -u CISSTAT_AUTH_MFA_ACTIVE_KEY \
    -u CISSTAT_AUTH_EMAIL_KEY -u CISSTAT_AUTH_SMTP_HOST \
    -u CISSTAT_AUTH_SMTP_PORT -u CISSTAT_AUTH_SMTP_USER \
    -u CISSTAT_AUTH_SMTP_PASSWORD -u CISSTAT_AUTH_SMTP_FROM \
    -u CISSTAT_AUTH_SMTP_TLS -u CISSTAT_PERSONAL_DEMO_ENABLED \
    -u NEXT_PUBLIC_DEMO_LOGIN -u NEXT_PUBLIC_DEMO_PASSWORD \
    docker compose "$@"
}
dc build api web
# Additive0036 (0019→0035 сохраняются), ДО запуска нового API:
dc run --rm --no-deps api python scripts/personal_demo/migrate.py --apply
dc run --rm --no-deps api python scripts/personal_demo/migrate.py --check
dc up -d --no-deps --force-recreate api web
dc ps api web
dc exec api python scripts/personal_demo/manage.py status
# Введите СОБСТВЕННЫЙ адрес для тестового письма, без логин-токена:
read -r -p 'Ваш email для проверки SMTP: ' smtp_test_to
dc exec api python scripts/personal_demo/manage.py smtp-test --to "$smtp_test_to"
unset smtp_test_to
curl -fsS -H 'Origin: https://datasetup.ru' https://datasetup.ru/api/v1/auth/personal-demo
curl -fsS https://datasetup.ru/demo >/dev/null
```

Ожидается email_configured:true и personal_demo.available:true (после apply в активном окне), limits14/100CU/10/1/50000; smtp-test ok/sent и письмо в ящике. `sent` означает принятие SMTP транспортом, не гарантию входящих; проверить ящик. Если SMTP не настроен/не работает — не считать запуск завершённым. Исправить реальные параметры и повторить `dc up -d --no-deps --force-recreate api`, status/smtp-test. Для smtp-test/pause/resume нужен интерактивный TTY (`exec` без -T), status/migrate не требуют TTY.

Браузерная приёмка: `/demo` на desktop — две колонки, mobile — одна; campaign entry/resume/leave прежние. Personal → email → письмо/код → `/upload` → загрузка → базовое исследование/прогноз; кошелёк100CU и конечный expiry. Повторный вход не выдаёт ещё100CU/14 дней. 11-я успешная загрузка отклоняется, failed upload лимит не расходует. Участники кампании имеют отдельные пространства, общей MULTI-учётной записи нет.

При необходимости остановить новые выдачи (без сброса старых):
`dc exec api python scripts/personal_demo/manage.py pause`, подтвердить `personal-demo`;
возобновить в пределах исходного окна/лимита — `resume` с тем же подтверждением. Продление окна или новая программа не делаются `resume`.
Не делать `down -v`, не откатывать0036 удалением receipts/wallets. Для оперативного выключения новых signup предпочтителен pause. Существующий AUTH14 профиль/worker secrets/тома сохранить: научные kernels и CU calibration digest этой поставкой не меняются. Нужна пересборка **api и web**, изменение API environment требует recreate, простой restart не подхватывает .env. Полную Docker image build в сессии не выполняли (Docker daemon отсутствует); npm production builds проверяются отдельно.
