# Акт независимой сертификации Task PROGR-3

**Дата:** 2026-09-24
**Объект:** Task PROGR-3 из plan_progress.md — «Внутрисессионный слой трассы
(§5 слой 1) + хук записи событий (§4.2)», commit `38f1cb9` (main).
**Реализовал:** коллега (запись PROGR-3 в worklog/worklog8.md).
**Аудитор:** независимая сертификация по методике PROGR-1-CERT / PROGR-2-CERT /
Task 144 / FORECAST-1; правила AGENTS.md (commit/push запрещены).
**Инструменты аудитора:** `scripts/audit_scripts/progr3cert_crossverify.py`,
`progr3cert_oracles.py`, `progr3cert_mutations.py` (все — СВОИ данные/кодировка).

---

## 1. Предмет сертификации

Заявленный объём (worklog8, запись PROGR-3, commit 38f1cb9 — 9 файлов, +2188/−4):

| Компонент | Файл | Суть |
|---|---|---|
| Хук трассы | `apps/api/trace_hook.py` (новый, 584 стр.) | таблица 40 маршрутов путь→(stage, node_id, event_type), fail-closed валидация на импорте, resolve по сегментам, троттлинг profile_viewed (env, дефолт 300 с), чистый ASGI-middleware |
| Слой 1 §5 | `apps/api/session_store.py` | +run_id "RUN-XXXXXXXX", +pipeline_trace (cap 1000, вытеснение старейших, deepcopy payload — R1), ensure/append/read, граница чтения нормализует legacy 3-поля, сброс в set_dataset, SESSION_SCHEMA_VERSION 1→2 |
| Интеграция | `apps/api/main.py` | add_middleware(TraceHookMiddleware) ДО CORS |
| Тесты | `tests/api/test_progress_trace_hook.py` (новый, 770 стр.) | 40 тестов; `test_session_store.py` — якорь схемы 2 |

Границы задачи (заявлены исполнителем): чтение трассы наружу — PROGR-4;
долговременный слой/чекпоинты/restore — PROGR-5; forecasting-события хуком не
дублируются (4 call-site make_trace_event в ForecastRun.trace, унификация PROGR-5);
passport_captured пишется, но паспорт — не узел графа (§2).

## 2. Воспроизведение заявлений исполнителя — 8/8 ПОДТВЕРЖДЕНО

| № | Заявление | Прогон аудитора | Итог |
|---|---|---|---|
| 1 | Сьют 40 тестов | `pytest tests/api/test_progress_trace_hook.py` | **40/40** |
| 2 | session_store-сьют цел | вместе с хук-сьютом | **122/122** |
| 3 | Оракулы 12/12 (`scripts/progr3_oracles.py`) | повторный прогон | **12/12 PASSED** |
| 4 | Мутации 13/13 KILLED (`scripts/progr3_mutations.py`) | повторный прогон | **13/13 KILLED**, файлы восстановлены |
| 5 | Связка store+events+forecasting+graph = 272 | прогон связки без хука | **272**; с хук-сьютом 312 = 272+40 — арифметика сходится |
| 6 | Полный tests/api: 923 passed / 3 failed | полный прогон | **923 passed / 3 failed**; падения дословно = средовой baseline PROGR-2-CERT (modeling_workflow catalog-only, neural_capacity память хоста, models_candidates unsupported-гейт) — новых падений нет |
| 7 | Якорь схемы SESSION_SCHEMA_VERSION == 2 | `test_session_store.py:726` | подтверждён |
| 8 | F-1/F-2 сертификации PROGR-2-CERT интегрированы | `packages/ui/eda-checks-json.test.ts` на main; jest EDA-сьюты | **45/45** (41 EDA + 4 json) |

Среда: python 3.12, statsmodels 0.15.0 (чек-лист R5 PROGR-1-CERT); node_modules
на месте; jest 2 сьюта зелёные. Прогнозирование хуком не дублируется (X5/X8b).

## 3. Кросс-верификация по живым исходникам — 21/21 (progr3cert_crossverify.py)

Ожидания читаются из ЖИВЫХ файлов (regex по роутерам/main.py/schemas), не из хука:

- **X1/X2:** TRACE_ROUTES == 40; каждый шаблон разрешается ровно в один живой
  маршрут с тем же методом (включая кейс `{stage}` паспорта и
  `/v1/session/target-column` БЕЗ `/dataset` — итерация исполнителя (1)
  подтверждена по живому роутеру).
- **X3/X4:** все пары (stage, event_type/preview_type) валидны по живому
  STAGE_EVENT_TYPES + RUN_LEVEL; узлы известны живому графу pipeline_graph;
  стадии == STAGES графа == KNOWN_STAGES трассы (X11c).
- **X5/X8b:** forecasting-маршрутов в таблице нет; все 4 изменяющих
  forecasting-эндпоинта вне таблицы (дизайн-решение, PROGR-1/PROGR-5).
- **X6:** throttled=True только у profile_viewed; все GET-строки троттлируются;
  env-имя `PROGRESS_PROFILE_VIEWED_THROTTLE_SECONDS`, дефолт 300 с (§4.2).
- **X7:** заявление «все 20 correction-эндпоинтов возвращают applied: bool»
  верифицировано по живым pydantic-схемам: `applied` есть во всех 20
  response-моделях.
- **X8:** полнота — каждый изменяющий сессионный эндпоинт либо в таблице,
  либо классифицирован аудитором как не имеющий канонического типа §4.1
  (список из 19 — см. §6/R-2); stateless-поверхности (public/internal/models/
  diagnostics) вне контура сессии.
- **X9:** хук не трогает session.stages (§3.1 дословно).
- **X10:** ни один роутер не изменён коммитом 38f1cb9 (§4.2 «единая точка»).
- **X11:** SESSION_SCHEMA_VERSION == 2; MAX_PIPELINE_TRACE_EVENTS == 1000.
- **X12:** TraceHookMiddleware зарегистрирован ДО CORS (CORS — внешний слой).
- **X13/X14:** set_dataset сбрасывает run_id и pipeline_trace;
  to_document пишет run_id + deepcopy(pipeline_trace); from_document читает
  run_id с дефолтом и фильтрует не-словари.

## 4. Оракулы аудитора на СВОИХ данных — 12/12 (progr3cert_oracles.py)

Своя кодировка контрактов, свой мини-ASGI-стенд (FakeStore, свои маршруты),
свой сид/метки времени; независимы от progr3_oracles.py исполнителя:

- **OR-A** — статус-гейт через ЖИВОЙ middleware на своих кодах: 200/204/399
  пишутся, 400/401/404/409/422/500/503 — нет (граница 399/400 проверяется на
  реальном ASGI-стеке, не эмулируется).
- **OR-B** — preview/apply по `applied` В ОТВЕТЕ: identity-семантика
  `is False`: False→correction_previewed; True/None/0/"false"/нет ключа→
  correction_applied (границы 0 vs False — dict-ловушка обойдена списком пар).
- **OR-C** — payload-белый список: тяжёлые columns/profile отсечены,
  отсутствующие ключи опущены; коллизия `payload["stage"]` паспорта снята
  dataclasses.replace: payload["stage"] из тела сохранён, event.stage=="eda",
  TypeError невозможен; не-JSON тело → payload {} при записанном событии.
- **OR-D** — арифметика окна: 299.5 с→throttle, 300 с→write (строгое `<`),
  300.5 с→write; naive-ts трактуется UTC; битый/пустой ts — деградация к
  «можно писать»; пер-узловость (correlation ≠ seasonality) и пер-типовость
  (profile_viewed ≠ passport_captured).
- **OR-E** — env-семантика: нет/""→300, "0"→0 (выкл), "-5"→0, "abc"→300,
  "5.5"→300, " 600 "→600, "600"→600, "999999"→999999.
- **OR-F** — run_id: без датасета не фиксируется (run_id=""); с датасетом
  `^RUN-[0-9A-F]{8}$`; идемпотентен; в события попадает зафиксированный;
  set_dataset → сброс; новая фиксация ≠ старой.
- **OR-G** — cap: при cap=5 из 8 своих событий остаётся хвост [3..7] (старейшие
  вытеснены, порядок сохранён); R1: мутация источника ПОСЛЕ append не меняет
  stored (включая вложенные структуры) — копия глубока.
- **OR-H** — свой legacy-корпус: 3-поля → канон stage="forecasting" (R2:
  маркер сильнее явной stage); канон — pass-through; не-словарь/чужая стадия —
  skip с warning; неизвестный event_type сохранён (R3); чтение не мутирует
  stored; run_id-фоллбек из сессии.
- **OR-I** — свои документы: раундтрип run_id+pipeline_trace точен;
  документ v1 без новых полей → дефолты; мусор в trace отфильтрован на
  загрузке; документ «из будущего» (v3) читается с warning, не падает.
- **OR-J** — интеграционный стенд: первая загрузка без cookie пишется через
  Set-Cookie fallback + фиксирует run_id; троттлинг сквозь стенд (1-й GET
  пишется, 2-й в окне — нет, другой узел — пишется); ответ клиенту не
  искажается; не-матчящий запрос — без событий; неизвестная сессия — тихий
  пропуск без поломки ответа.
- **OR-J2** — исключение хендлера матчящегося маршрута: пробивается наружу
  (re-raise), событие не пишется (трасса решений — не лог ошибок).
- **OR-K** — матчер: `{stage}` матчит непустой сегмент; метод строг;
  пустой сегмент/лишний сегмент/трейлинг-слэш → None; параллельные ветки
  regularity (validation vs preprocessing) не путаются.

## 5. Мутационный прогон аудитора — 11/12 KILLED, 1 охарактеризованный survivor

Дизъюнктный набор к 13 мутантам исполнителя; 12 мутантов × 3 детектора
(D1 — сьют исполнителя 40 тестов; D2 — его оракулы 12; D3 — мои оракулы 12).
Файлы восстанавливаются байт-в-байт (sha256 после прогона совпал).

| Мутант | D1 | D2 | D3 | Итог | Класс дефекта |
|---|---|---|---|---|---|
| CERT-M1 гейт: `>=400`→`>400` | . | K | K | KILLED | граница статуса 400 |
| CERT-M2 потеря пер-узлового throttle | K | . | K | KILLED | троттлинг глушит чужие узлы |
| CERT-M3 env окна игнорируется | K | K | K | KILLED | env-оверрайд мёртв |
| CERT-M4 payload не присоединяется | K | K | K | KILLED | события без фактов |
| CERT-M5 пустой сегмент {param} | . | . | K | KILLED | матчер-граница |
| CERT-M6 deepcopy→dict() (R1-регрессия) | K | . | K | KILLED | разделение вложенных структур |
| CERT-M7 загрузка пропускает мусор | K | . | K | KILLED | граница from_document |
| CERT-M8 set_dataset хранит старый run_id | K | K | K | KILLED | исследование не переоткрывается |
| CERT-M9 сериализация теряет run_id | K | K | K | KILLED | раундтрип документа |
| CERT-M10 потеря request-cookie ветки | K | . | K | KILLED | события после первой загрузки |
| CERT-M11 отсутствующий ключ роняет событие | K | K | K | KILLED | KeyError вместо пропуска |
| CERT-M12 удаление import-гейта forecasting | . | . | . | **SURVIVED** | см. F-1 |

Наблюдения над матрицей детекторов (честный кросс-отчёт):
- дыры сьюта исполнителя, закрытые ТОЛЬКО оракулами: CERT-M1 (граница ровно
  400 — их неуспешные кейсы 404/409/422), CERT-M5 (пустой сегмент);
- дыры оракулов исполнителя, закрытые сьютом/моими оракулами: CERT-M2/M6/M7/M10;
- 5 мутантов убиты всеми тремя детекторами (M3/M4/M8/M9/M11) — детекционная
  сила подтверждена с трёх независимых сторон.

**CERT-M12 (SURVIVED) — характеризация:** удаление import-гейта «stage ==
forecasting запрещён» не меняет поведение на ТЕКУЩЕЙ таблице (forecasting-строк
в ней нет), поэтому эквивалентен для всех существующих детекторов. Это
защитная ветка контракта таблицы (fail-closed), а не мёртвый код; риск —
тихая деградация защиты при будущих правках таблицы. Аналог прецедента
CERT-E01 PROGR-2-CERT (pragma no cover честна). Рекомендация — тест-нарушение:
подать в `_validate_table` пробную таблицу с forecasting-строкой и ожидать
ImportError (5 строк теста).

## 6. Находки

- **F-1 (Low, тест-контур): import-гейт запрета forecasting не покрыт
  тестом-нарушением.** Ни сьют, ни оракулы исполнителя, ни оракулы аудитора не
  подают forecasting-строку в `_validate_table` (CERT-M12 SURVIVED 0/3).
  Защитная функция жива и корректна для текущей таблицы; не покрыт именно
  сам гейт. Рекомендация: тест с пробной таблицей → ImportError. Не блокер.
- **R-1 (Info): «мёртвые» ключи общего payload-кортежа.**
  `_CORRECTION_PAYLOAD_KEYS` — общий кортеж на 20 correction-строк; для
  конкретного эндпоинта часть ключей не входит в его response-схему
  (convert-types: 7 из 11, feature-generations/spectral/feature-generations:
  9 из 11) и опускается рантаймом (отсутствующие ключи не пишутся).
  Поведения §4.1 не нарушает (payload — только факты данного эндпоинта), но
  таблица местами создаёт завышенное ожидание о составе payload.
- **R-2 (Info): полнота трассы слоя 1.** 19 изменяющих сессионных эндпоинтов
  без канонического типа §4.1 не трассируются: `/v1/session/date-column`,
  PUT `/dataset/validation-rules`, PUT `/dataset/type-schema`,
  POST `/stage/{stage}`; modeling: PUT `feature-regressors`, `candidates`,
  `baselines`, `backtest/exclude`, `tuning/skip`, `tuning/skip-pending`,
  `jobs/start`, `jobs/{id}/cancel`, `jobs/{id}/step`, `tuning/start`,
  `tuning/step`, `diagnostics`, `diagnostics/ensure`, `compare`,
  `selection/evaluate`. Это соответствует букве §4.1 (закрытый реестр типов,
  расширение — через STAGE_EVENT_TYPES), но «решенческие» факты этих шагов
  (сравнение моделей, правка правил/схемы типов, смена date-column) в трассу
  слоя 1 не попадают. Расширение реестра — отдельное решение (естественный
  задел PROGR-5+); зафиксировать осознанность.
- **R-3 (Info): граница гейта 400 не покрыта сьютом исполнителя** — ловится
  оракулами (их O11 и мой OR-A через живой middleware). Дыра детекции сьюта,
  не кода.
- **R-4 (Info): стабильность event_id legacy-записей.** Записи трассы без
  `event_id` (гипотетические старые Redis-документы) при каждом чтении
  получают НОВЫЙ сгенерированный id (from_dict → `raw.get("event_id") or
  _new_event_id()`); семантические поля стабильны, чтение stored не мутирует.
  Для рендера панели неважно; при экспорте трассы/чекпоинтах (PROGR-5) —
  либо backfill id при записи, либо детерминированный id.

## 7. Вердикт

**PASSED WITH REMARKS.**

Реализация PROGR-3 соответствует канону spec_progress.md §4.1/§4.2/§5 (слой 1)
и плану plan_progress.md: единая точка интеграции (ASGI-middleware, роутеры не
тронуты), события только на успешных ответах, payload — факты ответа (белый
список), preview/apply по applied в ответе, троттлинг profile_viewed с env и
дефолтом 5 минут, run_id "RUN-XXXXXXXX" фиксируется при первой трассируемой
загрузке (Set-Cookie fallback), буфер 1000 с вытеснением старейших, глубокая
копия payload (R1 закрыта), граница чтения нормализует legacy (R2/R3
зафиксированы тестами), схема 1→2 с полной обратной совместимостью чтения,
session.stages не тронут (§3.1), forecasting не дублируется. Все заявления
исполнителя воспроизведены (8/8); 21/21 кросс-верификация; 12/12 оракулов
аудитора на своих данных; мутационная устойчивость 11/12 (+1 охарактеризованный
survivor защитного гейта). Находки F-1, R-1–R-4 не блокируют; блокеров для
PROGR-4/PROGR-5 нет.

Deliverable: ZIP `cisstat-progr3-cert-trace-hook.zip` — пути репозитория
сохранены. НОВЫЕ: scripts/audit_scripts/cert_progr3_trace_hook_2026-09-24.md
(этот акт), scripts/audit_scripts/progr3cert_crossverify.py,
scripts/audit_scripts/progr3cert_oracles.py,
scripts/audit_scripts/progr3cert_mutations.py. ИЗМЕНЁННЫЕ:
worklog/worklog8.md (запись PROGR-3-CERT). Без commit/push (AGENTS.md).
