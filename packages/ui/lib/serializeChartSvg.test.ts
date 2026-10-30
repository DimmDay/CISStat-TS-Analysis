// packages/ui/lib/serializeChartSvg.test.ts
//
// PGV-10: оракулы сериализации frozen геометрии (критерий §13 «не
// первый SVG»): только СВОЙ контейнер; xmlns обязателен; null -- честный
// отказ без фабрикации.

import { serializeChartSvg, serializeChartSvgSafe } from "./serializeChartSvg";

describe("serializeChartSvg (PGV-10)", () => {
  it("сериализует svg КОНКРЕТНОГО контейнера с xmlns", () => {
    const container = document.createElement("div");
    container.innerHTML =
      '<div class="alien"><svg id="alien-svg"></svg></div><svg id="own-svg"></svg>';
    const own = container.lastElementChild as SVGSVGElement;
    const scoped = document.createElement("div");
    scoped.appendChild(own);
    const xml = serializeChartSvg(scoped);
    expect(xml).not.toBeNull();
    expect(xml).toContain('id="own-svg"');
    expect(xml).not.toContain("alien-svg");
    expect(xml).toContain('xmlns="http://www.w3.org/2000/svg"');
  });

  it("нет svg в узле -- честный null (screen_svg_required на бэкенде)", () => {
    const container = document.createElement("div");
    container.innerHTML = "<p>таблица без графика</p>";
    expect(serializeChartSvg(container)).toBeNull();
    expect(serializeChartSvg(null)).toBeNull();
    expect(serializeChartSvg(undefined)).toBeNull();
  });

  it("serializeChartSvgSafe глотает исключения DOM -- честный null", () => {
    expect(
      serializeChartSvgSafe(() => {
        throw new Error("detached node");
      }),
    ).toBeNull();
    expect(serializeChartSvgSafe(() => null)).toBeNull();
  });
});
