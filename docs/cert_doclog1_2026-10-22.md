# Независимая сертификация задачи DOCLOG-1 — устойчивые артефакты

**Дата:** 2026-10-22. **Сертификатор:** независимый контур CERT (сертификатор не является исполнителем DOCLOG-1).
**Аудируемая поставка:** commit `3effe9f` «Task ID: DOCLOG-1 (2026-10-22) — Persistent artifacts: Metadata/ObjectStore/schema/digests/staging/pins + passport adapters, OOF, cards, forecasts» на базе `main@fb26f6f`.
**База сертификации:** `main@78769bd` (DOCLOG-0-CERT включён; синхронизация по прямому указанию тимлида).
**Спека:** `spec_documentation_logging.md` (§8.1, §9.1, §9.3, §10.2 п.6, §16, §19 строка DOCLOG-1, §19.1, §20: AC04/AC05/AC06/AC08/AC09/AC13).
**Режим манифеста:** sha256-манифест НЕ ведётся (прямое указание тимлида; целостность обеспечивает git).

---

## 1. Вердикт

**PASSED.**

Заявления DOCLOG-1 подтверждаются независимым корпусом оракулов, мутационной кампанией и полным регрессом с побайтовой дельтой-0 против родителя. Продуктовый код сертификацией НЕ менялся (md5-паспорта до/после идентичны, `git diff` чист). Два выживших мутанта задокументированы как равносильные на данном контракте (см. §5.3); блокирующих дефектов НЕ обнаружено.

---

## 2. Объект аудита (сверка заявлений с кодом)

Поставка добавляет durable-контур артефактов поверх контура идентичности DOCLOG-0:

| Файл | Статус | Проверенный контракт |
|---|---|---|
| `apps/api/artifact_store.py` (945 строк) | НОВЫЙ | Три digest-схемы §9.3 (payload_sha256 / data_digest с algorithm+version / source_bytes_sha256-ссылка); канон-JSON `allow_nan=False` без маскировки; content-addressed object store `{CISSTAT_DATA_DIR\|<repo>/data}/artifacts/objects/{sha256[:2]}/{sha256}` + `staging/`; протокол stage→commit (перечитывание staging, сверка sha256+size, fail-closed) → чтение с проверкой целостности (T8); серверные ключи из хэша (T9); sweep orphan staging с grace period; ArtifactRegistry ABC + Memory (RLock, копии R1) + Postgres (ленивый psycopg, run_migrations, readiness_probe, идемпотентность UNIQUE(run_id, producer_key), конфликт контента без записи); пины с причиной UNIQUE(run_id, ref_kind, ref_id); фабрика get_artifact_registry (required — fail-closed P21/F14; advisory — явная деградация) + peek без провокации |
| `apps/api/artifact_promotion.py` (520 строк) | НОВЫЙ | PromotionService: авторизация ВНУТРИ сервиса (R09/T7: action=write/read через authorize_run_access DOCLOG-0; uniform-отказ без дисклоужения); адаптеры паспортов (start/validation/exit/modeling_entry + ИЗОЛИРОВАННЫЙ panel_entry — R4/AC13), backtest/OOF (перенос КАК ЕСТЬ, panel-блок с per-entity метриками и pooled scale), Model Card (dependencies=checkpoint), forecast (frozen, без пересчёта — §6 D08), данные чекпоинта (СЫРЫЕ CSV-байты — H10; авто-pin с reason=artifact:{id}); честные отказы PromotionUnavailable (R03); идемпотентность producer_key (AC09); NaN → отказ без маскировки (AC12-дух) |
| `apps/api/migrations/0007_doclog1_artifacts.sql` (51 строка) | НОВЫЙ | Аддитивная миграция: `research_artifacts` (UNIQUE(run_id, producer_key), panel JSONB, data_digest_algorithm/value, FK ON DELETE CASCADE) + `research_artifact_pins` (UNIQUE(run_id, ref_kind, ref_id), reason); файл-дубль каталога MIGRATION_STATEMENTS_0007 |
| `apps/api/research_runs.py` (+77) | ИЗМЁН | Каталог миграций + 0007; `DatasetFileStore.read_checkpoint_snapshot_bytes` — СЫРЫЕ байты снимка, честный None при отсутствии |
| `apps/api/routers/progress.py` (+25/−1) | ИЗМЁН | Pin-aware prune: keep-список keeper'а «последних пяти» объединяется с pinned checkpoint-id; сбой lookup пинов — prune ПРОПУСКАЕТСЯ целиком (fail-closed, T11); путь без пинов байт-в-байт прежний |
| `apps/api/storage_diagnostics.py` (+28) | ИЗМЁН | COMPONENT_ARTIFACTS; `build_artifacts_health` — peek без провокации фабрики, honest `not_initialized`, `object_store=local_fs`, `data_root_configured` как bool (без путей/DSN — T6/T10); блок `artifacts` в `/health/ops` |
| `docs/doclog1_durable_artifacts.md`, `tests/api/test_doclog1_artifacts.py` (1264 строки, 59 тестов) | НОВЫЕ | Документация и корпус исполнителя (в аудите НЕ использовались как источник оракулов) |

Сверка границ: новых HTTP-маршрутов поставка НЕ добавляет (заявление исполнителя подтверждено) — доступ через PromotionService; DOCLOG-2/3/4 не затронуты.

---

## 3. Оракулы на СВОИХ данных (62; GREEN ×2)

Корпус сертификатора: `scripts/doclog1cert/` (conftest + unit + api). Дизъюнкт с repo-корпусом: RUN-D1C*, сессии d1cert-*, отпечатки c1f5…/e7b4…, собственные полезные грузы (в т.ч. кириллица), изоляция каждого теста (свой tmp_path/CISSTAT_DATA_DIR, сброс singleton-фабрик).

**GREEN ×2 на 78769bd: 62/62 passed** (прогон 1: 3.00s; прогон 2: 2.98s) — `oracles_green_protocol.txt`.

Покрытие оракулов (контрактные точки, НЕ копии repo-тестов):
- **Digest-схемы (9):** детерминизм канона (сортировка+компактность), неэкранированный UTF-8, отказ NaN/±Inf (вложенные), независимый пересчёт content-sha256, algorithm/version у data_digest, структурное НЕсмешение digest-типов, строгая валидация source-ref (64-hex: регистр/длина/не-hex/типы), схема artifact_id, каталог kind'ов.
- **Staging-протокол (10):** точность sha/size и серверное имя staging-файла (T9), отказ не-bytes/пустого media_type, content-addressed размещение + очистка staging, дедупликация одинакового контента, fail-closed при подмене байтов staged (объект НЕ появляется), отказ при подмене размера, целостность чтения против content-key (T8), sweep только возрастных orphan с нетронутыми commit-объектами, `default_root` по env/фолбэку.
- **Реестр и пины (8):** round-trip + семантика копий R1 (мутация выдачи не портит store), идемпотентность (новый id, тот же producer+контент → existing, False), конфликт контента без записи, фильтры list по run/kind, отказ на плохой id/kind, идемпотентность pin по тройке с сохранением первой причины, unpin только целевой тройки, scope pinned_checkpoint_ids по run И ref_kind.
- **Миграция и health (7):** таблицы/UNIQUE/FK в каталоге, файл-паритет 0007, вхождение в общий MIGRATION_STATEMENTS; honest `not_initialized` peek'а, память после инициализации без утечки путей, явный memory-backend; required-режим с недоступным Postgres → RuntimeError fail-closed (P21/F14).
- **Сервис/маршруты (28):** матрица авторизации (owner/foreign reason=foreign_session/anonymous/creator-continuity на legacy/uniform-чтение «чужой=несуществующий»/admin-read); uniform-отказ отсутствующего run на WRITE-пути (ArtifactAccessDenied, не PromotionDenied); **критерий §19 — чтение артефакта и payload ПОСЛЕ удаления TTL-сессии**; адаптеры (payload паспорта с source-ссылкой, honest-отказы неизвестного этапа/отсутствующего снимка БЕЗ фабрикации, изоляция panel_entry от однорядной вселенной + перенос panel-блока, per-entity/pooled КАК ЕСТЬ, dependencies Model Card, frozen-прогноз payload==entry, NaN-отказ без записи, идемпотентный репромоушен без дубля объекта); данные чекпоинта (СЫРЫЕ байты, data_digest, авто-pin с причиной, честное отсутствие, source_bytes_sha256=None — отказ от ложного provenance); невалидный source-ref → None; `/health/ops` artifacts-блок (honest not_initialized/memory, без утечек путей/DSN); **AC04 через реальный POST** (7 чекпоинтов: pinned выживает, unpinned вытолкнут окном, свежий в окне); **fail-closed prune** (сломанный lookup пинов — НИЧЕГО не удалено при реальном вытеснении); базлайн keeper'а без пинов (честно-зелёный пин).

В ходе калибровки корпуса (до RED) исправлены 6 дефектов САМОГО оракульного корпуса; продуктовый код не менялся. Находка дизайна оракула: для checkpoint-data артефакта реализация честно НЕ переносит fingerprint исходного датасета (байты снимка ≠ байты исходного файла) — оракул закрепляет честное `None` вместо ложного provenance.

---

## 4. RED на родителе `fb26f6f` (git worktree)

Факт того, что корпус проверяет ИМЕННО контур DOCLOG-1: на родительской базе (без `artifact_store.py`/`artifact_promotion.py`/миграции 0007/artifacts-блока) корпус не может быть зелёным — `red_repro_protocol.txt`:

- **unit-файл: collection-error** — `ImportError: cannot import name 'artifact_store' from 'apps.api'` (32 теста не собраны);
- **API-файл: 27 FAILED / 2 честно-зелёных пина**:
  - FAILED — `ModuleNotFoundError: No module named 'apps.api.artifact_promotion'` / `'apps.api.artifact_store'`, `KeyError: 'artifacts'` (нет блока health), отсутствие PromotionService/маршрутного pin-контурта;
  - честные пины (GREEN на обеих базах, доказывают работоспособность харнеса): `test_baseline_keeper_without_pins_unpinned_sixth_removed` (контракт keeper'а «последних пяти» существовал ранее), `test_ops_health_leaks_no_paths_or_dsn` (отсутствие утечек в уже существовавшем ответе).

Итого RED-факт: 27/29 API-проверок + весь unit-корпус падают строго на отсутствующем контуре; пины — вне границ DOCLOG-1.

---

## 5. Мутационная кампания на СВОИХ мутантах

Двухканальная схема repo+oracle: ORACLE-канал — 62 оракула сертификатора; REPO-канал — `tests/api/test_doclog1_artifacts.py` + `tests/api/test_research_runs.py` + `tests/api/test_session_store.py`. Точечные байтовые замены (контроль единственного вхождения), побайтовое восстановление, md5-паспорта до/после, финальный контроль `git diff` чист — `mutations_protocol.txt`.

### 5.1. Результаты: 27 боевых мутантов

- **17 DUAL-KILLED** (убиты обоими каналами): M01 маскировка NaN (T12); M02 инверсия verify staging (AC08); M03 снятие проверки целостности чтения (T8); M04 искажение algorithm/version; M05 снятие идемпотентности/конфликта Memory (AC09); M06 pinned_checkpoint_ids без фильтра kind; M08 sweep не удаляет orphan; M10 схема artifact_id; M15 снятие write-классификации отказа (R09); M16 снятие изоляции panel-вселенной (R4/AC13); M17 подмена честного NaN-отказа (AC12-дух); M19 снятие авто-pins (AC04); M20 снятие зависимости card→checkpoint; M23 миграция 0007 вне каталога; M25 снятие объединения keep+пины (AC04); M26 удаление artifacts-блока health (T6); M27 раскрытие пути в health (T10).
- **8 ORACLE-ONLY** (убиты только оракулами сертификатора — вклад независимого корпуса): M07 идемпотентность pin_ref; M09 схема content-ключа `[:2]`→`[:1]`; M11 required fail-closed фабрики (P21/F14); M12 staging не убирается после коммита; M13 семантика копий реестра (R1); M14 uniform-отказ отсутствующего run на write-пути; M21 фабрикация невалидного source-ref; M24 fail-closed prune при сбое lookup (T11).
- **2 DUAL-SURVIVOR** — равносильные, задокументированы (§5.3).
- **Контроли: 3/3 ALIVE(OK)** (CTL-01/02/03, no-op-комментарии во всех целевых файлах).

### 5.2. Итоговая метрика

**25/27 боевых мутантов убиты (17 DUAL + 8 ORACLE-ONLY); 0 необъяснённых выживших; 2 равносильные задокументированы; контроли 3/3 ALIVE; RESTORE-FAIL 0.**

### 5.3. Равносильные мутанты (честная документация)

- **M18** (`artifact_promotion.py`, снятие предварительного `_find_by_producer`): идемпотентность AC09 гарантируется самим реестром — `register_artifact` возвращает существующую запись по UNIQUE(run_id, producer_key), object store дедуплицирует по content-key; предварительный поиск — оптимизация, исключающая лишнюю запись объекта. Поведенческой разницы на контракте нет; мутант равносилен на обоих каналах.
- **M22** (`research_runs.py`, снятие явного `return None` при отсутствии файла снимка): при мутанте `path.read_bytes()` бросает `FileNotFoundError`, который ловится существующим `except OSError` → тот же честный `None` + warning. Сходящийся fail-путь; мутант равносилен.

Примечание к методике: в ходе кампании первоначальная редакция M14 и M27 (слабые якоря) дала DUAL-SURVIVOR; после уточнения якорей и добавления оракула uniform-отказа оба переведены в убитые (ORACLE-ONLY / DUAL-KILLED соответственно) — кампания перезапущена целиком, финальный протокол — в `mutations_protocol.txt`.

---

## 6. Полный регресс (дельта против родителя)

Полный `pytest tests/` на сертифицируемой базе и на родителе `fb26f6f` через git worktree (среда идентична, `DATABASE_URL=""` песочницы):

| База | passed | failed | skipped | время |
|---|---|---|---|---|
| `78769bd` (сертифицируемая) | 4411 | 23 | 66 | 453s |
| `fb26f6f` (родитель, worktree) | 4352 | 23 | 66 | 449s |

Прирост passed: **+59** (корпус исполнителя DOCLOG-1); дельта failed: **0**.

**Сравнение FAILED/ERROR-ID: множества ИДЕНТИЧНЫ (23/23, побайтово)** — `regress_cert_failed_ids.txt` vs `regress_parent_failed_ids.txt`; класс отказов — средовой (psycopg DSN песочницы, neural-зависимости вне установленного каталога), идентичен сертификационным отчётам 3b-FIX/DOCLOG-0/DOCLOG-0-CERT. Дельта-0: поставка не меняет поведение вне своего контура.

Сборка: импорт всех затронутых модулей + FastAPI-приложение (OpenAPI: 171 путь; роутеры монтируются `_IncludedRouter`); каталог миграций 41 statement / 7 файлов с 0007; `ARTIFACT_KINDS` = 5. Фронтенд/TS не затронуты.

---

## 7. Воспроизводимость

```bash
# оракулы (GREEN)
python -m pytest scripts/doclog1cert -q --no-header -p no:cacheprovider
# RED на родителе
python scripts/doclog1cert/red_repro.py
# мутационная кампания (восстанавливает состояние сама)
python scripts/doclog1cert/mutations.py
```

Артефакты сертификации: `oracles_green_protocol.txt` (GREEN ×2), `red_repro_protocol.txt` (RED), `mutations_protocol.txt` (кампания + паспорта), `md5_passport_before.txt` / `md5_passport_after.txt` (идентичны), `regress_cert_failed_ids.txt` / `regress_parent_failed_ids.txt` (дельта-0), полные выводы регрессов.

md5-паспорта продуктовых файлов поставки (после сертификации, = до):
`9229c221cc6f… artifact_store.py`, `c32b3736dc94… artifact_promotion.py`, `45b7f11e1fff… 0007_doclog1_artifacts.sql`, `593f23e42796… research_runs.py`, `524809a9a375… routers/progress.py`, `132840ed89b3… storage_diagnostics.py`.

---

## 8. Границы сертификации (честные ограничения)

1. Postgres-ветка (`PostgresArtifactRegistry`, миграция 0007 на живой БД) проверена статически (DDL-паритет, контракт-каталог) и через контракт-зеркало Memory-реализации; runtime-прогон на реальном Postgres вне песочницы — среда сертификации не содержит БД (тот же класс ограничений, что в предыдущих CERT).
2. Полный mark-and-sweep GC объектов, retention/backup, render-очередь — границы DOCLOG-5/6 (заявления исполнителя совпадают со спекой).
3. Равносильные M18/M22 — на текущем контракте; ужесточение контракта (например, spy на отсутствие лишней записи объекта) отнесено к задачам исполнения, не сертификации.
4. `/health/ops` проверен в advisory-режиме песочницы; required-режим покрыт оракулом фабрики (fail-closed) без полного поднятия приложения.
