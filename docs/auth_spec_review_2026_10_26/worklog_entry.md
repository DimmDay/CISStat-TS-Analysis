# Запись для добавления в актуальный worklog после сверки целевой базы


---

## Task ID: AUTH-SPEC-REVIEW-2 (2026-10-26) — проект обновления аутентификации, ADMIN обеих оболочек и универсального форумного demo

Запрошенная база: 21946a7a80878b7dcbe5a9e57f2fa132208914a6. Fetch требует авторизации; объект отсутствует локально. Пользователь установил GitHub; installed=true подтверждено, но вызываемые GitHub tools/skill в текущую сессию ещё не переданы, повторный fetch также не авторизован. Не заявляется синхронизация на 21946a7. В отдельном detached worktree bee3f8e подготовлена редакция spec_auth.md 2.0-proposed с явным статусом незавершённой целевой сверки; старые рабочие копии не менялись.

Изучены старая spec целиком, Role/Plan/Billing, auth.py/plans.py/AdminProgressDashboard/admin client/embedded admin page/standalone proxy. Наблюдения относятся только к bee3f8e; они не выдаются за проверку 21946a7. Актуальные общие рекомендации сверены с первичными NIST/OWASP (sources §19).

Решения: named ADMIN + MFA/step-up в embedded и standalone; общий backend resolver/UI и first-party session transport; одна общая пара campaign entry на флаере → приватные participant/grant/temporary Account вместо общего владельца данных; immutable bounded grant, hard end кампании, shared finite budget, atomic reservations/idempotency/fencing, admin campaign console, усиленная выдача одноразовых admission codes. Явно признано: общий пароль/cookie/IP не устанавливают уникальность человека; обещание «никогда не получить повторный trial после очистки browser» не даётся. Browser API также можно автоматизировать, поэтому защита — серверные ограничения, не User-Agent.

В документе: assessment прежних тезисов, trust/identity/session/grant модель, admin bootstrap/recovery, UX/API/policy/state/retention, совместимость Role/Account/Seats/CU/identity, этапы AUTH-0…CERT и 30 AUTH-AC. Реализация сервиса не выполнялась. Documentation RED→GREEN 12/12, Markdown integrity и diff checks; software tests/build неприменимы к изменению документа и не заявлены. Review/provenance/checks в docs/auth_spec_review_2026_10_26 и scripts/auth_spec_review_2026_10_26. Поставка имеет статус PROJECT/PENDING TARGET CHECK; после появления GitHub capabilities необходимо завершить AUTH-0 на указанном commit, а не считать задачу полностью закрытой. Без commit/push/deploy.
