/** @type {import('ts-jest').JestConfigWithTsJest} */
module.exports = {
  testEnvironment: "jsdom",
  transform: {
    "^.+\\.tsx?$": [
      "ts-jest",
      {
        tsconfig: {
          jsx: "react-jsx",
          module: "esnext",
          moduleResolution: "bundler",
          esModuleInterop: true,
          strict: false,
          noImplicitAny: false,
          target: "es2020",
          lib: ["es2020", "dom", "dom.iterable"],
          types: ["jest", "@testing-library/jest-dom"],
        },
      },
    ],
  },
  moduleNameMapper: {
    "^@cisstat/ui$": "<rootDir>/packages/ui/index.ts",
    "^@cisstat/ui/(.*)$": "<rootDir>/packages/ui/$1",
  },
  testMatch: ["**/*.test.{ts,tsx}"],
  moduleFileExtensions: ["ts", "tsx", "js", "jsx", "json"],
  // Polyfills для jsdom: ResizeObserver (Preprocessing/EDA), IntersectionObserver
  // (recharts ResponsiveContainer), matchMedia. Подробности — в jest.setup.js.
  setupFilesAfterEnv: ["<rootDir>/jest.setup.js"],
};
