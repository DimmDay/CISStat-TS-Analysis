// packages/ui/components/TsAnalysisNavigator.test.tsx
//
// Тесты для TsAnalysisNavigator — основной 3-колоночный компонент
// Путеводителя на странице "Навигатор":
//   - 10 остановок степпера (6 существующих + 4 будущих с пометкой Soon)
//   - кнопка "Начать анализ" ведёт на /upload (для существующих) /
//     "Скоро" с Lock-иконкой (для будущих)
//   - правая панель показывает превью пунктов активной остановки
//   - клик по пункту меняет заголовок центрального окна "Обзор"
//   - кнопка "Запустить анализ" в правой панели — disabled
//   - "Тарифы" — декоративный STUB, выбор radio меняет активный план

import "@testing-library/jest-dom";
import { render, screen, fireEvent } from "@testing-library/react";
import { TsAnalysisNavigator } from "./TsAnalysisNavigator";
import { AppShellProvider } from "../context/AppShellContext";
import { NAVIGATOR_STOPS } from "../lib/navigator-stops";

// Мокаем next/link, чтобы получить обычный <a> (jest/jsdom не понимает
// Next-Link, и не нужно — нам важна href, а не навигация).
jest.mock("next/link", () => {
  return ({ href, children, ...rest }: { href: string; children: React.ReactNode }) => (
    <a href={href} {...rest}>{children}</a>
  );
});

// Провайдер оборачивает, чтобы useAppShell был доступен (без активного
// датасета — будут показаны примеры метрик).
function renderNavigator() {
  return render(
    <AppShellProvider>
      <TsAnalysisNavigator />
    </AppShellProvider>,
  );
}

describe("TsAnalysisNavigator", () => {
  it("renders 10 stops in the stepper", () => {
    renderNavigator();
    const stops = NAVIGATOR_STOPS;
    stops.forEach((stop) => {
      expect(screen.getByLabelText(stop.label)).toBeInTheDocument();
    });
    expect(stops).toHaveLength(10);
  });

  it("marks 4 future stops with 'Soon' badge", () => {
    renderNavigator();
    const soonBadges = screen.getAllByText("Soon");
    expect(soonBadges).toHaveLength(4);
  });

  it("shows 'Начать анализ' link to /upload for active existing stop by default", () => {
    renderNavigator();
    const link = screen.getByRole("link", { name: /Начать анализ/i });
    expect(link).toHaveAttribute("href", "/upload");
  });

  it("switches 'Начать анализ' href when active stop changes", () => {
    renderNavigator();
    // Клик по "Валидация" (вторая остановка)
    fireEvent.click(screen.getByLabelText("ВАЛИДАЦИЯ"));
    const link = screen.getByRole("link", { name: /Начать анализ/i });
    expect(link).toHaveAttribute("href", "/validation");
  });

  it("shows 'Скоро' disabled button for future stops instead of 'Начать анализ'", () => {
    renderNavigator();
    // Клик по "Сценарный анализ" (7-я остановка, soon=true)
    fireEvent.click(screen.getByLabelText("СЦЕНАРНЫЙ АНАЛИЗ"));
    expect(screen.queryByRole("link", { name: /Начать анализ/i })).toBeNull();
    expect(screen.getByText("Скоро")).toBeInTheDocument();
  });

  it("renders 'Путеводитель' and 'Тарифы' headings in the left column", () => {
    renderNavigator();
    expect(screen.getByText("Путеводитель")).toBeInTheDocument();
    expect(screen.getByText("Тарифы")).toBeInTheDocument();
  });

  it("renders all 4 tariff options as radio", () => {
    renderNavigator();
    const tariffRadios = screen
      .getAllByRole("radio")
      .filter((r) => r.getAttribute("name") === "tariff-plan");
    expect(tariffRadios).toHaveLength(4);
    ["demo", "starter", "professional", "enterprise"].forEach((plan) => {
      expect(
        tariffRadios.find((r) => (r as HTMLInputElement).value === plan),
      ).toBeDefined();
    });
  });

  it("selecting a different tariff plan updates active state", () => {
    renderNavigator();
    const radios = screen
      .getAllByRole("radio")
      .filter((r) => r.getAttribute("name") === "tariff-plan");
    const starter = radios.find((r) => (r as HTMLInputElement).value === "starter") as HTMLInputElement;
    fireEvent.click(starter);
    expect(starter.checked).toBe(true);
    // До: professional был активен по умолчанию (см. useState init).
    const professional = radios.find(
      (r) => (r as HTMLInputElement).value === "professional",
    ) as HTMLInputElement;
    expect(professional.checked).toBe(false);
  });

  it("renders 'Описание' and 'Обзор:' headings in center column", () => {
    renderNavigator();
    expect(screen.getByText("Описание")).toBeInTheDocument();
    // Заголовок "Обзор: ..." — для первой остановки (Загрузка) и её первого
    // пункта ("Автопревью и типы колонок").
    expect(screen.getByText(/Обзор:/)).toBeInTheDocument();
  });

  it("renders preview items in the right panel for active stop", () => {
    renderNavigator();
    // Первая остановка = Загрузка, 9 пунктов (включая «График» —
    // добавлен после «preview», см. lib/navigator-stops.ts).
    const uploadStop = NAVIGATOR_STOPS[0];
    uploadStop.items.forEach((item) => {
      expect(screen.getByText(item.title)).toBeInTheDocument();
    });
  });

  it("renders the new 'График' item between 'preview' and 'distribution' in Загрузка", () => {
    renderNavigator();
    const uploadStop = NAVIGATOR_STOPS[0];
    const previewIdx = uploadStop.items.findIndex((it) => it.id === "preview");
    const chartIdx = uploadStop.items.findIndex((it) => it.id === "chart");
    const distributionIdx = uploadStop.items.findIndex((it) => it.id === "distribution");
    expect(chartIdx).toBeGreaterThan(previewIdx);
    expect(chartIdx).toBeLessThan(distributionIdx);
    // Сам элемент с правильным title рендерится в правой панели
    expect(screen.getByText("График")).toBeInTheDocument();
  });

  it("clicking an item in the right panel updates center 'Обзор:' title", () => {
    renderNavigator();
    // Пункт «Подтверждение автоопределения» (id=structure_confirm) —
    // после добавления «Графика» стал третьим в items Загрузки.
    const itemTitle = "Подтверждение автоопределения";
    fireEvent.click(screen.getByText(itemTitle));
    expect(screen.getByText(`Обзор: ${itemTitle}`)).toBeInTheDocument();
  });

  it("renders disabled 'Запустить анализ' button in each preview item", () => {
    renderNavigator();
    // Текст кнопки — "Запустить анализ". Карточка-обёртка <article role="button">
    // не имеет этого текста, поэтому query по name отфильтрует её.
    const buttons = screen.getAllByRole("button", { name: /Запустить анализ/i });
    // Не менее одного — по числу пунктов активной остановки (9 для Загрузки,
    // включая «График»).
    expect(buttons.length).toBeGreaterThanOrEqual(1);
    buttons.forEach((btn) => expect(btn).toBeDisabled());
  });

  it("switching to a future stop shows 'Скоро' subtitle and updates Описание", () => {
    renderNavigator();
    fireEvent.click(screen.getByLabelText("ПРИЧИННЫЙ АНАЛИЗ"));
    expect(
      screen.getByText(/ПРИЧИННЫЙ АНАЛИЗ — модуль в разработке/i),
    ).toBeInTheDocument();
  });

  it("shows 'пример' badge in Обзор when no active dataset", () => {
    // AppShellProvider без гидрирующей сессии — activeDataset = null,
    // поэтому в "Обзор" должна быть пометка "пример".
    renderNavigator();
    expect(screen.getByText("пример")).toBeInTheDocument();
  });
});