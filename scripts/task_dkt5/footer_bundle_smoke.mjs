#!/usr/bin/env node
// Task DKT-5 — футер-специфичные проверки СКОМПИЛИРОВАННОГО CSS standalone
// (прецедент css_bundle_smoke.mjs: «программная сверка, не на глаз»).
import { readFileSync, existsSync, readdirSync, statSync } from "node:fs";
import { resolve, join } from "node:path";

const NEXT = resolve("/home/z/my-project/CISStat-TS-Analysis", "apps/standalone/.next");
if (!existsSync(NEXT)) {
  console.error("Бандл не найден — сначала npm run build:all");
  process.exit(2);
}

function walkCss(dir, acc = []) {
  for (const name of readdirSync(dir)) {
    const p = join(dir, name);
    const st = statSync(p);
    if (st.isDirectory()) walkCss(p, acc);
    else if (name.endsWith(".css")) acc.push(p);
  }
  return acc;
}

const css = walkCss(NEXT)
  .filter((p) => !p.includes("cache"))
  .map((f) => readFileSync(f, "utf8"))
  .join("\n");

const checks = [
  [css.includes("--c-footer-bg:"), "токен --c-footer-bg объявлен в бандле"],
  [css.includes("202 215 247"), "светлое значение 202 215 247 (#CAD7F7) в бандле"],
  [css.includes("23 29 44"), "тёмное значение 23 29 44 (#171D2C) в бандле"],
  [/\.dark \.home-footer \.text-black/.test(css), "scoped-ревизия .dark .home-footer .text-black в бандле"],
  [/\.dark \.home-footer \.text-black\\\/50/.test(css), "ревизия text-black/50 в бандле"],
  [/\.dark \.home-footer \.text-black\\\/40/.test(css), "ревизия text-black/40 в бандле"],
  [/\.dark \.home-footer \.border-black\\\/20/.test(css), "ревизия border-black/20 в бандле"],
  [/\.dark \.home-footer \.decoration-black\\\/30/.test(css), "ревизия decoration-black/30 в бандле"],
  [/\.dark \.home-footer \.bg-white\\\/40/.test(css), "ревизия bg-white/40 (форма поиска) в бандле"],
  [/rgb\(var\(--c-neutral-900\)\)/.test(css), "ревизия ссылается на токен neutral-900"],
];

let failures = 0;
for (const [ok, label] of checks) {
  console.log(`${ok ? "PASS" : "FAIL"}  ${label}`);
  if (!ok) failures++;
}
process.exit(failures ? 1 : 0);
