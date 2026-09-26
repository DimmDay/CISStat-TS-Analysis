/** @type {import('ts-jest').JestConfigWithTsJest} */

// Детерминизм таймзоны тестов (Task FIX: PROGR-5.1, 2026-09-26).
//
// Компоненты рендерят время событий трассы через toLocaleTimeString("ru-RU")
// в ЛОКАЛЬНОЙ таймзоне среды (осознанная конвенция UI: пользователь видит
// своё локальное время -- ProgressTraceLog.formatTime, ProgressCheckpointBar.
// formatCheckpointTime; продуктовое поведение корректно и НЕ меняется).
// Но тесты, ассертящие литерал отрендеренного времени (ProgressCheckpointBar:
// «09:02:00» для ts "2026-09-25T09:02:00+00:00"), проходили только на
// TZ=UTC-машинах: при TZ=Europe/Moscow компонент рендерил «12:02:00» и тест
// падал (TestingLibraryElementError: Unable to find an element with the text:
// 09:02:00). CI гоняет только pytest, поэтому в UTC-контейнерах падение
// не проявлялось.
//
// Почему пин ЗДЕСЬ, в конфиге: этот файл исполняется в ГЛАВНОМ процессе
// до форка воркеров, и воркеры наследуют реальный TZ=UTC. Запись из
// setup-файлов/тестов не работает: jest-runtime даёт им КОПИЮ process.env
// (createProcessObject), реальное окружение воркера и кэш таймзоны V8/ICU
// она не меняет. Пин устраняет КЛАСС падений «тест зависит от таймзоны
// хоста»: весь сьют детерминирован независимо от машины запуска.
process.env.TZ = "UTC";

module.exports = {
  testEnvironment: "jsdom",
  transform: {
    "^.+\\.tsx?$": [
      "ts-jest",
      {
        // Внешний tsconfig (вместо инлайн-объекта): добавлены types: node
        // (имя `global` в TsAnalysisModeling/TsAnalysisEDA тестах), paths
        // для алиаса "@/..." (tsconfig standalone-приложения) и глобальная
        // декларация "*.css" (jest.modules.d.ts) — иначе импорт layout.tsx
        // в layout.test.tsx падает на типизации (TS2304/TS2307/TS2882).
        tsconfig: "<rootDir>/jest.tsconfig.json",
      },
    ],
  },
  moduleNameMapper: {
    "^@cisstat/ui$": "<rootDir>/packages/ui/index.ts",
    "^@cisstat/ui/(.*)$": "<rootDir>/packages/ui/$1",
    // Task 121 (fix): алиас tsconfig standalone-приложения — layout.test.tsx
    // импортирует layout.tsx, который тянет "@/components/ProductHeader".
    "^@/(.*)$": "<rootDir>/apps/standalone/$1",
    // Task 121 (fix): side-effect импорт "./globals.css" в layout.tsx
    // подменяется пустым стабом (ts-jest/jsdom CSS не исполняют).
    "\\.css$": "<rootDir>/jest.stub.css",
  },
  testMatch: ["**/*.test.{ts,tsx}"],
  moduleFileExtensions: ["ts", "tsx", "js", "jsx", "json"],
  // Polyfills для jsdom: ResizeObserver (Preprocessing/EDA), IntersectionObserver
  // (recharts ResponsiveContainer), matchMedia. Подробности — в jest.setup.js.
  setupFilesAfterEnv: ["<rootDir>/jest.setup.js"],
};
