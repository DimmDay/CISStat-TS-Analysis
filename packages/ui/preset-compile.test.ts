// packages/ui/preset-compile.test.ts
//
// Task DKT-1 — тест компиляции CSS-бандла (spec_dark_theme.md §8.2).
//
// Ловит деградацию формата var-троек: слэш-прозрачность (~150 инстансов
// bg-brand-light/50, border-brand/30, bg-brand/10...) обязана компилироваться
// в rgb(var(--c-*) / .NN), а dark:-вариант — в селектор с классом .dark
// (механизм точечных оверрайдов §6.2, например dark:text-brand-bright).

import postcss from "postcss";
import tailwindcss from "tailwindcss";
import preset from "./tailwind-preset";

const RAW_CONTENT = [
  "bg-brand-light/50 border-brand/30 bg-brand/10 bg-brand/5",
  "bg-white text-neutral-500 border-neutral-200 text-brand",
  "dark:text-brand-bright dark:text-neutral-800 dark:ring-1",
  "text-white bg-brand text-green-700 bg-green-50",
].join(" ");

async function compile(): Promise<string> {
  const tailwind = (tailwindcss as unknown as (cfg: object) => postcss.Plugin)({
    presets: [preset as never],
    content: [{ raw: RAW_CONTENT, extension: "html" as const }],
    corePlugins: { preflight: false },
  });
  const result = await postcss([tailwind]).process("@tailwind utilities;", {
    from: undefined,
  });
  return result.css;
}

describe("Компиляция CSS-бандла: слэш-прозрачность (§8.2, R-1)", () => {
  it("bg-brand-light/50 компилируется в rgb(var(--c-brand-light) / .5)", async () => {
    const css = await compile();
    expect(css).toMatch(
      /rgb\(var\(--c-brand-light\)\s*\/\s*0?\.5\)/
    );
  });

  it("border-brand/30 компилируется с var и альфой", async () => {
    const css = await compile();
    expect(css).toMatch(/rgb\(var\(--c-brand\)\s*\/\s*0?\.3\)/);
  });

  it("bg-brand/5 и bg-brand/10 компилируются (одноразрядные альфы)", async () => {
    const css = await compile();
    expect(css).toMatch(/rgb\(var\(--c-brand\)\s*\/\s*0?\.05\)/);
    expect(css).toMatch(/rgb\(var\(--c-brand\)\s*\/\s*0?\.1\)/);
  });
});

describe("Компиляция CSS-бандла: dark:-вариант (darkMode: class)", () => {
  it("dark:text-brand-bright компилируется в селектор под .dark", async () => {
    const css = await compile();
    // Tailwind 3.4 компилирует dark:-вариант в современный селектор :is(.dark *)
    expect(css).toContain(".dark\\:text-brand-bright:is(.dark *)");
  });

  it("базовые классы палитры компилируются в var-значения", async () => {
    const css = await compile();
    expect(css).toMatch(/\.bg-white\s*\{[^}]*rgb\(var\(--c-white\)/s);
    expect(css).toMatch(/\.text-brand\s*\{[^}]*rgb\(var\(--c-brand\)/s);
    expect(css).toMatch(/\.text-green-700\s*\{[^}]*rgb\(var\(--c-green-700\)/s);
  });
});
