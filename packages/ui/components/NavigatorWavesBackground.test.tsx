// packages/ui/components/NavigatorWavesBackground.test.tsx
//
// Контракт точного переноса авторского файла
// CISStat_TS_Analysis_wave_background_3200x1600.svg (1600×3200) в JSX:
// 1 rect-подложка с диагональным градиентом + 6 содержательных path
// (4 «ленты»/заливки + нижняя ширма) + 3 тонких белых штриха-акцента
// = 1 rect + 9 path, 6 linearGradient. Геометрия d="...", палитра,
// opacity и stroke-width — дословно из источника (сверка с источником —
// scripts/task_navbg_verify_transfer.py, тест прижимает дрейф).
//
// Отличия от исходного файла — ТОЛЬКО презентационные, по паттерну
// HomeWavesBackground: id градиентов префиксованы cisstat-nav-
// (SVG id глобальны для DOM, голые "bg"/"waveA" столкнутся с другими
// инлайн-SVG), preserveAspectRatio="none" (фон растягивается на
// фактическую коробку страницы, абсолют inset-0).

import { render } from "@testing-library/react";
import "@testing-library/jest-dom";
import { NavigatorWavesBackground } from "./NavigatorWavesBackground";

// Точные d-строки источника (в порядке документа) — гард дословности.
const SOURCE_PATHS_D = [
  "M0 1050 C210 930 390 920 590 1030 C790 1140 900 1260 1060 1160 C1250 1040 1400 820 1600 760 L1600 1450 C1390 1500 1210 1430 1040 1320 C870 1210 750 1110 580 1060 C380 1000 190 1050 0 1150 Z",
  "M0 1050 C210 930 390 920 590 1030 C790 1140 900 1260 1060 1160 C1250 1040 1400 820 1600 760",
  "M0 1420 C230 1300 420 1270 620 1330 C850 1400 1010 1530 1190 1510 C1350 1492 1470 1410 1600 1370 L1600 1770 C1410 1810 1240 1850 1060 1780 C850 1700 720 1510 540 1460 C350 1410 170 1450 0 1540 Z",
  "M0 1750 C230 1660 430 1580 620 1470 C830 1345 990 1180 1160 1030 C1320 890 1450 810 1600 760 L1600 1160 C1450 1210 1310 1300 1160 1430 C970 1590 810 1770 600 1880 C390 1990 190 2020 0 2090 Z",
  "M0 2090 C190 2020 390 1990 600 1880 C810 1770 970 1590 1160 1430 C1310 1300 1450 1210 1600 1160",
  "M0 2210 C220 2100 420 2110 620 2210 C800 2300 930 2460 1100 2440 C1280 2418 1430 2240 1600 2160 L1600 2600 C1430 2690 1260 2750 1080 2700 C870 2640 760 2470 570 2390 C370 2310 180 2340 0 2430 Z",
  "M0 2210 C220 2100 420 2110 620 2210 C800 2300 930 2460 1100 2440 C1280 2418 1430 2240 1600 2160",
  "M0 2460 C210 2380 420 2390 600 2460 C790 2535 910 2680 1090 2700 C1280 2720 1450 2630 1600 2530 L1600 2890 C1430 2980 1260 3010 1070 2940 C870 2870 720 2730 530 2670 C340 2610 160 2650 0 2730 Z",
  "M0 2770 C250 2670 450 2680 650 2760 C850 2840 980 2990 1160 3020 C1320 3045 1470 2970 1600 2890 L1600 3200 L0 3200 Z",
];

describe("NavigatorWavesBackground", () => {
  it("является чисто декоративным слоем: aria-hidden и не перехватывает клики", () => {
    const { container } = render(<NavigatorWavesBackground />);
    const root = container.firstElementChild;

    expect(root).toHaveAttribute("aria-hidden", "true");
    expect(root?.className).toContain("pointer-events-none");
  });

  it("спозиционирован абсолютно позади контента (absolute inset-0 -z-10), не fixed к вьюпорту", () => {
    const { container } = render(<NavigatorWavesBackground />);
    const root = container.firstElementChild;

    expect(root?.className).toContain("absolute");
    expect(root?.className).toContain("inset-0");
    expect(root?.className).toContain("-z-10");
    expect(root?.className).not.toMatch(/\bfixed\b/);
  });

  it("скруглённые углы фоновой коробки по паттерну главной страницы (rounded-2xl) с обрезкой содержимого", () => {
    const { container } = render(<NavigatorWavesBackground />);
    const root = container.firstElementChild;

    expect(root?.className).toContain("rounded-2xl");
    expect(root?.className).toContain("overflow-hidden");
  });

  it("рендерит инлайн SVG (не растровое изображение, не canvas) с полной геометрией источника: 1 rect-подложка + 9 path", () => {
    const { container } = render(<NavigatorWavesBackground />);

    expect(container.querySelector("img")).not.toBeInTheDocument();
    expect(container.querySelector("canvas")).not.toBeInTheDocument();
    const svg = container.querySelector("svg");
    expect(svg).toBeInTheDocument();
    expect(svg?.querySelectorAll("rect").length).toBe(1);
    expect(svg?.querySelectorAll("path").length).toBe(9);
  });

  it("viewBox соответствует авторскому источнику (1600×3200) и растягивается на весь контейнер", () => {
    const { container } = render(<NavigatorWavesBackground />);
    const svg = container.querySelector("svg");

    expect(svg).toHaveAttribute("viewBox", "0 0 1600 3200");
    expect(svg).toHaveAttribute("preserveAspectRatio", "none");
  });

  it("геометрия всех 9 path дословно совпадает с авторским SVG (в порядке документа)", () => {
    const { container } = render(<NavigatorWavesBackground />);
    const dList = Array.from(container.querySelectorAll("svg path")).map((el) =>
      el.getAttribute("d"),
    );

    expect(dList).toEqual(SOURCE_PATHS_D);
  });

  it("использует точную палитру подложки и всех лент из авторского SVG", () => {
    const { container } = render(<NavigatorWavesBackground />);
    const html = container.innerHTML;

    // Подложка (bg)
    expect(html).toContain("var(--wave-nav-1)");
    expect(html).toContain("var(--wave-nav-2)");
    expect(html).toContain("var(--wave-nav-3)");
    // Ленты: waveA / waveB / waveC / waveD
    expect(html).toContain("var(--wave-nav-4)");
    expect(html).toContain("var(--wave-nav-5)");
    expect(html).toContain("var(--wave-nav-6)");
    expect(html).toContain("var(--wave-nav-7)");
    expect(html).toContain("var(--wave-nav-8)");
    expect(html).toContain("var(--wave-nav-9)");
    expect(html).toContain("var(--wave-nav-10)");
    expect(html).toContain("var(--wave-nav-11)");
    expect(html).toContain("var(--wave-nav-12)");
    expect(html).toContain("var(--wave-nav-16)");
    expect(html).toContain("var(--wave-nav-14)");
    expect(html).toContain("var(--wave-nav-15)");
    // Нижняя ширма (lower)
    expect(html).toContain("var(--wave-nav-17)");
  });

  it("использует префиксованные id градиентов, чтобы не конфликтовать с другими инлайн-SVG на странице", () => {
    const { container } = render(<NavigatorWavesBackground />);
    const ids = Array.from(container.querySelectorAll("linearGradient")).map((el) =>
      el.getAttribute("id"),
    );

    expect(ids.length).toBe(6);
    for (const id of ids) {
      expect(id).toMatch(/^cisstat-nav-/);
    }
  });

  it("заполняющие path ссылаются на префиксованные градиенты (ни одной голой url(#...) ссылки)", () => {
    const { container } = render(<NavigatorWavesBackground />);
    const svg = container.querySelector("svg");
    const html = svg?.innerHTML ?? "";

    // Ни одной ссылки на голый id источника
    expect(html).not.toContain('url(#bg)');
    expect(html).not.toContain('url(#waveA)');
    expect(html).not.toContain('url(#waveB)');
    expect(html).not.toContain('url(#waveC)');
    expect(html).not.toContain('url(#waveD)');
    expect(html).not.toContain('url(#lower)');
    // Ссылки только на префиксованные: rect-подложка (bg) + 6 заливок
    // path (waveA/waveB/waveC/waveD/waveC-повтор/lower) = 7; 3 штриха —
    // fill="none" и ссылок не имеют.
    expect(html).toContain('url(#cisstat-nav-bg)');
    expect((html.match(/url\(#cisstat-nav-/g) ?? []).length).toBe(7);
  });

  it("штрихи-акценты и полупрозрачные заливки сохраняют точные opacity/stroke-width источника", () => {
    const { container } = render(<NavigatorWavesBackground />);
    const paths = Array.from(container.querySelectorAll("svg path"));
    const html = container.innerHTML;

    // Белые штрихи-акценты: stroke-opacity .80/.68/.78 (дословно из
    // источника, включая ведущий ноль ".80"), width 3
    expect(html).toContain('stroke-opacity=".80"');
    expect(html).toContain('stroke-opacity=".68"');
    expect(html).toContain('stroke-opacity=".78"');
    const stroked = paths.filter((el) => el.getAttribute("stroke"));
    expect(stroked.length).toBe(3);
    for (const el of stroked) {
      expect(el.getAttribute("stroke-width")).toBe("3");
    }
    // Полупрозрачные заливки: ribbon .58 и нижняя ширма .52
    const opacities = paths
      .map((el) => el.getAttribute("opacity"))
      .filter(Boolean);
    expect(opacities).toEqual([".58", ".52"]);
  });
});
