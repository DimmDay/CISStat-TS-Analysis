# AUTH-KABINET-DEMO — сертификация TASK-1…TASK-7

База53ebba5525814f6622774e86da319b274ef27946. В spec_auth_architecture.md нет Task1…Task7: там AUTH-00…25. Предмет запроса — семь TASK из явно указанной spec_auth_kabinet_demo.md; общий архитектурный план и AUTH-AC используются как ограничения, а не как повторная сертификация всего AUTH.

Процесс: source review → независимые негативные/развёртываемые oracles → RED для найденных дефектов → минимальные исправления → GREEN/регресс/AUTH-00 → production builds и браузер с собранными оболочками → акт с границами → task-only ZIP/clean-base overlay. GitHub только read; commits/push/VM запрещены.

Точки: publicDemoCredentials/DemoEntry/DemoLanding, navigator, header/pivot и metadata двух shells, Docker/Compose build config, спецификации/работы/route inventory. Backend authentication/migrations/budgets/registry не меняем.

Предварительные findings:
- F01: build-time NEXT_PUBLIC pair не передаётся Compose→Docker build; runtime .env не меняет browser bundle. Обязательны explicit optional build args; пустые defaults сохраняют disabled состояние. Проверяем реальный browser bundle, а не только grep.
- F02: лендинг обещает доступ к результатам после окончания демо до retention, хотя AUTH-16 запрещает все операции на exact expiry. Retention — срок удаления, не продление доступа.
- F03: спецификация и worklog направляют VM-оператора в Vercel; актуализировать нормативный runbook, историю не переписывать.
- F04: абсолютное AC22 «никаких credentials в bundle» конфликтует с утверждённой публичной campaign-парой. Уточнить исключение для неё; личные/API/MFA/OIDC secrets остаются запрещены. Никогда не использовать personal/admin пару в NEXT_PUBLIC.

Риски: публичная пара намеренно публикуется в JS; budget/window/max_grants/throttle остаются серверными. Reset usage недопустим: ротация/новая кампания сохраняют историю предыдущей. Внешний HTTPS browser smoke с protocol stub проверяет UX/transport, не объявляется доказательством auth authority; SQL/expiry/quota проверяются отдельно на настоящем PostgreSQL. Настоящие production credentials не читаются и не создаются.
