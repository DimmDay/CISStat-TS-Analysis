// packages/ui/components/ForecastExportMenu.vars.test.ts
//
// Task DKT-3 §6.4 — резолв var() в клоне SVG перед сериализацией PNG.
//
// Контракт (§10.1, реализация по рекомендации спеки): PNG-артефакт
// «всегда светлый» — резолв из светлой карты переменных независимо от
// активной темы просмотра; canvas-заливка #FFFFFF сохраняется.
// Переменные вне карты остаются без изменений (explicit fail-visible).

import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { CHART_VARS_LIGHT, resolveSvgVarsLight } from "../lib/chartVars";

const SVG_NS = "http://www.w3.org/2000/svg";

function el(tag: string, attrs: Record<string, string>): SVGElement {
  const node = document.createElementNS(SVG_NS, tag);
  for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, v);
  return node;
}

describe("DKT-3 §6.4: resolveSvgVarsLight", () => {
  it("резолвит fill/stroke/stop-color на корне и во вложенных элементах", () => {
    const svg = el("svg", { fill: "var(--chart-brand)", stroke: "var(--chart-grid)" });
    const stop = el("stop", { "stop-color": "var(--status-error)" });
    svg.appendChild(stop);
    const resolved = resolveSvgVarsLight(svg);
    expect(resolved.getAttribute("fill")).toBe("#2E3192"); // бренд, светлая карта
    expect(resolved.getAttribute("stroke")).toBe("#F0F0F0");
    expect(resolved.querySelector("stop")!.getAttribute("stop-color")).toBe("#DC2626");
  });

  it("резолвит var() внутри inline-style, исходный SVG не мутируется", () => {
    const svg = el("svg", { style: "fill: var(--chart-blue); stroke-width: 2" });
    resolveSvgVarsLight(svg);
    expect(svg.getAttribute("style")).toBe("fill: var(--chart-blue); stroke-width: 2");
    const resolved = resolveSvgVarsLight(svg);
    expect(resolved.getAttribute("style")).toBe("fill: #2563EB; stroke-width: 2");
  });

  it("переменные вне световой карты остаются как есть (fail-visible)", () => {
    const svg = el("svg", { fill: "var(--unknown-var)" });
    const resolved = resolveSvgVarsLight(svg);
    expect(resolved.getAttribute("fill")).toBe("var(--unknown-var)");
  });

  it("артефакт «всегда светлый»: класс .dark на <html> не влияет на резолв", () => {
    document.documentElement.classList.add("dark");
    const svg = el("svg", { fill: "var(--chart-brand)" });
    const resolved = resolveSvgVarsLight(svg);
    expect(resolved.getAttribute("fill")).toBe("#2E3192"); // не тёмная #8F94F5
    document.documentElement.classList.remove("dark");
  });
});

describe("DKT-3: световая карта — зеркало globals.css (:root)", () => {
  const GLOBALS = readFileSync(resolve(__dirname, "..", "globals.css"), "utf8");
  const block = GLOBALS.match(/:root\s*\{([\s\S]*?)\n\}/)![1];
  const declared: Record<string, string> = {};
  for (const m of block.matchAll(/--((?:chart|status|wave)-[a-z0-9-]+)\s*:\s*(#[0-9A-Fa-f]{6})/g)) {
    declared[m[1]] = m[2];
  }

  it("карта покрывает все --chart-*/--status-*/--wave-* из :root без расхождений", () => {
    const problems: string[] = [];
    for (const [name, hex] of Object.entries(declared)) {
      if (CHART_VARS_LIGHT[name] !== hex) {
        problems.push(`${name}: карта ${CHART_VARS_LIGHT[name] ?? "нет"}, globals ${hex}`);
      }
    }
    expect(problems).toEqual([]);
    expect(Object.keys(declared).length).toBe(Object.keys(CHART_VARS_LIGHT).length);
  });
});
