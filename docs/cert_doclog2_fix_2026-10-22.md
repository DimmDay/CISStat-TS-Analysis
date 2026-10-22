# Акт пересертификации DOCLOG-2-FIX (2026-10-22)

**Задача DOCLOG-2-FIX**: устранение блокирующего продуктового дефекта
F-D2C1 из акта сертификации DOCLOG-2 (`docs/cert_doclog2_2026-10-22.md`,
§4/§4.1) и пересертификация поставки DOCLOG-2 (288fdde) на базе
main@a6175d0. Режим «без манифеста sha256» (указание тимлида),
целостность дерева — git + md5-паспорта файлов мутационной кампании.
Продуктовый код изменён ровно одной строкой (фикс F-D2C1); тесты
репозитория дополнены гвардом класса.

## Вердикт: **СЕРТИФИЦИРОВАНО (PASSED)** — блокер F-D2C1 устранён, все критерии DOCLOG-2 §19 подтверждены, дельта-0 полного регресса доказана

---

## 1. Постановка и граница

Постановка тимлида: «Синхронизируйся до a6175d0. Спроектируй и исправь
найденные тобой находки — DOCLOG-2-FIX: однострочный фикс
_record_from_row (убрать created_at=/транслировать в captured_at),
перенос PG-зеркальных оракулов в repo-сюиты как гварда класса, полный
регресс + пересертификация. Следуй правилам AGENTS.md. По завершении
работы выложи в открытый контейнер сессии zip новых/обновленных файлов
для скачивания».

Объём пересертификации = план устранения акта DOCLOG-2-CERT §4.1:
1. однострочный фикс `_record_from_row`;
2. перенос PG-зеркальных оракулов в repo-сюиту (гвард класса F-D2C1);
3. полный регресс дельта-0 + пересертификация Postgres-ветки —
   поведенческая мутационная кампания SQL-зоны (закрытие честной
   границы §9 прежнего акта).

## 2. Синхронизация, атрибуция, среда

База: main@a6175d0 (чистое дерево, `git reset --hard`; локальные
артефакты прошлой сессии поглощены a6175d0 — запись DOCLOG-2-CERT
закоммичена тимлидом байт-в-байт; в рабочем дереве также найдены
случайные удаления двух page.tsx — восстановлены синхронизацией).
Атрибуция переносится: `git diff 288fdde a6175d0 --
apps/api/report_snapshot.py apps/api/snapshot_builder.py` = 0 строк —
на дереве a6175d0 поверх DOCLOG-2 добавлен только DOCLOG-3 (b530606:
telemetry/audit; продукты DOCLOG-2 не тронуты).

Среда пересоздана до паритета сессии DOCLOG-2-CERT: на чистой сессии
отсутствовали pandera/psycopg/statsforecast/prophet/arch/sqlalchemy/
duckdb/syrupy/PyWavelets, statsmodels был 0.14.5 — установлено по
требованиям репо (pandera 0.34.1, PyWavelets 1.8.0, psycopg 3.3.6,
statsforecast 2.1.1, prophet 1.4.0, arch 8.0.0, sqlalchemy 2.1.6,
duckdb 2.0.0, syrupy), statsmodels → **0.15.0**; pip строго
`python3 -m pip`. Прецедент: база оракулов на неполной среде давала
1 failed + 8 errors (pandera/pywt) — после восстановления паритета
79/79.

## 3. Фикс (TDD RED → GREEN)

**Точка изменения — одна строка**: apps/api/report_snapshot.py,
`PostgresSnapshotRegistry._record_from_row` (строка 611), kwarg
`created_at=` → `captured_at=` (выражение значения не менялось).
Семантика: INSERT реестра пишет `snapshot.captured_at` в колонку
`created_at` (report_snapshot.py:705), поэтому трансляция
`row[30] → captured_at` — точный раундтрип значения. Альтернатива
плана §4.1 «просто убрать kwarg» отвергнута: трансляция сохраняет
метку времени и паритет с Memory-реестром (записи несут captured_at);
дефект-класс идентичен fit_panel_var:806 (3b-CERT) — kwarg, которого
нет у дата-класса.

**RED** (на дефектном коде, до фикса): перенесённый гвард
`TestPostgresMirrorRegistry` — **3 RED / 2 GREEN**: падают
test_register_then_get_roundtrip, test_find_idempotent_returns_
existing_with_same_fingerprint, test_conflict_replay_path_raises_409_
semantics — все три с корнем `TypeError: ReportSnapshot.__init__()
got an unexpected keyword argument 'created_at'` на путях
get_snapshot_record / find_idempotent / конфликт-ветка
register_snapshot (то самое F-D2C1); статический alignment и
list_dependencies GREEN. Протокол: scripts/doclog2fix/protocols/
red_repo_guard.txt (прогон с временным реверсом фикс-строки,
восстановление md5-паспортом — байт-точно).

**GREEN**: гвард 5/5; repo-сюита DOCLOG-2 целиком **73/73**
(protocols/repo_suite_green.txt); оракульный корпус сертификации
scripts/doclog2cert — **79/79 ×2** (3.37s/3.37s; три бывших
F-D2C1-RED перевернулись в GREEN). Протоколы: protocols/
oracle_green_run1.txt, oracle_green_run2.txt.

## 4. Перенос PG-зеркальных оракулов (гвард класса)

Из сертификаторского класса TestOrcPostgresMirror (6 оракулов) в
tests/api/test_doclog2_snapshots.py перенесены **5** как класс
`TestPostgresMirrorRegistry` (секция 4b): fake-psycopg раундтрип
«INSERT-параметры → строка SELECT-порядка → _record_from_row»
(прецедент fakeredis) + статическая сверка 31 колонки
INSERT≡SELECT≡%s + deps-контракт list_dependencies. Корпус d2-mirror
дизъюнктен сертификаторскому (RUN-D2C*) и остальному repo-корпусу.
Оракул migration-catalog НЕ дублируется сознательно — уже покрыт
тремя пинами TestSnapshotRegistry (test_migration_catalog_contains_
0008 / test_migration_file_parity_with_catalog /
test_unique_constraints_in_ddl).

Усиления против сертификаторской версии (обоснованы гвардом именно
фикс-строки и SQL-зоны): (а) асимметричный cutoff
(last_sequence=12, event_count=9, ordering_quality=legacy) — ловит
индексные сдвиги row[11]/row[12]/row[13], на симметричном корпусе
12/12 сертификатора они не убивались; (б) фиксация
captured_at="2026-10-22T09:30:00+00:00" с ассертом раундтрипа и
isinstance str — гвард фикс-строки (isoformat-ветка); (в) полнополевые
ассерты (kinds/payload_sha256/size_bytes/storage_key/idempotency/
fingerprint/created_by/knowledge_version/context/revision/data_ref/
digest/completeness/reproducibility/dependencies/template); (г) pin
границы N2: event_id_manifest=None в metadata-пути — документированное
текущее поведение (manifest живёт в канонических байтах).

## 5. Мутационная кампания SQL-зоны (закрытие границы §9)

Цель: Postgres-зона apps/api/report_snapshot.py (_record_from_row,
INSERT-параметры register_snapshot, конфликт-ветка идемпотентности).
**13 боевых мутантов + 3 no-op-контроля**, точечные байтовые замены с
пред-проверкой ровно 1 вхождения, восстановление md5-паспортом.
Двухканальная схема: REPO = tests/api/test_doclog2_snapshots.py (73,
вкл. гвард F-D2C1); ORACLE = scripts/doclog2cert (79, БЕЗ deselect —
RED устранены фиксом). Скрипт: scripts/doclog2fix/mutations_sql.py;
протокол: scripts/doclog2fix/protocols/mutations_sql_protocol.json.

**Итог: 13/13 боевых KILLED — 6 DUAL-KILLED (S07 sha←size,
S08 size←sha ValueError, S09 missing_refs←repro_status, S10
created_by=None, S11 INSERT-перестановка sha/size, S13 инверсия
fingerprint-сравнения) + 7 REPO-ONLY (S01 captured_at=None, S02
str(datetime) вместо isoformat, S03/S04 индексные сдвиги cutoff,
S05 захардкоденный ordering_quality, S06 knowledge_version=None, S12
INSERT created_at←now()) — 0 SURVIVED; контроли 3/3 ALIVE
(CTL-S1 docstring, CTL-S2 SQL-пробел, CTL-S3 литерал 00); RESTORE-FAIL
0; tree_restored=True (md5-паспорта).**

REPO-ONLY — ожидаемый результат усиления гварда: сертификаторский
корпус (симметричный cutoff 12/12, без фиксации captured_at, без
полнополевых ассертов PG-пути) эти мутантов не различает; после
переноса усиленного гварда в repo-сюиту канал REPO стал сильнее по
SQL-зоне. Примечание о паспорте: в протоколе кампании
git_diff_empty=False — в дереве НАМЕРЕННО присутствуют правки задачи
(фикс + гвард, 2 файла +312/−1); отсутствие остатков мутантов
доказано md5-паспортами (tree_restored=True, финальный md5
report_snapshot.py 85e534cb7b29c585ddf95993c35d4590 = пост-фиксный).

## 6. Полный регресс (дельта-0)

Метод: посекционный прогон (tests/unit, tests/api, root+integration)
— фоновые/длинные процессы песочницы убиваются на ~4–5-й минуте
(два преждевременно прерванных фоновых прогона отброшены), полный
одним куском не помещается в лимит вызова; прецедент 3b-FIX (unit/api
отдельно). Секунды: unit ~260s, api ~220s, root ~7s.

- **База** (чистый a6175d0, среда §2): unit 26 failed / 1950 passed /
  24 skipped; api 14 failed / 2478 passed / 42 skipped; root+integration
  130 passed. **Итого 40 failed / 4558 passed / 66 skipped.**
- **Пост-фикс** (фикс + гвард): unit 26/1950/24; api 14/**2483**/42
  (+5 = гвард-оракулы); root 130. **Итого 40 failed / 4558+5 passed /
  66 skipped.**
- **Сверка FAILED-ID: множества 40/40 байт-идентичны** (diff пуст;
  protocols/regress_failed_ids_diff.txt). Классы средовые: 14
  MNS-SPEC-PATH + 8 psycopg-DSN (progress_audit_5b/panel) + 6 neural
  (registry-reject пути + capacity) + 12 прочих средовых
  (structural_breaks/rupts, profile-detail, modeling-workflow,
  models-candidates, model-execution-contract). Ноль содержательных
  падений; ноль пересечений с контурами DOCLOG.

Отличие от базы прежнего акта (31 failed @ fa8c949): другая сессия
среды — классы `прочие средовые` расширены версионными сдвигами
опциональных зависимостей; дельта-0 честно считается ВНУТРИ одной
среды (база/пост-фикс выше), что и требуется критерию.

## 7. Сборка

Импорт 8/8 затронутых модулей (report_snapshot, snapshot_builder,
research_runs, storage_diagnostics, telemetry, security_audit,
artifact_store, main); FastAPI-приложение **183 маршрута** (новых нет
— паритет); каталог миграций **9 файлов / 53 statement** (0008 на
месте); DOCUMENT_KINDS = 9 (D01–D09); фикс-строка в исходнике
подтверждена (captured_at= присутствует, created_at= отсутствует).

## 8. Вердикт пересертификации

Блокер F-D2C1 устранён однострочным фиксом, доказанным: RED 3/2 →
GREEN (гвард 5/5, repo-сюита 73/73, оракулы 79/79 ×2); Postgres-ветка
реестра снимков впервые валидирована ПОВЕДЕНЧЕСКИ (мутационная
кампания SQL-зоны 13/13 KILLED, 0 SURVIVED) и гвардом класса в
repo-сюите; полный регресс дельта-0; сборка без изменений. Критерии
DOCLOG-2 §19 (concurrent mutation не смешивает версии,
current/stale/unknown и gaps честны) в durable-режиме теперь
выполнимы: чтение Postgres-реестра (get/find_idempotent/конфликт/
список) не падает. **DOCLOG-2: СЕРТИФИЦИРОВАНО (PASSED).**

## 9. Честные границы

- Живой PostgreSQL-прогон миграции 0008/реестра — по-прежнему вне
  среды (паттерн AUDIT-6A): Postgres-ветка валидирована контракт-
  зеркалом (fake-psycopg), статической сверкой DDL/колонок и
  поведенческими мутантами SQL-зоны; живой прогон — при следующем
  durable-срезе.
- ORDER BY-предложения SQL исполняются СУБД — fake-зеркало не может
  убить их мутантов поведенчески; такие мутанты в кампанию сознательно
  не включены.
- Статический red_repro.py прежнего акта привязан к worktree
  cert-сессии (wt-parent-78769bd) — сессионный артефакт; поведенческое
  RED-доказательство теперь живёт в protocols/red_repo_guard.txt.
- N2 (legacy event_id_manifest в metadata-строке Postgres), N3
  (dependency_refs без авторизации → зафиксировать гейтом в
  постановке DOCLOG-4, дух T15), N4 (валидный JSON вне контракта даёт
  TypeError вместо SnapshotIntegrityError при пустом payload_sha256) —
  остаются неблокирующими наблюдениями прежнего акта; N2 запинован
  гвардом как документированное текущее поведение.
- Восемь ORACLE-ONLY пинов прежней кампании (M03/M08/M13/M14/M15/M16/
  M25/M26) остаются в статусе «рекомендация к переносу в repo-сюиты»
  (N6 прежнего акта) — вне объёма DOCLOG-2-FIX (переносились только
  PG-зеркальные оракулы).
- Jest/typecheck — вне границ: UI/TS не тронуты (прецедент
  PANEL-GMM-4/3b-FIX).
