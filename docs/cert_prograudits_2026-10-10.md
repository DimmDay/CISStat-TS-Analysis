# Акт независимой сертификации PROGR-AUDIT-S-CERT (2026-10-10)

**Задача:** plan_progress_audit.md §5, AUDIT-S — версионированная схема событий,
идентичность и время (коммит 4cd68be поверх deaed93).
**Аудитор:** независимая сессия (PROGR-AUDIT-S-CERT). Правила AGENTS.md соблюдены:
commit/push НЕ выполнялись; продуктовый код и тесты репозитория не изменялись —
только артефакты аудита (6 новых файлов, все untracked; `git diff HEAD` пуст).
**Постановка тимлида:** «честно сертифицируй AUDIT-S — схема событий, идентичность
и время. Используй мутантов на своих мутантах, оракулов на своих данных».
**Окружение:** свежий контейнер; лёгкая группа рецепта PROGR-25-A-CERT R6
(statsmodels 0.15.0, pandas 2.3.3, prophet 1.5.0, fakeredis, PyWavelets/pandera/
arch/ruptures/statsforecast), Python 3.12.14; node_modules восстановлен npm ci.

---

## 1. Сверка реализации с кодовой базой (4cd68be)

Все точки карточки §5 и контракта v0.2-AUDIT-S §12 на месте:

- `apps/api/trace_events.py` — 9 аддитивных Optional-полей envelope v2 на
  `TraceEvent`; `to_dict` включает ТОЛЬКО заполненные (v1 — ровно 9 ключей);
  `from_dict`/`normalize_trace_event_dict` восстанавливают envelope через
  `_typed_envelope` (мусор отброшен на границе; bool-подмена int отсечена;
  валидно типизированное неизвестное ЗНАЧЕНИЕ проходит — «журнал, не реестр»);
  `EVIDENCE_LEVELS` (4 уровня), `EVIDENCE_LEVEL_BY_EVENT_TYPE` (реестр полного
  объединения типов стадий и run-level), payload-aware override
  `target_column_changed source=auto → server_result` (дефолтный actor в выводе
  не участвует), `ENVELOPE_REQUIREMENTS` per-уровень, `validate_envelope`
  (v1 — не нарушение); идентичность: `derive_stable_event_id` — uuid5
  фиксированного namespace от канонического содержимого (json sort_keys),
  `normalize` для legacy без id ДЕТЕРМИНИРОВАН; время: `mark_honest_time`
  (degraded/substituted, идемпотентность, сам ts не переписывается);
  порядок: `merge_canonical_events` (dedupe строго по event_id, первый источник
  приоритетен, несловарные пропускаются) + `canonical_event_order` (ветка
  sequence только при полном покрытии; нечитаемые ts — в конец, stable);
  `stamp_envelope` — точка принятия v2 продюсером (ValueError на незнакомом
  поле); `canonicalize_stored_event` — сохранение идентичности артефактов.
- `apps/api/routers/progress.py` — адаптер прогнозов на canonicalize_stored_event;
  `GET /trace` на merge_canonical_events (sort_events_chronologically отчёта
  не тронут — миграция AUDIT-5B).
- `apps/api/research_runs.py` — mark_honest_time на границе записи ОБОИХ store
  (Memory: substituted=False; Postgres: substituted=True).
- `apps/api/schemas.py` — ForecastTraceEventSchema + 9 Optional-полей.
- `packages/ui/lib/progress.ts` — TraceEventInfo + envelope-поля (JSDoc);
  `lastCheckpointableEvent` — stage-фильтр forecasting при сохранении семантики §5.1.
- Versioned-обновление оракула PROGR-10 (контракт §12.6):
  `test_progress_panel.py::test_artifact_events_carry_stable_identity_not_anchors`
  (старое имя-пин дефекта F11 удалено) + кейс «forecasting с id — не якорь» в
  `progress.test.ts`.
- Инструмент аудита не тронут: `scripts/progress_audit_readonly.py`,
  `progress_audit_readonly_results.json`, `progress_audit_checks.txt` — md5
  рабочих файлов == git HEAD; коммит 4cd68be их не содержит (оракул S1).

## 2. Независимая верификация базлайнов (1:1 с worklog9)

| Прогон | Заявлено разработчиком | Воспроизведено аудитором |
|---|---|---|
| Ядро (test_trace_events + test_node_status_engine) | 92 passed | **92 passed (3.55s)** |
| Адресные сюиты (trace_hook + panel + research_runs + audit_s + trace_events) | 196 passed | **196 passed (12.03s)** |
| Полный tests/api + tests/integration | 1547 passed / 19 failed / 1 skipped | **1547 passed / 19 failed / 1 skipped (194.88s)** |
| Jest монорепо | 160 сюит / 1912 тестов, все зелёные | **160/1912, все зелёные** |
| typecheck:all | чисто | **чисто** |

Набор 19 failed идентичен задокументированному средовому классу
(16 test_forecasting_session параметрическая + modeling_workflow +
neural_capacity + models_candidates — лёгкое окружение, нейро-fail-closed).
НОЛЬ новых падений, ноль «исцелений».

## 3. RED-воспроизведение на deaed93 (до AUDIT-S)

Метод: git-worktree deaed93 (рабочее дерево аудита не покидало 4cd68be);
прогон ТОЛЬКО своих оракулов с pre-registered классификацией (таблица
EXPECTED_RED зафиксирована в шапке скрипта ДО отката).

**Результат: полное совпадение — 38 KILLER упали / 3 GUARD зелёные,
ложно-красного нет.**

- Поведенческие API-KILLER (не импортируют новых функций): P2 (зеркало одного
  event_id дублируется — merge нет), P3 (артефактное событие без event_id,
  F11), P4 (адаптер теряет мою идентичность), P5 (envelope не доходит до
  /trace: TypeError конструктора TraceEvent — envelope-полей нет).
- Unit-группы (I/A/M/E/T/V/S2/S3): ImportError новых API AUDIT-S — честная
  фиксация отсутствия (прецедент PROGR-24-A-CERT).
- GUARD (зелёные на обеих базах, классы совпадающего поведения): P1 (явная
  идентичность слоя 1 стабильна и ДО AUDIT-S — F11 касался только адаптера
  артефактов), P6 (мусор в слое 1 не роняет /trace), S1 (git-факт).
- Восстановление: worktree удалён; рабочее дерево аудита — md5-контроль
  (только untracked-артефакты сертификации).

Протокол: scripts/prograuditscert_red_repro.txt.

## 4. Оракулы на СВОИХ данных — scripts/prograuditscert_oracles.py: 41/41 GREEN

Свои данные: wind_hourly.csv (timestamp,windspeed; 96 часовых точек с
2026-03-01, сид 20261010, генерируется детерминированно скриптом); run_id
RUN-CERTS-W01..W03; event_id c-wind-*; actor «operator» (≠ user/system
разработчика); ts 2026-03-15T08:30:00+00:00 / нечитаемый «2026-03-15 08:30
wind»; типы-представители уровней model_card_generated /
outliers_profile_status / tuning_skipped / checkpoint_saved (≠ пара
разработчика upload_completed/profile_viewed). Сюит НЕ копирует
test_progress_audit_s.py — углы другие.

- **P-группа (живой API, 6):** P1 загрузка своего CSV → стабильность явной
  идентичности слоя 1 + v1-форма без envelope; P2 дедупликация зеркала
  своего прогнозного события (слой 1 + артефакт, один id → 1 в /trace);
  P3 legacy-артефакт — стабильный id между чтениями, узел из типа, run_id
  не выдуман; P4 канонический артефакт — мои event_id/run_id/actor в /trace
  как есть; P5 мой envelope слоя 1 доходит до HTTP-JSON (schema_version/
  evidence_level/operation_id); P6 мусорный envelope в слое 1 — /trace 200,
  мусор не прошёл.
- **I/A (6):** детерминизм stable-id + чувствительность к каждому из 6 полей
  материала + канонический порядок ключей payload; правило normalize == derive;
  разные payload → разные id; адаптер сохраняет мою идентичность и мой
  envelope; fail-safe несловаря/пустого типа.
- **M (8):** dedupe по одному id с ПРОВЕРКОЙ ВЫЖИВШЕЙ КОПИИ (мой payload-
  маркер origin=layer1 — первый источник приоритетен); независимые одинаковые
  результаты не склеены; byte-идентичные legacy — один факт, другой payload —
  два; хронология перемешанного корпуса; нечитаемые/пустые ts — в конец,
  взаимный порядок сохранён; полная sequence-примеса [5,1,3]→[1,3,5];
  частичная sequence НЕ переупорядочивает; несловарный мусор пропущен.
- **E (6):** полнота/точность реестра == объединению типов стадий и run-level
  (без пропусков и лишних); мои представители 4 уровней; payload-aware
  auto/user/чужой-источник/отсутствие/payload=None; неизвестный тип → None;
  ENVELOPE_REQUIREMENTS == независимая транскрипция контракта §12.3;
  validate_envelope: полный user_decision — [], нарушение именует поле, v1 —
  ровно одно «не нарушение», schema_version=3 и вне-реестровый level —
  нарушения.
- **T (6):** мой нечитаемый ts не подменён (degraded, raw_ts мой, observed_at
  ISO); валидный/пустой — без time_quality; идемпотентность; substituted/
  degraded семантика mark_honest_time на моём событии; Memory-store на моём
  run — raw сохранён + degraded, валидный не тронут; контракт строки БД
  (_ts_to_db → datetime) сохранён.
- **V (6):** v1-форма ровно 9 ключей; авто-штамп моего типа + приоритет
  явных значений + ValueError на незнакомом поле; v2 to_dict аддитивен и
  обратим (dataclass-равенство); щит мусора на моём наборе + typed-unknown
  VALUE проходит (evidence_level='wind_level', schema_version=9);
  bool-подмена int отсечена; ForecastTraceEventSchema принимает мой envelope
  аддитивно и отдаёт в JSON (V6, см. §6).
- **S (3):** git-факт нетронутости инструмента аудита; versioned-обновление
  оракула PROGR-10 (новое имя есть, старое удалено); TS-кейс AUDIT-S в
  progress.test.ts.
- TS-оракул packages/ui/lib/prograuditscert_anchor_oracle.test.ts: 4/4 GREEN —
  forecasting-событие С моим стабильным id не якорь (stage-фильтр), мои не-
  forecasting типы якорятся, mixed-корпус, envelope-поля TraceEventInfo
  принимают мои значения.

## 5. Мутационный прогон СВОИХ мутантов — 18 мутантов, ноль переживших оба канала

Каналы: repo (адресные сюиты разработчика: pytest test_progress_audit_s +
test_trace_events + test_progress_panel; для TS-мутанта — jest
progress.test.ts) + oracle (свой сюит; для TS-мутанта — мой TS-оракул).
Дисциплина: backup-копии с побайтовым восстановлением и md5-контролем
каждого шага и в finally (урок PROGR-19); аварийный останов при неединичном
якоре правки.

**Набор ДИЗЪЮНКТЕН 4 мутантам разработчика** (uuid5→uuid4; dedupe отключён;
substituted сломан; sequence инвертирован) — пересечение по семантике только
по каноническому зеркалу, реализация своя (CM-10 dedupe по тип+ts; CM-8
any/all; CM-9 inf/-inf).

| Мутант | Семантика | Исход |
|---|---|---|
| CM-0 | no-op контроль харнесса | SURVIVED в обоих (достоверность) |
| CM-1 | payload-aware override снят | KILLED-BOTH |
| CM-2 | to_dict включает незаполненные поля | KILLED-BOTH |
| CM-3 | типовой щит границы чтения снят | KILLED-BOTH |
| CM-4 | bool-гард int снят | KILLED-ORACLE-ONLY (repo-гэп) |
| CM-5 | method исключён из обязательных server_result | KILLED-ORACLE-ONLY (repo-гэп) |
| CM-6 | mark_honest_time вырожден | KILLED-BOTH |
| CM-7 | normalize не маркирует нечитаемый ts | KILLED-BOTH |
| CM-8 | частичная sequence переупорядочивает (all→any) | KILLED-BOTH |
| CM-9 | нечитаемые ts в начало (inf→-inf) | KILLED-BOTH |
| CM-10 | dedupe по (тип, ts) вместо event_id | KILLED-BOTH |
| CM-11 | адаптер отбрасывает явный id | KILLED-BOTH |
| CM-12 | stamp_envelope принимает незнакомое поле | KILLED-BOTH |
| CM-13 | TS stage-фильтр якорей снят | KILLED-BOTH (repo: jest; oracle: мой TS) |
| CM-14 | Memory-граница без маркировки | KILLED-BOTH |
| CM-15 | Forecast-схема без envelope-полей | KILLED-BOTH (после усиления, §6) |
| CM-16 | payload исключён из материала stable-id | KILLED-BOTH |
| CM-17 | приоритет второго источника при merge | KILLED-ORACLE-ONLY (repo-гэп) |

Пересчитанный итог: **KILLED-BOTH: 14 | KILLED-ORACLE-ONLY: 3 (все три —
предсказанные до прогона repo-гэпы) | SURVIVED: 1 (CM-0, контроль).
Переживших ОБА канала — НОЛЬ.** Предрегистрация исходов подтверждена
полностью (см. §6 — единственное расхождение первой итерации разрешено
усилением оракула с открытой фиксацией).

Протокол: scripts/prograuditscert_mutation_results.txt (включая раздел
«Эволюция оракула»).

## 6. Эволюция оракула (открытая фиксация, прецедент PROGR-24-C-CERT R4)

Предрегистрация CM-15 (KILLED-BOTH) в ПЕРВОМ прогоне не сбылась: фактический
исход KILLED-REPO-ONLY. Причина — исходный набор оракулов аудитора не
содержал пробы ForecastTraceEventSchema (P5 проходит через
ProgressTraceResponse и на снятие полей Forecast-схемы не реагирует); repo-
канал убил мутанта собственным тестом. Мера: набор усилен оракулом V6
(ForecastTraceEventSchema на своих значениях + model_dump), полный перегон
41/41 GREEN, RED перегнан на deaed93 (38/3, полное совпадение), CM-15
перегнан — KILLED-BOTH, md5-восстановление сошлось. Полный перегон остальных
17 мутантов не требовался: V6 добавляет независимый канал, не ослабляя ни
одного зафиксированного исхода. Ценность находки: двухканальная схема
вскрыла гэп собственного набора аудитора мутационно, а не оставила скрытым.

## 7. Находки (акт §7)

- **F-CERTS1 (МЕТОДОЛОГИЧЕСКАЯ, закрыта в ходе сертификации):** гэп исходного
  набора оракулов по ForecastTraceEventSchema — выявлен расхождением
  предрегистрации CM-15, закрыт V6 (см. §6).
- **R1 (РЕКОМЕНДАЦИЯ, не блокер):** три repo-гэпа покрытия, предсказанные и
  подтверждённые: CM-4 (bool-подмена int в envelope не пинится мусор-тестом
  разработчика — bool-кейса в нём нет), CM-5 (обязательность server_result
  сверх causation_id не пинится — repo проверяет только user_decision/causation_id
  и форму таблицы), CM-17 (какая копия пережила merge, repo-тест не
  различает). Прикрыты оракулами аудита; рекомендуется перенести repo-пины
  ближайшей коммит-возможностью (прецедент TB-8 → PROGR-25-D).
- **R2 (НАБЛЮДЕНИЕ):** нулевая выживаемость обоих каналов — каждый пункт
  контракта §12 прикрыт минимум одним независимым каналом, ядро (идентичность/
  время/порядок/щит) — обоими.
- **R3 (НАБЛЮДЕНИЕ):** P1 корректно классифицирован GUARD — F11/P17 касался
  только адаптера артефактов; явная идентичность слоя 1 была стабильна и до
  AUDIT-S (это подтверждено поведенчески на deaed93).
- **R4 (НАБЛЮДЕНИЕ):** versioned-обновление оракула PROGR-10 выполнено по
  правилу (контракт §12.6, Донастройка_2 п.3): новое имя пинит исправленный
  контракт, старый пин дефекта удалён, семантика §5.1 доказана с двух сторон
  (repo-тест + TS-кейс + мой TS-оракул).
- **R5 (СРЕДОВЫЕ):** лёгкая группа рецепта R6; 19 средовых падений полного
  регресса идентичны базлайн-классу разработчика 1:1; prophet 1.5.0 (у
  разработчика эпохи AUDIT-S — 1.4.x в журнале не зафиксирован) на контракт
  задачи не влияет (readiness-гейт Modeling).

## 8. Вердикт

**PASSED.**

Ядро приёмки AUDIT-S подтверждено независимо, на своих данных: envelope v2
аддитивен и обратимо совместим (v1-корпус не меняет форму ни в одном
оракуле, включая HTTP-JSON /trace); идентичность legacy стабильна по всем
адаптерам и чувствительна к содержимому (I1 закрыт на уровне
схемы/адаптера/чтения); время честно (нечитаемый ts не подменяется,
degraded/substituted с raw_ts/observed_at, идемпотентно, контракт строки БД
сохранён); единое чтение канонического порядка введено (dedupe строго по
event_id, первый источник приоритетен, частичная sequence не
переупорядочивает, нечитаемые — в конец stable); уровни доказательности
полны и payload-aware (дефолтный actor не участвует); таблица
обязательности соответствует контракту v0.2-AUDIT-S; щит границы чтения
деградирует, не роняет; якорная семантика §5.1 сохранена с переносом
механизма защиты (versioned-обновление по правилу). Базлайны разработчика
воспроизведены 1:1; RED честный (38/3, ложно-красного нет); 41/41 оракулов
на своих данных; 18 своих мутантов, ноль переживших оба канала, набор
дизъюнктен мутантам разработчика. Противоречий «код vs журнал» не
обнаружено.

Ограничения (унаследованы, планом предусмотрены): sequence никем не
присваивается (AUDIT-6A); Postgres-строка слоя 2 остаётся v1 до миграции
AUDIT-6A (durable-хранение маркировки); продюсеры пока сеют v1-форму
(переход по §7 «читатели раньше писателей» — AUDIT-C/6A/6B/7A); live
PostgreSQL/Render/Vercel не проверялись (вне периметра задачи).

## 9. Поставка

Deliverable: ZIP `cisstat-prograudits-s-certification.zip` → открытый
контейнер сессии (download): docs/cert_prograudits_2026-10-10.md (настоящий
акт), scripts/prograuditscert_oracles.py (+ .txt), 
scripts/prograuditscert_red_repro.txt, scripts/prograuditscert_mutations.py
(+ _mutation_results.txt), packages/ui/lib/prograuditscert_anchor_oracle.test.ts,
worklog/worklog9.md. Без commit/push (AGENTS.md).
