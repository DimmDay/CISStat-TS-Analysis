# Акт независимой сертификации PROGR-AUDIT-6C — backend, health и операционные логи

**Дата:** 2026-10-13
**База сертификации:** origin/main@**9f4dc69** (коммит `PROGR-AUDIT-6C`, план
plan_progress_audit.md §18; контракт docs/progress_audit_contract.md аддендум
v1.6-6C §26; база реализации — 8b309eb, коммит PROGR-AUDIT-6B)
**Сертификатор:** независимый раунд (паттерн F-7AC1/F-7BC1: «мутанты на своих
мутантах, оракулы на своих данных»)
**Вердикт:** **PASSED WITH REMARKS** (0 блокирующих; 1 замечание F-6CC1 —
граница паттерн-редакции safe_error; H29/H30 остаются незакрытыми
operational acceptance-пунктами, как честно заявлено реализацией)

---

## 1. Предмет и границы

Сертифицируется РЕАЛИЗАЦИЯ задачи AUDIT-6C в коммите 9f4dc69: режимы хранения
required/advisory (fail-closed P21/F14), драйвер psycopg в requirements и
build-гейты Dockerfile, деградация Modeling dispatch по построению + 503 в
точке исполнения (Донастройка_2 п.2), health-пара /health (liveness) +
/health/ops (operational), операционные логи с ids и safe_error, in-process
worker восстановления (остаток AUDIT-6B), аддендум контракта v1.6-6C §26.

Сертификатор НЕ является автором реализации; корпуса оракулов и мутантов
дизъюнктны корпусу исполнителя (tests/api/test_progress_audit_6c.py) — по
данным, техникам инъекции отказов, методам наблюдения и классам мутантов
(§3, §4). Коммит/push не выполнялись (AGENTS.md). Выкат на Render/Vercel в
сертификацию не входит (план §18).

## 2. Метод сертификации

Три независимых доказательных канала, каждый на СВОИХ данных сертификатора:

1. **Оракулы на своих данных** (scripts/prograudit6ccert_oracles.py, 45
   оракулов, группы G6CC-*). Ключевой принцип дизъюнктности: РЕАЛЬНЫЕ отказы
   вместо monkeypatch-инъекций исполнителя — фабрики получают настоящие
   недостижимые DSN (TEST-NET-3 203.0.113.6 с честным 3-секундным probe-
   таймаутом; порт 1 на loopback — мгновенный ECONNREFUSED) и настоящую
   ошибку конфигурации (CISSTAT_RUNS_BACKEND=postgres при ПУСТОМ
   DATABASE_URL); лёгкая среда моделируется в СВЕЖЕМ интерпретаторе подменой
   importlib.util.find_spec (настоящая причина — отсутствие пакетных спеков
   prophet/statsforecast), а не importlib.reload; живой PostgreSQL поднимается
   pgserver'ом в СВОЁМ tempdir (cisstat6ccert-pg-*) с РЕАЛЬНЫМ оракулом
   состояний миграций (не-мигрированная БД обязана честно ok=False); логи
   перехватываются собственным logging.Handler (не caplog).

2. **RED на базе** (scripts/prograudit6ccert_red_repro.txt): git-worktree
   базы 8b309eb (до реализации 6C) — протокол честного RED.

3. **Мутанты на своих мутантах** (scripts/prograudit6ccert_mutations.py,
   классы CM6CC-1..19, дизъюнктны CM-7A и CM7B): поверхность §26 целиком,
   два канала kill'а (O — свои оракулы; R — repo-сюиты), дисциплина якорей
   sha256 и побайтового восстановления (прецедент 7A-CERT).

## 3. Дизъюнктность корпусов (оракулы)

| Измерение | Исполнитель (test_progress_audit_6c.py) | Сертификатор (G6CC-*) |
|---|---|---|
| Инъекция отказов | monkeypatch from_env/readiness_probe, sys.modules['psycopg']=None | реальные недостижимые DSN, реальная ошибка конфигурации (пустой URL), подмена find_spec в свежем интерпретаторе |
| DSN/секреты | db-host-6c.invalid / supersecret / redispass | pg-cert6c.internal.east / Qx7vLp%21 / t0ken-6cc-777 / CERT-SEC-42 |
| Данные | forecast_monitor_synthetic_n150.csv | hydrogen_plant_monthly_n150.csv (давление/частота) |
| Ids | R6C / op-6c-* / report-6c-* / S-6C* | RUN-CERT6C-* / op-cert6c-* / cert6c-report-77/78 / sid-cert6c-* |
| Лёгкая среда | importlib.reload + подмена PRODUCTION_BACKTEST_MODEL_IDS | свежий интерпретатор + MetaPath-подмена find_spec (настоящая причина) |
| Дрейф dispatch | pop 'ets' | pop 'theta' (свой series) |
| Живой PG | pgserver, tempdir исполнителя; probe подменяется/чистится | pgserver, tempdir cisstat6ccert-pg-*; РЕАЛЬНЫЕ состояния миграций (ok=False на пустой схеме) |
| Логи | pytest caplog | собственный logging.Handler (LogTap) |

## 4. Результаты канала оракулов: 45/45 PASS (в т.ч. живой PG)

Протокол: scripts/prograudit6ccert_oracles_results.txt. На HEAD 9f4dc69 —
**45 PASS / 0 FAIL** (41 без живой БД + 4 живого PG; pgserver поднят, FK-гейт
миграции 0005 соблюдён честно: обязательство ссылается на существующий run).

- **G6CC-MODE (11)** — §26.1. required: реальная ошибка конфигурации
  (backend=postgres, URL пуст) → fail-closed RuntimeError, singleton не
  создан, configured=postgres/effective=unavailable/degraded=True (MODE-1);
  недостижимая БД по РЕАЛЬНОМУ probe (TEST-NET-3, ~3с) → fail-closed (MODE-2);
  опечатка CISSTAT_STORAGE_MODE → fail fast на get_storage_mode и на фабрике
  (MODE-6). advisory: реальный отказ конструктора → ЯВНАЯ деградация
  (Memory + configured/effective/degraded + fallback_events + error-лог без
  DSN; MODE-3, LOGS-3); недоступная БД при advisory НЕ роняет фабрику —
  ленивый контракт конструирования сохранён (пин исполнителя
  test_database_url_selects_postgres_lazily подтверждён с другой стороны),
  недоступность наблюдаема через /health/ops readiness с КЛАССОМ исключения
  (MODE-3b/8b). explicit memory observable (MODE-4), auto честный (MODE-5).
  Redis симметричен: required fail-closed (конфигурация MODE-7, PING MODE-9),
  advisory ЯВНАЯ деградация (MODE-8) + ленивая наблюдаемость (MODE-8b).
- **G6CC-SAFE (5)** — §26.4. СВОЙ враждебный корпус: DSN трёх схем
  редактируются ЦЕЛИКОМ при сохранении содержательной части (SAFE-1);
  password=/token=/Bearer/api_key значения редактированы, ключи сохранены,
  голый хост вне URL-схемы не обещан редакцией в safe_error (SAFE-2 — см.
  замечание F-6CC1); клип 300 + '...' + схлопывание переносов в одну строку
  (SAFE-3); None→'unknown error', пустой BaseException→класс, не-исключение
  →str (SAFE-4); safe_health_error несёт ТОЛЬКО класс исключения — строгий
  уровень: не выживает даже голый маркер (SAFE-5).
- **G6CC-PROBE (3)** — §26.3. probe_store: Memory ok с latency; None →
  честное not_initialized (PROBE-1); три формы «вранья» хранилища (ok=False
  с враждебной причиной / бросок / мусор вместо dict) → ok=False с
  безопасной причиной, проба не роняет health (PROBE-2); backlog_age_seconds
  на СВОИХ обязательствах (~90с наблюдаем; после доставки — честный None,
  PROBE-3; паритет на живом PG — PG-3).
- **G6CC-OPS (5)** — §26.3. /health — ровно {'status':'ok'} и не зависит от
  недоступной БД (OPS-1); GET /health/ops с peek-семантикой: не
  инициализирует фабрики фактом запроса — singletons остаются пустыми, честное
  not_initialized (OPS-2 — мутант CM6CC-15 убит только этим оракулом); форма
  §26.3 целиком + degraded=True при деградации + НЕТ секретов в теле при
  враждебной причине fallback (OPS-3); degraded-агрегация: ok-базлайн,
  degraded по worker consecutive_errors / dispatch not-ready, readiness
  ok=None не деградирует (OPS-4); backlog/возраст/projection lag по СВОИМ
  обязательствам: 2 pending/1 failed/1 delivered → lag=3, возраст ~120с
  (OPS-5; failed-состояние достигнуто честным исчерпанием бюджета повторов).
- **G6CC-WORKER (7)** — §26.5. run_once доставляет СВОЁ pending-обязательство
  из required-карты с одноразовым отказом cache (слой 1 восстановлен worker'ом,
  статус consecutive_errors=0, WORKER-1); идемпотентность второго прохода
  due=0/delivered=0 (WORKER-2); устойчивость: сбой цикла → consecutive_errors=1
  с безопасным last_error, успех сбрасывает (WORKER-3); env-матрица:
  ENABLED 0/false/NO выключает, INTERVAL 0→None, 3→клип к 5, мусор→дефолт
  + warning в логе (WORKER-4); singleton идемпотентен, stop останавливает
  (WORKER-5); lifespan авто-старт/останов через TestClient (WORKER-6); статус
  worker'а наблюдаем в /health/ops (WORKER-7).
- **G6CC-DISPATCH (4)** — §26.2. Полная среда: ready, множества согласованы,
  19 моделей (DISPATCH-1); лёгкая среда в СВЕЖЕМ интерпретаторе (настоящая
  причина — отсутствие спеков prophet/statsforecast): import apps.api.main
  РАБОТАЕТ, /health и /health/ops в маршрутах, деградация честна
  (dropped_by_registry ⊇ {prophet, tbats}, missing=[]) — Донастройка_2 п.2
  закрыта (DISPATCH-2); runtime-дрейф theta → state not ready + 503
  fail-closed В ТОЧКЕ ИСПОЛНЕНИЯ, фиктивные метрики невозможны (DISPATCH-3);
  состояние dispatch видно в /health/ops (DISPATCH-4).
- **G6CC-LOGS (3)** — §26.4. Отказ advisory-зеркала хука: СВОЙ способ
  захвата event_id (хвост слоя 1 сессии внутри отказавшего record_run_event):
  лог несёт event/run/session ids, producer-маркер trace_hook_mirror,
  advisory-ссылку v1.5-6B §25.1, безопасную причину; одна строка, без
  сырого трейса (LOGS-1); отказ задачи доставки: честное исчерпание бюджета
  повторов ПО РЕАЛЬНОМУ backoff-контракту (гейт due: между попытками задача
  НЕ доставляется до next_attempt_at) → state=failed; КАЖДЫЙ отказ в логе с
  operation_id/run_id/kind/номером попытки и safe reason (LOGS-2); отказ
  фабрики advisory: компонент/configured/effective в логе, без DSN (LOGS-3).
- **G6CC-DECL (3)** — §26.2/F14/H29. requirements.txt объявляет
  psycopg[binary]>=3.1.0 с пометкой AUDIT-6C (DECL-1); Dockerfile несёт три
  build-гейта (import psycopg; полный import apps.api.main; ассерты
  '/health' и '/health/ops') (DECL-2); Docker-эквивалент команды ИСПОЛНЕН
  сертификатором: 'psycopg + full API startup OK: 3.3.6' (DECL-3).
- **G6CC-PG (4)** — §26.6 «фактическая долговечность наблюдаема». required на
  ЖИВОЙ БД выбирает настоящий Postgres fail-closed-путём с реальным probe
  (БЕЗ подмен, PG-1); РЕАЛЬНЫЙ оракул состояний миграций: не-мигрированная
  схема → probe честно ok=False, после штатных миграций (0001-0005) → ok=True
  с латентностью (PG-2); backlog age паритет Memory/Postgres на СВОИХ
  обязательствах (~60с → None после доставки; PG-3); worker доставляет СВОЁ
  обязательство на живом PG, событие появляется в слое 1 (PG-4).

## 5. RED-протокол на базе 8b309eb: 2 PASS / 43 FAIL из 45

Протокол: scripts/prograudit6ccert_red_repro.txt (git-worktree 8b309eb; код
AUDIT-6C отсутствует). Команда: `env -u DATABASE_URL -u REDIS_URL
PYTHONPATH=. python scripts/prograudit6ccert_oracles.py`.

- **2 PASS — пины УЖЕ честного поведения базы** (остаются зелёными и на HEAD):
  G6CC-OPS-1 (liveness /health == {"status": "ok"} — совместимость Render
  healthCheckPath) и G6CC-LOGS-3 (advisory fallback при РЕАЛЬНОЙ ошибке
  конфигурации уже логировался с причиной без DSN — spec H21 «Error-лог
  есть»; 6C добавил структурную фиксацию record_backend_fallback).
- **43 FAIL — все новые требования v1.6-6C §26 красные на базе**, в том числе
  ключевые контракты: fail-closed required отсутствует (фабрики молча
  деградируют — P21/F14 подтверждён на своих данных); safe_error/safe_health
  отсутствуют; readiness_probe/backlog_age_seconds не существуют; /health/ops,
  peek-семантика, degraded-агрегация, projection lag отсутствуют; in-process
  worker отсутствует; models_dispatch_state нет; лёгкая среда УБИВАЕТ импорт
  apps.api.main (ASSERT «импорт apps.api.main в лёгкой среде обязан работать»
  — воспроизведён дефект Донастройка_2 п.2); requirements без psycopg;
  Docker-эквивалент падает ('/health/ops' нет в маршрутах); живой PG: все
  требуемые пути отсутствуют.

RED честный: «операция ≠ результат» удостоверена — новый контракт не
выполнялся базой, каждый FAIL имеет причину (ImportError отсутствующей
поверхности 6C либо нарушение контракта §26).

## 6. Мутационная кампания CM6CC-1..19: 19/19 KILLED, ALIVE 0

Протокол: scripts/prograudit6ccert_mutation_results.txt. Дисциплина
прецедента 7A/7B-CERT: sha256-якоря 9 файлов до кампании; побайтовое
восстановление после каждого мутанта (backup + контроль sha256 в finally);
RESTORE-CHECK — все файлы байт-в-байт; контрольные прогоны без мутантов
зелёные (O: 45/45; R: 225 passed / 19 skipped).

| # | Мутант (точка §26) | O | R | Убивающий оракул сертификатора |
|---|---|---|---|---|
| CM6CC-1 | fail-fast режима хранения удалён | KILL | KILL | G6CC-MODE-6 |
| CM6CC-2 | required fail-closed (runs) → тихий fallback | KILL | KILL | G6CC-MODE-1/-2 |
| CM6CC-3 | required probe-гейт удалён | KILL | KILL | G6CC-MODE-2 |
| CM6CC-18 | required fail-closed (session/Redis) удалён | KILL | KILL | G6CC-MODE-7/-9 |
| CM6CC-4 | fallback_events теряются | KILL | KILL | G6CC-MODE-3/-8 |
| CM6CC-5 | URL-редакция safe_error удалена | KILL | KILL | G6CC-SAFE-1/-2/-3 + OPS-3 |
| CM6CC-6 | kv-редакция safe_error удалена | KILL | KILL | G6CC-SAFE-2 + OPS-3 |
| CM6CC-7 | клип 300 удалён | KILL | KILL | G6CC-SAFE-3 |
| CM6CC-8 | safe_health_error отдаёт полное сообщение | KILL | KILL | G6CC-MODE-3b + SAFE-5 |
| CM6CC-9 | degraded игнорирует worker consecutive_errors | KILL | pass | **G6CC-OPS-4 (только O)** |
| CM6CC-10 | projection_lag теряет failed | KILL | pass | **G6CC-OPS-5 (только O)** |
| CM6CC-11 | Memory backlog_age → всегда None | KILL | KILL | G6CC-PROBE-3 + OPS-5 |
| CM6CC-15 | /health/ops инициализирует фабрики | KILL | pass | **G6CC-OPS-2 (только O)** |
| CM6CC-12 | env-выключатель worker инвертирован | KILL | KILL | G6CC-WORKER-4 |
| CM6CC-13 | клип интервала удалён | KILL | KILL | G6CC-WORKER-4 |
| CM6CC-14 | успешный цикл не сбрасывает consecutive_errors | KILL | KILL | G6CC-WORKER-3 |
| CM6CC-16 | исполнительный dispatch-гейт удалён | KILL | KILL | G6CC-DISPATCH-3 |
| CM6CC-17 | ids в логе зеркала хука выброшены | KILL | KILL | G6CC-LOGS-1 |
| CM6CC-19 | psycopg удалён из requirements | KILL | pass | **G6CC-DECL-1 (только O)** |

**Свидетельство силы своих оракулов:** O-канал убил 19/19; repo-канал 15/19.
ЧЕТЫРЕ мутанта убиты ТОЛЬКО оракулами сертификатора — в repo-корпусе
исполнителя нет покрытия контрактов: degraded-агрегация worker'а (§26.3),
failed-составляющая projection lag (§26.3), peek-семантика /health/ops
(§26.3), декларация драйвера в requirements (§26.2). Это самостоятельная
ценность независимого раунда (не претензия к исполнителю — его корпус
покрывал свою нарезку).

## 7. Сопутствующие проверки

- **Регресс:** аудит-серия целиком (s/c/h1/1a/2a/3/4/5b/6a/6b/6c/7a/7b/8):
  **412 passed / 36 skipped** — точное сложение показателей 6C-записи
  (374/32 по 13 файлам без 6c) и оракула исполнителя 6c (38/4); ДЕЛЬТА 0.
  Живой PG исполнителя (scripts/prograudit6c_pg_runner.sh): **42/42** —
  воспроизведено сертификатором до кампании мутаций.
- **Сборка:** py_compile оракулов и мутационного скрипта OK; Docker-эквивалент
  build-гейтов исполнен (G6CC-DECL-3); pgserver-прогоны живого PG OK.
- **Рабочее дерево:** после кампании git status чист (только файлы задачи);
  commit/push отсутствуют.

## 8. Замечания и границы (незакрытые пункты)

- **F-6CC1 (замечание, не блокирует; граница, а не противоречие):** редакция
  safe_error — ПАТТЕРН-базированная (DSN со схемой, key=value, Bearer/Basic).
  Голые учётные строки вне этих форм в свободном тексте исключения проходят
  дальше: в operational-логи, в worker last_error и — через
  record_backend_fallback (reason=safe_error(...)) — в ТЕЛО /health/ops
  (секция runs/session_backend.reason и fallback_events). Реальные сообщения
  psycopg/redis содержат голые hostname/порты (поэтому для readiness-причин
  реализован класс--only safe_health_error — сертифицирован G6CC-SAFE-5);
  контракт §26.3/§26.4 не нарушен (URL/tokens/сырые payload в границах
  определения безопасной причины). Рекомендация на будущее: при желании
  ужесточить — класс-only и для fallback-причин в health либо scrubbing
  голых токенов; решение versioned, через versioned-обновление контракта
  (план §20.2.6: оракулы дефектов не переписываются под реализацию).
- **H29/H30** (deployment-логи/БД Render, живая браузерная гонка P22) —
  read-only доступ не предоставлялся и в этом раунде; остаются НЕЗАКРЫТЫМИ
  operational acceptance-пунктами (без «production certified») — позиция
  реализации подтверждена, сдвига границ нет.
- Состояние фабрик — операционное (процессное, не durable-факты); advisory-
  пути (хук-зеркало, легаси-карты, коррекции DataFrame, Наставник) остаются
  advisory — миграция в required отдельные решения (границы §26.6 соблюдены).
- Retention/sampling логов, пул соединений — вне задачи (границы §26.6).

## 9. Вердикт

**PASSED WITH REMARKS.** Операция ≠ результат удостоверена по всем пяти
пунктам плана §18: (1) required не деградирует незаметно — fail-closed
подтверждён РЕАЛЬНЫМИ отказами (конфигурация/недоступная БД/драйвер-
поверхность) на фабрике и через startup-lifespan; advisory-деградация всегда
ЯВНАЯ (snapshot/fallback_events/логи), ленивый контракт advisory сохранён;
(2) драйвер объявлен и проверяется сборкой (декларации + исполненный
Docker-эквивалент); (3) фактическая долговечность наблюдаема — /health/ops
показывает configured/effective/degraded/readiness/backlog/возраст/
projection lag на Memory и на живом PostgreSQL, не выдаёт URL/tokens/сырых
exception'ов и не инициализирует фабрики; (4) операционные логи несут
request/operation/event/run/context ids (что доступно), результат/попытку и
безопасную причину, без сырых трейсов; (5) in-process worker восстановления
работает, идемпотентен, устойчив, управляем env'ом и виден в health.
Мутационная кампания 19/19 KILLED (4 kill'а — только своими оракулами);
RED на базе 43/45 честный; регресс ДЕЛЬТА 0; ограничения честно перенесены
(H29/H30, F-6CC1). Deliverable: ZIP cisstat-prograudit6c-certification.zip →
открытый контейнер сессии (download + upload): docs/cert_prograudit6c_2026-
10-13.md, scripts/prograudit6ccert_oracles.py (+_oracles_results.txt),
scripts/prograudit6ccert_red_repro.txt, scripts/prograudit6ccert_mutations.py
(+_mutation_results.txt), worklog/worklog9.md. Без commit/push (AGENTS.md).
Следующая по нарезке плана — AUDIT-CERT (§19: сквозная приёмка,
coverage-матрица P/H/F→tests, контрпримеры); перенос repo-слепых пинов
сертификаций в repo-сюиты — по-прежнему решение тимлида.
