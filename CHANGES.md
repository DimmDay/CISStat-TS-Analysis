# Патч: Sessions-aware Home + слияние Upload + Путеводитель

Применить: `git apply 0001-home-page-and-upload-merge.patch` из корня
репозитория `CISStat-TS-Analysis` (ветка `main`), либо `git am` для
сохранения как коммита с сообщением.

Патч реально проверен: `git apply --check` на чистом клоне — проходит
без конфликтов.

## Backend (apps/api)
- `session_store.py`, `upload_common.py`, `routers/session.py` (новые) —
  серверная `AnalysisSession` (in-memory cookie-сессия): активный
  датасет + прогресс по 6 этапам переживают F5.
- `routers/public.py` / `routers/internal.py` — `/upload` больше не
  дублирует логику, использует общий `upload_common.handle_upload`.
- `schemas.py` — аддитивные поля (`columns_info`, `quality`,
  `size_label` в `UploadResponse`; `SessionStateResponse`).
- `demo_data/sales_demo.csv` — демо-датасет для «Попробовать на демо».
- `.gitignore` — точечное исключение для `apps/api/demo_data/*.csv`
  (глобальный `*.csv` его иначе игнорировал).

Проверено эмпирически через `TestClient` (реальные HTTP-вызовы), не
только синтаксисом — детали в чате.

## Frontend (packages/ui, apps/embedded, apps/standalone)
- `AppShellContext.tsx` — гидрация `activeDataset`/`stages` с
  `GET /v1/session/current` при монтировании.
- `apiClient.ts`, `stages.ts` — единая точка выбора `/v1/public` vs
  `/v1/internal` (заменяет битую логику по `window.location.pathname`
  в старом `DataUploadForm.tsx`, которая не могла достучаться до API).
- `WorkbenchSummary.tsx`, `EmbeddedHome.tsx`,
  `apps/standalone/components/StandaloneHome.tsx` +
  `apps/standalone/lib/useAuth.ts` (заглушка авторизации) —
  sessions-aware Home для обоих приложений.
- `TsAnalysisUpload.tsx` — слияние с `DataUploadForm.tsx` (удалён):
  реальный аплоад, реальные `columns_info`/`quality`, лимит 50MB,
  toast-уведомления, `data-testid` для тестов.
- `apps/standalone/components/ProductJourneyGuide.tsx` (новый) —
  «Путеводитель» по образцу главной портала
  (`CISStat_PORTAL/components/JourneyGuide.tsx`): 6 остановок = 6 этапов
  пайплайна, карточки-фичи из реального кода модулей.
- `StandaloneHome.tsx` — hero-блок + путеводитель вместо плоских
  карточек ценностного предложения.

Проверено: `npm run typecheck:all` — 0 ошибок (весь монорепо).
`npm run build:all` не проходит только из-за офлайн-загрузки Google
Fonts в песочнице (`next/font/google`, не связано с этим патчем).
Dev-сервер (`npm run dev`) поднимается и отдаёт 200 без ошибок сборки.

## Известные пробелы (честно, не скрыты)
- Playwright/браузерная E2E-проверка визуала путеводителя недоступна в
  песочнице (сеть блокирует загрузку Chromium) — рекомендую визуально
  проверить `/​` в standalone локально перед мержем.
- `TsAnalysisUpload.test.tsx` не может быть запущен — в репозитории нет
  `jest`/`@testing-library` ни в одном `package.json` (было так и до
  этого патча).
- Реальный бэкенд-детектор структуры (дата/группировка/частота) не
  реализован — на фронте используется клиентская эвристика с TODO.
- Цены в тарифах на Home — намеренно не выдуманы («цена уточняется»).
