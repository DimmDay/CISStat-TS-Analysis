// apps/standalone/app/navigator/page.test.tsx
//
// Контракт страницы «Знакомство с платформой» /navigator (standalone):
// фон NavigatorWavesBackground (точный перенос авторского SVG
// 1600×3200) по паттерну главной страницы (apps/standalone/app/page.tsx):
//   - компенсация padding-top <main>: -mt-6 (обёртка и абсолютный фон
//     поднимаются вплотную к ModuleNav) + pt-6 на ТОЙ ЖЕ обёртке
//     (контент остаётся на прежнем месте); значения — один токен шкалы;
//   - скруглённые углы фоновой коробки rounded-2xl;
//   - футер HomeFooter — последний элемент потока контента, фон
//     #CAD7F7 (дефолт компонента = «в полном соответствии с главной»),
//     углы rounded-2xl.
// Shared-композиция PlatformIntroduction не менялась — embedded
// не затронут (прецедент фона/футера главной: standalone-only).

import { render, screen } from "@testing-library/react";
import "@testing-library/jest-dom";
import { AppShellProvider } from "@cisstat/ui";
import Page from "./page";

describe("Standalone navigator page", () => {
  it("растягивает фон вверх до меню компенсацией padding-top <main> (-mt-6 pt-6 на одной обёртке)", () => {
    const { container } = render(
      <AppShellProvider>
        <Page />
      </AppShellProvider>,
    );
    const root = container.firstElementChild;

    expect(root?.className).toContain("-mt-6");
    expect(root?.className).toContain("pt-6");
  });

  it("не меняет видимую позицию контента: -mt-6 и pt-6 -- один и тот же токен шкалы (компенсируют друг друга)", () => {
    const { container } = render(
      <AppShellProvider>
        <Page />
      </AppShellProvider>,
    );
    const root = container.firstElementChild;
    const classes = root?.className ?? "";

    const negMargin = classes.match(/-mt-(\d+)/)?.[1];
    const posPadding = classes.match(/(?<!-)pt-(\d+)/)?.[1];

    expect(negMargin).toBeDefined();
    expect(posPadding).toBeDefined();
    expect(negMargin).toBe(posPadding);
  });

  it("фон остаётся первым дочерним элементом обёртки и коробка скруглена (rounded-2xl)", () => {
    const { container } = render(
      <AppShellProvider>
        <Page />
      </AppShellProvider>,
    );
    const root = container.firstElementChild;

    // NavigatorWavesBackground рендерит aria-hidden="true" корневой div первым
    expect(root?.firstElementChild).toHaveAttribute("aria-hidden", "true");
    expect(root?.firstElementChild?.className).toContain("rounded-2xl");
  });

  it("композиция PlatformIntroduction сохранена: заголовок подробной навигации на месте", () => {
    render(
      <AppShellProvider>
        <Page />
      </AppShellProvider>,
    );

    expect(
      screen.getByRole("heading", { level: 2, name: "Подробная навигация по платформе" }),
    ).toBeInTheDocument();
  });

  it("рендерит футер последним элементом потока контента, фон #CAD7F7 (как на главной), скругление rounded-2xl", () => {
    const { container } = render(
      <AppShellProvider>
        <Page />
      </AppShellProvider>,
    );
    const root = container.firstElementChild;
    const content = root?.children[1]; // relative space-y-12 обёртка контента
    const footer = content?.lastElementChild;

    expect(footer?.tagName).toBe("FOOTER");
    expect(footer?.className).toContain("rounded-2xl");
    // jsdom нормализует hex к rgb(...); #CAD7F7 === rgb(202, 215, 247)
    expect((footer as HTMLElement)?.style.backgroundColor).toBe(
      "rgb(202, 215, 247)",
    );
    // Футер — ПОСЛЕДНИЙ ребёнок потока: за ним только фон-absolute
    expect(content?.querySelector(":scope > footer")).toBe(footer);
  });

  it("на странице нет голых id градиентов источника (коллизии с другими инлайн-SVG исключены)", () => {
    const { container } = render(
      <AppShellProvider>
        <Page />
      </AppShellProvider>,
    );

    const ids = Array.from(container.querySelectorAll("linearGradient")).map(
      (el) => el.getAttribute("id"),
    );
    expect(ids.length).toBeGreaterThan(0);
    for (const id of ids) {
      expect(id).not.toBe("bg");
      expect(id).not.toBe("waveA");
      expect(id).not.toBe("waveB");
      expect(id).not.toBe("waveC");
      expect(id).not.toBe("waveD");
      expect(id).not.toBe("lower");
      expect(id).toMatch(/^cisstat-nav-/);
    }
  });
});
