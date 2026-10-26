# Спецификация аутентификации, авторизации администратора и форумного демо CISStat TS Analysis

**Редакция:** 2.0-proposed, 26 октября 2026 года (Москва). **Статус:** проект требований; сверка целевого коммита не подтверждена.

**Запрошенная база:** `21946a7a80878b7dcbe5a9e57f2fa132208914a6`.
**Доступная проверенная база:** `bee3f8e300e6d2f5de6f8c9d9e4d6bc6e4091065`. Прямой fetch требует аутентификации; целевой объект локально отсутствует. Поэтому описание кода ниже относится только к доступной базе. Перед принятием этой редакции требуется сравнить исходный `spec_auth.md`, роли, identity, admin routes и смежные контракты с `21946a7`. Эта работа не называется синхронизацией или аудитом реализации на `21946a7`.

**Постановка:** администратор входит через embedded и standalone; панель администратора доступна в standalone. Одна универсальная учётная запись на флаере даёт бесплатный демо-доступ многим участникам; ограничения задаёт администратор. Реализация сервиса в этой задаче не выполнялась; настоящие credentials/пользователи/демо-кампании не создавались.

**Связанные контракты:** `docs/ROLES_AND_PLANS_SPEC.md`, `spec_billing_accounts.md`, действующий контракт объектов исследования и журналирования. Изменения к ним перечислены в §15; утверждение прежней редакции «смежные слои не меняются ни одной строкой» снимается.

## 1. Результат проектирования

1. **ADMIN-01.** Роль администратора не привязана к типу оболочки. Одна личная identity администратора работает через embedded и standalone. Интерфейс и API прав общие; маршруты страниц присутствуют в обоих приложениях.
2. **ADMIN-02.** Основной browser-вход администратора — личная учётная запись с MFA. Предпочтителен корпоративный OIDC с MFA; при отсутствии готового IdP доступен локальный пароль + MFA. Неизвестный корпоративный SSO не блокирует работу standalone.
3. **DEMO-01.** Для участников действительно существует **одна общая пара логин/пароль**, которую можно напечатать на флаере. Внутри платформы это credential кампании, а не один совместно используемый пользователь-владелец исследований.
4. **DEMO-02.** Каждый посетитель получает отдельный `participant_id`, `DemoGrant` и изолированное временное рабочее пространство. Общими остаются условия кампании и бюджет вендора, но не пользовательские документы, данные или роли владельца.
5. **DEMO-03.** Рекомендуемый форумный режим: фиксированное окно кампании, ограниченное время grant, лимиты запросов/задач/ресурсов, остановка всей кампании администратором. При необходимости строгой выдачи «один доступ участнику» добавляется отдельный одноразовый код участника при неизменной общей паре с флаера.
6. **BOUNDARY-01.** Общий пароль, IP и cookie **не доказывают** уникальность человека. Очистка cookie, другой браузер, VPN или передача флаера могут обходить мягкое распознавание повторного посетителя. Гарантируются конечность самой кампании и верхняя граница серверного бюджета, а не неустановимая уникальность физического лица [S1].

## 2. Оценка актуальности прежней доступной редакции

Старая редакция — Task 109, со ссылкой на `a42df0a…`; это архитектурное предложение, а не доказательство реализации. Сохранены разделение AuthN/AuthZ, отдельность API-ключей, адаптивное хеширование паролей, отзыв сессий, одноразовые токены и проверка актуальных прав.

| Положение прежней редакции | Оценка | Решение v2 |
|---|---|---|
| Admin относится к embedded; standalone обслуживает только external_user | Не отвечает новому требованию | ADMIN в обеих оболочках, без назначения роли из URL/клиентского флага |
| Embedded AuthN отложен до выяснения SSO | Недостаточно для работающей админки в обоих приложениях | Общая identity и локальный MFA fallback; OIDC — подключаемый способ входа |
| Демо только через личный email/passwordless | Полезный индивидуальный trial, но не сценарий общего флаера | Разделить личный trial и форумную кампанию с общей парой |
| Shared demo как один обычный User/Account | Ранее не спроектировано; опасно из-за общей истории и квот | Campaign credential → отдельные participant/grant/workspace |
| Только `trial_days` и число анализов | Не ограничивает повторные анонимные входы как человека и не задаёт бюджет форума | Жёсткий `ends_at`, grant TTL, квоты, глобальный бюджет и явная граница anti-abuse |
| JWT access + refresh обязателен для browser | Возможный механизм, но лишняя обязательность для first-party приложения | Основной browser-контракт — opaque server-side session; JWT допустим только для обоснованной границы сервисов |
| Разные домены требуют опираться на third-party cookies | Нельзя принять как единственный production путь | First-party `/api` proxy/BFF; текущий rewrite не равен полноценному BFF |
| `SameSite=Strict` как самостоятельная замена CSRF | Слишком сильное утверждение | CSRF token + Origin/Fetch Metadata; SameSite — дополнительная мера [S3, S4] |
| Stateless invite JWT без записи использования | Подпись не обеспечивает одноразовость, отзыв и защиту seats при гонке | Persisted Invitation с atomic consume и проверкой capacity |
| Принятие приглашения просто увеличивает `Account.seats` | Смешивает identity, membership и биллинг | Транзакционный вызов политики мест/биллинга; не самовольный increment из AuthN |
| CU и ограничения достаточно считать «на ключ» | Допускает обход выпуском новых ключей/сессий | Корневые лимиты account/grant/campaign; ключ — дополнительное измерение |
| `apps/api/auth.py` одновременно с новым `apps/api/auth/` | Риск затенения Python imports | Сохранить фасад auth.py; новый пакет authentication/ |
| Нижние слои не требуют ни одной правки | Не подтверждено даже доступным кодом | Нужны route/worker guards, identity bridge, admin UI и миграция владения |

### 2.1 Наблюдения кода: строго на bee3f8e

- `apps/api/auth.py`: `CISSTAT_API_KEYS` → `AuthenticatedPrincipal`; `require_admin_role` принимает `get_current_principal`, который требует `X-API-Key`.
- `packages/ui/components/AdminProgressDashboard.tsx` и `packages/ui/lib/admin.ts`: ввод ключа в памяти вкладки и запросы с заголовком. Ключ в памяти лучше постоянного browser storage, но это не личный MFA-вход.
- Есть `apps/embedded/app/admin/progress/page.tsx`; аналогичного standalone path в доступной базе нет. Это **не утверждение о наличии/отсутствии страницы на 21946a7**.
- В `apps/standalone/next.config.mjs` уже есть `/api/v1/*` rewrite к API; прежняя формулировка «такого слоя совсем нет» нуждается в уточнении. Rewrite проксирует запрос, но сам не реализует authentication session, CSRF, step-up и политику forwarding.
- В доступных Role/Plan документах admin назван embedded; Demo имеет отдельные capabilities. Комментарий о контексте роли нужно изменить, а доступные функции demo нельзя молча расширить кампанией.

Точные пути и хеши доступных исходников — `scripts/auth_spec_review_2026_10_26/source_evidence.json`. Наличие кода не удостоверяет конфигурацию production, включение guards или готовность IdP/email/Redis.

## 3. Модель доверия и правила доступа

`Identity` отвечает на вопрос, кто вошёл. `Credential` — чем доказан вход. `AuthSession` — какой browser-вход действует сейчас. `AccountMembership` — в каком аккаунте разрешена работа. `Capabilities` — какие функции разрешает план. `DemoGrant` — дополнительные временные/ресурсные ограничения форумного доступа. Исследовательская сессия — контейнер научной работы, не доказательство входа.

Серверное решение для обычной операции:

> authenticated identity/session ∩ актуальная роль и scopes ∩ membership/tenant/object access ∩ capabilities account ∩ действующий demo grant, если он есть ∩ ресурсные лимиты.

Для административной операции дополнительно нужны platform-admin permissions и требуемая свежесть MFA. Наличие полной analytical capability у internal_analyst, роль OWNER платного Account или знание admin URL не дают ADMIN.

- `deny-by-default`; проверка каждой операции, включая файлы, async jobs, polling, progress, checkpoint restore и прямой вызов API [S6].
- Нельзя вычислять роль по standalone/embedded, `NEXT_PUBLIC_API_MODE`, IP вендора, query `role=admin`, общей демо-паре или клиентским claims.
- Проверка account/role/plan/grant делается из доверенного серверного состояния. Отзыв не ждёт естественного окончания долгого токена.
- Если authoritative auth/grant/budget store недоступен, новые защищённые операции отклоняются с безопасным 503; анонимный fallback не включается.
- При двух разных предъявленных identities, например cookie и API-key, права не объединяются. Для такого конфликта — `400 auth_ambiguous`; правила приоритета одного credential задаются явно для выбранного типа endpoint.
- Для чужих object IDs использовать существующий uniform-404 контракт. Неаутентифицированный функциональный endpoint — 401, известный пользователь без функционального права — 403.

## 4. Администратор в embedded и standalone

### 4.1 Оптимальный сценарий

Администратор открывает `/login?return_to=/admin`, входит личным методом и проходит MFA. В обоих приложениях `/admin` показывает общий административный workspace; `/admin/progress` сохраняется как маршрут раздела. Видны только разрешённые разделы: пользователи/сессии, демо-кампании, журналы/поддержка, существующие административные инструменты.

Предпочтение для зрелого deployment: корпоративный OIDC Authorization Code + PKCE; связь пользователя по `(issuer, subject)`. Признак MFA принимается только по проверенному контракту доверенного IdP, а не произвольному `amr` из пользовательского тела запроса. Если IdP не подтверждает нужный уровень, требуется локальный step-up либо отказ в admin доступе.

Для запуска без корпоративного IdP: локальные именованные администраторы, пароль + WebAuthn/passkey с user verification либо пароль + TOTP как допускаемый политикой fallback. Email magic link/SMS не являются достаточным вторым фактором администратора в этой редакции. Не заявляется формальная сертификация NIST AAL [S1, S2].

Один и тот же administrator principal доступен через оба приложения. Разные домены могут иметь отдельные host-only auth cookies; это не две разные учётные записи. Для бесшовного входа между origins нужен центральный IdP/SSO. Доступ в standalone не зависит от предварительно открытой embedded-вкладки.

### 4.2 Защита административных действий

- MFA обязательно до открытия защищённого admin API. UI redirect/скрытое меню не заменяют backend gate.
- Предлагаемые начальные настройки: absolute session 8 часов, idle 15 минут, свежесть MFA для опасных изменений 5 минут. Это **проектные значения платформы**, не цитата нормативного стандарта; администратор может ужесточить их в заданных пределах.
- Перед назначением ADMIN, изменением MFA/recovery, выпуском привилегированного service credential, изменением demo policy/budget, массовым отзывом и export security logs нужен step-up.
- Для массовой блокировки показывать ожидаемое число затронутых grants/jobs; команда содержит причину и policy version. Не использовать непроверяемое поле «я уже подтвердил MFA» из клиента.
- Suspend пользователя, снятие роли ADMIN и глобальный logout отзывают соответствующие server sessions/privilege versions. Текущий опасный job перепроверяет разрешение на этапе исполнения и выдачи результата.
- Администратор не получает неаудируемое impersonation право. Просмотр частного исследования поддержки — отдельное разрешение/основание с журналом, а не автоматическое следствие входа в админку.

### 4.3 Bootstrap, recovery и миграция API-ключей

Первого администратора создаёт защищённая операционная процедура/CLI с одноразовым provisioning secret. В production нет публичного «назначить себя первым admin», пароля по умолчанию или универсального admin-логина на флаере. При первом входе завершается enrollment MFA. Резервные recovery-коды высокоэнтропийны, одноразовы, сохраняются только в виде хеша; восстановление MFA отзывает сессии и журналируется.

Существующий ADMIN API-key — временный совместимый программный/операционный путь, а не целевой login form browser. После миграции browser не должен требовать вводить ключ; ключи не помещаются в frontend bundle, URL, localStorage/sessionStorage. Для сервисной автоматизации используются отдельные principals/scopes и политика привилегированных machine credentials. Старые ключи отзываются по согласованному rollout, не одномоментно без проверки consumers.

## 5. Универсальная демо-учётная запись: сравнение сценариев

| Вариант | Опыт участника | Что обеспечивает | Ограничение | Решение |
|---|---|---|---|---|
| Один обычный пользователь, все работают в его Account | Очень простой | Общий вход | Общая история, коллизии datasets, чужие документы, общий logout и owner privileges | Запрещён |
| Общая пара → приватный DemoGrant | Ввести данные с флаера, без email | Изоляцию, ограничение одной выдачи, жёсткое окончание кампании и бюджет | Не устанавливает уникальность человека при новом браузере | **Основной режим форума** |
| Та же пара + одноразовый код участника | Дополнительно короткий код с персонального талона | Одна redemption на код, стабильный grant/лимит при повторном входе | Код можно передать; несколько полученных талонов — не один человек | **Усиленный режим** |
| Личный verified-email trial | Подтвердить собственный email | Лимит известного email/account, удобный follow-up | Email не уникален как человек; выше барьер на стенде | Отдельный сценарий после форума |

Вход с флаера распознаёт кампанию по login, проверяет secret и условия, затем выдаёт private participant/grant. Во внешнем UI это одна универсальная учётная запись, а внутри это тип `campaign_entry`. Он не может сменить общий пароль, забрать OWNER роль, приглашать участников или просматривать исследования других участников.

Не создавать 500 sessions с одним `principal_id`/общим единственным seat. Не переносить кампании на произвольную обычную учётную запись через выставление `plan=demo`: семантика владения у них разная.

## 6. Политика кампании и рекомендуемый форумный профиль

Ниже — стартовый профиль для обсуждения и нагрузочной проверки; значения не описывают уже действующие настройки платформы.

| Параметр | Предложение по умолчанию | Правило |
|---|---|---|
| `starts_at` / `ends_at` | Указанные администратором даты форума + короткое заранее заданное окно; пример — 48 часов всего | Ends_at обязательно, без бесконечного/скользящего значения |
| `grant_absolute_minutes` | 60 минут | От первой успешной выдачи, не от последнего login/refresh |
| `session_idle_minutes` | 15 минут | Неактивная session истекает; повторный вход не обнуляет grant |
| `participant_max_sessions` | 1 активная session на grant | Несколько вкладок одной session не считаются новыми участниками |
| `participant_max_analyses` | 3 новых исследования | В пределах гранта; retry той же idempotent операции не новый анализ |
| `participant_max_running_jobs` | 1 | Reservation перед постановкой; lease не даёт второй исполняющийся процесс |
| Данные | Подготовленные демо по умолчанию | Own upload выключен; при включении — не выше Capabilities, стартово до 5 000 строк/4 MiB |
| Тяжёлый fit/GPU | Выключены | При существующем Demo `can_train_models=False` кампания не может это разрешить |
| Вычисления | Allowlist недорогих операций и server job deadline, например 60 секунд | CPU/RAM/queue budget и единицы CU подтвердить калибровкой до включения |
| Public/programmatic API | Выключен | Browser вызывает нужные web API с grant; `can_use_api=False` не означает запрет любого HTTP |
| Экспорт | Owner-scoped, с demo watermark и лимитом размера/числа | Нельзя экспортировать данные соседнего grant или общий tenant corpus |
| История после завершения | Не включена как постоянная пользовательская услуга | Ephemeral datasets/documents удаляются по bounded retention, например через 24 часа после конца grant |
| Участники/выдачи | Конечные max grants и campaign resource budget | Лимит выбирает администратор под число флаеров и подтверждённую мощность; пустой бюджет запрещает activate |

Все обязательные конечные лимиты валидируются сервером; `null`, отрицательные значения или поле «0 = бесконечность» не допускаются. Нулевой лимит функций означает запрет. Capability ceiling берётся из текущего authoritative plan/policy: администратор кампании может сужать его, но не молча выдавать недоступный вид вычислений.

До activation требуется заполнить конкретный общий бюджет, max grants, max campaign concurrent jobs и параметры нагрузки. UI показывает их и последствия; неизвестная стоимость тяжёлой операции — основание не включать её. Для демонстрации прогноза без разрешённого fit допустимы заранее подготовленные примеры с явной пометкой происхождения; они не выдаются за расчёт на загруженных посетителем данных.

### 6.1 Гарантия конечности времени

Время хранится в UTC, UI показывает часовой пояс. Интервал `[starts_at, ends_at)`:

```text
grant.expires_at = min(campaign.ends_at, issued_at + grant_absolute_minutes)
request_deadline = min(session.absolute_expires_at, grant.expires_at, campaign.ends_at)
now >= expires_at  -> доступ отклоняется
```

`issued_at` не переписывается на logout/login, refresh, idle timeout, открытие второй вкладки, смену приложения или продление server session. Нельзя продлевать grant сменой версии credential, созданием нового access token или повторной активацией той же кампании. Полностью новая кампания — новое управленческое решение с отдельным бюджетом и аудитом, а не автоматическое продолжение старой.

Распознанный participant после исчерпания/истечения grant не получает новый grant той же кампании простым login: прежний ledger и выдача сохраняются. Новый неопознанный browser может обойти именно распознавание, но не конечный срок и общий бюджет.

Cookie participant identifier — случайный pseudonymous browser marker, а не аппаратный fingerprint. Его утрата может породить нового незнакомого посетителя в мягком режиме. Но даже тогда новая выдача подчинена неизменному `campaign.ends_at`, max grants и общему бюджету. **Именно это предотвращает вечное использование общей форумной пары**, а не обещание безошибочно узнать человека.

### 6.2 Усиленный режим

Общая пара остаётся одной. Дополнительно вендор выдаёт участнику случайный одноразовый admission code, отдельный от общего пароля. В БД — только хеш, campaign binding, срок и отметка atomic redemption. Повторное предъявление не создаёт новый grant. Возобновление существующего grant требует отдельного resume credential; знание уже погашенного кода само по себе не открывает чужое workspace.

Если нужна более длительная индивидуальная проба, посетитель создаёт личный verified-email account по отдельной политике trial. Логин флаера не выдаёт бессрочный личный аккаунт и не сбрасывает уже израсходованные лимиты. Claim/migration выбранных собственных результатов возможны только явно с проверкой владения и с сохранением provenance.

## 7. Поток входа участника и изоляция

1. Флаер содержит URL/QR, общий login/password и понятную конечную дату кампании. Пароль не помещается в URL/QR query; допускается публичный campaign alias.
2. `/demo` показывает условия без раскрытия чужой активности: время выдачи, длительность доступа, доступные данные/операции, отсутствие постоянной истории.
3. POST enter проверяет credential, campaign status/time, source throttling, идентификатор ранее выданного grant/требуемый admission code и остаток бюджета.
4. Одна транзакция принимает redemption, создаёт participant identity, private grant/workspace и auth session, фиксирует квоты. Частичная выдача не становится активной session.
5. Для каждой операции сервер устанавливает context `(subject_id=participant_id, tenant_id, account_id, demo_grant_id)`. Object access требует владельца/явный grant и подходящий tenant; общий `campaign_id` не является разрешением на чужие данные.
6. Повторный login известного участника возобновляет тот же grant до прежнего срока. Logout не удаляет usage ledger и не выдаёт новую квоту. При лимите одной session требуется явное заменить мою session с отзывом старой; новый посетитель с тем же общим паролем не выталкивает остальных.
7. По expiry/quota/pause UI показывает понятную причину и альтернативу: завершить, обратиться на стенд, войти личным аккаунтом. Таймер browser информационный; сервер продолжает проверять ограничения при ручном запросе.

Панель общего профиля не содержит списка чужих datasets, runs, forecasts, документов, jobs, sessions или billing. Account ID/Grant ID в URL не дают доступ. Одинаковое имя файла/демо-датасета не связывает рабочие пространства. Для same-browser kiosk на стенде нужна явная «Завершить и очистить» и новая контролируемая выдача; передача следующему человеку активной session не считается безопасной изоляцией автоматически.

## 8. Ограничение ресурсов без обхода сессиями и ключами

Учет и резервирование выполняются по иерархии `operation → grant → campaign → vendor resource pool`; для обычных пользователей — `operation → account → service pool`. API-key/session — аналитическое измерение и дополнительный throttle, а не единственная база лимита.

- Каждое создание исследования/тяжёлой операции имеет `idempotency_key`, привязанный к actor, operation, входу и resource scope. Повтор с другим телом — 409; один и тот же повтор не списывает лимит дважды.
- До ответа 202 reservation квоты/ресурсов атомарна и не может превысить остаток ни grant, ни campaign. Оптимистический «сначала выполним, потом спишем» запрещён.
- `worker` перед стартом проверяет grant/policy, reserve и deadline; во время выполнения действует hard timeout/лимит процесса. Отзыв/истечение не обходится ранее выданным job ID. Запрещена выдача готового результата после окончания прав, если bounded read-only grace не был заранее разрешён политикой.
- `lease` с TTL освобождает потерянную очередь, но не доказывает остановку старого процесса. Прежде чем переиспользовать running slot, старый worker fenced/cancelled; stale completion не возвращает свободный grant и не публикует результат новой попытки.
- Успешное завершение фиксирует фактический расход; неиспользованный reserve освобождается ровно один раз. Ошибка операции не даёт бесконечные бесплатные попытки: attempt/job/time ограничения и фактическая стоимость учитываются по политике.
- Pause/kill campaign немедленно закрывает новые requests/admission/jobs; queued jobs отменяются, running jobs получают revoke/fence и прекращаются в заданном operational bound. Доступ к результатам блокируется сразу, даже если физическая остановка процесса ещё завершается. Перед запуском фиксируются проверяемый bound отмены и способ его обеспечения.

Запрет programmatic API означает отсутствие соответствующего public API credential/entitlement, а не доказательство, что HTTP-запрос с browser cookie нельзя автоматизировать. Нельзя доверять User-Agent/Referer как признаку человека; квоты и time limits действуют для любого клиента.

Общий бюджет защищает стоимость вендора даже при смене IP и очистке cookies. Его исчерпание может затронуть честных посетителей — это явный trade-off. Для форума администратор видит остаток и может вручную выделить отдельные grants по одноразовым кодам. Бюджет не восстанавливается автоматически каждую новую browser session.

## 9. Browser AuthSession и две оболочки

### 9.1 Основной путь

Использовать общий Auth service и first-party endpoints `/api/v1/*` обеих оболочек с контролируемым proxy/BFF. Session identifier — высокоэнтропийный opaque token. На сервере хранится только его криптографический verifier/hash плюс identity/context/lifetime/revocation. Cookie `__Host-cisstat_auth` имеет `Secure`, `HttpOnly`, `Path=/`, без `Domain`; `SameSite=Lax` либо более строгая совместимая политика [S3].

BFF/прокси пересылает только разрешённые authentication cookies/headers по TLS. API сам валидирует session; самодельные `X-User`, `X-Role`, client account_id или один `X-Forwarded-*` не доказательство identity. Set-Cookie не должен устанавливать Domain стороннего API-хоста в ответе приложения. Выходные redirects/return_to — относительные allowlisted пути; открытый redirect запрещён.

`cisstat_session_id` хранит исследовательскую сессию и не считается auth credential. Login, logout, privilege elevation и account switch защищены от fixation: auth SID ротируется, старый отзывается, research context перепривязывается только по разрешённой политике. Пользователь не получает чужие legacy runs по первому предъявлению ID. Путь миграции существующего владения нужно согласовать с актуальным identity-контуром на 21946a7.

Cookies разных origins не пытаются объединить через широкий `Domain`. Shared User identity обеспечивается backend, а cross-app SSO — доверенным протоколом, не передачей SID в URL/postMessage от любого origin. Для настоящего third-party iframe embedded отдельно требуется браузерный протокол входа/перехода на first-party origin и проверка parent origin; нельзя обещать, что `SameSite=None` снимает все browser ограничения.

### 9.2 CSRF, CORS и отзыв

State-changing cookie-запросы, включая login, logout, смену account, demo enter/retry и admin policy, требуют CSRF-защиты: server-bound token и проверку Origin; Fetch Metadata — дополнительный слой. Нельзя менять данные GET-запросом. SameSite/CORS не заменяют CSRF token в выбранном контракте [S3, S4].

CORS разрешает только конкретные trusted origins с credentials там, где это нужно; wildcard для credentialed browser sessions запрещён. Прямой вызов API/старого internal endpoint проходит тот же AuthContext/permission/grant gate. Заголовок режима приложения не открывает обход.

AuthSession содержит absolute expiry и idle expiry; refresh/keepalive не двигает absolute deadline. Сервер проверяет revoke/role/policy status на каждом запросе. Для JWT-варианта в межсервисном протоколе обязательны signature algorithm allowlist, issuer, audience, exp, nbf, sid/jti и проверка server-side revocation/context. Права не берутся из устаревшего role/plan claim. Ротация refresh атомарна, reuse отзывает соответствующую family; конкурентные вкладки не должны обнулять все чужие sessions одного пользователя. Browser по умолчанию не хранит bearer/refresh в localStorage.

## 10. Остальные способы входа и API-ключи

- Личный email/password и passwordless — отдельный self-service/trial; forum enter не требует рассылать один magic link всем посетителям.
- Passwords: Argon2id с калибровкой; минимум не ниже выбранной актуальной рекомендации OWASP, параметры версионируются. Высокоэнтропийные random sessions/API keys/admission tokens хранятся как SHA-256 verifier либо keyed verifier с управлением ключами. Для короткого OTP быстрый несолёный hash недостаточен: нужны keyed verifier, ограничение попыток, короткий TTL и одноразовый consume [S5].
- Password policy поддерживает длинные passphrases, password manager/paste и проверку блок-листа; длина не заменяет MFA администратора. Не предписывать периодическую смену всех пользовательских паролей без основания. Общий campaign secret меняется по событию/компрометации и не считается личным секретом посетителя [S1, S2].
- Magic link/OTP, email verification и recovery имеют purpose, target, expiry, attempts и durable одноразовую запись. GET по ссылке не должен автоматически расходовать секрет из-за mail scanner; подтверждение/consume — защищённая команда. UI не раскрывает существование личного email по различимым ответам.
- OIDC identity связана по issuer+subject. Автоматическое склеивание аккаунтов только по непроверенному email запрещено. OAuth без проверенного OIDC identity protocol не называется входом пользователя.
- Invitations: token hash + email/account/scope/expiry/status; атомарный consume, актуальное право inviter, проверка capacity и membership uniqueness. Повторное принятие не создаёт второе membership и не расходует место повторно. AuthN не меняет правила seats биллинга сам по себе.
- API keys персональны/service-scoped, высокоэнтропийны, с expiry/revoke и показом секрета один раз. Они не принадлежат форумной общей паре и не выпускаются в demo. Несколько ключей одного Account не получают независимый полный Account budget.
- Общий public campaign login не блокируется для всех после пяти ошибок одного IP: rate limits применяются по source/participant/endpoint и защитному общему потоку. При аномалии — управляемая деградация/CAPTCHA/пауза; глобальный lockout общего логина от произвольного клиента создаёт простой DoS.

## 11. Предлагаемая модель данных

Ниже новые проектные сущности, а не утверждение о таблицах на 21946a7. Имена можно согласовать с существующими; смысл/инварианты обязательны.

| Сущность | Основные поля/инварианты |
|---|---|
| `UserIdentity` | stable subject_id, status, verified contacts; role/membership не равны credential secret |
| `Credential` | identity_id, type, verifier, issuer/provider_subject, version, revoke; unique issuer+subject |
| `AuthSession` | sid verifier, subject_id, active account, origin/client binding, auth_time, mfa_time, privilege_version, issued/idle/absolute expiry, revoke, optional grant_id |
| `DemoCampaign` | vendor/tenant, alias, status, starts_at, ends_at, current policy_version, limits, budget, allowed apps/origins; finite activation requirements |
| `DemoAccessCredential` | campaign_id, login alias, password verifier, version, rotated/revoked_at; не обычный личный User/OWNER |
| `DemoParticipant` | participant_id, campaign_id, pseudonymous resume/browser verifier; optional verified admission binding |
| `DemoGrant` | grant_id, participant_id, isolated workspace/account, campaign_id, issued_at, immutable upper expiry, status, policy_version, limit counters/refs; unique active redemption binding |
| `DemoAdmission` | campaign_id, code hash, expiry, redeemed_grant_id, redeemed_at; one atomic redemption |
| `UsageReservation` / ledger | actor/grant/campaign/operation/idempotency, resource estimate/actual, state, lease/fencing token, settled_at |
| `Invitation` / `AuthChallenge` | purpose, target, token verifier, expiry, attempts, consumed/revoked_at; persisted replay protection |
| `AuditEvent` | actor, session reference, campaign/grant/resource, action/result/reason, before/after policy version, correlation; без секретов |

Account и Membership переиспользуются там, где они уже являются источником истины. Для participant допустим отдельный временный MONO Account либо эквивалентное изолированное workspace с тем же object-policy контрактом. **Выбранное решение v2:** private temporary MONO Account на grant; forum campaign vendor budget — sponsor pool, не платный личный Account посетителя. Квоты кампании не умножаются количеством этих временных Account, право OWNER на sponsor pool им не выдаётся. Cleanup обрабатывает связанные datasets/documents/objects/jobs, а не только строку Account.

## 12. Администраторская панель и действия кампании

Обе оболочки используют общие `packages/ui` компоненты и API contracts. Поле ввода API-key не является основным экраном входа.

Раздел «Демо-кампании» показывает status, start/end, число выданных/активных grants, running/queued jobs, расход/резерв/остаток бюджета и долю отказов. Редактор имеет секции: общая пара и доступные приложения, окно времени, ограничения участника, ограничения кампании, функции/данные, export/retention, усиленная выдача кодов. Секрет после создания показывается один раз для выпуска флаера; позже — только rotate, без «показать сохранённый пароль».

Состояния: draft → scheduled/active → paused/exhausted/expired/revoked. `paused` запрещает работу согласно политике и не двигает время. `exhausted` не переоткрывается login; пополнение бюджета — явное step-up действие. Истёкшую кампанию нельзя незаметно превратить в бессрочную тем же credential. Pause/resume без изменения срока допустимы до hard end; отдельное продление/новая кампания требует явного решения и журнала. Возобновление не расширяет уже выданный immutable grant expiry автоматически.

Обязательные команды: создать draft, активировать, pause/resume, rotate secret, revoke credential/все grants, отозвать один grant, изменить будущую политику, просмотреть usage/audit, выдать/погасить набор admission codes. Ограничение новых grants применяется сразу; ужесточение действующих грантов — через policy/revoke version с указанием последствий. Ослабление limits не сбрасывает counters. Optimistic concurrency по policy_version предотвращает потерю правок двух администраторов.

Участник видит оставшееся время/анализы и доступные функции без CU/formula/internal IDs там, где они не нужны. При отказе — «Демо завершено», «Лимит вычислений исчерпан» или «Кампания приостановлена», с вариантом продолжить через личный доступ. Нельзя обещать сохранение истории после retention. Отдельное предупреждение перед загрузкой своих данных объясняет временность workspace и запрет конфиденциальных данных в публичном demo-профиле, если такая политика выбрана вендором.

## 13. API-контракты к реализации

| Endpoint | Назначение / gate |
|---|---|
| POST `/v1/auth/login` | Личный вход; до завершения MFA выдаётся только ограниченный challenge, не ADMIN session |
| POST `/v1/auth/mfa/verify` | Atomic challenge consume + elevation/rotation; rate limited |
| GET `/v1/auth/me` | Текущий safe AuthContext, доступные account/UI actions; без secrets |
| POST `/v1/auth/logout` | Revoke server session; CSRF; grant usage не удаляется |
| POST `/v1/auth/sessions/revoke` | Свои sessions либо admin scope + step-up + audit |
| POST `/v1/auth/step-up` | Новый challenge для конкретного sensitive action/context |
| POST `/v1/auth/demo/enter` | Общая пара, optional admission, policy/budget/atomic grant issuance |
| GET `/v1/auth/demo/me` | Только свой grant, remaining limits, absolute deadline |
| POST `/v1/auth/demo/resume` | Своё подтверждение владения существующим grant, без новой квоты |
| GET/POST `/v1/admin/demo-campaigns` | ADMIN + campaign-management scope; создание — step-up/mandatory audit |
| PATCH `/v1/admin/demo-campaigns/{id}` | Policy version precondition, validated finite limits, step-up |
| POST `…/{id}/activate`, `/pause`, `/resume`, `/revoke` | Переходы state machine; idempotency, audit, impact |
| POST `…/{id}/rotate-credential` | Новая версия секрета, явная политика отзыва старых sessions |
| POST `…/{id}/admissions` | Выдача codes ограниченным пакетом; секреты один раз, без URL/logs |
| GET `…/{id}/usage`, `/audit` | ADMIN scope, filtered safe metadata |

Register, email verification, passwordless, invite, recovery и personal API-key endpoints строятся на общих challenges/credentials; не дублируются для embedded/standalone. Browser endpoints маршрутизируются через first-party `/api` в обеих оболочках, backend path остаётся единым.

Ошибки: `401 authentication_required/session_expired`, `403 insufficient_permission/demo_expired/campaign_paused`, `409 idempotency_conflict/policy_version_conflict`, `422 invalid_policy`, `429 participant_quota_exceeded/campaign_budget_exhausted/rate_limited`, `503 auth_store_unavailable`. Для Retry-After указывать только реальный срок восстановления; конечное исчерпание не обещает автоматического повтора. Object existence не раскрывается через различия ответов.

## 14. Аудит, отказоустойчивость и удаление

Обязательно документируются named admin login/MFA/recovery, назначения ролей, изменения policy/budget, activation/rotate/revoke, admissions, выдача/окончание grant, quota rejects и privileged access к чужим данным. Общий пароль не позволяет достоверно подписывать действие фамилией участника; actor демо-события — private participant_id + campaign/grant.

Mandatory admin policy change и её audit intent/commit должны иметь согласованный transaction/outbox контракт. Нельзя сначала изменить политику, затем выбросить audit error и заявить, что изменение не произошло. Идемпотентный retry не создаёт второе повышение бюджета. При недоступности mandatory audit защищённая команда не исполняется; обычные события доступа следуют выбранной политике standard logging с измеряемой деградацией.

В логах нет passwords, OTP, cookies, raw API keys, magic links, admission codes, contents датасета или полного Authorization header. IP/device telemetry минимальна, с раздельной ограниченной retention; browser marker — pseudonym, не скрытый устойчивый fingerprint. Реальные сроки хранения/правовые основания утверждает оператор, а не придумывает AuthN код.

После окончания grant научные данные/документы временного Account удаляются по retention и политикам зависимостей; security/usage ledger может храниться отдельно в минимальном виде для anti-abuse/audit. Новый login не обнуляет этот ledger. Удаление данных пользователя и запрет хранить постоянную историю не означают удаления факта использованной квоты. Восстановление из backup не воскрешает revoked credential, consumed admission или исчерпанный budget. DB/Redis failover и восстановление должны быть проверены на replay и counters, а не только на наличие таблиц.

## 15. Интеграция и миграция

| Область | Изменение / проверка до реализации |
|---|---|
| Role/Plan spec, `plans.py`, TS-зеркало | ADMIN больше не embedded-only; Demo остаётся external_user + ограниченный plan; общая пара не расширяет capability потолок |
| Billing/Account/Seats/CU | Temporary Accounts sponsored by campaign; общий reserve/charge; приглашения через seat policy, не самостоятельный increment |
| `apps/api/auth.py` | Сохранить импортируемый фасад dependencies; подключить единый resolver cookie/API/OIDC с явными правилами |
| Новый `apps/api/authentication/` | Credentials, challenges, sessions, MFA, demo campaigns/grants/policies, recovery; избегать конфликта с auth.py |
| Identity/ownership/documentation/progress | Сначала проверить актуальный resolver на 21946a7; reuse существующего subject/tenant/access decision, не вводить второй независимый субъект |
| SessionStore | Research session отделить от AuthSession; account switch/logout не присваивают чужие runs |
| API и workers | Инвентаризация всех путей scientific writes, metadata, downloads, jobs; новый guard не только на login endpoint |
| `packages/ui` | Общие login/MFA/admin/demo components, safe AuthProvider, состояния expiry/quota/error; без долгоживущих JS secrets |
| Обе оболочки | `/login`, `/admin`, `/admin/progress`, `/demo`; same-origin transport/cookie/CSRF, самостоятельная работа standalone |
| Миграции | Выбрать следующий реальный номер на целевой базе, не резервировать неизвестный `0016`; additive reader-first и uniqueness constraints |
| Deployment | TLS, origins, trusted proxy settings, secret management, IdP callbacks, email, auth stores/backup, queue isolation/limits |

Совместимость с dev session-surrogate и существующими API-key consumers — явная ограниченная переходная политика. Production demo не может оставлять бесплатный необслуживаемый путь через прежние anonymous/internal endpoints. Существующее владение мигрируется по надёжным серверным основаниям; нельзя назначить owner первому вошедшему с известным run_id. Смена идентичности или upgrade из demo не повышает доказательность исторических научных событий.

## 16. Этапы реализации и критерии завершения

1. **AUTH-0 — сверка и threat model.** Получить 21946a7, проверить старую spec/paths/identity/migrations, собрать route/worker access inventory, согласовать trust/origins и baseline capabilities. Замерить allowlist вычислений и бюджет форума. Результат — проверенная карта источников, без утверждения реализации.
2. **AUTH-1 — identity/session/admin в двух оболочках.** Личные credentials, MFA/challenges, AuthSession, CSRF, bootstrap/recovery, единый API resolver и две страницы admin. Завершение: named admin работает из standalone без embedded, non-admin не проходит прямой API.
3. **AUTH-2 — общий forum entry и private grants.** Campaign credential, isolated temporary Accounts, finite expiry, atomic redemption, status/revoke. Завершение: несколько участников одним логином не видят/не сбрасывают состояние друг друга.
4. **AUTH-3 — бюджет/очередь/kill.** Atomic reservations, idempotency, per-grant/campaign quotas, fencing и server deadline, закрытие обходов. Завершение: гонка не перерасходует бюджет, отзыв не обходится queued/running job.
5. **AUTH-4 — администратор кампаний и усиленная выдача.** Общая панель, policy versions, impact, rotate, admission codes, безопасный export/retention; не включать бесконечные default limits.
6. **AUTH-5 — self-service/membership/API migration.** Personal trial/passwordless/OIDC/email, invitations/seats, ключи и deprecation legacy; без смешения forum credential с личным аккаунтом.
7. **AUTH-CERT — сквозная приёмка.** Настоящие обе оболочки/production-like origins, auth stores restart/rollback, отказ audit/DB/Redis, concurrent grants/jobs и негативные обходы; отдельно функциональные тесты и нагрузочная ёмкость форума.

Оба обязательных пользовательских требования входят в первые рабочие срезы, а не откладываются до неопределённого будущего SSO. Разработка идёт TDD согласно AGENTS.md; этот документ не создаёт runtime-функционал.

## 17. Приёмочные сценарии

| ID | Проверяемое ожидание |
|---|---|
| AUTH-AC01 | Named ADMIN проходит MFA и открывает рабочие разделы через embedded |
| AUTH-AC02 | Тот же ADMIN самостоятельно входит в standalone, `/admin` и `/admin/progress` вызывают реальные разрешённые API |
| AUTH-AC03 | external_user, internal_analyst и Account OWNER получают отказ на прямых admin API; изменение URL/role body/header не помогает |
| AUTH-AC04 | Незавершённый MFA challenge не годится как auth session; sensitive change требует свежего step-up |
| AUTH-AC05 | Logout/revoke/снятие ADMIN закрывают следующий запрос без ожидания длинного access TTL |
| AUTH-AC06 | Одна общая пара одновременно допускает разных участников, у каждого разные actor/grant/account/run/document IDs |
| AUTH-AC07 | Чужой participant не читает/не меняет dataset/run/checkpoint/document/rendition/job/forecast даже с известным ID |
| AUTH-AC08 | Shared credential не может менять пароль кампании, повышать роль, приглашать или управлять sponsor billing |
| AUTH-AC09 | Повторный login/logout/refresh известного grant сохраняет прежние expiry и usage |
| AUTH-AC10 | На точной границе `now >= expires_at` сервер отклоняет действие; изменение часов браузера не влияет |
| AUTH-AC11 | Новые cookies/браузер могут считаться новыми в мягком режиме, но не обходят campaign end/max grants/общий бюджет; тест не объявляет это распознаванием человека |
| AUTH-AC12 | Один admission code при параллельных enter погашается один раз; replay не выдаёт новый grant/право на чужое resume |
| AUTH-AC13 | Два конкурентных запроса на последний анализ/CU/job-slot не проходят оба; reservation и counters атомарны |
| AUTH-AC14 | Idempotent retry не создаёт второй grant/анализ/charge; другой payload с тем же ключом — 409 |
| AUTH-AC15 | Pause/revoke/expiry действуют на upload, analysis, downloads, progress, restore, polling и прямой internal route |
| AUTH-AC16 | Worker перед стартом перепроверяет grant; queued/running/late-completion не обходят kill/fencing/deadline |
| AUTH-AC17 | Новый API-key, cookie, ephemeral Account или вторая оболочка не создают новый campaign budget |
| AUTH-AC18 | Неразрешённый тяжёлый fit/GPU/public API запрещён сервером; подготовленный forecast помечен примером |
| AUTH-AC19 | При недоступном authoritative auth/grant/budget store — 503 и отсутствие новой protected операции, без anonymous fallback |
| AUTH-AC20 | Mandatory audit fault не оставляет неучтённое изменение роли/policy/budget; retry согласован с commit |
| AUTH-AC21 | Login fixation, cross-account switch и legacy claim не присваивают чужой ResearchRun; auth и research cookies различаются |
| AUTH-AC22 | Обе реальные browser origins работают с first-party cookies; отсутствуют credentials в URL/bundle/browser persistent storage |
| AUTH-AC23 | CSRF и неверный Origin на login/logout/admin/demo отклонены; CORS/заголовок режима не обходят checks |
| AUTH-AC24 | Один пользователь не блокирует всю общую учётку серией плохих паролей; rate limit/DoS политика проверена под NAT форума |
| AUTH-AC25 | Две админские policy edits с одной старой version не затирают друг друга; ослабление лимита не обнуляет usage |
| AUTH-AC26 | Invitation replay, changed inviter permission и гонка за последнее место не создают лишних membership/seats |
| AUTH-AC27 | Restart/backup restore не воскрешают revoked session, consumed code, старую квоту; завершённая операция не списывается дважды |
| AUTH-AC28 | Cleanup удаляет временные объекты/задачи, но сохраняет минимальный нужный usage/audit; plaintext secrets отсутствуют во всех логах |
| AUTH-AC29 | UI обеих оболочек: loading/forbidden/expired/quota/offline, клавиатура, мобильный экран и темы; нет ложного «вход выполнен» при 503 |
| AUTH-AC30 | Нагрузочный профиль соответствует заявленному числу участников/NAT, размеру очереди и budget; значения основаны на замере, не на предположении |

## 18. Решения по умолчанию и открытые зависимости

**Предлагается принять:** ADMIN обеих оболочек; личный MFA-вход; server sessions и first-party transport; форумная общая пара как campaign entry; private temporary Account на grant; hard campaign end и общий бюджет; admission code как усиление; явная работа с policy versions, jobs и аудитом.

**До activation нужно утвердить/измерить:** даты форума и часовой пояс, число флаеров/одновременных участников, конкретный finite budget/CPU/RAM/worker capacity, доступные функции при текущем Demo plan, возможность own upload/export, сроки retention и границы поддержки. Если единственная цель — невозможность использования после форума, hard end решает её без сбора персональных email. Если нужна норма «не более часа одному физическому человеку в течение многомесячной кампании», общего логина недостаточно: требуется индивидуальная выдача и признание пределов идентификации.

**Открытый блокер этой поставки:** доступ к `21946a7`. Новая архитектура учитывает поставленные пользователем требования, но актуальность кода/совместимость миграций на указанном commit не подтверждены. После предоставления GitHub-доступа либо архива этой версии требуется завершить AUTH-0, сравнить исходный spec и актуальные контракты и снять/уточнить этот статус. В текущей редакции нет утверждения, что новые endpoints, MFA, demo grants или панель уже реализованы.

## 19. Внешние первичные источники

Проверены 26 октября 2026 года. Они дают общие рекомендации безопасности; конкретные форумные лимиты, schema/API и UX выше — проектные решения для этой платформы, не требования этих организаций.

- [S1 — NIST SP 800-63B-4, Authentication and Authenticator Management](https://pages.nist.gov/800-63-4/sp800-63b.html). Разделение credentials/session и ограничения защиты при добровольном sharing. Не заявляется соответствие платформы AAL только по этому документу.
- [S2 — OWASP Authentication Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Authentication_Cheat_Sheet.html). MFA, reauthentication, rate limits, безопасное связывание identity.
- [S3 — OWASP Session Management Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet.html). Session lifecycle, cookie flags, fixation/expiry.
- [S4 — OWASP CSRF Prevention Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Cross-Site_Request_Forgery_Prevention_Cheat_Sheet.html). CSRF token, Origin и defense in depth.
- [S5 — OWASP Password Storage Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html). Адаптивное password hashing и калибровка Argon2id.
- [S6 — OWASP Authorization Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Authorization_Cheat_Sheet.html). Проверка каждого запроса, deny-by-default и объектный доступ.
