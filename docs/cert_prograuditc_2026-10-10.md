# Акт независимой сертификации PROGR-AUDIT-C-CERT (2026-10-10)

**Задача:** plan_progress_audit.md §6, AUDIT-C — данные, ревизии и серверный
контекст расчёта (коммит 0769547 поверх d54b648).
**Аудитор:** независимая сессия (PROGR-AUDIT-C-CERT). Правила AGENTS.md
соблюдены: commit/push НЕ выполнялись; продуктовый код и тесты репозитория
не изменялись — только артефакты аудита (все untracked; продуктовые файлы
после мутационных проб md5 == HEAD, побайтово).
**Постановка тимлида:** «честно сертифицируй AUDIT-C — данные, ревизии и
контекст расчёта. Спроектируй и реализуй данную Сертификацию. Используй
мутантов на своих мутантах, оракулов на своих данных».
**Окружение:** свежая установка лёгкой группы по рецепту R6 (statsmodels
0.15.0, pandas 2.2.3, prophet, fakeredis, PyWavelets/pandera/arch/ruptures/
statsforecast), Python 3.12.14; node_modules восстановлен npm ci (355
пакетов); jest/typecheck из корня монорепо.

---

## 1. Сверка реализации с кодовой базой (0769547)

Все точки карточки §6 и контракта v0.4-C §14 на месте:

- `apps/api/data_context.py` — НОВЫЙ единый модуль контекста, БЕЗ импортов
  из apps/api (направление session_store → data_context, циклы исключены;
  паттерн target_column_rule/column_origin): `compute_data_digest` (форма +
  имена колонок + `hash_pandas_object(index=True)` с фиксированным ключом;
  префикс `df1-`; None → «»; сбой → «» — защитный контур), `context_components`
  (data = `{fingerprint}#{revision}`, target/temporal = имя или «» — честное
  отсутствие), `compute_context_id` (`ctx-` + uuid5 фиксированного namespace
  от материала `{v:1, run_id, components}`, json sort_keys; без run_id — None;
  run-scoping УТВЕРЖДЁН: повторная загрузка = новый запуск = новый контекст),
  `describe_components` (диагностика без сырых рядов, спека §8.4).
- `apps/api/session_store.py` — `data_revision` (0 при set_dataset) +
  `data_digest`; ЕДИНАЯ ТОЧКА `set_dataframe(df, reason)` → факт изменения
  (bool): ревизия +1 ТОЛЬКО при фактическом изменении контента; недоступный
  дайджест — БЕЗОПАСНАЯ сторона (изменение, спека §8.2); no-op — False без
  bump; `current_context_components()/current_context_id()` (None без
  датасета/запуска); сериализация `data_revision/data_digest` +
  legacy-дефолты 0/«» (SESSION_SCHEMA_VERSION не поднят — аддитивные
  Optional, прецедент PROGR-24-ORIGIN-A/F1).
- `app/core/pipeline_graph.py` — ОДИН реестр: канон
  `CONTEXT_SCOPES = ("data","target","temporal")`, матрица
  `_STAGE_SCOPE_BASE` + `_NODE_SCOPE_OVERRIDES` → `NODE_DEPENDENCY_SCOPES`
  (stage → node → frozenset; материализован один раз; полнота страхуется
  тестом); `node_dependency_scopes` fail-closed (ValueError на неизвестной
  паре); `VALIDITY_*` + `node_context_validity(stage, node_id, captured,
  current)` → current|stale|unknown: captured отсутствует/не-Mapping/неполон
  — unknown (старый факт без контекста НЕ current, план §8); совпадение всех
  нужных scope — current; иначе stale. Матрица на реальной семантике:
  validation/preprocessing фреймовые проверки — data-only (смена цели НЕ
  инвалидирует типы/форматы/диапазоны), рядные — все три; исключения upload
  (chart/distribution/structure) и validation (regularity/sufficiency),
  preprocessing (missing/outliers/regularity/scaling).
- `apps/api/routers/session.py` — 18 точек `session.dataframe = X` переведены
  на `set_dataframe(..., reason="<endpoint>")` (валидационные коррекции ×12,
  preprocessing ×6); `_to_response` отдаёт `context_id/data_revision`;
  cleared-штамп в convert-types (контекст момента сброса: target-компонент
  пуст, ревизия конвертации применена).
- `apps/api/trace_hook.py` — `record_trace_event` штампует context_id момента
  сеяния во ВСЕ route-hook события (None — v1-форма, «читатели раньше
  писателей» §7). `apps/api/target_column_rule.py` — auto-событие штампуется.
- `apps/api/schemas.py` — SessionStateResponse: `context_id: Optional[str]`,
  `data_revision: int = 0` (аддитивно).
- `packages/ui/context/AppShellContext.tsx` — гидратация
  `contextId/dataRevision` ИЗ `/v1/session/current` (`data.context_id ?? null`;
  `typeof data.data_revision === "number"` — иначе null); фронт контекст не
  создаёт догадками, счётчик версий не ведёт (план §6 GREEN).
- Приёмка: `tests/api/test_progress_audit_c.py` — 32 acceptance-контракта
  (7 классов: TestDataRevision×5, TestContextIdentity×7, TestDataContextUnit×4,
  TestEnvelopeContextStamping×5, TestDependencyScopeRegistry×5,
  TestSerializationAndCas×3, TestApiContextExposure×3); jest-оракул
  `packages/ui/context/AppShellContext.test.tsx` (3).
- Инструмент аудита не тронут: `scripts/progress_audit_readonly.py` +
  `progress_audit_readonly_results.json` — md5 рабочих файлов == blob HEAD
  (оракул X1, GUARD на обеих базах).

## 2. Независимая верификация базлайнов (1:1 с worklog9)

| Прогон | Заявлено разработчиком | Воспроизведено аудитором |
|---|---|---|
| Контрольные сюиты карточки (test_session_store + test_target_column + test_pipeline_graph) | зелёные | **255 passed (10.13s)** |
| Адресные сюиты (audit_c + trace_hook + audit_s + trace_events + audit_h1) | 182 passed (набор разработчика) | **175 passed (11.87s)** (набор аудита) |
| Полный tests/api + tests/integration | 1621 passed / 3 failed / 1 skipped | **1621 passed / 3 failed / 1 skipped (200.20s)** |
| Jest монорепо | 162 сюиты / 1919 тестов | **162 сюиты / 1926 тестов, все зелёные** (см. R1 §7) |
| typecheck:all (embedded+standalone) | чисто | **чисто** |

Набор 3 failed идентичен задокументированному средовому нейро-fail-closed
классу 1:1 базлайна H1 (test_modeling_workflow + neural_capacity +
models_candidates — лёгкое окружение). НОЛЬ новых падений, ноль «исцелений».
Повторный полный регресс ПОСЛЕ всех мутационных проб: 1621/3/1 — тот же
набор (дерево не повреждено).

## 3. RED-воспроизведение на d54b648 (до AUDIT-C)

git-worktree d54b648 (рабочее дерево аудита не покидало 0769547; node_modules
скопирован — symlink запрещён ФС). Прогон ТОЛЬКО своих оракулов с
pre-registered таблицей EXPECTED_RED в шапке скрипта (зафиксирована ДО
отката): 33 KILLER — все unit-группы D/R/S/C/E/A (честный ABSENT: new API
нет — ImportError/AttributeError), API P1–P6 (/current без context_id/
data_revision, нет ревизий, трасса без контекста), межпроцессные D4/C3,
файловые пины X2/X3 (AppShellContext без гидратации, acceptance-файлов нет);
4 GUARD — зелёные на ОБОИХ базах: G1 (слоя-1 идентичность upload_completed
стабильна и до AUDIT-C), G2 (инвариант STAGE_NODES до задачи), G3 (чистый
pandas-детерминизм hash_pandas_object), X1 (git-факт инструмента аудита).
**EXPECTED_RED: полное совпадение (33/4), ложно-красного нет.** TS-оракул на
родителе: ts-jest ТИП-ошибка TS2339 (contextId/dataRevision отсутствуют в
AppShellContextValue) — честный KILLER на уровне типов. Восстановление:
worktree удалён, md5-контроль дерева. Протокол: scripts/prograuditccert_red_repro.txt.

## 4. Оракулы на СВОИХ данных — scripts/prograuditccert_oracles.py: 37/37 GREEN (+ TS-оракул 3/3)

Свои данные: hydro_meteo.csv (timestamp,humidity,pressure — 72 часовые точки
c 2026-02-01T00:00, сид 20261011, синус+шум, детерминированная генерация в
скрипте), hydro_fix.csv (тот же ряд с пропуском humidity для адресной
коррекции), session-ключи certc-hydro-*, run-материал RUN-CERTC-H01, actor
«auditor» (≠ user/system разработчика). Сюит НЕ копирует
test_progress_audit_c.py — свои углы: межпроцессный детерминизм digest/
context_id (субпроцессы, контракт «детерминирован между процессами»);
безопасная сторона недоступного дайджеста (спека §8.2 — у разработчика не
запинена); чувствительность дайджеста к переупорядочению строк (index=True)
и к смене ЗНАЧЕНИЯ при той же форме; forged-контекст (поддельные
context_id/data_revision в POST — сервер не принимает); чувствительность
context_id к каждой компоненте в отдельности + нечувствительность к порядку
словаря; Redis-путь полного save/get; honest absence (без датасета — v1-форма,
без выбора — «»); partial-v2 как легальная форма перехода (граница принимает,
аудит-линза называет только ещё-не-заполненные обязательные поля).
P-группа (6, живой API): устойчивый серверный контекст; повторная загрузка
того же filename — новый dataset_id И контекст (run-scoping); apply двигает
ревизию/контекст, preview — нет; смена цели humidity→pressure двигает
контекст при неизменном datasetId, no-op выбора — нет; forged отклонён;
исторические события не перепривязываются (I3), событие после коррекции
несёт актуальный контекст. GUARD-группа (3+1): инварианты, жившие до задачи.
D (4): детерминизм/префикс/None; чувствительность (значение/строка/имя
колонки/порядок строк); сбой → «»; субпроцесс. R (4): set_dataset → 0 +
set_dataframe факт/no-op; None-фрейм; safe-side; сброс ревизии новой
загрузкой. S (4): полнота 1:1 без сирот, ⊆ канона; матрица (chart/structure/
regularity/sufficiency/missing/scaling + стадии-базы eda/modeling);
fail-closed; validity-матрица (unknown×3, stale, current, target-only-смена
с двух сторон); канон scope-ключей == SCOPE_*. C (4): run-scoping/
детерминизм; per-компонентная чувствительность + порядок словаря;
субпроцесс; форма компонентов. E (5): hook-штамп (прямая точка, spec из
таблицы, СВОЙ response_body); auto-штамп (свой фрейм с одним кандидатом);
cleared-штамп (E2E convert-types, контекст момента сброса); partial-v2
легальность + аудит-линза + v1-«не нарушение»; honest absence. A (4):
Memory-roundtrip; legacy-дефолты; Redis save/get; CAS-конфликт без ложного
обновления (свой session-ключ, счётчик stale не выдуман). X (3): git-факт
инструмента; файловые пины гидратации/acceptance. TS-оракул
packages/ui/context/prograuditccert_context_oracle.test.tsx 3/3: клиент
СЛЕДУЕТ серверу при ре-гидратации (новый контекст после серверной мутации,
свой счётчик не ведётся); мусорные типы → честный null (data_revision
строкой не конвертируется); 0 — честное число, отсутствие поля — null.
Протокол: scripts/prograuditccert_oracles.txt.

## 5. Мутационный прогон СВОИХ мутантов — 13 мутантов (дизъюнкт к M0/MC1–MC12 разработчика), ноль переживших; контроль выжил

Каналы: repo (pytest tests/api/test_progress_audit_c.py; для TS —
AppShellContext.test.tsx разработчика) + oracle (свой сюит --cert; для TS —
мой TS-оракул). Дисциплина: backup/побайтовое восстановление/md5 на каждом
шаге и в finally (урок PROGR-19); аварийный останов при неединичном якоре;
коллекшн-ошибка/SyntaxError = KILLED (урок H1). M0 no-op-контроль —
SURVIVED в обоих каналах (repo 32 passed, oracle 37/37) — харнесс достоверен.
KILLED-BOTH (9): CM6 target-компонент всегда «» (repo:
test_target_change_moves_context; oracle: P4/C2); CM7 temporal-компонент
всегда «» (repo: test_date_change; oracle: C2); CM8 материал context_id без
компонентов (repo: 6 failed; oracle: 31/37); CM10 partial captured → stale
(repo: test_validity_unknown_current_stale; oracle: S3); CM11 cleared-штамп
снят (repo: test_cleared_event_carries_context; oracle: E3); CM12
legacy-дефолт ревизии 0→1 (repo: test_legacy_document_gets_honest_defaults;
oracle: A2); CM13 TS-гидратация contextId снята (оба jest-канала); CM5
несвежий дайджест (repo: no-op-тест ревизии — stale-дайджест делает
повторный apply «изменением»; oracle: R1-свежесть); CM9 реестр без overrides
(repo: спотчек upload.structure; oracle: S2 chart). KILLED-ORACLE-ONLY (4,
предсказаны ДО прогона как repo-гэпы): CM1 digest-префикс (D1), CM2 материал
без имён колонок (D2-переименование), CM3 index=False (D2-переупорядочение),
CM4 снятая безопасная сторона (R3). Итог: 13/13 KILLED, 0 выживших; 4
repo-гэпа прикрыты оракулами аудита. Протокол:
scripts/prograuditccert_mutation_results.txt (с разделом «Эволюция оракула»).

## 6. Эволюция оракула (открытая фиксация, прецедент PROGR-24-C-CERT R4)

До мутационного прогона, при отладке СВОИХ оракулов (не под мутантов):
P6 переписан (первая редакция требовала у upload_completed контекст ПОСЛЕ
коррекции — честное поведение: событие держит контекст своего момента,
I3); E2 исправлен (pipeline_trace хранит dict); E4 переписан
(validate_envelope — аудит-линза, называет недостающие обязательные поля;
легальность partial-v2 — принятие на границе); R1 усилен пином свежести
дайджеста, R3 усилен симуляцией недоступного предыдущего дайджеста. После
каждой правки — полный перегон 37/37 GREEN. Предсказания каналов:
11/13 совпали; 2 расхождения (CM5/CM9) — в более сильную сторону repo
(консервативное направление, ложной уверенности нет).

## 7. Находки (акт §7)

**F-CERTC1** (МЕТОДОЛОГИЧЕСКАЯ, закрыта в ходе сертификации): три первые
редакции собственных оракулов (P6/E2/E4) содержали неверные ожидания и
были переписаны до мутационного прогона с полным перегоном (§6) — двухточечная
семантика «момент сеяния vs текущий контекст» и различение «аудит-линза vs
форма перехода» вскрыты мутационно.

**R1** (РЕКОМЕНДАЦИЯ, не блокер, ЖУРНАЛ): арифметика jest-базлайна в записи
PROGR-AUDIT-C — заявлено «162 сюиты / 1919 тестов (базовая линия 161/1916 +
1 сюита/3 теста)»; базлайн 161/1916 взят от S-CERT, а коммит VALFIX-1
(f95e2f1 — непосредственный родитель 0769547) добавил ещё +7 тестов
(TsAnalysisValidation.test.tsx +5, tailwind-preset.test.ts +2), что
подтверждается записью VALFIX-1 («161 сюита / 1923 теста»). Фактическое
измерение аудитора: 162/1926 = 1923+3, все зелёные. Код не затронут —
ошибка учёта в журнале (число сюит верно, число тестов занижено на 7);
рекомендуется учесть дельту в следующей versioned-правке журнала.

**R2** (РЕКОМЕНДАЦИЯ, не блокер): четыре repo-гэпа (CM1–CM4: digest-префикс,
материал имён колонок, index=True-чувствительность, безопасная сторона «»)
прикрыты оракулами аудита; рекомендуется перенести repo-пины ближайшей
коммит-возможностью (прецедент TB-8 → PROGR-25-D).

**R3**: нулевая выживаемость — каждый пункт контракта §14 прикрыт минимум
одним независимым каналом, ядро (компоненты контекста, ревизии, реестр
scopes, validity, штампование продюсеров) — обоими.

**R4**: 2 из 13 предсказаний каналов уточнены в более сильную сторону repo
(CM5/CM9) — двухканальная схема вскрыла, что repo-канал сильнее
предрегистрации аудитора; направление консервативное.

**R5**: средовые — лёгкая группа R6 (pandas 2.2.3 при statsmodels 0.15.0;
на контракт задачи не влияет), 3 failed 1:1 документированному классу;
jest/typecheck зелёные; повторный полный регресс после мутационных проб
не изменился (1621/3/1).

## 8. Вердикт

**PASSED WITH REMARKS** (R1 — журнальная арифметика jest-базлайна; R2 —
4 repo-гэпа, прикрытых оракулами аудита). Ядро приёмки AUDIT-C подтверждено
независимо на своих данных: серверный контекст расчёта существует в единой
точке (data_context без циклов), run-scoped и детерминирован МЕЖПРОЦЕСНО
(uuid5 фиксированного namespace — субпроцессные оракулы); ревизии данных
честны (no-op не выдаётся за изменение, preview не доходит до точки,
сброс новой загрузкой, безопасная сторона недоступного дайджеста);
повторная загрузка того же filename даёт новую идентичность (dataset/run/
context); смена цели/даты двигает только свои scope; forged-контекст от
клиента отклонён (сервер считает сам); исторические события не
переприбязываются (I3); реестр dependency scopes полон (fail-closed) и
семантически верен с ОБЕИХ сторон риска карточки (data-only остаётся current
при смене цели, target-dependent — stale); применимость различает
current/stale/unknown (частичный/нечитаемый captured — НЕ current); три
продюсера (hook/auto/cleared) штампуют контекст момента сеяния, прочие
честно остаются v1 (форма перехода §14.5); сериализация/legacy-дефолты/
CAS-конфликт честны на обоих хранилищах; UI гидратирует контекст с сервера
и не ведёт свой счётчик. Базлайны 1:1; RED честный (33/4 полное совпадение +
TS TS2339); 37/37 + 3/3 оракулов на своих данных; 13 своих мутантов —
ноль переживших, набор дизъюнктен к M0/MC1–MC12, M0-контроль выжил.
Противоречий «код vs контракт» не обнаружено; единственное расхождение
«журнал vs факт» — учётное (R1), не продуктовое. Ограничения (унаследованы,
планом предусмотрены): durable-хранение envelope слоя 2 и run-метаданных
ревизии — миграция AUDIT-6A; полная обязательность v2 — AUDIT-6B; result
context (параметры методов) — AUDIT-4/7A; UI keyed-кэши — AUDIT-3/2B;
проекции панели/Наставника/отчёта — AUDIT-5B/8; cross-run restore — AUDIT-8;
live PostgreSQL/Render/Vercel — вне периметра.

## 9. Поставка

Deliverable: ZIP `cisstat-prograuditc-certification.zip` → открытый контейнер
сессии (download): docs/cert_prograuditc_2026-10-10.md (настоящий акт),
scripts/prograuditccert_oracles.py (+ scripts/prograuditccert_oracles.txt),
scripts/prograuditccert_red_repro.txt, scripts/prograuditccert_mutations.py
(+ scripts/prograuditccert_mutation_results.txt),
packages/ui/context/prograuditccert_context_oracle.test.tsx,
worklog/worklog9.md. Без commit/push (AGENTS.md).
