# Акт независимой сертификации Task PROGR-5 (2026-09-25)

Аудитор: независимо от исполнителя (прецеденты PROGR-1/2/3/4-CERT, OUTL-1-CERT).
Синхронизация: main@b9a16ca (исполнение PROGR-5 — 4c5486a). Правила AGENTS.md: без
commit/push, ZIP в download. Детекторы — СВОИ данные аудитора (seed 20250925,
корпус progr5cert_revenue.csv 40×3 с NaN-зазором), НЕ фикстуры исполнителя.

## 1. Предмет

Task PROGR-5 (plan_progress.md): долговременный слой «Прогресса» — research_runs/
trace_events (spec_progress.md §5 слой 2, Postgres §12 п.1) + чекпоинты (§5.1,
паттерн PassportCheckpoint) + пауза (§5.2) + restore (§5.3) + файловый слой
(§12 п.3 uploads, §12 п.4 снимки, последние 5) + зеркало из хука §4.2 (в дополнение,
не вместо) + унификация Прогнозирования (обещание PROGR-3). Приёмка плана:
«run_id переживает cookie; restore строит новую сессию из трассы; чекпоинт —
именованная ссылка на событие».

## 2. Воспроизведение заявлений исполнителя (10/10 ПОДТВЕРЖДЕНО)

1. tests/api/test_research_runs.py — 60 тестов (заявлено 60/60) — счётчик совпал.
2. Полный tests/api: 1000 passed / 3 failed на b9a16ca = 996 (заявлено) + 4 теста
   DEPLOY-1 (test_docker_image_layout.py, вошли после); 3 падения — ТОЧНО средовой
   baseline (modeling_workflow catalog-only, neural_capacity память, models_candidates
   unsupported-гейт), новых падений нет.
3. Jest полный: 142 сюиты / 1674 теста зелёные = 140/1645 (заявлено) + 2 сюиты/+29
   тестов OUTL-1 — хронология сходится.
4. typecheck:all — чисто (воспроизведён).
5. RED (59 падений по ImportError) — исторически невоспроизводим напрямую; правдоподобен:
   файл теста импортирует research_runs, которого до реализации не было (60-й тест
   добавлен в GREEN; заявка «59» согласуется с 60 факт-тестами).
6. Модели: ResearchRun (8 полей §5, статусы active/paused/completed/abandoned),
   ResearchCheckpoint (event_id + label, has_snapshot) — сверка с §5/§5.1 дословная.
7. Контракт хранилища (10 методов), Memory + Postgres (ленивый коннект, идемпотентный
   DDL), фабрика по env (CISSTAT_RUNS_BACKEND приоритетнее DATABASE_URL; деградация
   в Memory со сбой-логом) — подтверждено оракулами E3/A*.
8. Зеркало в TraceHookMiddleware._record ПОСЛЕ store.save + вызов из _append_event
   forecasting_session.py (унификация) — подтверждено диффом 4c5486a и B5.
9. Отклонение 1 (заявлено): CSV вместо Parquet (§12 п.4) — pyarrow недоступен;
   изоляция в save/load_checkpoint_snapshot — подтверждено (C4, код).
10. Отклонение 2 (заявлено): dataset_fingerprint = SHA-256 байт файла вместо
    «переиспользуй series_fingerprint» (§12 п.3) — обоснование честное
    (series_fingerprint определён на ряде с датой/target, которых при загрузке нет);
    когорты Моделирования продолжают использовать series_fingerprint (grep:
    backtesting.py, modeling_workflow.py — не тронуты) — подтверждено (C1/D1).

## 3. Оракулы аудитора на своих данных: 40/40 PASS

Группа A (MemoryResearchRunStore, 6): R1-изоляция payload на чтении; R4-backfill со
стабильностью id между чтениями; append-only порядок на 12 событиях; supersede
(только активные своей сессии, keep цел, paused/completed/abandoned/чужие не тронуты);
set_run_status ValueError на неизвестный статус + last_active_at; list_runs
(сортировка по created_at, фильтр по сессии).
Группа B (зеркало record_run_event, 6): без run_id — фантом НЕ создан; первый запуск
несёт fingerprint/имя СВОЕГО датасета; target_column_changed ставит И снимает target;
last_active_at движется, session_id = «последний известный»; forecasting-событие с
пустым run_id получает attach из запуска; best-effort — падающий store не роняет вызов.
Группа C (DatasetFileStore, 6): fingerprint == независимый hashlib.sha256 СВОИХ байт;
round-trip байтов/меты; демо builtin_demo БЕЗ копии данных (только meta-sidecar);
CSV-снимок round-trip СВОЕГО df (NaN/float); prune ровно по keep-списку при
подменённом mtime (порядок из хранилища, не mtime); битая мета — честный None.
Группа D (HTTP на реальном стеке TestClient, 16): upload СВОЕГО CSV → запуск с
SHA-256-fingerprint; detail: events_total полн, ?limit — ПОСЛЕДНИЕ N; машина статусов
pause/resume 200/409/404 + run_paused стадии последнего события; чекпоинт 201+снимок
на своё событие, 404 на фантом, 409 на completed; чужая сессия — ссылка БЕЗ снимка;
restore 404/409(completed)/409(нет файла); happy path restore: НОВЫЙ cookie, ТОТ ЖЕ
run_id, мой датасет, target из метаданных, засев слоя 1, run_resumed{restored:true} в
обоих слоях, перелинковка session_id; supersede прочих активных старой сессии; run
переживает cookie (событие новой сессии продолжает запуск); cap засева (1005 в слое 2 →
events_restored=1000, слой 1 ≤ 1000, run_resumed последним); N-2 (stage-level остаются
node_id=None, session.stages не тронут); N-4 (ни одного ключа close_panel/open_panel/
navigate/redirect); 503-контур (сбой → 503, 404 фактов насквозь); demo →
builtin_demo-fingerprint == SHA-256 демо-файла; target НЕ из колонок файла не
применяется; чужая сессия не получает зеркала чужой паузы.
Группа E (Postgres-контур без сервера, 6): MIGRATION_STATEMENTS == 0001_research_runs.sql
(текст в текст по каждому утверждению — файл-дубль не разошёлся); DDL-структура (PK/FK
ON DELETE CASCADE/UNIQUE(run_id,event_id)/индексы); фабрика (memory-приоритет, DATABASE_URL
→ Postgres лениво без коннекта, from_env без DSN → RuntimeError, деградация в Memory);
_ts_to_db/_ts_from_db (round-trip, naive→UTC, битый ts — деградация к текущему моменту);
иммутабельность моделей + from_dict/to_dict; stage_for_run_level_event.

## 4. Мутационный прогон аудитора: 20/20 KILLED (у исполнителя мутационного прогона не было)

M1 supersede no-op; M2 supersede трогает keep; M3 target не фиксируется; M4 фантом
без run_id; M5 R4-backfill удалён; M6 md5 вместо sha256; M7 prune отключён; M8 стадия
run-level всегда upload; M9 двойная пауза без 409; M10 resume из любого статуса;
M11 чекпоинт на фантом-событие; M12 чекпоинт по completed; M13 restore completed;
M14 restore без файла не 409; M15 target без проверки колонки; M16 засев без cap;
M17 run_resumed без restored=true; M18 без перелинковки session_id; M19 503 проглочен;
M20 зеркало в чужую сессию слоя 1. Детекторы — только оракулы аудитора; сьют
исполнителя в прогоне не участвовал. Методология: побайтовое восстановление с
верификацией, purge __pycache__, PYTHONDONTWRITEBYTECODE, сдвиг mtime (уроки
OUTL-1-CERT применены сразу). Среды: два дефекта раннера (потеря __name__ в
декораторе-обёртке; ложный «пустая база»-гард) пойманы и устранены ДО зачётного
прогона — baseline 20/20 PASS на нетронутых исходниках.

## 5. Находки

- CERT-N-1 (Info, дизайн-следствие §5.3): run_id — bearer-возможность. Любой, кому
  известен run_id, может паузить/ресторить/чекпоинтить ЧУЖОЙ запуск (аутентификации
  на /v1/session/* нет — §10 спеки это фиксирует; §5.3 дословно: «если предъявленный
  run_id валиден»). Для MVP корректно, но к PROGR-8 (админ-контур, API-ключ) и
  появлению auth стоит вернуться к ownership-модели; ответ D16 подтверждает хотя бы
  честность зеркала (чужая сессия слой 1 не получает).
- CERT-N-2 (Info): Postgres get_event читает ВСЕ события запуска и фильтрует в Python
  (O(n) на операцию); на объёмах одной платформы (§12 п.1) приемлемо; при росте —
  WHERE event_id = %s в SQL.
- CERT-N-3 (Info): при заполненном cap засева (1000) дописывание run_resumed вытесняет
  старейшее событие из слоя 1 (граница буфера — контракт PROGR-3); полная история
  остаётся в слое 2, events_total честен — поведение соответствует дизайну, зафиксировано
  тестом D10.
- CERT-N-4 (Info): Postgres-операции делают conn.commit() внутри context-manager'а,
  который сам коммитит при выходе — двойной commit безвреден, на исключение — rollback
  контекст-менеджером; шум, не дефект.
- CERT-R-1 (Low): DatasetFileStore._ext_of сохраняет файл с НЕизвестным расширением под
  суффиксом .csv; restore определяет формат по имени из меты — для известных форматов
  (csv/xlsx/xls/tsv/json) корректно, для будущих (parquet и пр.) возможно расхождение
  суффикса и содержимого; кандидат в допустимые расширения при появлении таких форматов.
- Замечание о среде (не находка по коду): Postgres-реализация в среде аудтора не
  исполняется (нет сервера/драйвера) — как и у исполнителя; компенсации: текстовая
  сверка DDL, структурные проверки, ленивый импорт, выбор фабрики (E-группа);
  поведенческий интеграционный прогон — на on-prem Postgres (ops: 0001_research_runs.sql).

## 6. Вердикт

**PASSED WITH REMARKS.** Реализация PROGR-5 соответствует spec_progress.md §5/§5.1–5.3,
§12 п.1/п.3/п.4 и плану: 40/40 оракулов аудитора на своих данных, 20/20 мутантов KILLED
(детекторы — только оракулы аудитора), 10/10 воспроизведений заявлений исполнителя,
оба отклонения (CSV вместо Parquet; file-SHA-256 вместо series_fingerprint) обоснованы,
изолированы и не затрагивают смежные контракты (когортная сверка Моделирования цела).
Приёмка плана «run_id переживает cookie» подтверждена независимо (D7/D9). Блокеров нет.
