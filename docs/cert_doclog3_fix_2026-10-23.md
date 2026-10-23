# Акт исправления находок DOCLOG-3-CERT (DOCLOG-3-FIX)

**Задача:** DOCLOG-3-FIX (2026-10-23) — проектирование и исправление находок независимой сертификации DOCLOG-3 (акт `docs/cert_doclog3_2026-10-23.md`): N1 — перенос PG-зеркал (pgm01–pgm08+) в repo-сюиты; N4 — пин честной слоистости CORS/telemetry (preflight-OPTIONS отвечает внешний слой, X-Request-ID только на ответах телеметрии); повторное подтверждение AC10/AC11 сентинел-батареей и fault-injection оракулами.
**База:** `main@52315ac` (рабочее дерево чистое до работ; `git diff 52315ac` после работ = только `tests/api/test_doclog3_telemetry_audit.py` +563 строки и новые артефакты `scripts/doclog3fix/` — продуктовый код НОЛЬ изменений).
**Дата акта:** 2026-10-23. **Режим:** TDD (RED→GREEN на мутантах), мутанты СВОИ на СВОИХ находках, оракулы на СВОИХ данных, манифест sha256 НЕ ведётся (указание тимлида), AGENTS.md соблюдён (без commit/push).

---

## 1. Постановка и дизайн

Постановка: «Синхронизируйся до 52315ac. Следующая задача — спроектируй и исправь свои находки: N1 — перенести PG-зеркала (pgm01–pgm08) в repo-сюиты; N4 — CORS-preflight OPTIONS отвечает внешний слой (X-Request-ID только на ответах телеметрии — слоистость честная); AC10/AC11 подтверждены сентинел-батареей и fault-injection оракулами. Следуй правилам AGENTS.md. По завершении работы выложи в открытый контейнер сессии zip новых/обновлённых файлов».

Дизайн решения (обе находки — дефекты **покрытия**, не продуктового кода; поведение в акте DOCLOG-3-CERT признано корректным):

- **N1** — перенос 11 PG-зеркальных оракулов класса F-D2C1 из `scripts/doclog3cert/test_doclog3cert_oracle_pgmirror.py` в repo-сюиту `tests/api/test_doclog3_telemetry_audit.py` как гвард-класс `TestPostgresMirrorTelemetryAudit` (прецедент `TestPostgresMirrorRegistry` фикса DOCLOG-2-FIX). Критерий закрытия: PG-зона мутантов M29/M30/M31 из акта переходит из ORACLE-ONLY в DUAL-KILLED.
- **N4** — три пина честной слоистости в repo-сюиту: статический (порядок middleware-стека main.app) + динамический preflight (OPTIONS+Origin+ACRM → внешний CORSMiddleware, CORS-заголовки есть, X-Request-ID НЕТ, событие api.request не пишется) + динамический контраст (простой OPTIONS проходит внутрь стека и получает X-Request-ID; событие по-прежнему не пишется). Критерий закрытия: синтетический reorder-мутант M32 переходит из SURVIVED (старый канал) в KILLED новым каналом.
- **AC10/AC11** — повторное подтверждение обоими каналами: сентинел-батарея 10 векторов × 2 канала (repo 22 + SQL-literal + health/error = 33 теста класса AC10) и fault-injection оракулы (collector failure → spool/dropped/emergency, mandatory fail-closed) в repo + 21 оракул класса AC10/AC11 в корпусе сертификации.

Среда пересоздана до паритета cert-сессии: venv requirements + requirements-dev + apps/api/requirements, опциональные (pandera/PyWavelets/psycopg[binary]/statsforecast/tbats/prophet/arch/sqlalchemy/syrupy/duckdb), **pytest 9.1.1, statsmodels 0.15.0** (neural-зависимости не ставились — как в cert-сессии; 6 neural-падений средовые). Оракульный корпус на чистой среде: **107/107 GREEN ×2** (3.27s/3.13s — `protocols/oracle_green_run1.txt`).

## 2. RED (честное доказательство гэпа на мутантах)

Дефект N1/N4 — отсутствие покрытия, поэтому RED доказывается выживанием мутантов на старом repo-канале (прецедент трактовки «RED» для покрытийных находок — ORACLE-ONLY вердикты акта DOCLOG-3-CERT):

| Мутант | Суть | Старый repo (96) | Oracle (107) |
|---|---|---|---|
| M29 | telemetry INSERT: сдвиг severity_text/number | **SURVIVED** | KILLED |
| M30 | audit INSERT: сдвиг actor_via/tenant_id | **SURVIVED** | KILLED |
| M31 | PostgresTelemetrySink.write → False | **SURVIVED** | KILLED |
| M32 | reorder: телеметрия внешнее CORS | **SURVIVED** | SURVIVED |
| M33 | telemetry _INSERT_SQL: сдвиг колонок в SQL | **SURVIVED** | KILLED |
| M34 | audit _INSERT_SQL: сдвиг колонок в SQL | **SURVIVED** | KILLED |

- M29/M30/M31 на старом канале — `protocols/red_n1_repo_gap_M29_M30_M31.json` (повтор акта: 3 × ORACLE-ONLY).
- M32/M33/M34 на старом канале — `protocols/red_oldrepo_m32_m33_m34.txt` (**3/3 SURVIVED**, восстановление md5-паспортами True).
- M32–M34 — новые мутанты фикса (СВОИ): M32 — reorder-блок main.py целиком (контроль 1 вхождения); M33/M34 — сдвиг колонок в самих `_INSERT_SQL` (класс F-D2C1 на уровне SQL).

## 3. GREEN (реализация)

Единственный изменённый файл — `tests/api/test_doclog3_telemetry_audit.py` (+563 строки; продуктовый код не тронут, `git diff apps/` пуст):

- **Секция 14 `TestMainAppWiring` — N4 (3 теста):**
  - `test_middleware_layering_cors_outermost` — статика: `app.user_middleware` == [CORSMiddleware, TelemetryContextMiddleware, TraceHookMiddleware] (CORS внешний, телеметрия внутри CORS и снаружи TraceHook);
  - `test_cors_preflight_answered_externally_no_request_id` — preflight (OPTIONS /health + Origin + Access-Control-Request-Method) → 200, `access-control-allow-origin` присутствует, **X-Request-ID отсутствует**, `api.request` не пишется (внешний слой замкнул запрос, телеметрия не вызывалась);
  - `test_simple_options_passes_through_with_request_id` — контраст: OPTIONS без ACRM → 405 (маршрута нет), CORS-заголовок добавлен внешним слоем на выходе, **X-Request-ID присутствует** (ответ прошёл через телеметрию), `api.request` по-прежнему не пишется. Симметрия доказывает: отсутствие заголовка на preflight — свойство слоистости, а не случайность.
- **Секция 16 `TestPostgresMirrorTelemetryAudit` — N1 (12 тестов):** pgm01 (INSERT≡DDL 29/29 по порядку), pgm02 (NOT NULL-без-DEFAULT покрыты), pgm03 (динамический раундтрип fake-psycopg warn/13, GET, client_error — каждый параметр ≡ СВОЕЙ колонке ПО ИМЕНИ; attributes→JSON, sampled→bool), **pgm03b (усиление: вторая точка асимметрии error/17, POST, success — ловит маппинг «всё в одну severity» и сдвиги outcome/method)**, pgm04 (ON CONFLICT DO NOTHING), pgm05 (audit INSERT≡DDL минус recorded_at, 16/16), pgm06 (NOT NULL покрыты), pgm07 (динамический раундтрип audit-записи; details→JSON; occurred_at — ISO c UTC-офсетом), pgm08 (list_recent → NotImplementedError — честная граница DOCLOG-7), pgm09 (без REFERENCES), pgm10 (6 индексов), pgm11 (файл-паритет каталогу).
- **Усиления против сертификаторской версии** (урок DOCLOG-2-FIX): корпус `d3mirror` (RUN-D3MIRROR01/02, d3mirror.pg.alpha/bravo, d3mirrorreq-pgm03/03b/07, tenant-d3mirror, subj-d3mirror01, DSN postgres://d3mirror/*) дизъюнктен repo-корпусу (RUN-DOCLOG3*/d3-*) и оракульному (RUN-D3CERT*/d3cert-*); асимметрия severity/outcome/method между pgm03 и pgm03b; контроль плейсхолдеров `sql.count("%s") == 29/16`; фейки psycopg — СВОИ (`_MirrorFakeCursor/_MirrorFakeConnection`, fixture `mirror_psycopg`, прецедент fakeredis/fake-psycopg).
- GREEN: repo-сюита **111/111** (96 + 12 pgm + 3 N4), оракульный корпус 107/107 — поведение на чистом дереве не сломано (находки были покрытийные).

## 4. Мутационная кампания закрытия (scripts/doclog3fix/mutations_fix.py)

Каналы: REPO = tests/api/test_doclog3_telemetry_audit.py (**111**); ORACLE = scripts/doclog3cert (**107**). Дисциплина: точечные байтовые замены (контроль 1 вхождения), восстановление md5-паспортом, no-op-контроли.

**Итог: 6/6 KILLED (5 DUAL-KILLED + 1 REPO-ONLY), 0 SURVIVED; контроли 2/2 ALIVE; паспорта OK** (`protocols/mutations_fix_protocol.json`):

- **M29/M30/M31 → DUAL-KILLED** (были ORACLE-ONLY): N1 закрыт — repo-канал теперь убивает PG-зону класса F-D2C1 (pgm03/pgm03b/pgm07 по имени колонки; pgm01/pgm05 статикой).
- **M32 → REPO-ONLY**: reorder-мутант N4 убит новым каналом (статический пин слоистости + preflight-тест); оракульный корпус его не пинует — ожидаемо (корпус сертификации заморожен, новый пин живёт в repo).
- **M33/M34 → DUAL-KILLED**: сдвиг колонок в `_INSERT_SQL` ловится и статикой (pgm01/pgm05), и динамикой (pgm03/pgm07) обоими каналами.
- Контроли C4 (repo-сюита) / C5 (main.py): ALIVE — канал не ловит ничего на no-op.

## 5. Регресс дельта-0 и сборка

- **База (чистый 52315ac, git-worktree):** полный pytest tests/ — **31 failed / 4572 passed / 66 skipped** (458.5s).
- **Пост-фикс:** полный pytest tests/ — **31 failed / 4587 passed / 66 skipped** (463.8s).
- **Дельта-0 побайтово:** множества 31 FAILED-ID **ИДЕНТИЧНЫ** (0 расхождений в обе стороны — `protocols/regress_failed_ids_diff.txt`); прирост passed **+15 = ровно 12 pgm + 3 N4**. Классы падений средовые предсуществующие (14 MNS-SPEC-PATH + 7 progress_audit_5b psycopg-DSN + 6 neural + 4 modeling). База 4572P vs акт 4567P — сдвиг сессии среды (+5, прецедент DOCLOG-2-FIX: дельта-0 честно внутри одной среды).
- **Адресные смежные контуры:** doclog0+1+2+3+research_runs+session_store **432/432**; diagnostics+diagnostics_internal+admin_progress+run_report **93/93** (`protocols/regress_adjacent_*.txt`).
- **Сборка:** `apps.api.main` импортируется; OpenAPI **171 путь / 179 операций** (паритет — новых HTTP-поверхностей нет); middleware-стек [CORS, Telemetry, TraceHook]; каталог миграций **9 файлов / 53 statement**; AUDIT_ACTIONS=20; схемы `doclog.telemetry/1` + `doclog.security_audit/1` (`scripts/doclog3fix/build_check.py`, СБОРКА OK).

## 6. Подтверждение AC10/AC11

- **AC10 (sentinel-батарея), repo-канал:** 33/33 — 10 векторов (пароль/DSN/Bearer/X-API-Key/cookie/signed URL/URL-encoded/многострочный/session_id/CRLF-инъекция) × 2 канала (message/attribute) + SQL-literal отсекается allowlist'ом + health/error response чисты (`protocols/ac10_ac11_repo*.txt`).
- **AC11 (fault-injection), repo-канал:** TestCollectorFailure — исключение sink → spool+emergency и never-raises; честный False → dropped; границы 500/20; flush; mandatory fail-closed (MandatoryAuditFailure до действия).
- **Oracle-канал:** 21/21 fault-injection/sentinel оракулов (`protocols/ac10_ac11_oracle*.txt`); полный оракульный корпус 107/107 ×2.
- Репо-сюита целиком 111/111 в пост-фиксном регрессе — сентинелы и fault-injection зелёные на исправленном дереве.

## 7. Границы и вердикт

**Н1: ЗАКРЫТ** — PG-зеркала класса F-D2C1 (pgm01–pgm11 + усиление pgm03b) живут в repo-сюите гвардом `TestPostgresMirrorTelemetryAudit`; класс мутантов M29/M30/M31 переведён ORACLE-ONLY → DUAL-KILLED; SQL-уровень класса (M33/M34) покрыт статикой+динамикой. **N4: ЗАКРЫТ** — честная слоистость запинена статикой стека + preflight/контраст-динамикой; reorder-мутант M32 пойман новым каналом. **AC10/AC11: ПОДТВЕРЖДЕНЫ** повторно сентинел-батареей (10×2 + SQL-literal) и fault-injection оракулами обоих каналов.

Честные границы: живой PG-прогон миграции 0009 — при следующем durable-срезе (AUDIT-6A); 10 ORACLE-ONLY пинов не-PG-зоны из акта (M01/M06/M14/M17/M18/M20/M22) — вне объёма FIX (не блокируют, рекомендация акта остаётся); оракульный корпус не дополнен N4-пином (заморожен по определению — новые пины живут в repo). Продуктовый код: **ноль изменений**; единственная строка поставки — тесты.

Акт: `docs/cert_doclog3_fix_2026-10-23.md`. Артефакты: `scripts/doclog3fix/` (mutations_fix.py, red_oldrepo_m32_m33_m34.py, delta0_check.py, build_check.py, probe_cors.py, protocols/ — 13 файлов), `worklog/worklog10.md` (запись DOCLOG-3-FIX). Без commit/push (AGENTS.md). Манифест sha256 не ведётся и не используется (указание тимлида).
