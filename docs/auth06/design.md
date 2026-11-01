# AUTH-06 — восстановленная поставка

База 8e8f747b376c9b09ec7406996dec2374dc1fdf54. Исходный ZIP и checkout предыдущего прогона утрачены. Это восстановление функциональных изменений по сохранённому контексту с новыми тестами/протоколами; не побайтовая копия прежнего ZIP. AGENTS.md, spec_auth.md §§4/9/13, spec_auth_architecture.md §§5/6/9 и worklog11 приняты как входной контракт.

## Границы и риски

Сохранён дизайн: API — единственный authority; PostgreSQL/opaque sessions/MFA AUTH-04/05 не подменены. Риски: SSRF/open redirect, spoofed identity/forwarded headers, cookie Domain/понижение Secure/HttpOnly, CSRF старых scientific callers после login, повтор mutation, stale context, iframe/third-party cookies. TDD: RED Python CSRF/CORS/DTO, SQL account selection, отсутствующие frontend modules, route collector → реализация → новые GREEN проверки → map/build/package. Первоначальная Node-suite требовала browser-only jest.setup guard; такой инфраструктурный RED не считается проверкой security поведения.

Обе Next apps: force-dynamic Node /api/v1/[...path], 7 exports, один shared handler. API_URL — server-only fixed TLS origin (loopback HTTP только вне production). CISSTAT_AUTH_PUBLIC_ORIGIN — exact HTTPS origin именно этой оболочки. Target не выбирается клиентом/Host/X-Forwarded/NEXT_PUBLIC_API_URL. Generated allowlist только известных API method/path AUTH-00; неизвестные и encoded traversal закрыты. GET restore закрыт на browser proxy, безопасный ownership/restore bridge — AUTH-09. Upstream redirects не follows; Location и произвольные response headers не выдаются.

Request headers и cookies пересобираются: никаких X-Role/User/Subject/Account/Tenant/Permissions/Authorization/Host/X-Forwarded/portal headers. Явный X-API-Key сохраняется для legacy credential paths, backend его проверяет; ENV key не подставляется. Cookies только __Host-cisstat_auth, __Host-cisstat_csrf, отдельный resource pointer cisstat_session_id. Duplicate/invalid auth cookies запрещены. Response cookies разделяются корректно с Expires commas; Domain и ослабленные auth cookies отвергаются. Research pointer приводится к host-only Secure/HttpOnly/SameSite=Lax, включая удаление. Auth cookies не переносятся между origins.

Unsafe requests требуют Origin текущей оболочки, Fetch Metadata и matching CSRF cookie/header до body/upstream. Missing/null/sibling Origin запрещён. CSRF GET без Origin требует X-CSRF-Request:1 + Sec-Fetch-Site:same-origin. API независимо проверяет HMAC/привязку к SID/revoke/MFA/membership; прямой API не обходит AuthN. CORS только exact configured HTTPS origins, без *.vercel.app regex и implicit localhost credentials. SameSite/CORS не заменяют CSRF.

Body чтение ограничено 15 секундами/abort, auth 16KiB, прочие 52MiB; hosting ingress limit этим не увеличивается, существующий upload UI cap 4MiB сохранён. Response streaming, private/no-store/Pragma/nosniff/sandbox CSP. Errors не отражают upstream URL/secrets/exception text. Исходный peer IP не выдумывается из client XFF; API видит BFF peer плюс login/global/subject limits, verified ingress contract для real IP — отдельно.

## Browser transport

Browser getApiBase всегда /api (включая dev). Существующие 63 fetch callers мигрированы на apiFetch без global monkey-patch и без изменения domain payload/response logic. Personal authClient работает только /api/v1/auth. Новые auth commands заранее получают signed CSRF. Старые callers допускают один resend только после reserved local 403 X-Cisstat-CSRF:required: этот header выдаётся до forwarding и удаляется из всех upstream responses. Это не повтор выполненной mutation. Backend error/401/network/timeout/streaming bodies не повторяются. На внешний origin proof не добавляется.

Bootstrap переиспользует валидный proof для текущего SID, при expiry/смене SID выдаёт новый. Параллельный первый выпуск/rotation может дать безопасный отказ с ручным повтором, не расширение прав. Нет положительного auth cache/browser secret storage.

## Login UI и DTO

Общий LoginScreen/AuthProvider в обеих shells: password → ограниченный MFA challenge → enrollment/TOTP либо recovery → server me. Password очищается при submit. Challenge/seed/codes только transient memory, без URL/localStorage/sessionStorage/logging. Recovery codes показываются один раз, скрываются по acknowledgement. Expiry/error не дают authenticated. Путь return_to — finite exact allowlist без query/hash/external/encoded paths. Полный переход после server me очищает scientific client caches. Focus rereads revoke; смена subject/account/SID в другой вкладке вызывает reload. Stale response не восстанавливает logout; 503 — unavailable, 401 — anonymous. UI authority не заменяет API.

Me: Pydantic AuthMeResponse → actual response_model/OpenAPI → generated TS; runtime projection исключает лишние response fields. Login account_id optional: после password/version proof server выбирает единственный active membership/account, либо отдаёт limited own account choices без session/challenge. UI просит повторный пароль при выборе; membership/password проверяются заново. Это не account switch/lifecycle (AUTH-08).

Avatar links ведут top-level /login. В iframe форма credentials не отправляет и предлагает _top переход. Login no-store/noindex/no-referrer, XFO SAMEORIGIN/frame-ancestors self. Cross-origin portal SSO/handoff не заявлен, bearer в URL/postMessage не передаётся. Cookies изолируются разными hostnames, не портами одного hostname. Native named admin APIs/общая админка — AUTH-07, scientific enforcement — AUTH-09/11.

## Конфигурация до rollout

- API: migrations AUTH-05 до 0021, auth DB, CSRF key >=32 bytes, MFA keyring/active key по AUTH-05; новых SQL migrations в AUTH-06 нет.
- API CISSTAT_AUTH_ALLOWED_ORIGINS (или ALLOWED_ORIGINS): exact HTTPS origins двух shells, preview добавлять явно.
- У каждой Next app: API_URL=https://api-host и CISSTAT_AUTH_PUBLIC_ORIGIN=https://именно-этот-app-host. Не NEXT_PUBLIC_, не cookie Domain. Настроить до включения нового shell.
- Dev cookie-auth нужен HTTPS; plain HTTP fallback не открывается. Первый ADMIN — существующий AUTH-05 CLI, default password/public bootstrap не добавлены.

Проверки текущего восстановления — scripts/auth06/protocols. Native PostgreSQL CI отдельно от PGlite wire; Next production/browser certificate не подменяется unit/HTTP adapter tests. Репозиторий/внешние Vercel/Render настройки не коммитятся/не публикуются.

Первичные источники: https://nextjs.org/docs/14/app/building-your-application/routing/route-handlers ; https://cheatsheetseries.owasp.org/cheatsheets/Cross-Site_Request_Forgery_Prevention_Cheat_Sheet.html ; https://vercel.com/docs/functions/limitations .
