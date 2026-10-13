# AUDIT-CERT — акт сквозной приёмки контура «Прогресс»

Дата: 2026-10-13. База: `2a4cd6cf3cca02e09c9746a5bc7d3ca7b9a1d1b3`.
Основание: `plan_progress_audit.md §19–20`, `spec_progress_audit.md`,
контракт `docs/progress_audit_contract.md` по аддендум v1.6-6C включительно.

**Вердикт: новые локальные acceptance-контракты PASSED; полная приёмка OPEN.**
Реализованы интеграционные/UI/store-оракулы, проверка живучести, матрица
P01–P25/H01–H30/F01–F17 и протоколы. Исправлен обнаруженный при приёмке
дефект атомарности Memory. Нельзя ставить «production certified» или
объявлять весь pipeline завершённым: свежий real-store прогон,
Next/Docker build и эксплуатационные H29/H30 не закрыты. В полном
регрессе остаются падения базы.

## Проектирование, точки изменения и риски

1. Проверить точный HEAD, чистоту базы и `AGENTS.md`; изучить последние
   AUDIT-6B/6C/CERT записи, producers, ledger/outbox, context guards,
   projection, consumers и React delivery.
2. До изменения продукта выполнить базовый и полный регресс, сохранив
   прежний отрицательный корпус. Acceptance-ожидания брать из принятого
   контракта, не из исходного скрипта, который фиксировал дефекты.
3. Создать свой CSV и HTTP-сценарии через полный API; использовать
   persisted event ids и receipt как независимые свидетельства. Для
   исходов коррекций дополнительно подавать заданные факты результата:
   это проверяет интерпретацию, не математический алгоритм.
4. Проверить cache/DB/artifact отказы, concurrent duplicate, три
   поверхности отчёта, затем отключить семь защит из §19. Требовать
   поведенческого assertion failure своего оракула; import/collection/
   TypeScript ошибки не считать обнаружением дефекта.
5. Обнаруженный дефект исправить RED→GREEN, выполнить адресную и полную
   регрессию; не менять прежние оракулы под реализацию. Открытые gates
   вынести отдельно от локальных успешных проверок.

Риски и ограничения: Memory не долговечно после перезапуска; новые
HTTP fixtures изолируют фабрики/файловые каталоги и отключают фонового
worker; Redis-поведение отказа моделируется копированием сессии, не
ссылочной мутацией. PG runner работает только со своей временной БД и
не использует внешнюю DSN. Ни production restart, ни deployment не
выполнялись. Browser-only очередь остаётся ограничением AUDIT-2B.

## Наблюдаемая хронология и новый дефект

| Шаг | Подтверждённое наблюдение |
|---|---|
| T0 | Синхронизация с указанным `2a4cd6c`; рабочее дерево чистое. Commit/push не выполнялись. |
| T1 | Минимальное ядро: 175 passed. Полный исходный Python-корпус: 3408 passed / 99 failed / 61 skipped / 3 errors. Jest базы: 169 suites / 2005 passed. |
| T2 | Новый outbox failure test на неизменённом продукте: 2 failed / 2 passed / 4 PG skipped. Отказ ДО и ПОСЛЕ регистрации менял run.target=stock вместо сохранения flow, несмотря на отсутствие receipt. |
| T3 | Исправление: подготовка событий/чекпоинтов/receipt до публикации, общий RLock для store/outbox, rollback outbox. Новые Memory-оракулы GREEN, включая отсутствие событий/чекпоинтов/receipt/task и повтор с watermark=1. |
| T4 | Все семь обязательных мутаций и дополнительная на rollback outbox обнаружены своими поведенческими оракулами; 8/8, ошибок запуска вместо assertion нет. SHA256-restoration и контрольные прогоны зелёные. |
| T5 | Новые локальные проверки: 23 passed / 4 PG skipped; React: 3 passed. Полный финальный Python-корпус: 3431 passed / 99 failed / 65 skipped / 3 errors, перечень 102 отрицательных test ids точно равен базе. |
| T6 | Jest: 170 suites / 2008 passed. Typecheck embedded+standalone PASS. Py_compile изменённых Python-файлов, полный API import с psycopg и HTTP health smoke PASS. Next build обоих приложений блокируется Node ENOENT без участия прикладного кода. |

**F-CERT-01 (исправлен).** `MemoryResearchRunStore.commit_event_batch`
публиковал run/events/checkpoints до `MemoryDeliveryOutbox.register`.
Исключение этой операции оставляло частичный commit без receipt. Кроме
того, независимый lock outbox не давал общей границы видимости.
Подтверждение — собственные fault-тесты, а не чтение комментария о
транзакционности. Изменены только `apps/api/research_runs.py` и
`apps/api/delivery_outbox.py`; внешние DTO/статистические алгоритмы не
менялись. Реальный PostgreSQL-код не изменён.

Решение: подготовить новые списки без мутации опубликованного состояния;
создать receipt; зарегистрировать обязательство внутри rollback-контекста
outbox под общим RLock; затем опубликовать подготовленный batch. При
отказе регистрации, в том числе после записи task, остаётся прежнее
состояние. Это гарантия атомарности в процессе Memory, не дисковая
долговечность. Дополнительные копии нужны для безопасной публикации;
оптимизация Memory под высокие нагрузки не сертифицирована.

Первое тестовое ожидание слова «устаревший» в отчёте было уточнено до
принятого шаблона «исторический факт: другой контекст расчёта». Это
исправление формулировки нового оракула, **не** RED-дефект продукта;
из него не выводится результат RED→GREEN.

## Сценарии §19

Полная адресная трассировка находится в
`docs/progress_audit_cert_coverage.md`.

| Обязательный сценарий | Свежая проверка / результат |
|---|---|
| Singleton upload/demo, ambiguity, manual | Собственный CSV; один shared id, auto/system; ambiguity без выбора; manual=user. PASS. |
| Auto→conversion→clear→raw restore→manual | Реальная convert-types; session/run/mentor согласованы; cleared цель не воскресает; raw/revision=0; прежний done stale; новый manual. Отдельно auto restore без нового choice. PASS. |
| Report A→upload B; same run иной target/revision | Четыре endpoints: 422 формы, 409 old run/context без новых фактов, target сменён HTTP; ревизии дополнительно A-c. PASS для strict v2, legacy имеет границу. |
| Duplicate/lost receipt/concurrent duplicate | 12 конкурентных commit из 6 потоков в Memory; один batch/receipt/outbox. Отказ cache даёт committed_projection_pending; retry тот же receipt; recovery дважды — один эффект. PASS Memory; PG SKIP. |
| EDA done→GET→remount/seed failure/target | Реальные GET не понижают done; pending карты того же context защищены; новый target stale→новый pending current. UI-3 покрывает seed failure и remount в jsdom. PASS локально. |
| >1000/reverse/equal clocks/Forecast merge | 1007 одинаковых clock-фактов плюс ранние решения, reverse ts, два независимых Forecast actions и зеркала. Status/start/watermark/identity сохранены. PASS. |
| Clean/no-op/partial/invalid | Три независимых факта с фиксированными исходами; count/reason/source согласованы, invalid статус не меняет детали. A-4 даёт адресный correction/методический регресс. PASS. |
| Job start/cancel/late completion, метод | Реальный ETS tuning job: in_progress→pending; step отменённого job 409, старый после смены цели 404 без нового факта; mentor phase=modeling. P19 проверяется реальным IQR→zscore тестом A-7a на том же count. PASS. |
| Cache/DB/artifact/crash recovery | Memory + настоящий файловый слой: отсутствие ledger даёт incomplete panel/503 consumers; отсутствующий snapshot не обещан; staged orphan удаляется повторяемым sweep. Cache receipt/recovery проверен. Настоящие PostgreSQL crash/restart tests этого запуска **OPEN**. |
| MD/HTML/mentor/panel один watermark | На одном committed corpus совпадают watermark, origin, stale и event ids; mentor observation не добавляет исследовательский факт. PASS. Advisory незафиксированный layer1-хвост не объявляется такой гарантией. |

После полного регресса HTTP-оракул Modeling дополнительно усилен
проверками mentor phase и отклонением позднего step. Повторный прогон
всех новых Python-контрактов: те же 23 passed / 4 skipped; продукт после
полного регресса не менялся.

## Живучесть и восстановление исходников

Кампания: `scripts/prograuditcert_mutations.py`; машинный результат:
`scripts/prograuditcert_mutation_results.json`.

| Мутант | Собственный поведенческий оракул | Итог |
|---|---|---|
| MC1: выключен clear reducer | Auto→convert→clear→restore | KILLED |
| MC2: выключены v2 run/context guards | Четыре карты, old context/run | KILLED |
| MC3: выключен report-id dedup Memory | Повтор карты требует прежний receipt/ноль событий | KILLED |
| MC4: Forecast получает новый id при чтении | Два исходных id и размер полного корпуса | KILLED |
| MC5: projection читает только capped layer1 | Ранние статусы/position/start при >1000 | KILLED |
| MC6: 200 без receipt считается delivered | React: accepted_legacy и delivered=false | KILLED |
| MC7: выключена EDA context protection | Done после GET и pending seed того же context | KILLED |
| MC8: выключен rollback outbox | Отказ ПОСЛЕ реальной register не оставляет task | KILLED |

Каждый source anchor уникален; subprocess свежий; kill требует
ожидаемого assertion failure конкретного оракула, errors=0. До/после
кампании контрольные каналы PASS. Все 7 затронутых файлов восстановлены
побайтово по SHA256. Продуктовые изменения финала — только два файла
исправления F-CERT-01; мутанты не поставляются.

## Окружение, регресс и сборка

Python 3.12.14; pytest 9.1.1; FastAPI 0.143.0; pandas **runtime 2.3.3**;
numpy 2.5.3; statsmodels 0.15.0; psycopg 3.3.6; pgserver 0.1.4;
Node 24.19.0. API-зависимости предоставлены через локальный PYTHONPATH,
npm lockfile установлен `npm ci --ignore-scripts`. Реальные версии импорта
и отдельно найденная distribution metadata сохранены: metadata pandas
в этом окружении отличается от версии импортируемого модуля.

| Проверка | Результат |
|---|---|
| Новый HTTP+store корпус | 23 passed / 4 PG skipped |
| Новый React корпус | 3 passed |
| Адресный Progress+core+consumers корпус | 805 passed / 40 skipped / **1 baseline failed** |
| Full Python база | 3408 passed / 99 failed / 61 skipped / 3 errors |
| Full Python финал | 3431 passed / 99 failed / 65 skipped / 3 errors |
| Дельта отрицательных test ids | **0 новых, 0 исчезнувших**, 102 ids равны базе |
| Full Jest база→финал | 169→170 suites, 2005→2008 passed, failed=0 |
| Typecheck embedded+standalone | PASS |
| Python compile, psycopg import, полный API/HTTP health | PASS |
| Next build embedded и standalone | **BLOCKED**: Node `uv_resident_set_memory`, ENOENT |
| Docker image build | **НЕ ВЫПОЛНЕН**: Docker отсутствует |
| Свежий live PostgreSQL | **НЕ ВЫПОЛНЕН**, 4 новых contract tests SKIP |

Отрицательный baseline не скрыт. В нём отсутствуют optional runtime
библиотеки Prophet/TBATS/CatBoost/LightGBM/XGBoost/neural, есть проверки
среды/fixtures и subprocess-зависимостей. Конкретно Progress-падение:
`tests/api/test_progress_audit_6c.py::TestModelsDispatchDegradation::test_light_env_reload_imports_and_degrades_honestly`:
его exact-set ожидание не учитывает дополнительные отсутствующие
модельные библиотеки этой среды. Это существующее воспроизводимое
падение; тест не переписан и не исключён из общего прогона.
Совпадение ids доказывает отсутствие новых наблюдаемых регрессий в
данном корпусе, а не отсутствие любых дефектов приложения.

Next build останавливается до компиляции на чтении памяти Node.
`node -e 'console.log(process.memoryUsage())'` воспроизводит то же
ENOENT без Next/приложения. Подмена этой метрики/гейтов не выполнялась.
Typecheck не заменяет завершённую production build.

## Открытые gates и минимальная повторная приёмка

| Gate | Что требуется для закрытия |
|---|---|
| G-PG | Запустить `python scripts/prograuditcert_pg_runner.py tests/api/test_progress_audit_cert_store.py tests/api/test_progress_audit_6a.py tests/api/test_progress_audit_6b.py tests/api/test_progress_audit_6c.py -q` от обычного пользователя в тестовой среде с pgserver/psycopg. Требуется зелёная реальная concurrency/rollback/restart/fault половина. Runner не создаёт OS accounts, не меняет permissions родительских каталогов и не принимает production DSN. |
| G-BUILD | В полноценной Node/Docker среде: `npm run typecheck:all`, `npm run build:all`, `docker build -f apps/api/Dockerfile .`. Затем startup required на тестовой PG/Redis без fallback. |
| G-REGRESS | Повторить полный Python-корпус в установленном API/model runtime с необходимыми fixtures; закрыть либо отдельно согласовать оставшиеся отрицательные baseline gates. |
| H29 | Разрешённые read-only backend/boot/migration metadata и известный run/raw file между уже произошедшими restart. Здесь нет соответствующего доступа. |
| H30 | Уже существующие request/correlation-id логи response→read→commit и UI observation; никаких искусственных production-сбоев. Здесь нет доступа. |

Прежние акты AUDIT-6A/6B/6C о настоящем PostgreSQL — **исторические
свидетельства**, не свежий результат настоящего прогона. Их успешные
показатели не перенесены в таблицу текущих результатов.

P09/P22 advisory, legacy write compatibility, browser queue lifetime,
raw restore без snapshot replay, PROGR-23 cap/«Исправлено» и
stale-производные остаются явными границами принятых контрактов.
Не заявляются backup/retention, нагрузка нескольких инстансов,
полная статистическая корректность всех методов и production readiness.

## Поставка

В ZIP — только новые/обновлённые файлы этой задачи с репозиторными
путями. `worklog/worklog9.md` и контракт дополнены; прежние записи и
исходный audit JSON не редактировались. Список и SHA256 файлов —
`manifest.json` внутри ZIP. Протоколы: `scripts/prograuditcert_protocol.json`,
`scripts/prograuditcert_protocols/`; отрицательный baseline и дельта
прилагаются целиком. Commit/push/deploy не выполнялись.
