# Акт сертификации AUTH-KABINET-DEMO TASK-1…TASK-7

Дата:16 ноября2026, Москва. Исходная база53ebba5525814f6622774e86da319b274ef27946.

Предмет: семь TASK спецификации spec_auth_kabinet_demo.md. В spec_auth_architecture.md они не пронумерованы Task1…7: AUTH-01…07 — другой набор работ. Общий план/ARCH/RP/AC используются как ограничения и регрессионные gates. Этот акт не заменяет общий AUTH-CERT и не утверждает приёмку всех30 AC/production-нагрузки.

## Метод и независимые доказательства

AGENTS выполнен: checkout exact base/read-only GitHub; требования/история/код; дизайн и риски design.md; RED/GREEN; source/INDEX/route checks; production builds; task-only ZIP с manifest/CRC/byte verification. Не было commit/push/изменений VM.

На исходной базе выявлены F01…F04 ниже. Поэтому исходная поставка без исправлений **не сертифицирована для VM-цепочки**. Повторная приёмка относится к базе + данному overlay, с результатами protocols.

| TASK | Объект | Oracle и статус |
|---|---|---|
| 1 | Публичный запуск, форма, resume/leave, условия, admin copy | Shared UI/transport tests; реальные compiled SSR/JS shells + HTTPS/proxy, пары только в body; missing/partial pair disabled; native AUTH15/16 для authority; F01/F02 исправлены |
| 2 | 4-й badge, anchors, desktop/mobile grid | NavigatorHero tests (4 карточки, md:2/lg:4) + compiled /navigator markup обеих оболочек; реальная viewport-геометрия не подтверждена |
| 3 | ProductHeader и /dashboard | Header tests, AuthProvider+pivot4 состояния, compiled standalone markup и AuthProvider/Jest: loading/authed/anonymous/503; client E2E не подтверждён; noindex/no-referrer /dashboard; legacy nested route не удалён |
| 4 | Embedded /demo | Тот же DemoLanding; metadata index/follow/no-referrer; compiled embedded HTTP/JS и обе production builds |
| 5 | Контрактные/негативные тесты | Восемь адресных suites; добавлены реальный env-helper без mock и loading oracle; отсутствие входа по503 сохранено |
| 6 | Согласованная нормативная копия | spec_auth §20/AC22, VM deployment/rotation в spec_auth_kabinet_demo; F03/F04 исправлены, история worklog не переписывается |
| 7 | Проверки/поставка | Новый local/CI gate, независимые SQL/browser/route/build проверки, manifest из фактических путей и ZIP exact bytes; clean-base overlay с Windows CRLF |

## Findings и исправления

- **F01 (блокирующий VM):** NEXT_PUBLIC пары не было в Docker ARG/ENV/Compose build args. Одно изменение runtime .env не изменяло бы JS. Добавлены optional build args с пустыми defaults в build-stage; в runtime Compose environment пара не дублируется. В .env.example только пустые значения. Browser smoke намеренно подставляет противоречащие runtime values и проверяет, что побеждает собранный bundle.
- **F02 (ошибочная UX-гарантия):** «результаты доступны после окончания до retention» противоречило hard-expiry AUTH16. Исправлена копия: по expiry доступ закрывается, retention определяет удаление.
- **F03 (неверная эксплуатационная цепочка):** вместо Vercel нормативный runbook теперь описывает .env→Docker build args→web rebuild/recreate на VM. Embedded размещается отдельно, её build-time env задаётся соответствующим оператором.
- **F04 (противоречие спецификации):** буквальное AC22 запрещало credentials в bundle, хотя утверждённый §20 намеренно публикует shared campaign pair. Уточнено только исключение этой public пары; personal/admin/API/MFA/OIDC secrets запрещены. Пара не в URL/storage. Никаких настоящих credentials в тестах/ZIP.

Серверные API routes, resolver, grant/session/expiry/admission, budget, migrations и access_registry не изменяются. Лексическая приёмка касается пользовательской копии; negative assertions и исторические worklogs не являются предлагаемой пользователю формулировкой. Операционный rollover — новая конечная кампания, а не сброс прежнего usage/ledger.

## Границы сертификации

Compiled evidence: production .next обеих оболочек, реальные SSR HTML/static JS assets, HTTPS→Next first-party proxy→controlled HTTP authority stub. Это проверяет build-time pair/markup/transport, **не подменяет backend authority или client navigation/layout**. Chromium E2E попытки завершились FAIL до открытия страницы: sandbox запрещает AF_UNIX socket в Chromium ProcessSingleton (EPERM). Положительного браузерного вердикта нет. Переключение в http-only явно отражено в JSON протоколов; оно не называется Chromium PASS. Последнее проверяется отдельно существующими native PostgreSQL AUTH06/15/16 suites с настоящими SQL/HTTP/cookies/CSRF/expiry/quotas/races/audit rollback. Test fixtures маркированы synthetic, не реальные public campaign credentials.

Docker daemon/VM/production campaign/configuration не исследовались. Реальные commercial provider/SMTP/OIDC/нагрузка и все30 AC не сертифицируются этим UI-актом. CI Linux/Windows определён workflow, локальная ОС Linux; PostgreSQL16.2, PG18 не запускался. Production activation требует действующей конечной public campaign без admission-кода и корректных allowed_origins. Пустая пара намеренно оставляет кнопку disabled. Само по себе наличие build args не активирует кампанию и не выдаёт бесплатный бюджет.

## Результаты и вердикт

- TDD:3 RED на исходной реализации →5/5 independent deployment/spec contracts GREEN. Whitespace-sensitive assert копии исправлен до финального GREEN.
- Адресный Jest70/70,8 suites; full Jest2902 PASS/2 штатных skips,267 suites PASS/1 штатный skipped suite; renderer build и TypeScript обеих оболочек PASS.
- Native35/35 AUTH06/15/16 +6/6 full AUTH-CERT demo =41/41, zero skips. No-DSN runner exit2 подтверждён.
- Общий regression:29 старых default gates PASS,2 разрабатываемых гейта (new cert oracle/AUTH00 source map) имели промежуточный FAIL; их финальный повтор PASS. consolidated-gates.json честно сводит31/31 по двум фазам, default-gates.txt сохраняет историю. Единого непрерывного31/31 default прогона не заявляем.
- AUTH00:59 tests PASS, strict INDEX PASS; actual API281 == inventory281, bindings285, entries659; added=[]/missing=[]. Обновлён source-review fingerprint, API/page набор unchanged относительно53ebba5.
- Обе production builds с synthetic public pair PASS; SSR и реальные JS assets подтверждают compile-time значения вопреки конфликтующим runtime значениям. Дополнительная standalone production build с пустой парой PASS: disabled SSR и отсутствие fixtures в реальных JS assets, вопреки runtime override (http-standalone-disabled.txt).

**Вердикт: TASK-1…TASK-7 приняты по заявленным contract/native/build/compiled-HTTP проверкам только вместе с этим исправляющим overlay.** Положительная визуальная/client browser-E2E сертификация не выдана: Chromium заблокирован средой до старта. Ручная после-deploy browser проверка и реальная campaign/VM конфигурация остаются эксплуатационной приёмкой (deploy.md), а не замаскированным PASS. Новая публичная кампания не активирована в этой сессии. Backend guard/budget не ослаблялись.


## Контроль поставки

Clean checkout exact53ebba5 + candidate ZIP: manifest/CRC/каждый payload byte PASS. Strict INDEX PASS после принудительных CRLF blobs для apps/standalone/Dockerfile и deployment/cisstat-stack/.env.example при LF WORKTREE. Actual ASGI routes281/inventory281/bindings285/entries659, added=[]/missing=[]. Исходный INDEX/HEAD не менялся. Итоговая переупаковка обновляет только protocol/report bytes; packager повторно сверяет полный payload и SHA256. Полный список paths — scripts/kabinet_demo_cert/files.txt. Требуется только web rebuild/recreate; SQL/API image не меняются. Копии акта/worklog/manifest доступны рядом с ZIP.


## Дополнение HOTFIX1 — Windows source encoding (16.11.2026)

После локального прогона тимлида выявлен дефект portability cert tooling: read_text без encoding зависел от Windows locale. На CP1251 воспроизведены UnicodeDecodeError и искажённый русский текст. Все чтения исправлены на UTF-8-SIG; теперь7 tests:5 прежних acceptance oracles +2 portability regression (CP1251 default, BOM+CRLF fixture и ожидаемый FAIL при смысловой подмене). Ассерты не ослаблены. Runtime/API не меняются. Исходный акт дополняется данным hotfix; native Windows CI здесь по-прежнему не запускался, эмуляция не называется native Windows PASS.

Подробный вывод, присланный тимлидом, относится к успешному AUTH00. Traceback failing kabinet-demo-cert отсутствует: кодировочный дефект воспроизведён независимо, но не объявляется доказанной причиной его конкретного прогона. Если FAIL остаётся после hotfix, нужен stdout/stderr именно этого unittest step по инструкции hotfix1.md.
