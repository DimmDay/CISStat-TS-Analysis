// Глобальные декларации для ts-jest (jest.tsconfig.json): side-effect
// импорты стилей в Next.js-компонентах (например, "./globals.css" в
// apps/standalone/app/layout.tsx) не имеют TS-типов — объявляем их модулями.
declare module "*.css";
