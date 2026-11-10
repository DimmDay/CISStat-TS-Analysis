# AUTH-17 — приёмка

База201a3b1f12eac55525fb07301b5e37f8e962d938. Source INDEX не менялся; strict gate проверял отдельный GIT_INDEX_FILE. GitHub/VM не изменялись.

| Проверка | Результат / протокол scripts/auth17/protocols |
|---|---|
| TDD RED | Missing team_contract, red.txt |
| Portable contracts | 4/4, unit.txt |
| Native AUTH-17 | 17/17 zero skips, native.txt |
| Native session/MFA/Account/demo regression | AUTH-04:42/42, AUTH-05:24/24, AUTH-08:24/24, AUTH-16:13/13; native-regression.txt |
| Default local gates | 20/20 PASS, default-gates.txt |
| Full Jest | 2870 passed,2 штатных skipped;260 suites passed,0 failures |
| New UI contracts | 5/5, ui.txt |
| Renderer/TypeScript обеих оболочек | PASS в default-gates.txt; typecheck.txt |
| Deployment contracts | 17/17, deployment.txt |
| Actual routes | API266/266, registry270, inventory638; routes.txt |
| Production builds | PASS, build-all.txt |
| Clean ZIP overlay strict INDEX/actual ASGI | PASS, overlay.txt (включая CRLF Dockerfile в INDEX при LF WORKTREE) |
| New Python Ruff/diff whitespace | PASS |

Native proof: настоящие PostgreSQL stores/SQL locks, две конкурентные выдачи последнего seat, same-token race/replay, payload/CAS conflicts, current inviter/status/target binding, verified-email ambiguity/no identity creation, no GET consume, anonymous/key/CSRF/extra-payment-claim denial. Прямой SQL по последнему OWNER/последнему месту/history deletion закрыт. Role transfer concurrency имеет одного победителя; audit fault откатывает роли/SIDs/pending invites. Removal→rejoin не оживляет SID; API-key terminal revocation выполняет неизменный AUTH-10 membership trigger. Реальный admin+MFA Member не OWNER; switch сохраняет исходные MFA/family/auth_time/absolute deadline, старый SID отзывается, HTTP очищает CSRF/research pointer. Seat pending intent не меняет capacity; trusted confirm idempotent; increase/decrease/churn сохраняют exact AUTH-12 budgets/postings с ненулевыми spent50/reserved100.

Нативный PostgreSQL16.2 локальный; PG18/Windows выполняет CI-матрица, здесь не заявляются. Полный scientific pytest/AUTH-CERT/browser E2E не запускались. Docker engine/VM images не собирались здесь; frontend production builds не подменяют Docker build. Научные kernels/dependencies не менялись. AUTH-16 regression содержит прежние best-effort artifact producer-key409 warnings, scientific pipeline проходит; это не сертификат document export.

До AUTH-18 нет provider quote/checkout/price/proration/paid credit. Pending requests применяет только trusted operator после внешней проверки основания; никакой browser payment_confirmed не открывает места. AUTH-17 не начисляет CU. До AUTH-19 нужны существующие personal credentials и активный Account; email accept только с unique verified contact, есть UUID fallback. Не включены SMTP и автоматическое создание identities. Existing seats при миграции не объявляются доказанной исторической оплатой. Полный operational запуск остаётся отдельной приёмкой.

ZIP task-only, точный список files.txt; packager проверяет base, пути, CRC, каждый payload byte и SHA256, копирует журнал и VM-инструкцию в download/. Роуты изменены после explicit review, frozen source hashes обновлены, strict INDEX и CRLF Dockerfile portable guard сохранены.

Финальная UI проверка добавляет запрет показывать personal trial OWNER кнопку выхода с последнего OWNER места. После неё повторены strict AUTH-00 + весь Jest/renderer/typecheck (final-gates.txt) и обе production builds. Остальные18 default gates и120 native tests относятся к тем же backend bytes.
