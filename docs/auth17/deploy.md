# AUTH-17 — установка поверх201a3b1

Task-only overlay к201a3b1f12eac55525fb07301b5e37f8e962d938. ZIP → локальная машина тимлида → его commit/push → pull VM. Сессия GitHub/VM не меняет. Нужны api+web rebuild и explicit0029; обязательных новых env/секретов/volumes нет. Прежние0019…0028 SQL/checksums не меняются. Научные kernels не менялись: дополнительная калибровка CU из-за AUTH-17 не нужна, существующие настройки profile сохраняются.

## Локальная приёмка

Распаковать в корень checkout на указанной базе, просмотреть manifest и подготовить INDEX:

```powershell
git status --short
git add --pathspec-from-file=scripts/auth17/files.txt
python scripts/local_gates.py --skip-install
# Только disposable PostgreSQL, не production DSN:
python scripts/local_gates.py --only auth17-postgres --skip-install
npm run build:all
# После своего commit, перед push:
python scripts/local_gates.py --auth00-target head --skip-install
```

Зависимости: npm ci; API requirements + scripts/auth17/requirements.txt при необходимости. AUTH-00 сохраняет strict INDEX/HEAD и Dockerfile CRLF portability предыдущего hotfix. При FAIL нужен полный UTF-8 logs/local_gates/auth00.log; не генерировать карту только ради PASS. Перечень файлов scripts/auth17/files.txt. Native runner без DSN/при skip не PASS. CI включает PG16/18 и Linux/Windows contracts.

## VM

Выбрать окно без новых admission, завершить текущие jobs. Сделать штатные backup PostgreSQL/.env/science_data/worker proof/CU profile/cache volumes. Не выполнять down -v, не менять MFA/worker keys. Ниже после собственного push и зелёного CI, из checkout VM:

```bash
set -euo pipefail
git pull --ff-only
cd deployment/cisstat-stack
docker compose build api web
docker compose run --rm --no-deps -T api python scripts/auth17/migrate.py --apply
docker compose run --rm --no-deps -T api python scripts/auth17/migrate.py --check
env -u CISSTAT_AUTH_MFA_KEYS -u CISSTAT_AUTH_MFA_ACTIVE_KEY \
    -u CISSTAT_WORKER_KEY -u CISSTAT_CU_PROFILE -u CISSTAT_CU_PROFILE_SHA256 \
    docker compose up -d --no-deps api web
docker compose exec -T api python scripts/auth17/migrate.py --check
docker compose exec -T api curl -fsS http://127.0.0.1:8000/health/ops
docker compose ps
```

Миграция additive и идемпотентна. Не импортирует identities/платежи и не меняет existing seats/балансы. Пока новый API/web не включены, новые browser routes недоступны. Старый код не должен обслуживать team mutations после их включения; при rollback закрыть team UI/API, сохранить0029/history/credits/volumes и остановить новые операции. Откат схемы/receipt deletion не поддерживается.

## Проверка UI и сценария

Обе оболочки: `/login` → после личного входа ссылка «Аккаунт и команда» → `/account`. Нужна существующая personal identity с активным Account и реальным credential; публичная регистрация/проверка email/рассылка — AUTH-19. UUID своей identity виден в /account. Новые identities при invite не создаются. Для forum credential team management запрещён. OWNER не становится ADMIN и ADMIN без OWNER не управляет командой.

1. У личного OWNER на starter/professional/enterprise/internal включить MULTI, явно подтвердив доступ участников к account-owned исследованиям. Account/tenant/run IDs прежние; legacy unresolved ownership не мигрирует. Сам переход не создаёт места/кредиты.
2. Создать приглашение по ID пользователя или подтверждённому email. Raw code показан один раз; передать получателю отдельным способом. Код не помещать в URL. Получатель входит личным способом и вставляет код в /account. Для email должен существовать единственный verified contact той же identity; иначе использовать ID. Pending invite не держит место. Первая успешная accept занимает имеющееся свободное подтверждённое место; при capacity exhausted409 старое приглашение остаётся pending до expiry/revoke. Replay не добавляет membership/seat/CU.
3. После accept выбрать новый Account явно. Смена создаёт новый SID, отзывает старый, сохраняет исходные auth_time/MFA/family/absolute deadline, очищает research pointer/CSRF и перезагружает UI. Данные остаются у своих Accounts. Другой Account нельзя выбрать только знанием ID без membership.
4. Передать OWNER активному personal участнику: reason + свежий вход≤5m; если MFA включён — требуется такое же свежее подтверждение. Кнопка повторного входа сначала завершает текущий SID. Перенос отзывает affected Account SIDs/challenges обоих участников и pending invites/seat requests; потребуется вход заново. Последнего OWNER удалить нельзя. Данные/исследования не переписываются.
5. Удаление участника сразу закрывает его Account access, отзывает SIDs/challenges; AUTH-10 SQL trigger терминально отзывает его Account API keys. Sibling Accounts не трогаются. Старый consumed invite не восстанавливает участие; нужен новый. Прежние SID/key не оживают после rejoin. История/расход/резервы не сбрасываются.
6. MULTI→MONO разрешён при capacity1, active members1 и отсутствии pending/running/uncertain obligations; неопределённые workers/holds не refund вручную. Для изменения capacity сначала выполнить подтверждённую заявку.

## Подтверждение мест до AUTH-18

`Account.seats` — подтверждённая capacity, включая OWNER. Browser «Подать заявку» создаёт pending durable intent максимум на7d. HTTP не принимает payment_confirmed/произвольный increment и не активирует покупку. В AUTH-17 provider quote/price/proration/paid CU credit не реализованы; это AUTH-18/21. До них допустима только защищённая операторская процедура после внешней проверки оплаченной entitlement либо явно разрешённого manual/internal allocation. Не подтверждать непроверенную заявку, не выдавать capacity за платёж и не вводить фиктивные financial credits.

OWNER передаёт оператору Account ID/request ID; текущая opaque entitlement_version читается штатным read-only операторским CLI:

```bash
# Подставить UUID Account:
docker compose exec -T api python scripts/auth08/manage_account.py show ACCOUNT_UUID
# После внешней проверки основания, в интерактивном терминале, без -T:
docker compose exec api python scripts/auth17/manage_seats.py ACCOUNT_UUID REQUEST_UUID \
  --expected-version CURRENT_VERSION \
  --confirmation-ref 'manual:APPROVED-UNIQUE-REFERENCE' \
  --reason 'Verified external entitlement or approved internal allocation'
```

CLI требует terminal и ввод точного Account UUID. Confirmation ref уникален и связывается с одним request; повтор того же результата не меняет capacity повторно. Reject stale version/expired request/сменившегося OWNER и capacity ниже active membership. Увеличение/уменьшение мест **не начисляет CU и не сбрасывает** existing limit/spent/reserved/postings. Provider/proration и положенный included credit подключаются отдельной AUTH-18/21 транзакционной политикой; браузер не является финансовым authority.

Штатный оператор AUTH-08 имеет полный серверный Account ID; пользовательское UI не делает его public admin API. Нового публичного bootstrap/поиска чужих identities/SMTP/provider credential нет. Public коммерческий запуск требует AUTH-18 и эксплуатационного AUTH-CERT.
