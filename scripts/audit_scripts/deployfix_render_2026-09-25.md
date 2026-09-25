# Акт инцидента DEPLOY-1 (2026-09-25): render.com — ImportError «Общий реестр EDA не найден»

Статус: ПРИЧИНА НАЙДЕНА И ИСПРАВЛЕНА (apps/api/Dockerfile). Без commit/push (AGENTS.md).

## 1. Симптом

Передеплой render.com (web-сервис cisstat-ts-analysis-api, runtime: docker, dockerfilePath:
./apps/api/Dockerfile, dockerContext: . — по render.yaml) падает циклично:

    ImportError: Общий реестр EDA не найден: /app/shared/pipeline_nodes/eda_checks.json
    (§12 п.2); файл обязателен для старта графа пайплайна
    ==> Exited with status 1
    ==> No open ports detected, continuing to scan...

Сборка образа при этом УСПЕШНА (шаги pip/COPY/RUN-гварды model_impls проходят) — падает
УЖЕ ЗАПУЩЕННЫЙ контейнер, поэтому Render показывает «No open ports detected» и перезапускает
деплой по кругу.

## 2. Цепочка старта (точки отказа)

CMD uvicorn apps.api.main:app
  → apps/api/main.py:32        from apps.api.trace_hook import TraceHookMiddleware
  → apps/api/trace_hook.py:61  from app.core.pipeline_graph import is_known_node
  → app/core/pipeline_graph.py:128   EDA_CHECK_DEFS = _load_eda_check_defs()  ← module-level,
     fail-closed: FileNotFoundError → ImportError (сообщение из §12 п.2) → exit 1.

## 3. Root cause

apps/api/Dockerfile копирует в образ только каталоги, отобранные СТАТИЧЕСКИМ AST-разбором
импортов бэкенда: app/, validation/, src/, apps/api/, rules/. Общий реестр EDA — файл-ДАННЫЕ,
не импорт: app/core/pipeline_graph.py читает shared/pipeline_nodes/eda_checks.json на уровне
модуля (§12 п.2). AST-разбор data-зависимости не видит → каталога shared/ в образе не было
НИКОГДА. Зависимость введена в PROGR-2 (4467fae, 2026-09-24); живой контейнер на render.com
был собран из кода старше PROGR-2 (независимо подтверждено live-пробой OUTL-1-CERT: OpenAPI
без DatasetOutlierLineResponse.bounds, без маршрутов /v1/progress), поэтому дефект был
латентным. Передеплой, рекомендованный в OUTL-1-CERT, впервые собрал образ из кода ≥ PROGR-2
и вскрыл его. Логика сбоя согласуется с предыдущей сертификацией: замечание тимлида
«счётчик 0, график не меняется» — стейл-деплой; передеплой вскрыл следующий слой проблемы.

Доказательство (scripts/audit_scripts/deployfix_simulate_image.py, без docker): имитация
сборки по COPY-строкам Dockerfile + слой touch apps/__init__.py + стартовый контракт
`from apps.api.main import app` в subprocess с чистым PYTHONPATH:
  [A] без shared/ — exit 1, stderr дословно содержит ошибку render.com;
  [B] с shared/   — exit 0, IMPORT_OK.

## 4. Исправление (apps/api/Dockerfile, блоки помечены «DEPLOY-1»)

1) COPY shared/ ./shared/ — с комментарием о классе бага (data-файлы невидимы AST-разбору).
2) Build-гвард после слоя `RUN touch apps/__init__.py`:

       RUN python -c "from app.core.pipeline_graph import EDA_STAGE_IDS; \
                      print('pipeline graph OK, EDA nodes from shared JSON:', len(EDA_STAGE_IDS))"

   Философия файла соблюдена (прецедент rules/modeling.yaml): при отсутствии/битом реестре
   СБОРКА падает с явной ошибкой — инцидент класса DEPLOY-1 отныне не доходит до прода.
   Верификация гварда (scripts/audit_scripts/deployfix_verify_guard.py, код RUN парсится
   из Dockerfile): [A] без shared/ сборка падает с искомой ошибкой; [B] с shared/ —
   «pipeline graph OK, EDA nodes from shared JSON: 10».

## 5. TDD и тесты

- tests/api/test_docker_image_layout.py (4 теста, docker не нужен): статическая проверка
  состава COPY; валидность реестра; имитация образа после фикса стартует; имитация БЕЗ
  shared/ воспроизводит инцидент дословно (защита fail-closed контракта §12 п.2 от
  ослабления). RED→GREEN подтверждены: до фикса падали (1) и (3) по правильной причине.
- Смежные сюиты после фикса: pipeline_graph + progress_panel + progress_trace_hook +
  research_runs + docker_layout = 257 passed. Python-код продукта не менялся.
- Отрицательные проверки (латентные баги того же класса): data/ для файлового слоя PROGR-5
  создаётся лениво mkdir(parents=True, exist_ok=True) — в образе не нужна; config/, docs/,
  packages/ на импорте бэкендом не читаются (полный стартовый импорт проходит на
  {app, validation, src, apps/api, rules, shared}).

## 6. Инструкция тимлиду

1. Взять apps/api/Dockerfile из ZIP (или добавить два блока «DEPLOY-1» вручную).
2. Manual Deploy на render.com.
3. Контроль сборки: в логе обязана появиться строка
   «pipeline graph OK, EDA nodes from shared JSON: 10».
4. Контроль рантайма: python3 scripts/cert_outl1_live_probe.py — шаг 3 обязан показать
   bounds в ответе /outlier-line (замыкает контроль OUTL-1-CERT: границы метода и
   ревизионный refresh станут видны пользователю).
5. При повторении ошибки сборки на гварде — деплоится не тот Dockerfile: сверить
   dockerfilePath/dockerContext с render.yaml (Root Directory «.», Dockerfile Path
   «./apps/api/Dockerfile»).

## 7. Находки

- N-1 (Info): корневой Dockerfile (Streamlit, 8501) — другой деплой, не затронут (COPY . .).
- N-2 (Info): .dockerignore корня shared/ не исключает — масок-виновников нет, зависимость
  просто не была перечислена в COPY.
- R-1 (Low, осознанно): тест-парсер Dockerfile поддерживает только канонизированные строки
  `COPY <dir>/ ./<dir>/`; новый синтаксис уронит тест (1) и заставит расширить парсер явно.
- R-2 (Info): рекомендация OUTL-1-CERT остаётся: git-sha маркер в /health — drift деплоя
  проверялся бы одной командой; в объём данной задачи не входил.
