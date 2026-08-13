# scripts/smoke/ — дымовые тесты деплоя CISStat TS Analysis

Smoke-тесты проверяют **продакшн-деплой целиком** (бэкенд + CORS + cookies + сессия), а не отдельные функции как unit-тесты из `tests/`. Их задача — быстро (за минуту) ответить на вопрос: «можно ли вообще работать с платформой прямо сейчас?».

## Когда запускать

| Ситуация | Зачем |
|---|---|
| После деплоя нового коммита в `main` | проверить, что ничего не сломалось в реальной среде |
| Перед началом новой фазы разработки (см. `worklog.md`) | убедиться, что фундамент для следующей фазы работает |
| При жалобах пользователя «не работает» | локализовать: беда на стороне бэкенда или UI |
| После паузы в разработке | render.com Free Tier засыпает; cold-start может вылиться в реальные баги |

## Структура папки

```
scripts/smoke/
├── README.md          ← этот файл
├── pre_0_smoke.py     ← PRE-0: продакшн-деплой API (render.com) + cookies + CORS
└── *_output/          ← генерируется при запуске (в .gitignore)
```

Каждая новая фаза разработки получает свой smoke-тест:

- `pre_0_smoke.py` — базовая связка /health, CORS, session, upload, /v1/models (без auth)
- `phase_0_smoke.py` — SessionStore abstraction, мост Upload → Backtest (появится в Phase 0)
- `phase_6_p0_smoke.py` — реальные ETS/ETS Damped/Theta/ARIMA/Auto-ARIMA в проде
- и т.д.

### Что проверяет `phase_6_p0_smoke.py`

Запускается против Vercel-фронта (`https://ts-standalone.vercel.app`), все запросы
через Next.js rewrite → Render backend. Использует ту же cookie/session что и
реальный пользователь:

1. **POST /api/v1/internal/upload** — загрузить 24-месячный CSV (тренд + сезонность)
2. **POST /api/v1/session/target-column** — выбрать колонку "value"
3–7. **POST /api/v1/internal/models/backtest** для каждой из 5 моделей:
   - `ets`, `ets_damped`, `theta`, `arima`, `arima_auto`
   - Проверка: `data_source === "session"` (РЕАЛЬНЫЙ ряд), `mae > 0`,
     `weighted_score ∈ [0, 1]`, `n_train + n_test === 24`
8. **≥3 уникальных MAE из 5 моделей** — доказательство, что это НЕ заглушка
   `naive*penalty` (там бы 3 exponential_smoothing модели дали одинаковое
   значение). Если 5 моделей дают только 2 уникальных MAE — заглушка активна.

**Критерий PASS Phase 6-P0**: 8/8 (1 upload + 1 target-column + 5 backtest + 1 distinct-MAE).


## Требования

- Python 3.10+ (тестировалось на 3.12)
- `httpx>=0.27` — единственная внешняя зависимость

```bash
pip install httpx
# или, если используется uv:
uv pip install httpx
```

Системные зависимости не нужны — это чистый HTTP-клиент, без `pandas`/`statsmodels`.

## Запуск

### По умолчанию (против продакшена)

```bash
cd CISStat-TS-Analysis
python scripts/smoke/pre_0_smoke.py
```

Это обратится к `https://cisstat-ts-analysis.onrender.com` с `Origin: https://ts-standalone.vercel.app` — те же параметры, что использует реальный standalone-фронтенд.

### Против локального бэкенда

```bash
# Терминал 1: поднять бэкенд
cd apps/api
uvicorn apps.api.main:app --reload --port 8000

# Терминал 2: поднять фронтенд (любой)
cd apps/standalone
npm run dev  # поднимется на http://localhost:3000

# Терминал 3: smoke-тест
CISSTAT_API_URL=http://localhost:8000 \
CISSTAT_FRONTEND_ORIGIN=http://localhost:3000 \
python scripts/smoke/pre_0_smoke.py
```

### Свои параметры (CLI)

```bash
python scripts/smoke/pre_0_smoke.py \
  --api-base https://cisstat-ts-analysis.onrender.com \
  --frontend-origin https://ts-standalone.vercel.app \
  --demo-csv apps/api/demo_data/sales_demo.csv \
  --output-dir ./pre_0_smoke_output
```

`--help` покажет все опции.

### Где отчёты

После запуска в `--output-dir` (по умолчанию `./pre_0_smoke_output/`):

```
pre_0_smoke_output/
├── report.json   — структурированный отчёт (для парсинга)
└── report.md     — человекочитаемый отчёт (для чтения / в PR)
```

Каталог `*_output/` добавлен в `.gitignore` — не коммитить.

## Что проверяет `pre_0_smoke.py`

7 кейсов, по возрастанию сложности. Каждый следующий использует cookie/session из предыдущего — порядок важен.

### 1. GET /health → 200, body.status=ok

Самая простая проверка: сервер жив, отвечает за разумное время. Дополнительно выступает как «cold-start break»: если render.com Free Tier спал, этот запрос разбудит сервис, и последующие кейсы не получат 30-секундных задержек.

**Критерий PASS**: HTTP 200, JSON `{"status": "ok"}`.

### 2. OPTIONS /v1/session/current → CORS preflight проходит

Браузер перед credentialed cross-origin запросом отправляет preflight `OPTIONS`. Этот кейс проверяет, что:

- `Access-Control-Allow-Origin` равен **точному** Origin фронтенда (не `*` — `*` не работает с credentials)
- `Access-Control-Allow-Credentials: true`
- Все нужные методы разрешены

Если здесь FAIL — фронтенд не сможет сделать ни один авторизованный запрос.

**Критерий PASS**: HTTP 200/204, ACAO=`<frontend_origin>`, ACAC=`true`.

### 3. GET /v1/session/current → Set-Cookie с правильными атрибутами

Проверяет, что бэкенд выдаёт cookie сессии с корректными атрибутами для cross-domain:

- `cisstat_session_id=<uuid>` — само значение
- `HttpOnly` — недоступен из JS (защита от XSS)
- `SameSite=none` — разрешает cross-site (нужно для Vercel→Render)
- `Secure` — только по HTTPS (обязательно с `SameSite=none`)

Если `SameSite=lax` (значение по умолчанию для dev-режима) — браузер не отправит cookie на cross-site fetch, и весь session-based flow сломается.

**Критерий PASS**: HTTP 200, cookie set, все 4 атрибута присутствуют.

### 4. GET /v1/session/current с cookie → round-trip

Повторяет #3, но теперь httpx.Client отправляет cookie из предыдущего ответа. Проверяет два свойства:

- Сервер **узнаёт** сессию (не создаёт новую)
- В ответе **нет** нового `Set-Cookie` (если есть — сервер не различает сессии, баг)

**Критерий PASS**: HTTP 200, в ответе нет `Set-Cookie: cisstat_session_id=...`.

### 5. POST /v1/internal/upload → загрузка CSV

Реальная загрузка файла `apps/api/demo_data/sales_demo.csv` (72 строки, 5 колонок, 3.1 KB). Проверяет всю цепочку:

- `python-multipart` парсит `multipart/form-data`
- `app.data.file_loader.read_uploaded_file` читает CSV
- `upload_common._compute_column_info` строит метаданные колонок
- `upload_common._compute_quality_teaser` считает пропуски/выбросы
- Сессия сохраняет DataFrame в `SessionStore`

**Критерий PASS**: HTTP 200, в ответе есть `dataset_id`, `rows > 0`, `columns > 0`, `error is None`.

### 6. GET /v1/session/current после upload → has_active_dataset=true

Использует ту же cookie/session, что #5. Проверяет, что SessionStore **сохранил** датасет между запросами — это и есть тот «мост», на котором будет строиться Phase 0 (`/backtest` должен читать `session.dataframe[target_column]`).

Дополнительно проверяет `stages.upload = "done"` — серверная стадийная модель корректно обновляется.

**Критерий PASS**: HTTP 200, `has_active_dataset=true`, `dataset` заполнен, `stages.upload="done"`.

### 7. POST /v1/models/candidates без API-ключа → 401/422

Контр-интуитивный кейс: мы ожидаем **отказ**, а не успех. Эндпоинт `/v1/models/candidates` защищён `require_capability("can_train_models")`, который требует `X-Api-Key`. Без ключа FastAPI должна вернуть:

- **422** — заголовок `X-Api-Key` отсутствует (ожидаемое поведение)
- **401** — заголовок есть, но ключ невалиден
- **403** — ключ валиден, но capability отсутствует

**Если 200 — это баг**: auth-цепочка пропускает без ключа. Это означало бы, что любой посетитель может дёргать `/v1/models/*` (включая будущий `/tune`, `/compare`), что нарушает платёжную модель.

**Критерий PASS**: HTTP 401/422/403 (всё, что не 200).

## Интерпретация результатов

```
[PASS] 1. GET /health (31361ms)           ← холодный старт OK
[PASS] 2. OPTIONS /v1/session/current (455ms)
[PASS] 3. GET /v1/session/current (Set-Cookie) (191ms)
[PASS] 4. GET /v1/session/current (round-trip с cookie) (162ms)
[PASS] 5. POST /v1/internal/upload (CSV) (336ms)
[PASS] 6. GET /v1/session/current (после upload) (178ms)
[PASS] 7. POST /v1/models/candidates (без API-ключа → 401/422) (166ms)
============================================================
TOTAL: 7/7 passed, 0 failed
```

| Что значит | Действие |
|---|---|
| **7/7 passed** | Прод работает, можно переходить к следующей фазе разработки |
| **6/7, fail на #1** | Сервис упал. Проверить логи в Render Dashboard, перезапустить |
| **6/7, fail на #2 или #3** | CORS/cookie сломался. Скорее всего, сменили ALLOWED_ORIGINS или CERT. Проверить `apps/api/main.py` и `apps/api/session_store.py` |
| **fail на #5 или #6** | Upload сломан или SessionStore не персистит. Чинить до любых других работ |
| **fail на #7 = 200 OK** | Auth-цепочка пропускает без ключа. Это **критический баг безопасности** — чинить немедленно |

## Что НЕ проверяет PRE-0

- Авторизованный доступ к `/v1/models/candidates` и `/v1/models/backtest` (нужен API-ключ; для standalone-UI этот вопрос будет решён в Phase 0 через principal extraction из сессии — см. `worklog.md` Task ID 8)
- `/v1/public/*` (зеркало `/v1/internal/*` с auth) — для внешних покупателей
- Производительность под нагрузкой — это нагрузочное тестирование, отдельный класс
- Восстановление после рестарта render.com — в MVP in-memory SessionStore теряет данные; будет покрыто после перехода на Redis (Phase 0.5)

## Связанные документы

- **`docs/MIGRATION_ARCHITECTURE.md`** — общая архитектура монорепо (apps/api, packages/ui, …), обоснование решений
- **`worklog.md`** — история разработки по фазам (Task ID 8: PRE-0 + зафиксированные решения)
- **`apps/api/main.py`** — FastAPI-приложение (CORS, роутинг)
- **`apps/api/session_store.py`** — `SessionStore`, `AnalysisSession`, `get_or_create_session_id` (cookie cross-domain)
- **`apps/api/upload_common.py`** — общая логика `/upload` (public + internal)
- **`apps/api/auth.py`** + **`apps/api/plans.py`** — auth-цепочка: API-ключ → Principal → Capability

## Добавление новых smoke-тестов

Шаблон для новой фазы:

```python
# scripts/smoke/phase_N_smoke.py
"""
PHASE-N smoke-тест: <что проверяет>

Запуск:
    python scripts/smoke/phase_N_smoke.py
"""
from scripts.smoke.pre_0_smoke import CheckResult, write_reports, check_health, check_session_set_cookie
# reuse setup from PRE-0 — он уже проверил базу
```

Конвенции:
- Один файл на фазу: `phase_N_smoke.py`
- Использовать `CheckResult` и `write_reports` из PRE-0 — единый формат отчётов
- В docstring — что тестирует и как запустить
- В README здесь — добавить секцию «Что проверяет `phase_N_smoke.py`» по аналогии с PRE-0
