# Акт независимой сертификации PROGR-AUDIT-6B-CERT

**Задача:** AUDIT-6B — восстановимая доставка и операции
(plan_progress_audit.md §17; контракт docs/progress_audit_contract.md,
аддендум v1.5-6B §25; спека spec_progress_audit.md §8.3, P08–P10/P22).
**Объект:** main@**8b309eb** (коммит PROGR-AUDIT-6B). **База RED:**
main@**56f431c** (коммит PROGR-AUDIT-7B, предшественник по нарезке плана).
**Дата:** 2026-10-13. **Сертификатор:** независимый раунд — «мутанты на
своих мутантах, оракулы на своих данных» (данные, оракулы, швы отказа и
классы мутантов дизъюнктны исполнителю).
**Метод:** TDD RED→GREEN на своих оракулах; независимая мутационная
кампания на незакоммиченном дереве (якорь sha256 + побайтовое
восстановление, без git checkout); полный регресс со сверкой дельты к
базе; fault-tests на живом PostgreSQL (pgserver — план §17 GREEN).
**Вердикт: PASSED** (§10).

---

## 1. Постановка и сверка периметра

Постановка тимлида: «Изучи spec_progress_audit.md и
plan_progress_audit.md, а также текущий код по основным файлам контура
"Прогресс", записи в журнале worklog9.md. Следующая задача: честно
сертифицируй PROGR-AUDIT-6B — восстановимая доставка и операции.
Спроектируй и реализуй данную Сертификацию. Используй мутантов на своих
мутантах, оракулов на своих данных. Следуй правилам AGENTS.md и
паттернам сертификации на платформе. По завершении работы выложи zip
новых/обновленных файлов для скачивания».

Карточка §17 — состав: (1) реестр producers required/advisory без
пустого слова «durable» на весь сервис; (2) UI-report фиксируется
ledger'ом до durable receipt, слой 1 — восстанавливаемая проекция, отказ
cache не отменяет committed событие; (3) для научных мутаций —
восстановимый протокол: staged-артефакт до commit'а, атомарная
регистрация ссылки/состояния/события; незапубликованные staged-артефакты
не считаются завершённым расчётом; (4) outbox переживает потерю
процесса и cache (очередь памяти/«недоказанный Redis» недостаточны);
(5) retry доставляет факт/проекцию по operation_id и НЕ повторяет
математическую операцию; (6) честная таксономия not_executed /
executed_documentation_pending / committed_projection_pending / failed
без фиктивного rollback; (7) контролируемое восстановление после crash +
staged cleanup внешних артефактов; (8) read-after-write по
receipt.watermark либо честное ожидающее; advisory после ответа остаётся
best-effort. RED-карточки §17: crash до/после ledger commit; повтор
после потерянного ответа; cache недоступен; worker дважды; artifact
подготовлен, DB commit не состоялся; операция записана, проекция ещё не
обновилась. GREEN/приёмка: устойчивый restart не теряет required-факты;
операция имеет один эффект и повторяемый receipt; полный ledger
восстанавливает cache; fault-tests на настоящем PostgreSQL обязательны.

## 2. Сверка реализации с кодовой базой

Все точки аддендума §25 на месте (сверено чтением кода):

* **Реестр producers (§25.1)**: REQUIRED_PRODUCERS — ровно 5
  (`progress_maps_v2` с ключом `report:{run_id}:{report_id}`;
  `runs.pause/resume/checkpoint/restore` с ключом
  `event:{run_id}:{event_id}`); ADVISORY_PRODUCERS — ровно 4
  (`trace_hook_mirror` с маркером P09/P22 в `trace_hook.py`,
  `progress_maps_legacy`, `corrections_dataframe`,
  `mentor_observations`) с непустыми обоснованиями; пересечение
  множеств невозможно; `DELIVERY_KINDS = frozenset({"layer1_mirror"})`
  — retry физически не имеет вида «повторить научную операцию».
* **Durable outbox в транзакции (§25.2)**: `CommitEventBatch` расширен
  аддитивно (`checkpoints`, `delivery_task`); Memory-регистрация под
  тем же замком (research_runs.py, шаги 5a/5b commit_event_batch), PG —
  `OUTBOX_INSERT_SQL` + `outbox_row_params` на ТОМ ЖЕ соединении перед
  `conn.commit()` (шаг 8); миграция 0005 — таблица
  `progress_delivery_outbox` (PK operation_id, FK CASCADE на
  research_runs, индексы due/run) + файл-дубль, каталог
  MIGRATION_FILES дополнен; дедуп commit'а возвращает прежний receipt
  ДО шага регистрации (обязательство не дублируется);
  `bind_idempotency_key` привязывает ключ commit'а при регистрации
  (связь с receipt для п.8); состояния `pending/delivered/failed`.
* **Required-протокол карты и run-level (§25.3)**: v2-путь
  progress_maps.py строит `layer1_mirror_task` (operation_id =
  report_id) и передаёт в `commit_map_report` (обязательство В
  транзакции commit'а); отказ sync-зеркала слоя 1 — 500 с честным
  текстом (`committed_projection_pending`, `operation_id`,
  `watermark`, контракт повтора), фиксируемая строка «фиктивный
  rollback не сообщается»; pause/resume/checkpoint/restore мигрированы
  в `_commit_run_level` (CAS `expected_context_id` = хранимый контекст
  момента чтения; restore — легитимный сдвиг контекста по паттерну
  коррекций 6A; commit ПЕРЕД сохранением сессии).
* **Worker и staged cleanup (§25.4)**: `run_delivery_recovery` —
  due-выборка, доставка по operation_id, дедуп по event_id в слое 1,
  `session_absent` → факт остаётся в ledger + mark_delivered + честная
  сводка, backoff `30s·2^(n−1)` кэп 3600, бюджет 5 → `failed`,
  неизвестный kind — отказ без изобретения операции;
  `sweep_orphaned_checkpoints` удаляет только снимки без ссылки в
  ledger (повтор — no-op); примитивы
  `checkpoint_snapshot_files`/`remove_checkpoint_snapshot`; runner
  `scripts/prograudit6b_recovery_runner.py` (--once/--interval/--skip-*).
* **Эндпоинты и классификатор (§25.5)**: `GET /runs/{run_id}/delivery`
  (обязательства + counts_by_state) и
  `GET /runs/{run_id}/delivery/{operation_id}` (classify_operation +
  receipt с watermark; поиск по привязке ключа + фолбэк
  event:/report:-паттернам; неизвестная операция — 200 not_executed,
  неизвестный запуск — 404); payload наружу не выдаётся;
  `classify_operation` — предшествование delivered/failed старше
  receipt, defensive-ветка «обязательство без receipt» —
  committed_projection_pending (не «успех»), mutation_applied —
  executed_documentation_pending.
* **Верификация исполнителя (§25.6)**: оракул 51 тест / 9 классов;
  RED-протокол 34 FAIL / 2 PASS / 15 skip на базе 56f431c —
  воспроизведён по файлу; versioned-пины миграций
  (test_research_runs/test_research_runs_postgres — 0005) на месте;
  пины дефектов не переписывались.

Граница наблюдаемости: аддендум v1.5-6B и код в одном коммите 8b309eb —
порядок «спецификация до кода» вне-коммитно не реконструируется (как в
7A/8-CERT).

## 3. Независимая верификация базлайнов (1:1 со средой песочницы)

Полный tests/api (100 файлов, 2 батча):
* **HEAD 8b309eb**: 1893 passed / 3 failed / 33 skipped;
* **база 56f431c** (worktree): 1857 passed / 3 failed / 18 skipped;
* дельта passed ровно **36** = Memory-набор нового
  tests/api/test_progress_audit_6b.py (51 собрано = 36 + 15 PG-skip
  без DSN); **множества отказов идентичны 1:1** (modeling_workflow
  catalog-only, models_backtest_neural_capacity LSTM-503,
  models_candidates naive-penalty — документированный средовой класс;
  forecasting_session ×16 в этой песочнице зелёные — средовое
  расхождение с журналом 19 failed, как зафиксировано в 7A/8-CERT) —
  **ДЕЛЬТА К БАЗЛАЙНУ 0**.
* Адресная серия исполнителя: test_progress_audit_6b.py — **36 passed /
  15 skipped** (Memory), на живом PostgreSQL (`pgserver`) — **51/51**;
  test_research_runs.py + 6b — 96 passed (repo-канал кампании).
* tests/unit+integration: HEAD и база — **1567 passed / 6 failed +
  3 errors / 24 skipped**, множества отказов идентичны 1:1
  (neural-registry fail-closed ×5, model_execution_contract,
  snapshot-fixture ×3; ets-симуляции в этой среде зелёные — средовое
  расхождение с журналом 10 failed) — **ДЕЛЬТА 0**.
* py_compile изменённых файлов OK; import apps.api.main OK
  (env -u DATABASE_URL). packages/ui и apps/standalone коммитом 8b309eb
  не затронуты (git show --stat) — jest/tsc не требовались (прецедент
  7A-CERT).

## 4. RED-протокол (база 56f431c, worktree чистой базы)

Протокол scripts/prograudit6bcert_red_raw.txt: СВОИ оракулы на базе —
**24 FAIL / 4 PASS-контролов / 0 SKIP**. Отказы: ENV-1/2/3 — модуль
delivery_outbox и реестр/математика отсутствуют; OUT-1..5 — контракт
outbox отсутствует; ATOM-2/3 — расширение батча отсутствует; MAP-1/2 —
обязательство в транзакции карты и worker отсутствуют (протестированное
500-тело карт на базе не содержит committed_projection_pending — пин
детали входил в MAP-1); RUN-1/2/3 — CAS с обязательством,
run-level required-путь, fault-timeline restore отсутствуют; SWEEP-1/2 —
sweep отсутствует; EP-1/2 — эндпоинты и классификатор отсутствуют;
REC-1/2 — реестр видов и дедуп доставки отсутствуют; PG-1/2/3 —
capability-check раньше DSN (модуля нет). Контролы GREEN на базе:
O-ENV-4 (контракт 6A — commit событий/receipt), O-ATOM-1 (дедуп того же
тела), O-CTRL-1 (пауза advisory-пути базы — 200 и факт), O-CTRL-2
(чекпоинт базы — 201 и staged-снимок; наблюдение base-совместимым
методом через каталог файлового слоя). Дельта HEAD−база: ровно
**24 RED→GREEN** при 4 стабильных контролах (финал 28/28).

## 5. Оракулы на СВОИХ данных — scripts/prograudit6bcert_oracles.py: 28/28 PASS

Корпус дизъюнктен исполнителю: поденный CSV «period,revenue,temp»
88 суток 2025 (исполнитель — «date,value,humidity» n=150 от 2026-02-01),
запуски RUN-C6B-*, отчёты rep-cert6b-*, операции op-c6b-*, ключи
cert6b-key-*, метки отказов «Cert-6B», свои бюджеты (max_attempts=2/7/1)
и метки времени. Свои швы отказа (не хелперы исполнителя): честная
Redis-симуляция слоя 1 — серверный документ как снимок каждого
успешного SET (write-copy), читатели получают копии (read-copy), отказ
SET не меняет серверный документ; инъекция отказа outbox-INSERT в
транзакции PG; nth-отказ сохранения слоя 1. Свои наблюдательные методы,
отсутствующие у исполнителя: полная серия backoff-математики 1..12 с
кэпом; полевая верификация roundtrip DeliveryTask (13 полей) + изоляция
копий + first-wins дедуп register; трёхкейсная семантика
bind_idempot_key (привязка пустого / НЕ-перезапись непустого / no-op /
иммутабельность); list_due на своих метках времени (будущее не due,
None первым, state-фильтр, limit); НОВОЕ направление атомарности —
отказ outbox-INSERT в транзакции на живом PG → полный откат (исполнитель
ломал шов подготовки СОБЫТИЙ; шов обязательства не проверялся);
дедуп-рекоммит ПОСЛЕ доставки (обязательство не сбрасывается);
fault-timeline restore «commit прошёл, второй save слоя 1 отказал»
(исполнитель проверял отказ ДО commit'а и отказ cache на картах);
sweep-скоупинг (сирот удалён / ссылаемый выжил / повтор no-op / явный
run_ids); пин НЕпубличности payload в эндпоинтах; таблица
предшествования classify_operation (6 строк); сводка worker'а
(second pass due=0); crash между доставкой и закрытием обязательства
(O-REC-2, волна 2); PG-группа: restart-выживание своими ключами,
outbox-INSERT rollback, due-фильтр + паритет list_due Memory/PG.
Группы ENV(4)/OUT(5)/ATOM(3)/MAP(2)/RUN(3)/SWEEP(2)/EP(2)/REC(2)/
CTRL(4)/PG(3).

## 6. Мутационная кампания СВОИХ мутантов — scripts/prograudit6bcert_mutations.py: 13/13 KILLED, 0 SURVIVED

Дизъюнкт классов от прежних кампаний (7A/8/2B/2A/4/1A/5B/6A правили
редьюсер/хук/маршруты Modeling — контур доставки не мутантовался):
MD-1 смерть first-wins дедупа register (перезапись), MD-2 потеря
bind_idempotency_key при регистрации, MD-3 переворот предшествования
classify_operation, MD-4 бюджет без исчерпания, MD-5 база backoff
30→31, MD-6 смерть дедупа доставки по event_id, MD-7 изобретение
операции для неизвестного kind, MD-8 sweep без guard'а ссылок, MD-9
run-level батч без обязательства, MD-10 закрытие обязательства ДО
сохранения проекции, MD-11 дрейф каталога миграций (0005 выпал),
MD-12 подмена сводки (session_absent→delivered), MD-13 смерть due-
фильтра PostgresDeliveryOutbox. Каналы: O — СВОИ 28 оракулов (с живым
pgserver для PG-группы); R — repo-канал исполнителя (test_progress_audit_6b
+ test_research_runs, 96 Memory-тестов). КОНТРОЛЬ перед каждым батчем:
оба канала зелёные; RESTORE-CHECK после каждого батча; якорь sha256
четырёх файлов; побайтовое восстановление после каждого мутанта и в
finally; кампания выполнялась последовательными батчами MD-1..4,
MD-5..9, MD-10..13 (каждый — полный якорь/контроль/восстановление).

**Волна 1 → волна 2 (открыто, продукт не менялся):** исходная сюита без
O-REC-2 оставила **MD-6 SURVIVED** — оба канала проверяли
идемпотентность worker'а на уровне СПИСКА due (после mark_delivered
повторной доставки нет), а дедуп по event_id упражняется только при
crash МЕЖДУ доставкой событий в слой 1 и mark_delivered («доставлено,
но обязательство ещё открыто» — тот же класс швов, что P08/P10).
Усиление: оракул O-REC-2 — прямая двойная доставка того же
pending-обязательства с пином «ровно одна копия / ноль дубликатов
event_id». Волна 2: MD-6 убит (KILLED-ORACLE-ONLY). Прецедент усиления:
7A-CERT CM-5, 2B-CERT D5/D6.

**Финальная грануляция: KILLED-BOTH=6 (MD-2,3,4,7,9,10),
KILLED-ORACLE-ONLY=6 (MD-1,5,6,8,12,13), KILLED-REPO-ONLY=1 (MD-11),
SURVIVED=0.** ORACLE-ONLY — repo-канал слеп к математике backoff (MD-5),
first-wins дедупу register (MD-1), sweep-guard'у ссылок (MD-8), сводке
session_absent (MD-12), PG due-фильтру (MD-13) → рекомендация F-6BC1.
REPO-ONLY (MD-11 — каталог миграций) — versioned-пин исполнителя несёт
самостоятельную ценность, мои оракулы каталог не пинают (симметрия
слепоты). Дисциплина: якорь sha256, побайтовое восстановление после
каждого мутанта и в finally, RESTORE-CHECK в батчах; git status
продуктовых файлов пуст после кампании.

## 7. Находки

* **F-6BC1 (РЕКОМЕНДАЦИЯ):** repo-канал исполнителя слеп к 5 классам
  мутантов: математика backoff (MD-5 — вся серия и кэп без единого
  пина), first-wins дедуп register (MD-1), sweep-guard ссылаемых
  снимков (MD-8 — их sweep-тест не создаёт живого чекпоинта рядом с
  сиротой), сводка session_absent (MD-12), PG due-фильтр (MD-13).
  Прецедент переноса пинов: F-7AC1/F-6A1/F-1A1/F-4C1/F-2A1/F-2B1/
  F-8C1 — решение тимлида.
* **R-6BC-1 (НАБЛЮДЕНИЕ):** fault-timeline restore «commit прошёл,
  отказ второго save слоя 1» — run-level путь отвечает защитным
  503 «Долговременный слой недоступен» (контур _durable_ops ловит
  любое не-HTTPException), тогда как v2-карта честно называет
  committed_projection_pending с operation_id/watermark (п.2/п.6).
  Состояние КОНСИСТЕНТНО и восстановимо (факт + обязательство в
  ledger, worker доставляет проекцию — удостоверено O-RUN-3),
  фиктивного rollback нет, но клиентская таксономия run-level ответов
  беднее карт: «сбой долговременного слоя» не различает «committed,
  проекция ждёт» от реальной недоступности ledger. Вопрос единой
  честной таксономии для runs.* — решение тимлида (не блокер:
  контракт §25.3 пинит атомарность и обязательство, а наблюдаемость
  состояния обеспечивает delivery-эндпоинт §25.5 — проверено).
* **R-6BC-2 (НАБЛЮДЕНИЕ):** «worker дважды» в обоих каналах (волна 1)
  упражнялся на уровне списка due; дедуп по event_id требует шва
  «доставка исполнена, закрытие обязательства не состоялось» — пин
  добавлен сертификацией (O-REC-2), перенос в repo-сюиты — вместе с
  F-6BC1.
* **R-6BC-3 (НАБЛЮДЕНИЕ):** MD-11 (каталог файлов-дублей миграций)
  убит ТОЛЬКО repo-пином исполнителя — мои оракулы каталог не
  пинают; взаимодополняемость каналов зафиксирована как свойство
  пары «исполнитель + сертификация».
* **R4 (ГРАНИЦЫ):** совпадают с §25.6: хук-зеркало — advisory
  (маркер в коде, P09/P22 честный остаток); коррекции DataFrame —
  unmigrated (executed_documentation_pending честен, миграция —
  отдельное решение); in-process авто-старт worker'а,
  health/backlog/lag, fail-closed required-режим хранилища (P21/F14)
  — AUDIT-6C; live PostgreSQL Render/Vercel и H29/H30 — вне
  периметра; Redis как носитель обязательств не используется (п.4).

## 8. Полный регресс (сверка с базами)

tests/api: HEAD 1893/3/33 против базы 1857/3/18 — дельта ровно 36 новых
Memory-тестов 6b, множества отказов идентичны 1:1 (ДЕЛЬТА К БАЗЛАЙНУ
0); адресная серия исполнителя 36/15 (Memory) и 51/51 (живой PG);
repo-канал кампании 96/15; tests/unit+integration 1567/6+3 на обеих
сторонах с идентичными множествами (ДЕЛЬТА 0); py_compile OK; import
apps.api.main OK. Продуктовые файлы по завершении кампании и
сертификации: git status/diff пусты (sha256 == HEAD); артефакты
сертификации untracked (скрипты + протоколы + акт + запись worklog).

## 9. Воспроизводимость

```
# RED (база)
git worktree add /home/z/my-project/wt-56f431c 56f431c
cp scripts/prograudit6bcert_oracles.py <worktree>/scripts/
cd <worktree> && python3 scripts/prograudit6bcert_oracles.py \
  --protocol scripts/prograudit6bcert_red_raw.txt   # 24 FAIL / 4 PASS
# GREEN (HEAD 8b309eb, живой pgserver для PG-группы)
CISSTAT_CERT6B_PG=1 python3 scripts/prograudit6bcert_oracles.py \
  --protocol scripts/prograudit6bcert_oracles_results.txt  # 28/28
# Fault-половина исполнителя на живом PG (контроль §25.6)
bash scripts/prograudit6b_pg_runner.sh "tests/api/test_progress_audit_6b.py -q"  # 51/51
# Кампания (батчи --ids MD-1..4 / MD-5..9 / MD-10..13; якорь+контроль+restore в каждом)
python3 scripts/prograudit6bcert_mutations.py --ids MD-1,MD-2,MD-3,MD-4
```
Окружение: Python 3.12.15, statsmodels 0.15.0, fastapi 0.128.0, pytest 9,
psycopg 3.3.6, pgserver; env -u DATABASE_URL (документированный
средовой класс песочницы, AUDIT-7A/8-CERT).

## 10. Вердикт

**PASSED.** Противоречий «код vs контракт v1.5-6B §25» не обнаружено:
гарантия durable имеет ЯВНЫЙ периметр (5 required / 4 advisory,
пересечение невозможно, физическое ограничение видов доставки);
обязательство регистрируется ТОЙ ЖЕ транзакцией commit'а — отказ
outbox-INSERT на живом PostgreSQL откатывает ВСЁ (ноль событий/строк
outbox/receipt/сдвига метаданных — новое направление отказа,
исполнителем не проверявшееся); отказ cache не отменяет committed
событие и честно называется (карта — 500 с committed_projection_pending
и watermark; run-level — защитный 503 при консистентном
восстановимом состоянии, находка R-6BC-1); worker доставляет по
operation_id идемпотентно вплоть до шва «доставлено, закрытие не
состоялось» (O-REC-2 после волны усиления), неизвестный kind — отказ
без изобретения операции, backoff/бюджет сходятся к честному failed;
sweep удаляет только сирот (ссылаемые выживают, повтор no-op);
read-after-write различает все пять состояний без фиктивного rollback и
не выдаёт payload; restart на живом PostgreSQL не теряет ни
обязательства, ни receipt; дедуп commit'а не дублирует обязательство и
не сбрасывает доставленное. RED обеих сторон воспроизведён (24 FAIL на
базе → 28/28 на HEAD), кампания 13/13 без выживших (волна 1→2
задокументирована), полный регресс с дельтой к базе 0, fault-tests на
настоящем PostgreSQL выполнены. Deliverable: ZIP
cisstat-prograudit6b-certification.zip → открытый контейнер сессии
(download + upload): docs/cert_prograudit6b_2026-10-13.md,
scripts/prograudit6bcert_oracles.py (+_oracles_results.txt),
scripts/prograudit6bcert_mutations.py (+_mutation_results.txt),
scripts/prograudit6bcert_red_raw.txt, worklog/worklog9.md. Без
commit/push (AGENTS.md). Следующие по нарезке плана — AUDIT-6C (§18)
и AUDIT-CERT (§19); перенос пинов F-6BC1 в repo-сюиты — решение
тимлида.
