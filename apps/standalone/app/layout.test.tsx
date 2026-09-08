// Task 121 (fix): layout.tsx на уровне модуля вызывает Inter({...}) из
// next/font/google — вне контекста сборки Next.js это тянет сетевой загрузчик
// шрифтов. Мокируем локально (hoisted jest.mock), не затрагивая другие тесты.
jest.mock("next/font/google", () => ({
  Inter: () => ({ variable: "--font-sans-mock", style: { fontFamily: "mock" } }),
}));

import { metadata } from "./layout";

// Task 121 — favicon вкладки браузера должен использовать логотип продукта
// public/logo_TS.png вместо дефолтной иконки Next.js.

describe("RootLayout metadata", () => {
  it("sets the favicon to the product logo (public/logo_TS.png)", () => {
    expect(metadata.icons).toEqual({ icon: "/logo_TS.png" });
  });

  it("keeps the existing title and description untouched", () => {
    expect(metadata.title).toBe("CISStat TS Analysis");
    expect(metadata.description).toBe(
      "Платформа анализа временных рядов — самостоятельный продукт: веб и API"
    );
  });
});
