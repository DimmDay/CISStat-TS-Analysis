// Сертификационная обёртка PGV-10-CERT: репозиторный jest.config.js (jest 30)
// в этой среде SIGBUS (несовместимость jest 30 + Node 24 песочницы; зафиксировано
// в акте). Оракулы сертификатора выполняются той же цепочкой ts-jest 29 + jsdom +
// setupFiles репозитория, но под jest 29.7.0. Корпус -- мои p10cert-файлы
// packages/ui; конфигурация -- зеркало репозиторной (transform/mapper/setup).
const REPO = "/home/z/my-project/CISStat-TS-Analysis";

module.exports = {
  rootDir: REPO,
  testEnvironment: "jsdom",
  testMatch: [
    "<rootDir>/packages/ui/lib/serializeChartSvg.p10cert.test.ts",
    "<rootDir>/packages/ui/components/VisualExportButton.p10cert.test.tsx",
    "<rootDir>/packages/ui/lib/visualExportRegistry.pg10coverage.test.ts",
  ],
  transform: {
    "^.+\\.tsx?$": [
      "/tmp/jestmini/node_modules/ts-jest/dist/index.js",
      { tsconfig: "<rootDir>/jest.tsconfig.json" },
    ],
  },
  moduleNameMapper: {
    "^@cisstat/ui$": "<rootDir>/packages/ui/index.ts",
    "^@cisstat/ui/(.*)$": "<rootDir>/packages/ui/$1",
    "^@/(.*)$": "<rootDir>/apps/standalone/$1",
    "\\.css$": "<rootDir>/jest.stub.css",
  },
  moduleFileExtensions: ["ts", "tsx", "js", "jsx", "json"],
  setupFilesAfterEnv: ["<rootDir>/jest.setup.js"],
};
