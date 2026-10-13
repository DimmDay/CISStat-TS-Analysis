# Акт независимой сертификации PROGR-AUDIT-7A-CERT

**Задача:** AUDIT-7A — матрица Modeling и происхождение методов
(plan_progress_audit.md §15; контракт docs/progress_audit_contract.md,
аддендум v1.3-7A §23; спека spec_progress_audit.md F09/F13, P13/P19).
**Объект:** main@**b43e2eb** (коммит PROGR-AUDIT-7A). **База RED:**
main@2353e65 (коммит PROGR-AUDIT-8, предшественник по нарезке плана).
**Дата:** 2026-10-13. **Сертификатор:** независимый раунд — «мутанты на
своих мутантах, оракулы на своих данных» (данные, оракулы и классы
мутантов дизъюнктны исполнителю).
**Метод:** TDD RED→GREEN; независимая мутационная кампания на
незакоммиченном дереве (единый якорь + побайтовое восстановление, без
git checkout); полный регресс со сверкой дельты к базе.
**Вердикт: PASSED** (§10).

---

## 1. Постановка и сверка периметра

Постановка тимлида: «Синхронизируйся до b43e2eb. Изучи
spec_progress_audit.md и plan_progress_audit.md, а также текущий код по
основным файлам контура "Прогресс", записи в журнале worklog9.md.
Следующая задача: честно сертифицируй PROGR-AUDIT-7A — матрица Modeling
и происхождение методов. Спроектируй и реализуй данную Сертификацию.
Используй мутантов на своих мутантах, оракулов на своих данных. Следуй
правилам AGENTS.md. По завершении работы ВЫЗОВИ открытый контейнер
сессии DOWNLOAD/UPLOAD и выложи туда zip новых/обновленных файлов для
скачивания».

Синхронизация: рабочая копия переведена на b43e2eb (git checkout;
commit/push не выполнялись — AGENTS.md). Локальные артефакты предыдущей
сессии (сертификация AUDIT-8-CERT, не выгруженные из-за обрыва контекста)
сохранены в /home/z/my-project/backup_audit8_local/ и НЕ входят в
периметр: AUDIT-8-CERT уже интегрирован апстримом отдельным коммитом
685c40f (содержимое совпадает по составу файлов).

Карточка §15 — состав: (1) таблица producer → событие → result/outcome →
node/status → reason → фаза/Наставник → human report в поставке; (2) семь
типов P13 с ЯВНОЙ семантикой («не назначать всем done»); (3) реальные
носители фактов для problem_definition/data_structure/constraint_mapping/
baseline_estimation либо честное отсутствие («не создавать done по
открытию вкладки»); (4) связность job-фактов одним operation/job id,
обоснование skip, «позднее завершение старого job не повышает
current-context»; (5) метод/параметры и version/result reference
независимо от картинки узла, без журналирования каждого focus-refetch;
(6) сохранение готовности production-моделей и контрактов
BacktestPlan/EDA-fold. RED-карточки §15: P13/P19; cancel до completion;
skipped с причиной; результат старого job; иной метод при том же count;
отсутствующий producer не даёт вымышленного done.

## 2. Сверка реализации с кодовой базой

Все точки аддендума §23 на месте (сверено чтением кода):

* **Единый редьюсер** (app/core/node_status.py): EVENT_NODE_STATUS/
  EVENT_NODE_REASON расширены 7 типами P13 — словарь ПРОЦЕСНОЙ стадии
  Modeling: candidates_generated→done, selection_evaluated→**in_progress**,
  models_compared→done, diagnostics_run→done, tuning_skipped→done,
  tuning_job_started→**in_progress**, tuning_job_cancelled→**pending**
  (инвариант «не всем done» соблюдён; reason-тексты — факты; ключи
  reason-карты == статусы | payload-статусные — проверено оракулом
  G-ENV-2). Инвариант прежних карт сохранён; resolve_event_status
  для 7 типов проходит через ту же карту (гейт фазы — тот же).
* **Бейдж P16**: ключ `runnable_candidates` добавлен ПОСЛЕДНИМ в
  NODE_SUMMARY_COUNT_KEYS (относительный порядок прежних приоритетов не
  менялся — проверено G-SEM-5).
* **Носитель baseline** (§23.3): payload_carrier_node — чистая функция
  (backtest_run + payload.family_id=="baselines" → modeling/
  baseline_estimation; мусор payload → None, фантомных атрибуций нет);
  BASELINE_CARRIER_FAMILY_ID/NODE константы; PAYLOAD_CARRIER_REASON —
  свой честный текст («Baseline рассчитан на OOF-когорте…»), отличный от
  «Бэктест выполнен» главного узла; _apply_baseline_carrier — своя
  книжка деталей (касание/reason/P16-очистка бейджа) + статус через
  ЕДИНУЮ _commit_status; guard двойной записи (свой узел == носитель →
  носитель не дублирует); stage-level backtest_run (контракт E6) узел
  носителя получает; легаси без family_id / не-baseline семья — носитель
  не срабатывает.
* **Единая точка записи**: хвост apply() (гейты контекста AUDIT-3
  P25/F17/H27/H28 дословно + запись статуса/происхождения I10) вынесен
  в _commit_status — вторая реализация семантики отсутствует.
* **Честное отсутствие** (§23.3): problem_definition/data_structure/
  constraint_mapping — продюсеров нет, узлы pending без reason;
  никакого done по открытию вкладки (проверено на полном реалистичном
  контуре G-E2E-6).
* **Хук трассы** (apps/api/trace_hook.py): payload_keys — +`job_id`
  (jobs/start, jobs/{id}/cancel — связность одним operation/job id),
  +`reason` (tuning/skip, tuning/skip-pending); сознательные исключения
  PROGR-20 (jobs/{id}/step, /baselines, /backtest/exclude, tuning/start,
  tuning/step) не пересмотрены; dedupe-гейт прежний.
* **Маршрут** (apps/api/routers/modeling_session.py): /tuning/skip и
  /tuning/skip-pending ЭХОМ возвращают reason (в т.ч. unchanged-путь);
  форма ответов аддитивна (model_ids/status/execution_scope прежние).
* **UI** — без изменений (редьюсер серверный; NODE_ICON поддерживает
  in_progress; reason-тексты приходят из ответа).
* **Фаза/Наставник** (§23.2): фазу двигают только узловые факты — все
  7 типов теперь узловые (G-SEM-4); Наставник потребляет статусы
  ЕДИНОГО редьюсера без собственных копий (G-ORG-2 на живом next-step).
* **P19** (§23.5, совместно с AUDIT-4): DEDUPE_PARAM_KEYS=(method,mode)
  не менялись; origin в payload фактов — spec_version/selection_analysis_id/
  comparison_id/backtest_run_id/params_source/job_id.

Граница наблюдаемости: аддендум и код в одном коммите b43e2eb — порядок
«спецификация до кода» вне-коммитно не реконструируется (как в 8-CERT).

## 3. Независимая верификация базлайнов (1:1 с журналом)

Полный tests/api (98 файлов, 5 батчей в среде песочницы):
* **HEAD b43e2eb**: 1824 passed / 3 failed / 18 skipped;
* **база 2353e65** (worktree, те же батчи): 1805 passed / 3 failed /
  18 skipped;
* дельта passed ровно **19** = новый tests/api/test_progress_audit_7a.py
  (19 тестов исполнителя); **множества отказов идентичны 1:1** (те же 3
  теста: modeling_workflow catalog-only, models_backtest_neural_capacity
  LSTM-503, models_candidates naive-penalty — документированный средовой
  класс production-dispatch моделей; в этой песочнице forecasting_session
  ×16 зелёные — расхождение с журналом 19 failed средовое, как
  зафиксировано в 8-CERT) — **ДЕЛЬТА К БАЗЛАЙНУ 0**.
* Адресный repo-канал: test_progress_audit_7a.py + test_node_status_engine.py
  + test_progress_trace_hook.py = **139 passed** (контроль кампании).
* Jest полный: **167 сюит / 1997 тестов / 0 failed** (4 батча; сюиты 1:1
  с журналом 7A — 167; арифметика журнала 1992 = passed при 5 skipped в
  среде исполнителя, в этой среде 0 skipped).
* typecheck:all EXIT=0; py_compile изменённых Python-файлов OK; import
  apps.api.main OK (env -u DATABASE_URL).

## 4. RED-протокол (база 2353e65, worktree чистой базы)

Протокол scripts/prograudit7acert_red_repro.txt: СВОИ оракулы на базе —
**22 FAIL / 5 PASS-контролов**. Классы отказов: R1 — 7 типов без
семантики редьюсера (статус/фаза/Наставник не двигаются); R2 — носитель
baseline отсутствует (узел pending после реального расчёта); R3 — эхо
reason потеряно (в т.ч. unchanged-путь); R4 — job_id не в payload
запуска/отмены; P16 — бейдж пула не доезжает; ORG — два расчёта пула
неразличимы. Контролы GREEN на базе: G-ENV-1/2 (окружение + инвариант
карты из 13 типов), G-CAR-5 (guard двойной записи), G-ORG-2 (Наставник —
моделинг-фаза достигается каноническим backtest_run и на базе: класс
оракула честно переклассифицирован в контроль), G-ORG-3 (честный
fallback отчёта существовал до 7A). Дельта HEAD−база: ровно 22 RED→GREEN
при 5 стабильных контролах (финал 27/27).

## 5. Оракулы на СВОИХ данных — scripts/prograudit7acert_oracles.py: 27/27 PASS

Корпус дизъюнктен исполнителю: поденный CSV «dt,sales,promo,price»
57 суток 2023 (три числовых столбца; исполнитель — помесячный
«date,value,driver» 2021–2025), цели sales→price для смены контекста;
свои параметры контуров (candidates sliding 1/3/2/45 и expanding 3/2;
jobs max_trials=3/metric=mae/random_state=7, ключи cert7a-*), свои
reason-метки «Cert-7A…», min_oof_points=5. Свои наблюдательные методы,
отсутствующие у исполнителя: жизненный цикл start→cancel→start→cancel
(4 факта last-wins, различимость job_id); переоткрытие selection
повторной оценкой после model_selected; честное отсутствие done ДО
baseline-family backtest на живом контуре (носитель требует РЕАЛЬНЫЙ
факт — /baselines вне трассы не фабрикует done); неизменность узла
Baseline после не-baseline backtest; P16-гигиена бейджа НОСИТЕЛЯ
(счётчик следует за reason-событием); stage-level носитель (E6); guard
двойной записи; потребление Наставником единого редьюсера (живой
next-step); fallback отчёта с исходным типом; сквозная сверка бейджа
/trace с payload факта. Группы ENV(2)/SEM(5)/CAR(5)/JOB(3)/E2E(8)/ORG(4).
Ключевые смысловые проверки: «оценка ≠ выбор» (in_progress + переоткрытие
last-wins), «cancel до completion не даёт done» (pending + жизненный
цикл), «запуск — не результат» (in_progress, validity current→stale→
current через смену контекста с реалистичным ре-подтверждением
моделинг-entry), «skip закрывает вопрос решением» (done) c эхом
обоснования в ответе и факте (в т.ч. unchanged-путь — payload.status=
unchanged, узел стабилен), «отсутствующий producer не даёт
вымышленного done» (3 узла pending без reason на полном контуре).

## 6. Мутационная кампания СВОИХ мутантов — scripts/prograudit7acert_mutations.py: 15/15 KILLED, 0 SURVIVED

Дизъюнкт классов от кампаний 6A/5B/1A/4/2A/2B/3/8: семантические флипы
карты моделинг-стадии (CM-1..4), перепутанные reason-тексты (CM-5),
потеря бейджа пула (CM-6), смерть носителя — чужая семья (CM-7) и
P16-гигиена (CM-8), потеря связности job_id (CM-9), потеря reason в
факте (CM-10), потеря эха маршрута — штатный и unchanged-пути (CM-11/12),
механический done всем 7 (CM-13), смерть канала фиксации статуса
носителя (CM-14), потеря происхождения контекста _status_ctx (CM-15).
Каналы: O — СВОИ 27 оракулов; R — repo-канал исполнителя (139 тестов).
Контроль перед каждым батчем: оба канала зелёные.

**Волна 1 → волна 2 (открыто, продукт не менялся):** CM-5 SURVIVED —
оба канала сравнивали reason-тексты с САМОЙ картой (самореференция:
подмена текстов внутри карты самосогласованна). Усиление своего оракула
G-SEM-2 литеральными пинами текстов §23.1 (сверка с контрактом, не с
картой) — прецедент 2B-CERT D5/D6. Волна 2: CM-5 убит.

**Финальная грануляция: KILLED-BOTH=9 (CM-1..4, 7, 9..11, 13..15),
KILLED-ORACLE-ONLY=6 (CM-5, 6, 8, 12 + CM-5 волна 2), SURVIVED=0.**
ORACLE-ONLY-мутанты — repo-канал слеп (карта-относительные пины,
отсутствие бейдж-пинов, unchanged-эхо) → рекомендация F-7AC1.
Дисциплина: якорь sha256 трёх файлов; побайтовое восстановление после
каждого мутанта и в finally (RESTORE-CHECK в каждом батче); git diff
пуст; единственный инцидент — прерывание кампании таймаутом песочницы
(оставленный мутант CM-4 обнаружен git status и восстановлен немедленно,
до продолжения; в протоколе не искажает ничего — результат батча с ним
не записывался).

## 7. Находки

* **F-7AC1 (РЕКОМЕНДАЦИЯ):** repo-канал исполнителя слеп к 4 классам
  мутантов: литеральные reason-тексты (CM-5 — самореференциальная
  проверка по карте), бейдж пула runnable_candidates (CM-6), P16-гигиена
  бейджа носителя (CM-8), эхо reason на unchanged-пути (CM-12). Прецедент
  переноса пинов: F-6A1/F-1A1/F-4C1/F-2A1/F-2B1/F-8C1 — решение тимлида.
* **R-7AC-1 (НАБЛЮДЕНИЕ):** параметр strategy расчёта пула не входит в
  whitelist payload_keys хука — journaled origin candidates_generated
  это spec_version и состав пула (runnable/catalog_only/blocked); клетка
  §23.1 контракта выполняется как утверждено, вопрос полноты
  происхождения методики — к тимлиду (одна строка payload_keys, если
  решит усилить; human-шаблон — AUDIT-7B).
* **R-7AC-2 (НАБЛЮДЕНИЕ):** факт tuning_skipped сеётся и на
  unchanged-пути /tuning/skip-pending (hook — response-based). Контракт
  §23.1 допускает (строка таблицы включает skip-pending со status в
  payload); повторное решение не меняет закрытый узел (done стабилен,
  оракул G-E2E-5) — фабрикации нет, наблюдение о семантике факта.
* **R-7AC-3 (НАБЛЮДЕНИЕ):** смена цели сбрасывает passport-историю
  (passport_history_reset) — реалистичный контур нового job требует
  ре-подтверждения modeling_entry + пула; honesty-цепочка
  current→stale→current удостоверена полным контуром (G-JOB-3).
* **R4 (ГРАНИЦЫ):** совпадают с §23.6: human-шаблоны семи типов и
  версии методических пояснений — AUDIT-7B (fallback честен, тип/ids
  сохраняются — G-ORG-3); сознательные исключения PROGR-20 не
  пересматривались; полная транзакционность доставки — AUDIT-6B;
  /baselines вне трассы — факт контура это backtest baseline-модели.

## 8. Полный регресс (сверка с базами)

tests/api: HEAD 1824/3/18 против базы 1805/3/18 — дельта ровно 19 новых
тестов 7a, множества отказов идентичны (ДЕЛЬТА К БАЗЛАЙНУ 0); repo-канал
139/0; Jest 167/1997/0 (сюиты 1:1); typecheck:all EXIT=0; py_compile OK;
import apps.api.main OK. Продуктовые файлы по завершении кампании и
сертификации: git diff пуст (md5 == HEAD).

## 9. Воспроизводимость

```
# RED (база)
git worktree add /home/z/my-project/wt-2353e65 2353e65
cp scripts/prograudit7acert_oracles.py <worktree>/scripts/
cd <worktree> && env -u DATABASE_URL python3 scripts/prograudit7acert_oracles.py \
  --protocol scripts/prograudit7acert_red_raw.txt     # 22 FAIL / 5 PASS
# GREEN (HEAD b43e2eb)
env -u DATABASE_URL python3 scripts/prograudit7acert_oracles.py   # 27/27
# Кампания
env -u DATABASE_URL python3 scripts/prograudit7acert_mutations.py # 15/15 KILLED
```
Окружение: Python 3.12.15, statsmodels 0.15.0, fastapi 0.128.0, pytest 9;
env -u DATABASE_URL (документированный средовой класс песочницы).

## 10. Вердикт

**PASSED.** Противоречий «код vs контракт v1.3-7A §23» не обнаружено:
семь типов P13 имеют ЯВНУЮ семантику единого редьюсера с инвариантом
«операция ≠ результат» (всем done НЕ назначено; механический done убит
мутантом CM-13); baseline_estimation несёт РЕАЛЬНЫЙ носитель факта
(backtest_run family_id=baselines) со своим честным reason и P16-гигиеной
бейджа; problem_definition/data_structure/constraint_mapping — честное
отсутствие (done не фабрикуется ни одной вкладкой, ни /baselines);
job-факты связаны одним job_id; обоснование skip эхом в ответе и в факте
(включая unchanged-путь); поздний старый job не повышает current-context
(current→stale→current удостоверено); происхождение метода/параметров в
payload независимо от картинки узла; P19 сохранён; готовность
production-моделей и контракты BacktestPlan/EDA-fold не тронуты;
UI не менялся (редьюсер серверный). RED обеих сторон воспроизведён,
кампания 15/15 без выживших, полный регресс с дельтой к базе 0.
