# Акт независимой сертификации задачи DOCLOG-0 — идентичность и контракт

*Дата: 2026-10-22. База сертификации: main@fb26f6f (задача DOCLOG-0, родитель
cc5c14e = PROGR-17-R1FIX). Исполнитель: независимый сертификатор по постановке
тимлида («честно сертифицируй DOCLOG-0; мутантов на своих мутантах, оракулов
на своих данных»). Правила AGENTS.md соблюдены: commit/push не выполнялись,
продуктовый код и тесты репозитория аудитом не менялись.*

## 1. Предмет и границы

**Предмет**: реализация DOCLOG-0 (коммит fb26f6f, 23 файла, +1935/−74):
`apps/api/identity.py` (НОВЫЙ), `auth.py`, `plans.py`, `session_store.py`,
`research_runs.py` (+ миграция 0006), `routers/progress.py` (единый гейт
`_authorized_run` на 9 run-маршрутах), `routers/session.py`,
`upload_common.py`, `storage_diagnostics.py`,
`tests/api/test_doclog0_identity.py` (НОВЫЙ, 42), 9 рекалиброванных
тест-файлов, контракт `docs/doclog0_identity_contract.md`.

**Спецификация-источник**: `spec_documentation_logging.md`
(§9.1 идентичность/provenance, §15 R09 права/tenancy, §15.1 переход от
текущих сессий, §19 строка DOCLOG-0 — блокер «нельзя читать чужой
run/document/artifact/job во всех путях, существующий report учтён»,
§20 AC06, §22).

**Вне границ** (по §19 и честным границам поставки): durable-артефакты
(DOCLOG-1), ReportSnapshot (DOCLOG-2), durable audit-поток (DOCLOG-3),
UI выдачи (DOCLOG-4), живой PostgreSQL-прогон миграции 0006 (pgserver —
при следующем durable-срезе), portal assertion-адаптер `scoped`-режима.
Фронтенд коммитом не тронут (git show --stat) — Jest/typecheck/build вне
границ сертификации (статическая проверка состава коммита).

## 2. Сверка заявлений с кодовой базой (статический аудит)

Все ключевые заявления ворклога/контракта подтверждены чтением кода fb26f6f:

| Заявление | Подтверждение |
|---|---|
| Псевдоним subj-<hex16> = HMAC-SHA256(соль, материал)[:16]; env-соль `CISSTAT_IDENTITY_SALT`, dev-константа честно документирована | identity.py:130–146 (`_DEV_SALT`), T4 в докстринге |
| Каталог Scope — ровно 11 прав §15; ADMIN — полный каталог, аналитики — пусто (не фантазируется) | identity.py:181–210; перечисление совпадает с §15 дословно |
| Реестр ключей: аддитивный формат `key:role:plan[:subject:tenant[:scopes]]`, scopes через «+»; subject==key отклонён; без subject — псевдоним ключа, НЕ значение | auth.py:26–78 (`continue` на subject==key), `resolve_principal_for_key` → None без исключений |
| Решающая таблица `authorize_run_access` — fail-closed, 7 строкец, tenant-mismatch запрещает любой непривилегированный исход | identity.py:360–444; строкиец «unresolved ∧ session ∧ tenant» содержит tenant-границу |
| Uniform 404 (отказ == отсутствие, тело без run_id) | progress.py `_authorized_run` + `_RUN_NOT_FOUND_DETAIL = "Запуск не найден"`; прежний `_require_run` дисклоужал `f"Запуск {run_id} не найден"` (F10 RED) |
| Гейт на 9 run-маршрутах (detail, report, pause, resume, checkpoints, restore, delivery×2, mentor/next-step), write — `action="write"` | progress.py: 9 вхождений `_authorized_run(request…)` (1295–2256), action-распределение read/write сверено |
| Привязка владельца: `ensure_owner_binding()` first-write-wins; создание run только `ownership="bound"`; существующие не перепривязываются (restore — перелинковка без смены владельца) | session_store.py:379–393; research_runs.py `_mirror_run_base` (`owner_subject=owner_subject, …, ownership="bound"` только в ветке создания) |
| Сериализация владения (урок F1): session_to_dict/from_dict; run to_dict/from_dict щитом типов; merge COALESCE Memory/Postgres; SQL upsert `COALESCE(EXCLUDED.x, …)` | session_store.py:894+, research_runs.py `_merge_run_additive`/`_UPSERT_RUN_SQL` (15-значный VALUES, 3 COALESCE) |
| Миграция 0006: 3 ADD COLUMN + 2 CREATE INDEX, IF NOT EXISTS, файл-дубль каталога, включена в MIGRATION_STATEMENTS | research_runs.py:766–800; файл migrations/0006 — паритет оператор-в-оператор (оракул OC32) |
| Гвард зеркала слоя 2: bound-run не принимает зеркало чужого субъекта (fail-closed), легаси — прежняя перелинковка, dev_single_user — объявленная изоляция | research_runs.py `record_run_event` (2025+); мой оракул OC47 — ДВУСТОРОННИЙ (чужое отклонено И создающая сессия пишет) |
| Restore: gate ДО создания сессии; наследование субъекта владельца; владелец run НЕ переписывается | progress.py restore (1498 gate; 1555+ наследование) |
| /health/ops identity-блок: режим, enforcement=owner_bound, дефолт-tenant, bool конфигурации БЕЗ значений (T6) | storage_diagnostics.py `build_identity_health` |
| Режимы: session_scoped (дефолт) / dev_single_user / scoped; незнакомое значение — fail-closed + warning | identity.py `get_identity_mode` (107–119) |
| RED: 40 failed + 2 честно-зелёных пина; GREEN 42/42; рекалибровка F08-класса паттернами P1/P2/P3; SESSION_SCHEMA_VERSION 3→4 | repo-прогон 42/42 воспроизведён; schema-пин сверен; рекалиброванные сюиты зелёные (553 адресных) |

Расхождений заявлений с кодом НЕ обнаружено. Численности сходятся
(42 теста; 9 маршрутов; 3 колонки/2 индекса; 11 scopes).

## 3. Оракулы на СВОИХ данных — 53/53 PASS (GREEN ×2)

Корпус сертификатора дизъюнктен repo-корпусу и всем корпусам прошлых
сертификаций: run_id `RUN-DCAC0Axx`, cookie-сессии `dca-cert-*`,
админ-ключ `dca-cert-admin-key-7f3`, явный субъект `dca-portal-subject-42`,
tenants `tenant-dca-alpha/beta`, salts `dca-cert-salt-one/two`
(`scripts/doclog0cert/oracle_corpus.py`). Ожидания — собственная деривация,
не ссылки на repo-тесты.

- **Юнит-контур** (`test_doclog0cert_oracle_unit.py`, 36): псевдонимизация
  (детерминизм, префикс/hex16, неутечка материала включая 4/8/16-префиксы,
  ротация salt-параметром И env, fail-closed на пустой материал); validity
  (резервированное пространство subj- вне hex невалидно; границы 64; слаг
  tenant; канон RUN-XXXXXXXX включая 7/9-знаковые промахи); каталог Scope
  ровно 11 == §15; базовая выдача по ролям (строковый алиас "admin"
  включительно; неизвестная роль — честно пусто); реестр (расширенная
  запись, legacy → псевдоним, fail-closed subject==key, мусорные соседи
  переживаются, разделитель «+», unknown → None без исключений);
  решающая таблица все строкец + МОИ глубокие случаи (tenant-граница
  континуитета bound И unresolved; fail-closed unknown-режима с
  каптурой warning); AccessDecision completeness (состав полей,
  JSON-safe, "anonymous"-маркер); effective_ownership строг (bound без
  owner → unresolved; "Bound" → unresolved); персистенция (roundtrip,
  no-fabrication включая 42-int, COALESCE в обе стороны, Memory-store,
  миграция-паритет файл↔каталог); **fakeredis-параметризация** save→get
  (F1-класс PROGR-25: Memory-алиасинг не маскирует потерю сериализации);
  resolve_request_subject (замороженный владелец приоритетен суррогату,
  ключ приоритетен cookie, аноним честен).
- **API-контур** (`test_doclog0cert_oracle_api.py`, 17): привязка владельца
  демо-загрузкой И БД-дорожкой (register_uploaded_dataframe — единая
  точка); владелец читает все 4 read-маршрута; чужая сессия — uniform 404
  на 5 поверхностях (включая delivery/{op}), тела byte-equal отсутствию,
  run_id не всплывает; write-пути (pause/resume/checkpoints/restore) — 404;
  аноним без носителя — 404; ADMIN-ключ читает чужой, **не-admin ключ
  (internal_analyst) — 404** (мой дискриминационный случай: ADMIN-исключение
  не резиновое); легаси-континуитет (создавшая — 200, чужая — 404, админ —
  200); restore-наследование (владелец run не переписывается на новый
  носитель; НОВАЯ сессия несёт субъекта владельца; чужой restore — 404);
  **action-факт** (oc46: pause/restore → `action="write"` через шпион
  authorize_run_access — контракт §4.2, не прикрытый repo-каналом);
  гвард зеркала ДВУСТОРОННИЙ (чужое отклонено, создавшая пишет —
  легитимный путь жив); легаси-перелинковка жива (oc48);
  /health/ops — 4 оракула честности (bool-тип, значения ключей отсутствуют).

**GREEN 53/53 на fb26f6f, два прогона подряд** (протокол
`scripts/doclog0cert/oracles_green_protocol.txt`).

## 4. RED на родителе cc5c14e (git-worktree, cleanup подтверждён)

`scripts/doclog0cert/red_repro.py` — **21/21 факт RED**:

- 15 статических: identity.py / тест-сюита / миграция 0006 / контрактный
  документ отсутствуют; MIGRATION_STATEMENTS_0006, owner-поля ResearchRun,
  ensure_owner_binding, гвард зеркала, `_authorized_run` — отсутствуют;
  SESSION_SCHEMA_VERSION == 3; реестр ключей без subject/tenant/scopes;
  `resolve_principal_for_key` отсутствует; identity-блока /health/ops нет;
  **детальный 404 родителя дисклоужал run_id** (f-string, F08-поверхность).
- Юнит-оракулы: 36 failed (collection error — модуля не существует).
- API-оракулы: **14 failed / 3 passed** — F08 живьём (чужая сессия читает
  запуск по знанию run_id: oc36/oc39/oc40/oc45 красные). 3 честно-зелёных —
  контракты вне DOCLOG-0, тривиально истинные без гейта (владелец читает
  своё; админ читает; легаси-перелинковка) — зафиксированы как
  регресс-пины родителя, паттерн DB-7-CERT.

## 5. Мутационная кампания — 26 боевых + 3 no-op-контроля, два канала

Харнесс `scripts/doclog0cert/mutations.py`: точечные байтовые замены
(контроль ровно 1 вхождения), побайтовое восстановление из git с md5-паспортом
до/после (RESTORE-FAIL 0), финальный контроль — md5 паспортов идентичен,
`git diff` пуст. Каналы: ORACLE (53 оракула сертификатора) + REPO
(test_doclog0_identity 42 + test_session_store + test_research_runs).

| Итог | Значение |
|---|---|
| DUAL-KILLED | 25 (M01–M20, M22–M26: оба канала) |
| ORACLE-ONLY | 1 (M21 — restore проходит как `action="read"`: repo-канал не пинует audit-факт действия, глубину добавил оракул oc46; кандидат на перенос пина в repo-сюиту) |
| DUAL-SURVIVORS | **0** |
| no-op-контроли | 3/3 ALIVE (харнесс достоверен, ложных убийств нет) |

Покрытие угроз: T1 (M01/M06/M07/M18 — аноним/чужие read-пути), T2
(M22 — гвард зеркала; oc40 — write-пути), T3 (M20/M23 — restore-наследование
и привязка на создании), T4 (M09/M14/M15 — псевдонимизация и fail-closed
реестра), T5 (M04 — tenant-граница; oc20/oc21/oc24 — включая мои
глубокие случаи континуитета), T6 (M13 — bool-флаг). Единственность причины
отказа, uniform-404 без дисклоужения (M19), сериализация F1-класса (M26),
first-write-wins (M25), COALESCE (M24), разделитель scopes (M16), fail-closed
режимов (M12) — убиты обоими каналами.

Режим кампании: возобновляемый (протокол ведён частями M01–M09,
M10–M17, M18–M26+CTL; суммарный итог по всем частям — протокол
`scripts/doclog0cert/mutations_protocol.txt`, лог `mutations_run_log.txt`).

## 6. Регресс и сборка

- **Полный pytest tests/**: 4352 passed / 23 failed / 66 skipped.
  **Дельта-0 доказана побайтно**: множествоFAILED-ID (23) воспроизведено
  на родителе cc5c14e через git-worktree — **IDENTИЧНО** (23/23; классы:
  14 × MNS-SPEC-PATH — предсуществующая поломка перемещения спек в docs/,
  9 × neural-каталог/зависимости вне установленной группы). Ноль
  содержательных падений, ноль регрессий DOCLOG-0
  (`scripts/doclog0cert/regress_full_failed_ids.txt`).
- Адресный контур: repo-канал 189/189 (42 + session_store +
  research_runs); рекалиброванные сюиты поставки (mentor_rules,
  admin_progress_api, run_report, progr13b, research_runs, audit_1a,
  audit_8, session_store, status_original_series, integration cert) —
  **553 passed** (`recalibrated_green_protocol.txt`).
- Сборка: apps.api.main импортируется во всех оракулах (TestClient);
  фронтенд коммитом не тронут — Jest/typecheck/build вне границ
  (статическая сверка состава коммита).

## 7. Находки (блокирующих нет)

- **N1 (repo-гэп, кандидат на пин)**: `action`-факт решающей таблицы
  (§4.2 «WRITE через ту же таблицу action="write"») repo-каналом не пинут —
  мутант M21 (restore как read) убит только оракулом oc46. Рекомендация:
  repo-пин шпионом authorize_run_access или пин AccessDecision в логе.
- **N2 (глубина repo-покрытия, закрыта оракулами)**: bound
  creator-continuity (M05) repo-сюитой не пинут (есть только
  unresolved-вариант) — мой oc21 добавляет случай + tenant-границу
  континуитета; кандидат на перенос в repo-сюиту.
- **N3 (положительное наблюдение)**: рейкаст-гвард restore-семантики —
  владелец run не переписывается при restore (перелинковка «последний
  известный» §5), наследует НОВАЯ сессия — контракт §15.1 соблюдён точно;
  repo-тест проверяет доступ, мой oc45 дополнительно пинит отказ
  переприсвоения.
- **N4 (честная граница)**: живой PostgreSQL-прогон миграции 0006 и
  pgserver-приёмка — вне этой среды (паттерн AUDIT-6A — при следующем
  durable-срезе); COALESCE-паритет Postgres-пути верифицирован статически
  (_UPSERT_RUN_SQL) и пинится repo-сюитой.

## 8. Вердикт

**PASSED.** Все заявления поставки DOCLOG-0 подтверждены независимыми
оракулами на своих данных (53/53), RED-композицией на родителе (21/21)
и мутационной кампанией на своих мутантах (26/26 убиты двухканально,
0 выживших, 1 ORACLE-ONLY — находка N1, контроли 3/3 ALIVE). Блокер §19
«нельзя читать чужой run во всех путях, существующий report учтён» закрыт
объектной авторизацией на всех 9 run-маршрутах с uniform-404 и
fail-closed семантикой; политика legacy-владения (§15.1) соблюдена:
unresolved вычисляется резолвером, привязка — только на создании,
restore наследует, «назначение владельца тому, кто первым назвал run_id»
исключено по построению (мутант M20/M23 + оракул oc45). Продуктовый код
и тесты репозитория аудитом не менялись.
