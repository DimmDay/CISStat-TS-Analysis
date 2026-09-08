/** @type {import('ts-jest').JestConfigWithTsJest} */
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
