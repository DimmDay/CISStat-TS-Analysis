# Спецификация: вкладка «Демо», самообслуживаемый демо-режим и «Вход»/кабинет на ProductHeader

**Task ID:** AUTH-KABINET-DEMO · **Дата:** 2026-11-15 · **База:** main@63bd315 (origin/main, дерево чистое)
**Статус:** постановка утверждена тимлидом; реализация по настоящей спеке, commit/push не выполняются (AGENTS.md).

## 0. Постановка

1. Демо-сценарий «флаер» расширить до **самообслуживаемого демо**: пользователь
   самостоятельно онлайн запускает демо-режим. Упоминания о флаере удалить везде.
2. Вместо пункта «Личный кабинет» — вкладка **«Демо»** на ProductHeader:
   полноценная страница с подробным описанием условий демо и входом в режим
   (по решению тимлида вкладка указывает на существующий маршрут `/demo`,
   который становится индексной поверхностью вкладки).
3. Вместо иконки User — надпись **«Вход»** со сценарием-пивотом:
   «Вход» → `/dashboard`: авторизован → `/account`, нет →
   `/login?return_to=/account`.
4. Вкладка «Знакомство с платформой» (`/navigator`), первая секция
   «Знакомство с платформой»: добавить **4-й бейдж «Попробовать в
   демо-режиме»** со ссылкой на вкладку «Демо» (страница `/demo`).
5. Все ссылки — plain first-party href, без credentials в URL (AC22).
6. Ограничение: **минимальные изменения реализованного контура AUTH** —
   API-роуты, `access_registry`, `check_routes`, контракт кампаний
   (campaign → private grant, policy, budgets, admission codes) не меняются.

## 1. Принятые решения (по рекомендациям, утверждены тимлидом)

| # | Вопрос | Решение |
|---|---|---|
| 1 | Хранение публичной пары | `NEXT_PUBLIC_DEMO_LOGIN` / `NEXT_PUBLIC_DEMO_PASSWORD` (инлайнинг Next.js на сборке; rotation = обновление env + редеплой, без правок кода). Пар не существует в коде — при отсутствии env кнопка самообслуживания честно отключена |
| 2 | robots страницы `/demo` | `index: true, follow: true` в обеих оболочках (поверхность стала маркетинговой; credentials в URL нет; enter public by design; rate-limit сохранён; `no-referrer` сохраняется) |
| 3 | Вторичная форма «Вход в кампанию» | Сохраняется (логин/пароль/код участника) — организаторские кампании и усиленный режим AUTH-16 остаются живыми механизмами |
| 4 | 4-й бейдж /navigator | Синхронно в обеих оболочках (shared-компонент, паттерн «одинаковые секции и якоря»; `/demo` существует в embedded) |
| 5 | «Тарифы» `/pricing` (404) | Вне скоупа задачи (отдельная история) |

## 2. Ключевая архитектурная развязка

Флаер в контуре AUTH-16 определяет только **канал дистрибуции** общей пары,
а не механику входа. Самообслуживание = тот же механизм (`prepare` → `enter`
с публичной парой; resume-кука 90 дней для продолжения; бюджеты/лимиты
кампании; опциональные коды участников), канал меняется с офлайн на онлайн:
пара публикуется на самой странице «Демо». BOUNDARY-01 не меняется: общий
пароль и раньше был публичным. Новых API-роутов нет — `POST /v1/auth/demo/
prepare`, `/enter`, `/resume`, `/leave` уже public + lockdown-guarded.

## 3. Задачи (пошагово)

### TASK-1 · packages/ui: дефлаеризация + самообслуживаемый вход
1. `packages/ui/lib/demo.ts`: сообщения без «флаера»/«стенда»:
   `invalid_credential` → «Вход не подтверждён. Проверьте логин и пароль
   кампании.»; `demo_expired` → «…Запустите демо заново или войдите в личный
   аккаунт.»; `campaign_capacity_exhausted` → «Лимит кампании исчерпан.
   Попробуйте позже.» Добавить `publicDemoCredentials()` (чтение env,
   `null` если не заданы).
2. `packages/ui/components/DemoEntry.tsx`: h1 «Демо-режим платформы»;
   первичная кнопка **«Запустить демо-режим»** — `prepare` + `enter` с
   публичной парой из env; при отсутствии env — disabled + честная пометка;
   вторичная форма **«Вход в кампанию»** (label «Пароль кампании» вместо
   «Пароль с флаера», submit «Войти в кампанию»); resume «Продолжить свой
   демо-доступ» и leave «Завершить демо на этом устройстве» — без изменений
   в механике; ссылки «Личный вход»/«На главную»; примечание про общий
   компьютер сохраняется. Успех → `window.location.assign("/upload")`
   (как сегодня).
3. Новый `packages/ui/components/DemoLanding.tsx`: h1 + вводный абзац +
   блок «Условия демо-режима» (временное пространство на участника; срок,
   лимиты запросов/исследований/объёма файла и retention задаёт кампания;
   постоянная история не ведётся; вход без регистрации; продолжение на том
   же устройстве; завершение на общем компьютере) + `<DemoEntry/>`.
4. `packages/ui/components/DemoCampaignAdmin.tsx`: label `alias` → «Логин
   кампании»; секрет → «Пароль показан один раз. Сохраните его для
   публикации (страница «Демо») или выдачи участникам:».
5. `packages/ui/components/AdminHome.tsx`: описание карточки «Демо-кампании»
   без «флаера».

### TASK-2 · packages/ui: 4-й бейдж навигатора
1. `packages/ui/lib/navigator-stops.ts`: тип `href` расширить до
   `` `#${string}` | `/${string}` `` (якорь ИЛИ first-party страница);
   добавить 4-й маршрут `{ title: "Попробовать в демо-режиме",
   description: "запустить демо без регистрации", icon: FlaskConical,
   href: "/demo" }`; комментарий «Три…» → «Четыре…».
2. `packages/ui/components/NavigatorHero.tsx`: сетка
   `grid-cols-1 md:grid-cols-3` → `grid-cols-1 md:grid-cols-2 lg:grid-cols-4`
   (4 карточки); шапка-комментарий файла актуализирована. `RouteCard`
   рендерит через `next/link` с `href: string` — изменений не требует.

### TASK-3 · apps/standalone: вкладка «Демо», «Вход», пивот /dashboard, robots
1. `apps/standalone/components/ProductHeader.tsx`: NAV_ITEMS — «Личный
   кабинет» → «Демо» (`/demo`); иконка User → текстовая ссылка **«Вход»** →
   `/dashboard` (стиль пунктов меню; `target="_top"` сохранён — согласовано
   с CSP `frame-ancestors 'self'` на `/login` и поведением прежней иконки);
   импорт `User` удалён; комментарии актуализированы.
2. Новый `apps/standalone/components/DashboardPivot.tsx` (client):
   `useAuth()` → `authenticated` → `router.replace("/account")`;
   `anonymous` → `router.replace("/login?return_to=/account")`; `loading` →
   статус «Проверяем вход…»; `unavailable` → fail-closed сообщение + ручные
   ссылки (без автопереходов — honest failure). `safeReturnTo` уже содержит
   `/account` — whitelist не расширяется; `/dashboard` в RETURNS не нужен.
3. Новый `apps/standalone/app/dashboard/page.tsx` (server): metadata
   `robots noindex`, `no-referrer`, title «Вход — CISStat DataTime Lab»;
   рендерит `<DashboardPivot/>`. Легаси `/dashboard/ts-analysis →
   /preprocessing` не конфликтует (отдельный маршрут).
4. `apps/standalone/app/demo/page.tsx`: рендер `<DemoLanding/>`; metadata
   robots → `index: true, follow: true`; `no-referrer` сохранён.

### TASK-4 · apps/embedded: синхронизация /demo
1. `apps/embedded/app/demo/page.tsx`: `<DemoLanding/>` + robots
   `index: true` (та же поверхность, тот же компонент). PortalNavBar и его
   иконка входа — вне скоупа (не трогаются).

### TASK-5 · тесты
1. Обновить: `product-header-nav-slogan.test.tsx`, `brand-rename.test.tsx`
   (пункт «Демо» → `/demo`; «Вход» → `/dashboard`), `auth15-demo.test.tsx`,
   `auth16-demo.test.tsx` (label «Пароль кампании», submit «Войти в
   кампанию»).
2. Новые: `packages/ui/components/auth-kabinet-demo.test.tsx` — публичный
   запуск (env задан → `prepare`+`enter` с парой; env не задан → disabled +
   пометка), рендер DemoLanding, состав `NAVIGATOR_SECTION_ROUTES` (4-й
   маршрут `/demo`);
   `apps/standalone/components/dashboard-pivot.test.tsx` — authenticated →
   `/account`, anonymous → `/login?return_to=/account`, unavailable →
   сообщение без автоперехода (мок `authMe`, паттерн auth19).

### TASK-6 · spec_auth.md: ревизия формулировок (механика не меняется)
1. Заменить «флаер»-обороты: §8, DEMO-01, DEMO-03, BOUNDARY-01 («передача
   пары»), §29, §91 (админ-флаер → «публичного admin-логина»), §100, §104,
   §126 («под подтверждённую аудиторию»), §152, §236, §347.
2. Добавить раздел «## 20. Самообслуживаемый демо-доступ
   (AUTH-KABINET-DEMO)»: публичная кампания, публикуемая пара (env),
   состав страницы «Демо», пивот «Вход», вкладка/бейдж, robots,
   операционная политика (rotation, окно, бюджет).

### TASK-7 · проверки и поставка
1. `npx jest` по затронутым сьютам; `npm run typecheck:all`; python
   `check_routes` — реестр не изменился (UI-only).
2. worklog-запись (Task ID, база, изменения, проверки, примечания).
3. ZIP новых/обновлённых файлов в открытый контейнер сессии (`download/`);
   спека отдельно для чтения.

## 4. Риски и меры (по AGENTS.md)

| Риск | Мера |
|---|---|
| Исчерпание бюджета публичной кампании кем угодно → демо недоступно всем | Конечный budget/max_grants policy; rate-limit (`too_many_attempts`) сохранён; stop/pause/rotate админом; ops-политика: новая конечная кампания без сброса прежнего usage/ledger + мониторинг панели `/admin/demo-campaigns` (issued/active grants, расход, доля отказов) |
| Rotation пары | Пара только в env (не в коде): rotate в админ-панели + обновление env + редеплой; `credential_version` поддерживает rotate; старая пара перестаёт входить сразу |
| Утечка credentials | AC22: ни одна ссылка не несёт пару в URL; пара ходит только в теле POST (как и сегодня); формы `autocomplete` сохранены |
| Абьюз самозапуска (много устройств) | Существующие границы: max_grants, campaign budget, `participant_max_sessions`, cleanup/leave, конечность кампании; уникальность человека НЕ декларируется (BOUNDARY-01 сохранён в спеке) |
| Пивот `/dashboard` при недоступном API | Fail-closed: `unavailable` → сообщение без автопереходов; `anonymous` → canonical `/login?return_to=/account`; никаких переходов по умолчанию «/» |
| CSP/iframe | `target="_top"` на «Вход» сохранён — согласован с `frame-ancestors 'self'` на `/login` (иначе переход внутри iframe был бы заблокирован CSP) |
| robots → индексация | На `/demo` нет секретов; enter — POST; noindex-метаданные /account /login не трогаются; `no-referrer` сохранён |
| Поломка при пустом env в production | Кнопка disabled с честной пометкой (никаких молчаливых fallback-пар в бандле); форма кампаний работает независимо |
| Регрессия контракта | API/registry/check_routes не меняются; гейты auth (в т.ч. cert-набор) запускаются для подтверждения неизменности; changes только в UI-компонентах/страницах/спеках/тестах |
| Тесты как контракт | Обновляются ровно те ассерты, чьё поведение легально изменилось; новые сьюты фиксируют новое поведение (публичный запуск, пивот, 4-й бейдж) |
| worklog/история | worklog-файлы не ревизируются (история задач), запись добавляется новой секцией |

## 5. Операционные шаги (после мерджа, вне кода)

1. Создать публичную кампанию существующей админ-процедурой
   (`/admin/demo-campaigns`/CLI): конечное окно, budget/max_grants под
   подтверждённую мощность, `allow_upload`/retention по политике.
2. Для VM задать публичную campaign-пару `NEXT_PUBLIC_DEMO_LOGIN`/`NEXT_PUBLIC_DEMO_PASSWORD`
   в `deployment/cisstat-stack/.env`; Compose передаёт её как build args web-образа.
   Выполнить `docker compose build web` и `docker compose up -d --no-deps web`.
   Runtime env без пересборки не обновляет browser bundle. Для отдельно размещённой
   embedded-оболочки задать те же переменные при её Next build. Личные/admin/API secrets запрещены.
   Оставленные пустыми значения честно отключают публичную кнопку.
3. Проверить путь: `/demo` → «Запустить демо-режим» → `/upload` (полоса
   DemoLimits) → resume после перезагрузки → leave.
4. Rotation-процедура: rotate в панели → обновить env → редеплой.

## 6. Критерии приёмки

- [ ] «флаер» отсутствует в UI-копии обеих оболочек, админ-панели, сообщениях ошибок, тестах, spec_auth.md (кроме исторических worklogs);
- [ ] ProductHeader: «Демо» → `/demo`; «Вход» → `/dashboard`; иконки User нет;
- [ ] `/dashboard`: authed → `/account`, anonymous → `/login?return_to=/account`, unavailable → fail-closed;
- [ ] `/demo` (обе оболочки): лендинг с условиями + запуск без регистрации + форма кампании + resume/leave;
- [ ] `/navigator`: 4-й бейдж «Попробовать в демо-режиме» → `/demo`, сетка не ломается;
- [ ] robots `/demo` = index, noindex /account//login//dashboard не тронуты;
- [ ] API-роуты/registry/check_routes без изменений; затронутые jest-сьюты зелёные; typecheck зелёный;
- [ ] credentials нигде не в URL; публичной пары нет в коде репозитория.

## 7. Сертификация на 53ebba5

Акт, точные доказательства и ограничения: `docs/kabinet_demo_cert/report.md`.
Retention — срок удаления результатов; по окончании демо доступ к ним закрыт AUTH-16.
AC22 допускает только утверждённую публичную campaign-пару в browser bundle; это не personal credential.
Для Task7 архив обязан включать page/dashboard и свой manifest, иначе поставка неполна независимо от tests в исходном checkout.
