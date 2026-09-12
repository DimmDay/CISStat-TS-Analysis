// apps/standalone/app/page.test.tsx
import { render } from "@testing-library/react";
import "@testing-library/jest-dom";
import Page from "./page";

// Контракт: фон главной страницы (HomeWavesBackground, absolute inset-0
// корневой обёртки) должен доходить до верхнего меню, а не начинаться
// ниже него с зазором в py-6 из <main> (layout.tsx). Компенсация --
// -mt-6 (сдвигает обёртку и абсолютный фон вверх на величину padding-top
// <main>) + pt-6 на ТОЙ ЖЕ обёртке (возвращает видимую позицию
// HomeHero/HomeCapabilities на прежнее место). Значения должны совпадать
// по модулю -- иначе либо остаётся зазор до меню, либо контент
// визуально сдвигается.

describe("Standalone home page", () => {
  it("растягивает фон вверх до меню компенсацией padding-top <main> (-mt-6 pt-6 на одной обёртке)", () => {
    const { container } = render(<Page />);
    const root = container.firstElementChild;

    expect(root?.className).toContain("-mt-6");
    expect(root?.className).toContain("pt-6");
  });

  it("не меняет видимую позицию контента: -mt-6 и pt-6 -- один и тот же токен шкалы (компенсируют друг друга)", () => {
    const { container } = render(<Page />);
    const root = container.firstElementChild;
    const classes = root?.className ?? "";

    const negMargin = classes.match(/-mt-(\d+)/)?.[1];
    const posPadding = classes.match(/(?<!-)pt-(\d+)/)?.[1];

    expect(negMargin).toBeDefined();
    expect(posPadding).toBeDefined();
    expect(negMargin).toBe(posPadding);
  });

  it("фон остаётся первым дочерним элементом обёртки (позади контента, до margin-компенсации)", () => {
    const { container } = render(<Page />);
    const root = container.firstElementChild;

    // HomeWavesBackground рендерит aria-hidden="true" корневой div первым
    expect(root?.firstElementChild).toHaveAttribute("aria-hidden", "true");
  });

  // Task w/n (2026-09-12): футер главной страницы.
  //  - рендерится последним в потоке контента (после HomeCapabilities);
  //  - фон главной страницы #CAD7F7 (дефолт компонента);
  //  - углы — rounded-2xl, по паттерну фоновой коробки страницы.
  it("рендерит футер последним элементом потока контента, фон #CAD7F7, скругление rounded-2xl", () => {
    const { container } = render(<Page />);
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
});
