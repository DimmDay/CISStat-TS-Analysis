# Deploy Vercel Checklist — CISStat TS Analysis (Frontend)

> Цель: задеплоить `apps/standalone` на Vercel и приёмочно проверить полный flow
> «CSV upload → выбор колонки → бэктест → зелёный badge "Реальные данные"».
>
> **Предусловие**: backend уже задеплоен на Render (Task 12 / Phase 0.5),
> `/v1/internal/models/backtest` и `/v1/session/target-column` доступны на
> `https://cisstat-ts-analysis.onrender.com`.

---

## 0. Что деплоим

| Компонент | Источник | Назначение |
|-----------|----------|------------|
| Frontend (Next.js) | `apps/standalone` | Веб-интерфейс для посетителей (без API-ключа) |
| Workspace build | `vercel.json` → `npm run build --workspace=@cisstat/ts-analysis-standalone` | Vercel-сборка standalone-приложения из монорепо |
| Proxy | `apps/standalone/next.config.mjs` → `rewrites()` | `/api/v1/:path*` → `${API_URL}/v1/:path*` (Task 11 fix для cookie) |

**Не деплоим на Vercel**: `apps/api` (на Render), `apps/embedded` (опционально позже).

---

## 1. Vercel: импорт проекта

1. Войти на https://vercel.com
2. **Add New → Project → Import Git Repository**
3. Выбрать репозиторий `CISStat-TS-Analysis`
4. Vercel автоматически определит:
   - Framework Preset: **Next.js**
   - Build Command: из `vercel.json` → `npm run build --workspace=@cisstat/ts-analysis-standalone`
   - Output Directory: `.next`
   - Install Command: `npm install`
5. **НЕ нажимать Deploy сразу** — сначала настроить env vars (шаг 2).

---

## 2. Vercel: Environment Variables

> **ВАЖНО**: «без новых env vars» означает «новые по сравнению с Task 11».
> Task 11 уже настроил `API_URL` для rewrite. Если проект импортируется впервые,
> нужно ОДНУ переменную.

### Обязательно (Production + Preview + Development)

| Key | Value | Type | Назначение |
|-----|-------|------|------------|
| `API_URL` | `https://cisstat-ts-analysis.onrender.com` | Server-side (НЕ `NEXT_PUBLIC_`) | URL backend для `next.config.mjs` rewrite. **НЕ попадает в клиентский bundle**. |

### Уже зашито в код (трогать НЕ нужно)

| Key | Value | Файл | Назначение |
|-----|-------|------|------------|
| `NEXT_PUBLIC_API_MODE` | `internal` | `apps/standalone/next.config.mjs` (env block) | UI ходит на `/v1/internal/*` (без auth, сессионный доступ) |

### Устаревшие (можно удалить, если были)

| Key | Причина удаления |
|-----|------------------|
| `NEXT_PUBLIC_API_URL` | Браузер больше не ходит напрямую на Render. Rewrite проксирует через тот же origin. Task 11 fix. |

---

## 3. Vercel: Deploy

1. Нажать **Deploy**
2. Ждать сборки (~2–3 минуты для первого деплоя)
3. После завершения: Vercel даст URL вида `https://ts-standalone.vercel.app`
   (или `https://cisstat-ts-analysis-<hash>.vercel.app` для preview)

### Если сборка падает

| Симптом | Причина | Решение |
|---------|---------|---------|
| `Module not found: @cisstat/ui` | Vercel не нашёл workspace | Проверить, что корневой `package.json` имеет `workspaces: ["packages/*", "apps/standalone"]` |
| `Cannot find module 'next'` | Установлен не в корне | Vercel installCommand = `npm install` в корне репо (см. `vercel.json`) |
| `transpilePackages error` | Старая версия Next.js | `apps/standalone/package.json` требует `next: ^14.2.25` |
| `Type error` в TsAnalysisModeling | Phase 1 не смержена | Проверить, что `packages/ui/components/TsAnalysisModeling.tsx` содержит `target_column` селектор |

---

## 4. Приёмочный smoke-test

### 4.1. Автоматический (8 проверок)

```bash
python /home/z/my-project/scripts/pre_1_frontend_smoke.py
```

**Ожидаемый результат**: `8/8 passed`. Если хоть одна FAIL — НЕ переходить к Phase 6-P0.

Отчёты:
- `/home/z/my-project/download/pre_1_frontend_smoke/report.json` — структурированный
- `/home/z/my-project/download/pre_1_frontend_smoke/report.md` — человекочитаемый

**Что проверяет**:

| # | URL | Что проверяет |
|---|-----|---------------|
| 1 | `GET /` | Vercel-фронтенд жив, отдаёт HTML |
| 2 | `GET /api/v1/health` | Next.js rewrite проксирует на Render backend |
| 3 | `GET /api/v1/session/current` | Set-Cookie `cisstat_session_id` через Vercel-proxy |
| 4 | `GET /api/v1/session/current` (round-trip) | Cookie доходит до backend через Vercel-proxy (Task 11 fix) |
| 5 | `POST /api/v1/internal/upload` | CSV upload через Vercel-proxy (проверка 4.5 MB body limit) |
| 6 | `GET /api/v1/session/target-column` | Phase 0.5 мост: `has_dataset=true`, `available_columns` содержит `sales`/`profit` |
| 7 | `POST /api/v1/session/target-column` | Выбираем колонку `sales` → сохраняется в сессии Redis |
| 8 | `POST /api/v1/internal/models/backtest` | **`data_source="session"`** — реальный ряд, в UI будет зелёный badge |

### 4.2. Ручной (визуальная проверка в браузере)

1. Открыть `https://ts-standalone.vercel.app/modeling`
2. Должен появиться селектор «Целевая колонка» с hint «Загрузите датасет»
3. Перейти на `/upload` → загрузить `sales_demo.csv` (из `apps/api/demo_data/`)
4. Вернуться на `/modeling` → селектор должен показать список с `sales` и `profit`
5. Выбрать `sales` → под селектором надпись «Бэктест будет на реальном ряде»
6. Нажать «Запустить бэктест» → в карточке результата **зелёный badge «Реальные данные»**
7. Сбросить селектор (выбрать «— не выбрано —») → повторить бэктест → **серый badge «Синтетический ряд»**

**Проверка через DevTools**:
- F12 → Network → XHR
- Запрос `backtest` должен идти на `/api/v1/internal/models/backtest` (НЕ на `/v1/models/backtest`)
- Response должен содержать поле `"data_source": "session"` или `"synthetic"`

---

## 5. Приёмочные критерии (Definition of Done)

| Критерий | Как проверить |
|----------|---------------|
| ✅ Frontend доступен на Vercel-домене | `GET /` → 200, HTML |
| ✅ Vercel-proxy работает | `GET /api/v1/health` → `{"status":"ok"}` |
| ✅ Cookie сохраняется между запросами | Round-trip #4 PASS |
| ✅ CSV upload через прокси работает | Upload #5 PASS |
| ✅ Phase 0.5 мост виден в UI | GET target-column #6 PASS |
| ✅ target_column сохраняется в Redis | POST target-column #7 PASS |
| ✅ Бэктест использует реальный ряд | Backtest #8: `data_source="session"` |
| ✅ Зелёный badge «Реальные данные» в UI | Ручная проверка 4.2, шаг 6 |

**Если ВСЕ критерии PASS** → можно переходить к **Phase 6-P0**.

**Если хоть одна FAIL** → остановить и разобраться:
- Cookie не round-trip'ится → проверить, что `apps/api` отдаёт `SameSite=None; Secure` (Task 11 fix) И что Vercel не режет `Set-Cookie`
- `data_source="synthetic"` → проверить, что POST target-column вернул 200 (а не 404/422)
- Upload FAIL → проверить 4.5 MB body limit на Vercel Serverless

---

## 6. Ограничения Vercel (важно знать)

1. **Serverless Function body limit: 4.5 MB** — большие CSV (>4 MB) упадут.
   - sales_demo.csv = 3 KB, не проблема.
   - Реальные пользовательские CSV могут быть больше — нужен future план B (напр., S3 direct upload).

2. **Cold start Render Free Tier** — первый запрос может ждать до 60–90 сек.
   - В `pre_1_frontend_smoke.py` `COLD_START_TIMEOUT=120.0` сек.
   - Для UX: добавить loading-spinner на frontend при первом запросе.

3. **Cookie domain** — cookie становится first-party к Vercel-домену (Task 11 fix).
   - `SameSite=None; Secure` в headers остаётся, но браузер НЕ блокирует (так как origin тот же).

4. **CORS** — НЕ нужен для проксированных запросов (same-origin).
   - `apps/api/main.py` всё ещё имеет `allow_origin_regex=r"https://.*\.vercel\.app"` на случай, если кто-то ходит напрямую.

---

## 7. Откат (Rollback)

Если что-то сломалось:

1. **Vercel**: Project → Deployments → выбрать предыдущий успешный деплой → **Promote to Production**
2. **Frontend code**: `git revert <commit>` → push → Vercel auto-redeploy
3. **Backend** (если виноват backend, а не frontend): см. `render.yaml` rollback в Task 12 worklog

---

## 8. Связанные документы

- `render.yaml` — Render Blueprint для backend (Task 12)
- `apps/standalone/next.config.mjs` — Vercel rewrite (Task 11 fix)
- `packages/ui/lib/apiClient.ts` — `getApiBase()` возвращает `/api` в проде
- `/home/z/my-project/scripts/pre_1_frontend_smoke.py` — автоматический smoke-test
- `worklog.md` Task 11 + Task 12 + Task 13 + Task 14 (этот) — история изменений
