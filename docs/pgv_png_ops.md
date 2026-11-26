# PGV-PNG-OPS — missing worker credential и честные отказы экспорта

Дата: 26.11.2026 (Москва). База: `20b835b8bd3a8f57f8a454bbcba8752cb689e6d7`.

## Факты и проектирование

Оператор подтвердил transport live PASS релиза3517969. Новая диагностика VM:
четыре конкретных request_id имеют visual_export_unexpected_error с типом
AuthHTTPException; PNG jobs отсутствуют; worker_credential.state=missing;
worker включён, last_run_at=null,289 последовательных worker_service_unavailable.
Print renderer UDS/browser/fonts/bundle/smoke ready. Первичные причины предыдущего
среза (freeze upload/revision0) в базе исправлены.

Локально с PostgreSQL воспроизведено вторичное искажение: штатный429
concurrency_exceeded перехватывается общим except маршрута и превращается в503.
На VM установлен **другой** штатный отказ:503 worker_service_unavailable из-за
отсутствующего credential. Старый native harness заранее выдавал ключ, а
transport-gate не проверял admission очереди; его PASS не доказывал готовность
авторизации worker. Security-audit показывает разрешение run, не credential.

План/риски до кода:

1. RED на missing credential в настоящем API/PG: безопасный доменный код,
   очередь и reservation не создаются. Контроль после официального bootstrap
   credential → queued, исполнение/выдача и освобождение слота. Отдельно429.
2. Сохранять только доверенный AuthHTTPException в обоих PGV orchestration
   маршрутах. Не выпускать произвольный HTTPException upstream; общий
   неожиданный отказ остаётся безопасным503. В UI разбирать flat/error/detail
   и объяснять service configuration и concurrency раздельно.
3. Host CLI check/repair: только metadata inspect и safe health; реконструировать
   **фактические ordered Compose inputs**. Зарегистрировать ключ через существующий
   bootstrap ensure; при missing сгенерировать новый прямо в закрытый.env без
   чтения/вывода других значений. Не передавать ключ в argv/stdout/JSON/логи.
   Не ротировать revoked/expired/invalid автоматически. Только явный repair.
4. API recreate с теми же image/pins/project/overlays, без build/pull/volume
   удаления; renderer не переключать. Проверить новый успешный worker cycle.
   Holds/лимиты/jobs не чистить и не освобождать принудительно.
5. Гейты/AUTH00/builds/worklog/task-only ZIP. Новых HTTP/DDL не требуется.

Операторский скрипт не считается запуском на VM до получения его результата.
Локальный renderer protocol double проверяет транспорт/публикацию/учёт,
не заменяет Chromium/visual/UDS certification. PGV-CERT не заявляется.

## Реализация и локальные результаты

Две ветки except AuthHTTPException в documentation.py сохраняют доверенный
штатный отказ. Непредвиденный upstream HTTPException по-прежнему503 без
его текста. Shared UI parser normalizes flat/error/detail, не принимает
объекты/массивы как message/code; два клиента используют его и объясняют
worker/concurrency/quota/auth отдельно. Новых endpoints/DDL/authority bypass нет.
Host CLI дополнен preflight `compose config --images api`: несовпадающий pin
останавливает операцию до one-off bootstrap или recreate. Полный config/env
не запрашивается. Все операции используют active ordered inputs.

TDD-протоколы — scripts/pgv_png_ops/protocols. RED API8F/6P; native1F/1E
при4tests (detail отсутствует,429 маскируется); UI отсутствующий shared parser;
operator CLI отсутствует. GREEN API16/16 (включая2 safe-upstream negatives),
UI30/30 (3 suites), host operator7/7, native PostgreSQL16.2 TCP/UTF8 4/4,
skips0, leftover DB=[]. В native выполнены bootstrap и настоящий AUTH13 worker
с isolated child/PNG client, публикацией и авторизованной выдачей bytes;
renderer HTTP protocol double возвращает фиксированный PNG1x1. Это проверка
lifecycle/учёта, не настоящего Chromium или качества визуализаций.
Регресс существующих PGV09/09fix/10/11/12/13/15/16:252/252.

Обе Next production builds PASS (embedded20/standalone27); renderer tsc PASS.
Для Next применён штатный offline font-response hook с настоящими локальными
Inter5.3.0; hook/fonts/dependency manifests не менялись и в ZIP не входят.
Зависимости установлены в этом checkout, workspace imports ведут к новым UI
файлам. Полный Jest/scientific suite/Windows/PG18/remote CI не заявляются.

AUTH00/check_routes:285 API,289 bindings,669 entries, added/missing=[].
HTTP методы/пути/dependencies/policy/admission прежние. Обработчики двух
POST изменены; карта обновлена по fingerprints и24 сдвигам evidence lines,
без семантических изменений entry. Reviewed источники дополнены явным review.
Default local_gates pgv-png и Ubuntu/Windows CI contracts включают новые API,
operator и UI tests; native остаётся opt-in/strict. VM worker check вынесен
в обязательный операторский pre/post rollout шаг, поскольку transport его
не покрывает. Окончательные INDEX/ZIP delivery результаты — в worklog12.
