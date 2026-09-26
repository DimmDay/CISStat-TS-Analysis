# Акт независимой сертификации Task PROGR-6 (2026-09-26)

**Задача:** PROGR-6 — Наставник v1: §7.1 «Следующий шаг» + §7.2 sanity-правила
(правило-движок без LLM, пороги `rules/mentor.yaml` §12 п.7).
**Коммит сертификации:** `main@564cd95` (синхронизация `git clone`, рабочее дерево
чистое; commit/push запрещены — AGENTS.md).
**Сертификатор:** независимый аудитор (не автор задачи; методология
PROGR-1-CERT / PROGR-2 / PROGR-3 / OUTL-1-CERT: оракулы на своих данных +
мутационный анализ).
**Вердикт: PASSED WITH REMARKS** (замечания N-1…N-4 не блокируют приёмку;
см. §6).

---

## 1. Объём изучения

Изучены дословно: `AGENTS.md`; `spec_progress.md` (§7, §7.1, §7.2, §8, §11, §12
п.7/п.8); `plan_progress.md` (строка PROGR-6 + зависимости); реализация:

| Файл | Роль в PROGR-6 |
|---|---|
| `app/core/mentor_rules.py` (новый, 773 стр.) | правило-движок: SANITY_RULES / HISTORY_RULES / NEXT_STEP_RULES (8), evaluate_*, derive_node_statuses, stage_node_summary, phase_text, load_mentor_config (fail-closed) |
| `rules/mentor.yaml` (новый) | пороги §12 п.7: 0.2 / 0.3 / 10 мин / 3 стратегии |
| `apps/api/routers/progress.py` (+221) | `GET /v1/progress/runs/{run_id}/mentor/next-step` (@_durable_ops: 404/503), `POST /v1/progress/mentor/sanity-check` (чистое вычисление, fail-closed 422) |
| `packages/ui/lib/mentor.ts` (новый) | клиентский маппинг §7.2, worstStdStats, best-effort запросы |
| `MentorPanel.tsx`, `MentorInlineWarning.tsx` (новые) | панель Наставника (deep-link, history-замечания), инлайн-баннер без блокировки кнопки |
| `Preprocessing{Missing,Outliers,Regularity}Pipeline.tsx`, `ProgressCheckpointBar.tsx`, `ProgressDrawer.tsx`, `packages/ui/index.ts` | интеграция: запрос после preview ДО apply, кнопка «Наставник →», экспорты |
| `tests/api/test_mentor_rules.py` (новый, 46 тестов), фронтенд-сьюты | TDD-контур коллеги |

## 2. Верификация заявленных коллегой фактов

| Заявление (worklog8.md, PROGR-6) | Проверка | Итог |
|---|---|---|
| test_mentor_rules.py 46/46 | локальный прогон | ✅ 46 passed |
| tests/api: 1046 passed / 3 failed — средовой baseline | полный прогон | ✅ 1046 passed / 3 failed / 1 skipped; те же 3 падения воспроизведены на родителе `1e00ab1` (modeling_workflow catalog-only, neural_capacity память хоста, models_candidates unsupported-гейт) — НЕ регрессии PROGR-6 |
| jest: 145 сьютов / 1726 тестов, все зелёные | полный прогон | ✅ 145/145, 1726 passed |
| typecheck:all чисто | см. §5 (новый TS-оракул компилируется jest-трансформом; продукт-файлы не менялись) | ✅ (косвенно) |
| пороги в YAML, не хардкод | мутации M3/M21/M22/M23 | ✅ подтверждено убиением |
| float-находка: доля как (before−after)/before | мутация M4 (`1 − after/before`) | ✅ M4 убит граничным тестом — находка под защитой |

## 3. Оракулные тесты на своих данных (независимая проверка)

Скрипт `scripts/audit_scripts/progr6cert_oracles.py` — **6/6 PASSED**
(seed 260926, данные сертификатора, не копии assert-ов коллеги):

- **OR-1 Целостность реестров (детектор мёртвых правил).** Все пары
  (stage, node) условий 8 on_demand-правил существуют в `STAGE_NODES`;
  все 12 типов `_EVENT_STATUS_MAP` реально испускаются платформой
  (TRACE_ROUTES хука ∪ FORECAST_EVENT_TYPES ∪ run-level); состав
  SANITY/HISTORY-реестров и триггер-семейства дословно §7; «мечется» без
  deep-link. Мёртвых правил нет.
- **OR-2 Независимая реимплементация §7.2** (чистая математика спеки) на
  **500 рандомизированных preview-исходах** + детерминированные границы:
  ровно 0.2 — тишина; std_after=0 — срабатывает; рост строк (fictitious_zero)
  — тишина. Ноль расхождений с движком.
- **OR-3 Независимая реимплементация окна «метаний»** на **300
  рандомизированных потоках** (наивный/битый ts, дубли стратегий,
  TraceEvent-объекты, apply внутри/вне окна) + границы: apply ровно на
  window_start снимает; apply вне окна не снимает; preview ровно на
  window_start учитывается; документирована cross-node семантика (см. N-1).
  Ноль расхождений.
- **OR-4 Зеркало derive_node_statuses**: фикстура 12 событий → ожидаемый
  словарь статусов (последнее событие выигрывает; run-level N-2 пропущен;
  фантомы пропущены; forecasting-узел выведен из типа при node_id=None).
- **OR-5 Живая проба API (TestClient)**: 404 чужого run_id; рекомендация
  `regularity_before_decomposition` c deep-link из моей трассы; ОДНА
  рекомендация; thrashing в `history_warnings`; sanity-check с реальной
  формой preview-ответа Мастера (поля `DatasetMissingCorrectionResponse`
  сверены со `schemas.py`): no_effect + over_aggressive одновременно;
  drop_rows 40% → excessive_data_loss; **ровно 30% — тишина**; 422 на
  фантомный узел/неизвестную стадию.
- **OR-6 Конфиг §12 п.7**: канонические значения 0.2/0.3/10/3; fail-closed
  матрица (нет файла / битый YAML / нет секции / строковый порог /
  **bool-порог** — все ImportError); документирование дегенеративных
  числовых порогов (N-2).

Фронтенд-оракул `packages/ui/lib/progr6cert_oracles.test.ts` — **9/9 PASSED**:
свойства worstStdStats (минимум отношения after/before, пропуск нулевых/
нечисловых std, null при отсутствии валидных колонок); точная проекция
buildCorrectionOutcomeSummary (состав ключей snake_case); best-effort
контракты (HTTP 503/404, сбой сети, битая форма ответа → `[]`/`null` не
исключения); кросс-слойное зеркало на фикстуре OR-4 (идентичные узловые
факты; документированное расхождение — frontend-зеркало PROGR-4 не имеет
layer-2 вывода forecasting-узла, см. §5-примечание).

Кросс-сверка контрактов (ручная, без скрипта): поля клиентского маппинга
(`total_missing/total_changed/total_still_missing/rows_removed/strategy/
method/total_violations_*/rows_*/columns[].stats_*/profile.total_rows`)
сверены с `apps/api/schemas.py` — все существуют и Optional-согласованы.

## 4. Мутационный анализ

`scripts/audit_scripts/progr6cert_mutations.py` (бэкенд) — **25 KILLED из 26**;
`scripts/audit_scripts/progr6cert_front_mutations.py` (фронтенд) — **4 KILLED
из 5**. Каждый мутант обязан быть убит сьютом коллеги ИЛИ независимыми
оракулами (убийца указан). Восстановление файлов байт-в-байт (sha256 + чистый
`git status`).

### 4.1 Бэкенд (26 мутантов app/core/mentor_rules.py, routers/progress.py, rules/mentor.yaml)

| ID | Класс ошибки | Убийца |
|---|---|---|
| M1 | no_effect тревожит при affected=0 | colleague |
| M2 | граница 0.2 включена (<=) | colleague |
| M3 | порог over_aggressive захардкожен | colleague |
| M4 | float-регрессия 1−after/before | colleague |
| M5 | граница 0.3 включена (>=) | colleague |
| M6 | потеря данных у не-drop_rows | colleague |
| M7 | «мечется» требует 4 стратегии | colleague |
| M8 | apply на границе окна не снимает | **oracle** |
| M9 | окно 30 мин вместо 10 | **oracle** |
| M10 | наивный ts ≠ UTC (TypeError) | colleague |
| M11 | preview на границе окна теряется | **oracle** |
| M12 | первое событие выигрывает | colleague |
| M13 | фантомные узлы возвращаются | colleague |
| M14 | forecasting-узел не выводится | colleague |
| M15 | default pending → done | colleague |
| M16 | инверсия приоритета §7.1 | colleague |
| M17 | sanity отдаёт только первое правило | colleague |
| M18 | снят гейт стадии — **SURVIVED, характеризован** (см. R-1) | — |
| M18b | сняты ОБА гейта (стадия+пара) | colleague |
| M19 | снят гейт пары (stage, node) | colleague |
| M20 | last_stage всегда upload | colleague |
| M21 | YAML 0.2 → 0.05 | colleague |
| M22 | YAML окно 10 → 60 | colleague |
| M23 | bool-порог проходит загрузчик | **oracle** |
| M24 | текст over_aggressive «в 1 раз» | colleague |
| M25 | потеря дедупликации стратегий | colleague |

### 4.2 Фронтенд (5 мутантов packages/ui/lib/mentor.ts)

| ID | Класс ошибки | Убийца |
|---|---|---|
| F1 | worstStdStats выбирает лучшую колонку | oracle+colleague |
| F2 | потеря guard нулевого std_before | oracle+colleague |
| F3 | перепутаны changed/still_affected | oracle+colleague |
| F4 | throw вместо return [] при !ok — **SURVIVED, характеризован** (см. R-2) | — |
| F4b | удалён catch-all (сеть/JSON роняют Мастер) | oracle+colleague |

Оба SURVIVED-мутанта охарактеризованы и НЕ являются дырами покрытия:
оба доказывают **избыточность защиты** (см. R-1/R-2), а дополняющие их
M18b/F4b убиты штатно.

## 5. Находки и замечания

- **N-1 (информационное, семантика «мечется»).** Текст §7.2 описывает узловую
  семантику («один и тот же узел за короткое окно») и второй паттерн
  «применение → повторная попытка другой стратегией»; реализация следует
  канонической лямбде §7.2 дословно — фильтра по node_id нет (3 разные
  стратегии на ТРЁХ разных узлах срабатывают — OR-3) и `correction_applied`
  в окне снимает предупреждение (второй текстовый паттерн не тревожится).
  Реализация = канон-пример спеки; расхождение «текст vs лямбда» — в самой
  спеке. Рекомендация: в Mentor v2 либо явно фильтровать по node_id, либо
  зафиксировать в спеке выбор «run-level семантика по канон-лямбде».
- **N-2 (робастность конфига).** `load_mentor_config` гарантирует «число, не
  bool», но не диапазон: `distinct_strategies: 1` тревожит с первой же
  попытки, `window_minutes: 0/-5` делают правило слепым (OR-6, демонстрация).
  Не нарушает §12 п.7 (значения калибруются ops-ом), но рекомендуется
  min/max-валидация в загрузчике при первой калибровке.
- **N-3 (косметика).** `_over_aggressive_text`: `round(1/factor)` может
  завышать формулировку для неканонических порогов (factor=0.26 → «в 4 раза»
  при фактической границе 3.85). Для канонического 0.2 текст точен («в 5 раз»).
- **N-4 (микро, входные данные).** Отрицательный `std_after` (некорректный
  клиент) проходит в over_aggressive и триггерит его; `worstStdStats`
  фильтрует только нечисловые/нулевые std. Для валидных данных недостижимо;
  можно усилить guard'ом `std_after >= 0` на досуге.
- **Примечание (зеркало).** Фронтенд-`deriveNodeStatuses` (PROGR-4, слой 1)
  не выводит forecasting-узел при node_id=None; бэкенд-версия — осознанное
  расширение под слой 2 (контракт PROGR-1). Расхождение зафиксировано
  кросс-фикстурой OR-4/OR-F4, поведение обеих сторон согласовано с их
  источниками данных.
- **R-1 (позитив, защита в глубину).** M18 SURVIVED: при снятии гейта стадии
  контракт 422 удерживает гейт пары (stage, node_id) — двойная защита
  fail-closed; M18b (оба гейта) убит. Избыточность здесь — свойство системы,
  не дыра тестов.
- **R-2 (позитив, best-effort двойной).** F4 SURVIVED: throw внутри try
  перехватывается catch-all — §12 п.8 «сигнал, не принуждение» защищён дважды;
  F4b (снятие catch-all) убит.
- **R-3 (позитив, TDD-находка под защитой).** Формула доли (before−after)/before
  страхована граничным тестом: мутант M4 «1 − after/before» убит ровно на
  кейсе «ровно 30%».

## 6. Соответствие приёмке plan_progress.md (строка PROGR-6)

| Критерий приёмки | Статус |
|---|---|
| Одно срабатывание §7.1 по priority | ✅ (evaluate_next_step по (priority, rule_id); мутации M16/M15 убиты; OR-5) |
| Весь список §7.2 | ✅ (evaluate_sanity; мутация M17 убита; OR-2/OR-5) |
| Предупреждение в Предпросмотре ДО apply, не блокирует кнопку (§12 п.8) | ✅ (запрос в else-ветке preview у трёх Мастеров; MentorInlineWarning не управляет кнопкой; best-effort — F4b/M-контур) |
| Пороги не хардкод | ✅ (MENTOR_CONFIG на вызове; мутации M3/M21/M22/M23 убиты) |
| TDD RED→GREEN | ✅ (46 бэктестов + фронт-сьюты в коммите; прогон зелёный) |

## 7. Воспроизведение

```bash
python scripts/audit_scripts/progr6cert_oracles.py          # ORACLES: 6/6 PASSED
python scripts/audit_scripts/progr6cert_mutations.py        # 25 KILLED + M18 характеризован
python scripts/audit_scripts/progr6cert_front_mutations.py  # 4 KILLED + F4 характеризован
pytest tests/api/test_mentor_rules.py -q                    # 46 passed
npx jest                                                    # 146 сьютов / 1735 тестов
```

## 8. Deliverable

ZIP: `cisstat-progr6-cert-mentor-v1.zip` (download контейнера сессии) — только
файлы текущей сертификации. НОВЫЕ: `scripts/audit_scripts/progr6cert_oracles.py`,
`scripts/audit_scripts/progr6cert_mutations.py`,
`scripts/audit_scripts/progr6cert_front_mutations.py`,
`packages/ui/lib/progr6cert_oracles.test.ts`,
`scripts/audit_scripts/progr6cert_mentor_act_2026-09-26.md` (этот акт).
ИЗМЕНЁННЫЙ: `worklog/worklog8.md` (запись PROGR-6-CERT). Без commit/push
(AGENTS.md). Продукт-код PROGR-6 не менялся.
