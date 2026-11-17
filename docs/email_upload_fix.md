# EMAIL-UPLOAD-FIX — вход по email и загрузка демо

База: main@68430f79389bfc020617a71e15c66985c035f88c. Дата: 17.11.2026 (Москва).

## Воспроизведение и проектирование

Чистый профиль: email OTP → /me → /current → upload проходит на базе.
При сохранённой cookie cisstat_session_id исследования другого аккаунта тот же
OTP-вход проходит (consume=200, /me=200), но /current и upload отвечают 404,
detail.code=scientific_object_not_found, «Объект исследования не найден».
Демо-карточки генерируют File в demoDatasets.ts и вызывают обычный multipart
POST /v1/internal/upload; POST /v1/session/demo к этому клику отношения не имеет.

Причина: password/MFA/demo/account-select очищают research pointer при смене
сессии, а общий _external_result (email/SSO, включая выбор Account) сразу
вызывает _authenticated. Новая личность получает оставшийся указатель;
scientific.preflight корректно закрывает чужой объект до multipart parsing.
Конкретное содержимое браузера/БД заявленного пользователя на VM не исследовано;
синтетический сценарий воспроизводит точно тот же код и сообщение.

Решение: при реально выданной внешней AuthSession использовать существующий
_clear перед _authenticated, как password flow. Сбрасываются прежние cookies
auth/CSRF и research pointer, затем выдаётся новый __Host-cisstat_auth. Ответы
account_required/email_bound/linked и отказы ничего не очищают. Научная
авторизация, владельцы и сохранённые исследования не меняются. Повторный вход
начинает новую рабочую сессию, как password login; trial receipt/expiry/лоты и
израсходованные исследования не обнуляются. Восстановление старого исследования
выполняется только существующим разрешённым механизмом.

Риски: очистка до успешного proof, потеря нового auth-cookie, ослабление
foreign-object 404, повторная выдача бюджета. Все закреплены тестами.

## Проверки

test_personal_demo_entry_pointer.py: реальные auth роуты и CSRF, контролируемый
результат service; OTP/link/selection email, OIDC callback/selection; issued,
dict, denied. Входит в прежний default personal-demo gate.

test_personal_demo_upload_e2e.py: HTTP E2E полного apps.api.main с настоящими
lifespan, PostgreSQL, cookies, CSRF, OTP, аккаунтами, парсингом, квотами и трассой.
SMTP только в памяти, внешних адресатов нет. demo_files.js исполняет реальные
четыре генератора и demoDatasetToFile UI. Сценарии: прежний пользователь →
новый OTP → пустой /current → четыре demo upload → dataset/trace; прежний
объект неизменен, чужой pointer по-прежнему 404 до parsing, квота не расходуется.
Чистый OTP → upload → повторный magic-link → upload не пополняет trial.
Это HTTP E2E с cookie jar, а не визуальный browser click test. Chromium в
среде сессии завершился до страниц: ProcessSingleton socket() EPERM; протокол
browser-environment.txt сохранён. Визуальная проверка остаётся VM smoke оператора.

Прежний personal-demo-postgres runner автоматически обнаруживает новый файл.
CI postgres job устанавливает Node22/npm ci для настоящих UI-генераторов.
E2E очищает process-wide registries прогрева до/после своей disposable DB;
не оставляет последующим suites singleton с уничтоженным DSN.
Native gate требует disposable CISSTAT_AUTH_TEST_DSN, Node>=22 и npm ci.
Без DSN/skips результат не считается PASS. Production DB для тестов запрещена.
Результаты: scripts/email_upload_fix/protocols и worklog/worklog12.md.

## Применение

Распаковать ZIP в корень checkout. PowerShell:

```powershell
git add --pathspec-from-file=scripts/email_upload_fix/files.txt
python scripts/local_gates.py --only personal-demo,auth19,auth06,auth00 --skip-install
python scripts/local_gates.py --skip-install
# Только disposable PostgreSQL:
python scripts/local_gates.py --only personal-demo-postgres --with-personal-demo-postgres --skip-install
```

Commit/push выполняет тимлид. После зелёного CI на VM (.env сохранить):

```bash
set -euo pipefail
cd /opt/cisstat/CISStat-TS-Analysis
git pull --ff-only
cd deployment/cisstat-stack
docker compose build api
env -u CISSTAT_AUTH_MFA_KEYS -u CISSTAT_AUTH_MFA_ACTIVE_KEY docker compose up -d --no-deps api
docker compose exec -T api curl -fsS http://127.0.0.1:8000/health
```

Только api image; web/SMTP/env/схема не меняются, миграций нет.
Уже вошедшему пользователю после деплоя запросить новое письмо и снова войти
по свежему коду/ссылке: успешный новый вход уберёт прежнюю pointer-cookie.
Не нужны очистка БД, переиздание trial или смена пароля.
Операторский smoke: «Вход» → email → код → «Загрузка» → демо-карточка →
превью/«Прогресс». Откат: предыдущий api image (дефект вернётся, данные сохранны).

HTTP methods/paths/DTO прежние: меняется Set-Cookie успешного ответа существующих
email/consume и oidc/callback. AUTH00 review/fingerprints/evidence обновляются
штатным генератором, registry/OpenAPI/proxy прежние.

## Итог приёмки

Pinned native regression96/96 (0 skips), новые HTTP E2E2/2; transport unit20
subcases; personal+auth19 unit31/31; targeted Jest87/87. Четыре выбранных
local gates PASS, AUTH00 unit60/60 и strict INDEX598 PASS. Обе production
Next builds20/27 страниц PASS. Clean-base ZIP overlay: strict CRLF INDEX,
actual ASGI282/286/661 и E2E+unit3/3 PASS. Полный default32-gate, Windows,
PG18, Docker build/VM и visual browser smoke не заявляются.
