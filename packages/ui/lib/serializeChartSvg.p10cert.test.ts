// packages/ui/lib/serializeChartSvg.p10cert.test.ts
//
// Независимая сертификация PGV-10 (сертификатор, корпус p10cert):
// «не первый SVG» -- сериализация СВОЕГО chart-узла (критерий §13).

import { serializeChartSvg, serializeChartSvgSafe } from "./serializeChartSvg";

function mount(html: string): HTMLElement {
  const host = document.createElement("div");
  host.innerHTML = html;
  document.body.appendChild(host);
  return host;
}

afterEach(() => {
  document.body.innerHTML = "";
});

describe("p10cert serializeChartSvg: не первый SVG документа", () => {
  it("U1 сериализует SVG СВОЕГО контейнера, не чужой/первый документа", () => {
    const own = mount(
      "<div><svg data-cert='own'><rect data-marker='OWN-VIEW'/></svg></div>",
    );
    const other = mount(
      "<div><svg data-cert='other'><rect data-marker='OTHER-VIEW'/></svg></div>",
    );
    const ownSvg = serializeChartSvg(own);
    const otherSvg = serializeChartSvg(other);
    expect(ownSvg).toContain("OWN-VIEW");
    expect(ownSvg).not.toContain("OTHER-VIEW");
    expect(otherSvg).toContain("OTHER-VIEW");
    expect(otherSvg).not.toContain("OWN-VIEW");
  });

  it("U2 контейнер без SVG и null-контейнер -- честный null", () => {
    const empty = mount("<div><p>таблица без графика</p></div>");
    expect(serializeChartSvg(empty)).toBeNull();
    expect(serializeChartSvg(null)).toBeNull();
    expect(serializeChartSvg(undefined)).toBeNull();
  });

  it("U3 xmlns добавляется при отсутствии (standalone-рендер PGV-08)", () => {
    const host = mount("<div><svg width='10'><circle r='2'/></svg></div>");
    const svg = serializeChartSvg(host);
    expect(svg).toContain("xmlns");
  });

  it("U4 serializeChartSvgSafe глушит исключения DOM в null", () => {
    const result = serializeChartSvgSafe(() => {
      throw new Error("DOM сломан");
    });
    expect(result).toBeNull();
  });

  it("U5 первый SVG документа не попадает в сериализацию чужого узла", () => {
    // Первый <svg> в document -- ЧУЖОЙ (левее по DOM); сериализация
    // собственного контейнера обязана его игнорировать.
    mount("<svg data-cert='document-first'><rect data-marker='FIRST-IN-DOC'/></svg>");
    const own = mount("<div><svg><rect data-marker='OWN-LATER'/></svg></div>");
    const svg = serializeChartSvg(own);
    expect(svg).toContain("OWN-LATER");
    expect(svg).not.toContain("FIRST-IN-DOC");
  });
});
