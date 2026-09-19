// packages/ui/lib/home-stops.test.ts
//
// Task EDU-1 — контракт исследовательской карты главной страницы в части
// маршрута «Обучение и база знаний» (второй бейдж первого ряда):
//   - ведёт на собственную страницу /education (база знаний: Библиотека
//     чтения + Словарь терминов, spec_education.md Часть I);
//   - НЕ дублирует /docs — этот маршрут остаётся за «Документацией API».

import { HOME_ROUTES } from "./home-stops";

describe("HOME_ROUTES — маршрут «Обучение и база знаний» (EDU-1)", () => {
  it("второй маршрут карты — «Обучение и база знаний»", () => {
    expect(HOME_ROUTES[1].title).toBe("Обучение и база знаний");
  });

  it("ведёт на собственную страницу /education, не на /docs", () => {
    expect(HOME_ROUTES[1].href).toBe("/education");
  });

  it("маршруты карты не дублируются (каждый href уникален)", () => {
    const hrefs = HOME_ROUTES.map((r) => r.href);
    expect(new Set(hrefs).size).toBe(hrefs.length);
  });
});
