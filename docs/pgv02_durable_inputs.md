# PGV-02 — Durable inputs/V01/P01/P02 (документ поставки)

**Дата:** 28 октября 2026. **База:** `main@7b72636` (PGV-00-FIX; клон, рабочее дерево синхронизировано до HEAD). **Статус:** durable-слой print inputs + печатные типы документов; producer-адаптеры/reader/renderer не реализованы. **Родительский контракт:** `spec_documentation_logging.md` §19 (аддитивная строка PGV-02). **Проектная спека:** `spec_passport_graphics_visual.md` §6/§8/§10.2/§13 (строка PGV-02), §14 (приёмочные сценарии).

---

## 1. Назначение и границы

PGV-02 замыкает контракты PGV-01 на **durable-слой**: печатные входы научных визуализаций и паспортов становятся устойчивыми артефактами, а печатные типы документов V01/P01/P02 входят в versioned каталог документации. Критерий готовности по spec §13 — «**Versioned migrations и legacy D01–12/readers работают**».

**Границы поставки (честно):** freeze-оркестрация переносит УЖЕ вычисленный результат (export не запускает науку, §3.1); producer-адаптеры (вызов freeze в момент фиксации результата) — PGV-03/04; `PassportHistoryReader`/сравнение — PGV-05/06; print layout/renderer/jobs — PGV-07/08/09; UI/API-роутеры печатных документов — PGV-13/15. Legacy-пути (D01–D12 renditions, forecast CSV/JSON) не менялись (AC22).

## 2. Состав поставки (файлы)

| Файл | Роль |
|---|---|
| `apps/api/visual_artifacts.py` | **НОВЫЙ**: durable inputs — валидаторы payload (`pgv.visual_result/1`, `pgv.visual_print_snapshot/1`, новый `pgv.passport_checkpoint/1`), producer_key-конвенции, CAS freeze (`PrintContextConflict` → 409 context_changed, AC07), durable read-хелперы (субстрат AC09) |
| `apps/api/artifact_store.py` | `ARTIFACT_KINDS` += `visual_result`, `visual_print_snapshot`, `passport_checkpoint` (spec §6 «расширяет schema/migrations/pins/tests»; §8 «новый artifact kind passport_checkpoint»); legacy kinds поимённо сохранены; PGV-02-FIX: `unregister_artifact` — компенсация AC08 в контракте реестра (ABC/Memory/Postgres — паритет F-D2C1; пин-защищённый артефакт не удаляется)
| `apps/api/artifact_promotion.py` | `persist_visual_artifact` — ЕДИНЫЙ конвейер (staging→verify→commit→registry, инвариант «одна точка интеграции») с обязательным валидационным гейтом + контентной сверкой идемпотентности (§11: «иной payload с прежним key → 409»); `_persist` принял опциональный `schema_version` |
| `apps/api/report_snapshot.py` | Versioned каталог `pgv.document_catalog/2`: `PRINT_DOCUMENT_KINDS` (V01 scientific_visual, P01 passport_print, P02 passport_comparison), `document_kind_family()`, `is_print_document_kind()`; `DOCUMENT_KINDS` (D01–D12) не тронут, `resolve_kinds` печатные типы не резолвит (их ревизии идут мимо снапшот-сборщика, §10.2) |
| `apps/api/document_jobs.py` | `DocumentPrintRevisionRecord` + печатный контракт реестра (ABC/Memory/Postgres — структурный паритет, урок F-D2C1) + `ensure_print_document_revision` (идемпотентность по basis_fingerprint, pins basis) + `list_print_documents` (субстрат PGV-15); legacy `list_documents`/`ensure_document_revision` не задействованы |
| `apps/api/research_runs.py` | `MIGRATION_STATEMENTS_0016` + запись в `MIGRATION_FILES` + конкатенация каталога |
| `apps/api/migrations/0016_pgv2_print_documents.sql` | **НОВЫЙ**: файл-дубль каталога (паритет PROGR-5.1) — `document_print_revisions` (basis = frozen print inputs; snapshot_id опционален; UNIQUE(document_id, version_no) + UNIQUE(document_id, basis_fingerprint)) |
| `tests/api/test_pgv02_durable_inputs.py` | **НОВЫЙ**: 51 тест поставки + 18 тестов PGV-02-FIX (секция 9) — kinds/schema-пины, валидатор checkpoint (AC11/AC12/AC14), freeze CAS (AC07), идемпотентность (§8/§11), durable read после утраты сессии (субстрат AC09), каталог (D02≠P01, legacy пины), печатные ревизии, миграция 0016/паритет/сумма; фикс-секция: basis-гейт, fail-closed CAS, manifest в fingerprint, самоссылка, атомарность пина, Memory UNIQUE-паритет, unregister-контракт |
| `tests/api/test_doclog4_document_delivery.py`, `test_doclog5_formats_worker.py`, `test_doclog6_approvals_archive.py`, `test_doclog8_monitoring.py` | Честное обновление пинов счётчиков миграций (15→16 файлов; 93→96 statements; +0016 по имени) — прецедент «честное обновление пина» DOCLOG-9 |
| `spec_documentation_logging.md` | §19: аддитивная строка PGV-02 |
| `docs/pgv02_durable_inputs.md` | Этот документ |
| `scripts/pgv02/check_documents.py` | Doc-contract гвард «документация == поставка» |
| `worklog/worklog11.md` | Запись Task ID: PGV-02 |

## 3. Проектные решения

### 3.1. Валидационный гейт на уровне промоушена (validators)

Registry хранит metadata, но не видит bytes — валидация размещена в `persist_visual_artifact` ДО staging: невалидный payload **не регистрируется вовсе** (`ArtifactPayloadInvalid` со стабильными кодами print-слоя, честный отказ вместо «готовой» картинки, §8). visual_result/visual_print_snapshot проверяются зеркалом PGV-01 (`print_schema.py`); сайт реестра PGV-00 резолвится по view_id — view вне реестра не морозится (unknown site блокирует CERT, §5).

### 3.2. Идемпотентность и честный конфликт (§8/§11)

Producer key выводится из идентичности результата: `pgv.visual_result:{view_id}:{result_ref}` (§6: перенос идемпотентен, пересчёт = НОВЫЙ immutable артефакт — старые не переписываются); `pgv.print_snapshot:{view_id}:{digest|reason}`; `pgv.checkpoint:{checkpoint_id}` (§8: идемпотентность по checkpoint_id). Тот же ключ + тот же контент → существующий артефакт; тот же ключ + другой контент → `ArtifactConflictError` (409-семантика §11). Контентная сверка добавлена в persist-гейт: `_persist` возвращает existing без сверки контента (достаточно для DOCLOG-1), для durable inputs подмена не маскируется.

### 3.3. CAS freeze (PGV-AC07)

`freeze_visual_result` сверяет явные `expected_context_id`/`expected_data_revision`, `freeze_visual_print_snapshot` — `expected_context` снапшота с текущим durable-состоянием запуска; расхождение → `PrintContextConflict` (код `context_changed`), НИЧЕГО не регистрируется. Демо-скоуп без контекста CAS не проходит (нет чего сверять — честно). Проверенный результат исторической версии морозится без CAS (первый explicit export, §6). PGV-02-FIX (F-P2C2): нечисловая непустая строка `expected_context.data_revision` — fail-closed CAS (`PrintContextConflict`), не тихий пропуск сверки; пустая/whitespace-строка — отсутствие значения (research-снапшот отвергает валидационный гейт persist).

### 3.4. Контракт `pgv.passport_checkpoint/1` (§8)

checkpoint_id (pck-*), stage ∈ {modeling_entry, panel_entry}, confirmed_at **XOR честная причина** (AC12: утраченная дата легаси — `legacy_unknown`, время промоушена не подставляется), snapshot_ref (rs-*) + previous_snapshot_ref, flags created/reused/unchanged: ровно одно из created|reused, unchanged ⊆ reused и не совмещается с created (никакой четвёртой физической копии, AC11), точные stage-refs (modeling_entry: start/validation/exit; panel_entry: panel), context (run/context/revision; entity_id обязателен для panel_entry — панели не смешиваются, AC14), provenance (producer_capture|legacy_import|session_replay — задел PGV-04).

### 3.5. Печатные ревизии: отдельная таблица вместо раздвижки legacy

`document_revisions.snapshot_id NOT NULL` + `UNIQUE(snapshot_id)` сохранены байт-в-байт (критерий «legacy D01–12/readers работают»): печатные ревизии живут в новой `document_print_revisions` (basis = список артефактов, snapshot_id — опциональный паспортный anchor). Идемпотентность выдачи — `UNIQUE(document_id, basis_fingerprint)` (digest тела §11: print_kind, basis_kind, basis_artifact_ids, snapshot_id, profile_id, manifest_artifact_id), монотонные версии — `UNIQUE(document_id, version_no)` (паритет 0010). Basis-артефакты пинятся с причиной `print_revision:{id}` (§16). Документы V01/P01/P02 — в существующей таблице `documents` (UNIQUE(run_id, kind_code) сохранён: «Создаётся revision», §10.2; «не плодит документы на каждый capture»). PGV-02-FIX: basis-артефакты проходят гейт существования/run-принадлежности (`PrintBasisInvalid`) до создания документа/ревизии/пинов; пин basis ставится ДО регистрации ревизии (id прегенерирован), отказ регистрации — unpin-компенсация поставленных этой операцией пинов (AC08-дух); Memory-реестр печатных ревизий даёт `PrintRevisionConflictError` на дубликаты обоих UNIQUE из DDL 0016 (паритет Memory/Postgres — урок F-D2C1).

### 3.6. Versioned каталог (§10.2)

`pgv.document_catalog/2`: семейство различает snapshot_section (D01–D12, снапшот-сборщик) и print_document (V01/P01/P02, печатный поток). D02 = source_passport, P01 = passport_print — kind-имена различны, «не переименование D02» пином. `resolve_kinds` печатные типы НЕ резолвит (ошибка содержит подсказку про печатный поток) — ревизии V01/P01/P02 создаются `ensure_print_document_revision`, а не секциями отчёта.

## 4. Приёмочные сценарии (покрытие поставки)

| AC | Покрытие |
|---|---|
| PGV-AC07 | CAS freeze: expected_context/expected_* против run-состояния → `PrintContextConflict`, ничего не регистрируется (тесты `test_context_cas_*`) |
| PGV-AC09 (субстрат) | Durable read visual_result/checkpoint после `reset_session_store` (тест `test_checkpoint_read_after_session_loss`); полный reader — PGV-05 |
| PGV-AC11 | Валидатор: reused требует snapshot_ref; unchanged не совмещается с created; подтверждение + ссылка на источник без четвёртой копии (тесты `test_reused_*`, `test_unchanged_*`) |
| PGV-AC12 | missing confirmed_at → `missing_date` (не фабкуется); честная причина `legacy_unknown` валидна (тест `test_missing_confirmed_at_*`) |
| PGV-AC14 | panel_entry требует entity_id → иначе `panel_mixing` (тест `test_panel_entry_requires_entity_context`) |
| PGV-AC22 | Legacy-пины: DOCUMENT_KINDS=12, resolve_kinds D01–D12, document_revisions NOT NULL snapshot_id, DDL 0010 нетронут, пины счётчиков обновлены честно (515 passed по срезам) |
| PGV-AC21 (частично) | payload валидация PGV-01 (raw_data_included=false пин) проходит через гейт; ZIP/манифест — PGV-14 |

## 5. TDD-протокол

**RED:** 51 тест собран, падения на отсутствии kinds/модуля/каталога/таблицы (честный import/assert-RED). **GREEN:** в процессе пойманы и честно исправлены: (1) три дефекта оракула — мутация `result_ref` не в тот уровень payload (execution.*), frozen ResearchRun в сид-хелпере (переход на `dataclasses.replace`), `expected_context.data_revision` — строка по контракту PGV-01 (`_str`); (2) два реальных дефекта реализации — schema_version не проставлялся per-kind (расширен `_persist` опциональным параметром), идемпотентность `_persist` возвращала existing без сверки контента (добавлена контентная сверка §11 в гейт); (3) три пина счётчиков миграций в legacy-тестах (честное обновление с комментарием, прецедент DOCLOG-9).

## 6. Верификация

Сюита PGV-02: **51/51 GREEN**. Регресс затронутых срезов (doclog1/2/4/5/6/8, h29, pgv01, research_runs, pgv02): **515 passed, 5 warnings, 0 failed**. Первые два прогона дали collection-ERROR test_research_runs (`pywt`, `pandera` отсутствовали в свежем окружении) и 2 падения doclog5 (pyarrow) — предсуществующие lacуны зависимостей окружения, устранены установкой requirements-пакетов, к диффу отношения не имеют. `py_compile` 7 файлов OK; `import apps.api.main` OK — 221 маршрут, каталог 16 файлов/96 statements; `git diff --check` PASS. Полный jest не гонялся: дифф не трогает packages/ui (граница зафиксирована; TS-контракты printSchema не менялись). Браузерная/docker приёмка неприменимы (runtime UI/контейнеров не менялся).

## 7. Честные границы

(1) Producer-адаптеры не вызываются из научных обработчиков — freeze доступен как API-слой для PGV-03/04; научный runtime не менялся (221 маршрут, index.ts не тронут). (2) `passport_checkpoint/1` определён Python-side; TS-твин в `printSchema.ts` — точка расширения PGV-07/13 (печать подтверждений). (3) Postgres-реестр печатных ревизий проверен контрактом/паритетом методов и DDL-пинами; живой Postgres-прогон — в контуре CERT (прецедент DOCLOG-серии). (4) API-роутеры `GET /visual-sources`/`POST /visuals`/`GET /passport-sources`/`POST /passport-documents` (§11) — PGV-13/15; ошибки 413/429/503 рендер-контура — PGV-09. (5) Backfill-семантика legacy_import — PGV-04 (provenance-поле задел).

## 8. PGV-02-FIX — исправления находок сертификации PGV-02-CERT

Акт: `docs/cert_pgv02_2026-10-28.md` (вердикт PASSED WITH FINDINGS). Исправления (Class B корпуса `scripts/pgv02cert/` стал GREEN без правки смысла — прецедент PGV-00-FIX §7.4):

| Находка | Фикс |
|---|---|
| F-P2C1 (высокая) | `_validate_print_basis` в `ensure_print_document_revision`: гейт существования и run-принадлежности каждого basis-артефакта ДО создания документа/ревизии/пинов; отказ — `PrintBasisInvalid` (§10.2 frozen refs, §5/§11 object authorization) |
| F-P2C2 (средняя) | `freeze_visual_print_snapshot`: нечисловая непустая строка `expected_context.data_revision` → `PrintContextConflict` (fail-closed CAS, 409 context_changed) вместо тихого пропуска сверки |
| F-P2C3 (низкая) | `manifest_artifact_id` входит в тело `basis_fingerprint` — повтор с тем же basis, но другим manifest → НОВАЯ ревизия (§11 идемпотентность по телу); тот же manifest — прежняя ревизия (§12.2 сохранён) |
| F-P2C4 (низкая) | Валидатор `pgv.passport_checkpoint/1`: самоссылка `previous_snapshot_ref == snapshot_ref` → `invalid_value` (§8: ссылка на ПРЕДЫДУЩИЙ снимок) |
| F-P2C5 (низкая) | `freeze_visual_print_snapshot`: отказ пина зависимости → компенсация AC08 (unpin поставленных этой операцией пинов + `unregister_artifact` созданного артефакта; артефакт, существовавший до операции, не удаляется); симметричный класс в `ensure_print_document_revision` — пин basis ДО регистрации ревизии с unpin-компенсацией при отказе регистрации |
| F-P2C6 (низкая) | Memory-реестр печатных ревизий даёт `PrintRevisionConflictError` на дубликаты UNIQUE(document_id, version_no) и UNIQUE(document_id, basis_fingerprint) из DDL 0016 (паритет Memory/Postgres — урок F-D2C1) |
| F-P2C7 (средняя) | Закрыта upstream PGV-03 (bf0ae7a): пины doclog3/7/9 обновлены (16/96, последний файл 0016) — верифицировано b09 GREEN и чистой дельта-0 |
| N-P2C1 (наблюдение, попутно) | Пустая строка `context.data_revision` чекпоинта → `missing_required_ref` (класс F-D7C2); 0 остаётся значением |

Новый контракт реестра: `ArtifactRegistry.unregister_artifact(artifact_id)` — компенсация AC08 (ABC/Memory/Postgres); пин-защищённый артефакт (ref_kind="artifact") не удаляется — ValueError (§16); байты object store не трогаются (content-addressed).
