# Независимая сертификация исправлений повторного аудита (DOCLOG-E2E-RECHECK-1-FIX)

**Дата:** 26 октября 2026 года, Москва. **Task ID:** DOCLOG-E2E-RECHECK-1-FIX-CERT.
**База аудита:** `9401fa5` (HEAD origin/main, коммит исправлений C01–C09 + F-D5C1); база сравнения RED -- `8f66e92`.
**Основание:** акт повторного аудита `docs/doclogcert_2026_10_26/certification.md` (находки C01–C09 + F-D5C1), хвост worklog11, реализация исправлений на `9401fa5`, `AGENTS.md`.

## 1. Вердикт

**Сертификация исправлений: PASSED.** Каждая находка повторного аудита
(C01–C09) и прежняя гонка отмены (F-D5C1) закрыта подтверждённым
исправлением, проверенным тремя независимыми каналами:

1. **RED → GREEN на собственных данных:** acceptance-оракулы аудита
   воспроизведены RED на чистом worktree `8f66e92` c регенерированным
   сценарием (5F/3P backend, 3F/1P UI -- байт-в-байт протокол аудита) и
   GREEN на `9401fa5` (8/8 backend, 4/4 UI) после штатного
   `reproduce_scenario.py` на собственном CSV из штатного TS-генератора.
2. **«Мутанты на своих мутантах»:** 26/26 мутантов 1-го порядка
   УБИТЫ оракулами (21 repo-корпусом fix-задачи, 5 -- ORACLE-ONLY
   собственными пробами сертификатора); 7/7 композиций 2-го порядка
   (пары из разных функций) DUAL-KILLED -- маскирования нет.
3. **Регресс дельта-0:** полный tests/api `9401fa5` vs `8f66e92`
   (git-worktree): FAILED-ID байт-идентичны 47/47, +19 passed = ровно
   корпус fix-задачи; DOCLOG-0…9 = 583/583.

Границы честно перечислены в §6: области, не охваченные самим fix-заданием (живой PG, veraPDF, нагрузка, browser-E2E, полная панель ≥5 сущностей), НЕ сертифицируются этим актом и остаются в состоянии акта повторного аудита.

## 2. Метод и границы опыта

- Отдельный клон + fetch; продуктовые файлы не изменялись; commit/push
  не выполнялись (AGENTS.md). Мутационная кампания -- в отдельном
  git-worktree `wt-fix-9401fa5` (9401fa5) с GUARD md5 до/после каждого
  мутанта; база RED -- worktree `8f66e92`.
- **Свои данные:** CSV получен штатным
  `DEMO_DATASETS[forecast_monitor_n150].generateCsv()` через
  `node --experimental-strip-types` (2691 байт, 150 строк; sha256 в
  `certification_summary.json`); store'ы одноразовые Memory; временная
  файловая область; фоновые workers отключены, PDF -- штатный
  `DocumentRenderWorker.run_once`. Артефакты/документы до опыта не
  подсевались.
- Оракулы аудита принимались КАК ЕСТЬ (требования, не баг-состояние);
  сценарий регенерирован сертификатором на обеих базах, поэтому RED/GREEN
  отражают поведение кода, а не устаревший файл.

## 3. Поведенческое подтверждение исправлений (собственные данные)

Результат `reproduce_scenario.py` на `9401fa5` (мой прогон):

| Наблюдение | База 8f66e92 (мой прогон) | Фикс 9401fa5 (мой прогон) |
|---|---|---|
| Артефакты после реального пайплайна | **0** | **8**: 4×data_frame (upload + target/date + 2 apply), passport, validation_result, 2×correction_recipe |
| Документы до явной команды | 0 (§12.1) | 0 (§12.1 -- авторегистрации нет, это честно) |
| D02 | `complete` при `data_ref=null`, limited/missing_data_artifact | `partial`, `missing_mandatory=[missing_source_passport_artifact]`, `data_ref` разрешён, repro=ready |
| D03 | статусы без протокола | протокол: «Протокол валидации зафиксирован», правила/режимы/знаменатели каждой проверки из validation_result |
| D04 | две строки apply | рецепты: «стратегия median_mode; изменено значений: 3» и «стратегия cap; метод iqr; изменено значений: 4; ревизия после: 2» |
| event_claim_validity | 12/13 чужого контекста = current | **0** mismarked (13 rows) |
| read_render_preserved_science | true | true |
| Явное создание D02–D04 из пустого реестра API | 3 | 3 (positive control) |

Пометка честности: D02/D03 на моём прогоне -- `partial` с кодом
`missing_source_passport_artifact` / `missing_validation_result_artifact`:
паспорт и протокол валидации продвинуты ДО коррекций, их контекст после
apply -- stale (единый reducer §10 R07), а обязательность current-паспорта
для D02 -- задокументированное семантическое решение fix-задания
(«источником ТЕКУЩЕЙ версии данных stale-паспорт не является»). Это
ЗАМЕТНОЕ изменение договора полноты (в базе было лживое `complete`),
задокументированное в fix-журнале и закреплённое тестами
`test_d02_partial_without_current_passport` /
`test_d02_complete_when_passport_current`.

## 4. «Мутанты на своих мутантах» (каталог и исход)

Оракулы: repo-корпус fix-задачи (18 backend + 5 UI) + динамический C08
acceptance + собственные пробы сертификатора
`scripts/doclogrecheckfixcert/` (5 backend + 4 lib + 4 client).

**1-й порядок -- 26/26 KILLED** (полная атрибуция в
`protocols/mutation_results.json` и `protocols/ui_attribution.json`):

| Группа | Мутанты | Killer-тесты (примеры) |
|---|---|---|
| promotion_integration | M01–M06 | capture/check/upload/apply-промоушен, зависимость рецепта→данных, durable-receipt |
| promotion_integration (sweep) | M07, M08 | ORACLE-ONLY: O1-пробы `test_o1_modeling_sweep_*` (счётчики честных нулей; sweep создаёт 3 вида) |
| snapshot_builder C04 | M09, M10 | stale-not-current / current-сохраняется |
| snapshot_builder C05 | M11, M12, M13 | d02-partial; ORACLE-ONLY: O2-проба каталога gaps; ось missing_mandatory |
| snapshot_builder C06 | M14, M15 | d04-strategy (median_mode/iqr); d03-протокол |
| doc_profiles C08 | M16, M17 | create/retire fail-closed по состоянию |
| document_jobs F-D5C1 | M18*, M19, M20 | *см. ниже; инверсия гейта #2 (positive control); ORACLE-ONLY: O3-проба rendition=failed |
| UI C01/C02/C07/C09 | UM01–UM05 | поимённо: C02-пустой реестр, C02-deep-link, C07-alert, C09-форматы, C01-no-run |
| lib resolveCurrentRun | UM06 | ORACLE-ONLY: OC1-проба единого источника run |

**M18 -- честная коррекция прогноза (важная находка):** удаление гейта
CAS #1 было предсказано SURVIVED (маскирование дубль-слоем #2) и
**фальсифицировано**: O3-проба гонки «cancel посреди рендера» убивает
мутант -- с одним гейтом #2 окно гонки ОТКРЫВАЕТСЯ заново (свежая запись
читается позже и видит rendering → job уходит в ready поверх отмены).
Гейты #1 и #2 НЕ дублирующие: они закрывают РАЗНЫЕ окна (отмена до входа
vs отмена во время рендера). Двухточечный дизайн fix-задания --
несущий, не страховочный.

**2-й порядок («мутанты на своих мутантах») -- 7/7 DUAL-KILLED:**
S1=M01+M09, S2=M04+M14, S3=M13+M16, S4=M19+M02, S5=UM01+UM04,
S6=M17+M06, S7=M10+M11. Композиции из разных функций; маскирования нет.

**ORACLE-ONLY kills (5):** M07, M08, M12, M20, UM06 -- обнаруживают
честные границы покрытия repo-корпуса (счётчики sweep, каталог gaps,
rendition=failed при отмене, резолв run в lib-слое), закрытые
собственными пробами сертификатора, а не «натянутыми» пинами.

## 5. Протоколы проверок (моя среда)

| Проверка | Факт |
|---|---|
| Acceptance-оракулы, `9401fa5`, мои данные | **8/8** |
| Acceptance-оракулы, `8f66e92` worktree, мои данные | **5 failed / 3 passed** (C03/C04/C05/C06/C08; контроли зелёные) |
| UI bootstrap, `9401fa5` / `8f66e92` | **4/4** / **3 failed, 1 passed** |
| Repo-корпус fix: backend / UI | **18/18** / **5/5** |
| Пробы сертификатора: backend / lib / client | **5/5** / **4/4** / **4/4** |
| DOCLOG-0…9 (10 файлов), `9401fa5` | **583 passed / 0 failed** |
| Полный tests/api delta-0 | база **47F/2762P/42S** vs голова **47F/2781P/42S**; FAILED-ID **байт-идентичны 47/47**; +19 = корпус (18 + новый пин legacy-контекста doclog2) |
| Jest packages/ui / apps / scripts | **2306/2307** (1 флак prograudit3 -- предсуществующий средовой класс DOCLOG-7; изоляция 5/5, батч 36/36) / **63/63** / **8/8** |
| typecheck:all | rc=0 (оба приложения) |
| Сборка/структура | import apps.api.main OK: **221 маршрут**, AUDIT_ACTIONS=29 (+artifact_promotion_failed), ARTIFACT_KINDS=7 (+validation_result, +correction_recipe) |
| Чистота дерева | git diff после кампании: только перегенерированное evidence (samples/protocols), продуктовых изменений нет |

Примечание о среде: FastAPI 0.128.0 (requirements `>=0.110`) -- 4 падения
интроспекции маршрутов из протокола аудита (их stand: FastAPI 0.143.0)
здесь НЕ воспроизводятся; корпус зелёный целиком. Разница сред
зафиксирована в `certification_summary.json`.

## 6. Открытые границы (не сертифицировано этим актом)

1. Живой PostgreSQL/PG-зеркала missing_mandatory, backup/RPO/RTO,
   veraPDF-конформа, нагрузка/SLA, полная панель ≥5 сущностей,
   browser-E2E на реальном стенде -- вне среды; не PASSED (как и в акте
   аудита; fix-задание эти области не заявлял).
2. Полный Jest в этой песочнице зависает на самофетчах (средовая
   граница); разбит на порции с `--forceExit` с сохранением полных
   протоколов. Флак prograudit3 подтверждён предсуществующим классом.
3. F-D9C1 (ICC-таймштамп PDF/A byte-determinism) -- вне скоупа fix-задания,
   не переиспытывалось, не объявлено закрытым.
4. UI-мутанты убиты jest-корпусом (поимённая атрибуция), не живым
   браузером; реальный путь C02 «кнопка на пустом реестре» проверен
   компонентно + API-позитивом из пустого реестра.
5. Промоушен версии данных выше 250k строк/64MB -- честный пропуск
   (задокументированная граница), подтверждён пробой O4.

## 7. Файлы поставки

- `docs/cert_doclogrecheckfix_2026-10-26.md` -- этот акт.
- `scripts/doclogrecheckfixcert/` -- собственные оракулы и кампания:
  `test_cert_oracle_unit.py` (O1–O4), `documentation-cert-oracle.test.tsx`
  (OC1/OC2), `documentation-client-cert.test.tsx` (CC1), `mutations.py`
  (каталог 26+7 с предсказаниями), `run_campaign.py`, `ui_attribution.py`,
  `protocols/` (mutation_results, ui_attribution, certification_summary,
  протоколы регресса/typecheck/jest).
- Перегенерированное evidence моего прогона:
  `scripts/doclogcert_2026_10_26/protocols/scenario.json`,
  `pipeline_events.json`, `docs/doclogcert_2026_10_26/samples/*` (D02–D04
  MD/HTML/JSON/PDF + snapshot'ы + progress_history).
- `worklog/worklog11.md` -- запись сертификации (прежние записи не менялись).

Воспроизведение (из корня, зависимости установлены, внешние БД не нужны):

```bash
node --experimental-strip-types -e "import('./packages/ui/lib/demoDatasets.ts').then(m=>{require('fs').writeFileSync('../forecast_monitor_synthetic_n150.csv', m.DEMO_DATASETS.find(d=>d.id==='forecast_monitor_n150').generateCsv())})"
python3 scripts/doclogcert_2026_10_26/reproduce_scenario.py
python3 -m pytest scripts/doclogcert_2026_10_26/test_acceptance_red.py -q
python3 -m pytest tests/api/test_doclog_recheck_fix.py scripts/doclogrecheckfixcert/test_cert_oracle_unit.py -q
npx jest scripts/doclogrecheckfixcert --runInBand
python3 scripts/doclogrecheckfixcert/run_campaign.py            # 1-й порядок (worktree)
python3 scripts/doclogrecheckfixcert/run_campaign.py all second # 2-й порядок
```
