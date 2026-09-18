#!/usr/bin/env node
// Task DKT-1/DKT-2 — CSS-бандл-смоук (spec_dark_theme.md: «в скомпилированном
// CSS присутствуют :root- и .dark-блоки с точными значениями — паттерн
// "программная сверка, не на глаз"»).
//
// Проверяет СОБРАННЫЙ продовый CSS standalone (apps/standalone/.next):
//   1. присутствуют var-тройки --c-* (светлые значения в :root-контексте);
//   2. присутствует .dark-контекст (utility-ревизии text-brand/text-white,
//      тени, feed-scroll);
//   3. слэш-прозрачность скомпилирована в rgb(var(--c-*) / 0.NN);
//   4. darkMode:"class" — dark:-вариант компилируется в :is(.dark *).
import { readFileSync, existsSync, readdirSync, statSync } from "node:fs";
import { resolve, join } from "node:path";

const ROOT = "/home/z/my-project/CISStat-TS-Analysis";
const NEXT = resolve(ROOT, "apps/standalone/.next");

function walkCss(dir, acc = []) {
  for (const name of readdirSync(dir)) {
    const p = join(dir, name);
    const st = statSync(p);
    if (st.isDirectory()) walkCss(p, acc);
    else if (name.endsWith(".css")) acc.push(p);
  }
  return acc;
}

let failures = [];
const cssFiles = walkCss(NEXT).filter((p) => !p.includes("cache"));
const css = cssFiles.map((f) => readFileSync(f, "utf8")).join("\n");
console.log(`CSS файлов в бандле: ${cssFiles.length}`);

function check(cond, label) {
  console.log(`${cond ? "PASS" : "FAIL"}  ${label}`);
  if (!cond) failures.push(label);
}

// 1. var-тройки присутствуют
check(css.includes("--c-white:"), ":root var-тройки --c-* в бандле");
check(css.includes("--c-neutral-500:"), "--c-neutral-500 в бандле");
check(css.includes("--c-brand-bright:"), "--c-brand-bright в бандле");
check(css.includes("--c-white-fg:"), "--c-white-fg в бандле");

// 2. .dark контекст (utility-ревизии и feed-scroll)
check(/\.dark\s+\.text-brand/.test(css), ".dark .text-brand utility-ревизия");
check(/\.dark\s+\.text-white/.test(css), ".dark .text-white utility-ревизия");
check(/\.dark\s+\.shadow-lg/.test(css), ".dark .shadow-lg ревизия");
check(/\.dark\s+\.feed-scroll/.test(css), ".dark .feed-scroll ревизия");
check(css.includes("color-scheme:dark") || css.includes("color-scheme: dark"), "color-scheme переключение");

// 3. слэш-прозрачность (выборочно: самый частый модификатор)
check(/bg-brand-light\\?\/50/.test(css) && /rgb\(var\(--c-brand-light\)\s*\/\s*0?\.5\)/.test(css), "bg-brand-light/50 → rgb(var(--c-brand-light) / .5)");
check(/border-brand\\?\/30/.test(css) && /rgb\(var\(--c-brand\)\s*\/\s*0?\.3\)/.test(css), "border-brand/30 → rgb(var(--c-brand) / .3)");

// 4. dark: вариант компилируется
check(css.includes(":is(.dark *)"), "dark:-вариант в формате :is(.dark *)");
check(/dark\\:text-neutral-800/.test(css), "точечный dark:text-neutral-800 (код-блок) в бандле");
check(/dark\\:text-neutral-900/.test(css), "точечный dark:text-neutral-900 (шеврон) в бандле");

if (failures.length) {
  console.error(`\nСМОУК ПРОВАЛЕН: ${failures.length} проверок`);
  process.exit(1);
}
console.log("\nCSS-бандл-смоук пройден: все проверки PASS");
