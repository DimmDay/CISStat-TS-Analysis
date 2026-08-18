// packages/ui/components/TsAnalysisNavigator.test.tsx
//
// Тесты для TsAnalysisNavigator — основной 3-колоночный компонент
// Путеводителя на странице "Навигатор":
//   - 10 остановок степпера (6 существующих + 4 будущих с пометкой Soon)
//   - кнопка "Начать анализ" ведёт на /upload (для существующих) /
//     "Скоро" с Lock-иконкой (для будущих)
//   - панель "Этапы модуля" показывает превью пунктов активной остановки
//   - клик по пункту меняет заголовок окна "Обзор"
//   - кнопка "Запустить анализ" в панели этапов — disabled
//   - "Тарифы" — декоративный STUB, выбор radio меняет активный план
//
// ── Task 23: перекомпоновка колонок ─────────────────────────────────
// Новая последовательность слева направо:
//   1. Степпер + Тарифы (w-60)   ← левая колонка (без изменений)
//   2. Этапы модуля (w-80)      ← бывшая правая, теперь средняя
//   3. Описание + Обзор (flex-1) ← бывший центр, теперь правая
//
// Тесты с within() проверяют, что элементы находятся в правильной колонке
// (а не просто присутствуют в DOM — это не гарантирует порядок).

import "@testing-library/jest-dom";
import { render, screen, fireEvent, within } from "@testing-library/react";
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

  it("renders 'Маршрут исследования' and 'Тарифы' headings in the left column", () => {
    // NOTE: заголовок левой колонки ранее назывался «Путеводитель», но
    // в коммите c29a503 тимлид переименовал его в «Маршрут исследования».
    // Тест был сломан до Task 23; зафиксирован здесь как попутный фикс.
    renderNavigator();
    expect(screen.getByText("Маршрут исследования")).toBeInTheDocument();
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
    // Сам элемент с правильным title рендерится в средней колонке (Task 23)
    expect(screen.getByText("График")).toBeInTheDocument();
  });

  it("clicking an item in the middle column updates right 'Обзор:' title", () => {
    renderNavigator();
    // Пункт «Подтверждение автоопределения» (id=structure_confirm) —
    // после добавления «Графика» стал третьим в items Загрузки.
    // После Task 23: панель «Этапы модуля» — средняя колонка (между
    // степпером и окном «Описание + Обзор»).
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

  // ── Task 22: блок-схема «Пайплайн автопревью» ──────────────────────
  //
  // По умолчанию активная остановка — «Загрузка», активный пункт — первый
  // (id="preview", title="Автопревью и типы колонок"). Именно для этой
  // пары в окне «Обзор» должен рендериться UploadAutoPreviewPipeline
  // вместо текстовой заглушки.

  it("renders UploadAutoPreviewPipeline when Загрузка + preview item are active", () => {
    renderNavigator();
    const pipeline = screen.getByRole("img", { name: /пайплайн автопревью/i });
    expect(pipeline).toBeInTheDocument();
  });

  it("replaces pipeline with placeholder when switching to another item in Загрузка", () => {
    renderNavigator();
    // Переключаемся на пункт «График» (id="chart") — должен вернуться
    // стандартный текст-заглушки.
    fireEvent.click(screen.getByText("График"));
    expect(
      screen.queryByRole("img", { name: /пайплайн автопревью/i }),
    ).toBeNull();
  });

  it("does not render pipeline when switching to another stop (Валидация)", () => {
    renderNavigator();
    fireEvent.click(screen.getByLabelText("ВАЛИДАЦИЯ"));
    expect(
      screen.queryByRole("img", { name: /пайплайн автопревью/i }),
    ).toBeNull();
  });

  it("renders pipeline again after navigating away and back to Загрузка+preview", () => {
    renderNavigator();
    // Уходим на Валидацию
    fireEvent.click(screen.getByLabelText("ВАЛИДАЦИЯ"));
    expect(
      screen.queryByRole("img", { name: /пайплайн автопревью/i }),
    ).toBeNull();
    // Возвращаемся на Загрузку (handleStopClick сбрасывает item на первый)
    fireEvent.click(screen.getByLabelText("ЗАГРУЗКА"));
    const pipeline = screen.getByRole("img", { name: /пайплайн автопревью/i });
    expect(pipeline).toBeInTheDocument();
  });

  // ── Task 23: перекомпоновка колонок ────────────────────────────────
  //
  // Новая последовательность слева направо:
  //   1. Степпер + Тарифы (левая колонка, без изменений)
  //   2. Этапы модуля (бывшая правая → теперь средняя)
  //   3. Описание + Обзор (бывший центр → теперь правая)
  //
  // Проверяем через within() — это единственный надёжный способ
  // верифицировать порядок в DOM. Тесты getByText проходят и при старом
  // порядке (текст всё равно где-то в DOM), а within() ловит перестановку.

  it("renders 3 top-level columns in the new order: stepper | stages | description+overview", () => {
    renderNavigator();
    // Корневой <div className="flex gap-6 mt-8"> содержит 3 прямых ребёнка:
    // <aside> (степпер), <aside> (этапы), <section> (описание+обзор).
    // Селектор .flex.gap-6.mt-8 — единственный элемент с такой комбинацией
    // классов (внутренние div используют другие классы).
    const rootFlex = screen.getByText("Маршрут исследования").closest(".flex.gap-6.mt-8");
    expect(rootFlex).not.toBeNull();
    const directChildren = Array.from(rootFlex!.children);
    expect(directChildren).toHaveLength(3);

    const [col1, col2, col3] = directChildren;

    // Колонка 1: степпер + тарифы (заголовок «Маршрут исследования»)
    expect(within(col1 as HTMLElement).getByText("Маршрут исследования")).toBeInTheDocument();
    expect(within(col1 as HTMLElement).getByText("Тарифы")).toBeInTheDocument();
    // Внутри степпера — 10 кнопок остановок, например ЗАГРУЗКА.
    expect(within(col1 as HTMLElement).getByLabelText("ЗАГРУЗКА")).toBeInTheDocument();

    // Колонка 2: Этапы модуля (после Task 23 — средняя)
    expect(within(col2 as HTMLElement).getByText(/Этапы модуля:/)).toBeInTheDocument();
    // Здесь же — пункты активной остановки (Загрузка по умолчанию).
    expect(within(col2 as HTMLElement).getByText("Автопревью и типы колонок")).toBeInTheDocument();
    // Здесь же — disabled-кнопка «Запустить анализ»
    expect(within(col2 as HTMLElement).getAllByRole("button", { name: /Запустить анализ/i }).length).toBeGreaterThan(0);

    // Колонка 3: Описание + Обзор (после Task 23 — правая)
    expect(within(col3 as HTMLElement).getByText("Описание")).toBeInTheDocument();
    expect(within(col3 as HTMLElement).getByText(/Обзор:/)).toBeInTheDocument();
    // Здесь же — метрики (примеры без активного датасета)
    expect(within(col3 as HTMLElement).getByText("пример")).toBeInTheDocument();
  });

  it("does NOT render 'Этапы модуля' in the right (3rd) column after Task 23", () => {
    // Регрессионный тест: до Task 23 «Этапы модуля» были в правой колонке.
    // Если кто-то вернёт старый порядок — этот тест должен упасть.
    renderNavigator();
    const rootFlex = screen.getByText("Маршрут исследования").closest(".flex.gap-6.mt-8");
    const directChildren = Array.from(rootFlex!.children);
    expect(directChildren).toHaveLength(3);
    const col3 = directChildren[2] as HTMLElement;
    // «Этапы модуля: ЗАГРУЗКА» НЕ должно быть в третьей (правой) колонке.
    expect(within(col3).queryByText(/Этапы модуля:/)).toBeNull();
  });

  it("does NOT render 'Описание' in the middle (2nd) column after Task 23", () => {
    // Регрессионный тест симметричный предыдущему: до Task 23 «Описание»
    // было в центре. После — в правой колонке.
    renderNavigator();
    const rootFlex = screen.getByText("Маршрут исследования").closest(".flex.gap-6.mt-8");
    const directChildren = Array.from(rootFlex!.children);
    expect(directChildren).toHaveLength(3);
    const col2 = directChildren[1] as HTMLElement;
    expect(within(col2).queryByText("Описание")).toBeNull();
  });

  it("preserves widths: w-60 for stepper, w-80 for stages, flex-1 for description+overview", () => {
    // Контракт ширин колонок сохранён из предыдущей реализации.
    renderNavigator();
    const rootFlex = screen.getByText("Маршрут исследования").closest(".flex.gap-6.mt-8");
    const [col1, col2, col3] = Array.from(rootFlex!.children);

    // Колонка 1: w-60 (степпер + тарифы)
    expect((col1 as HTMLElement).className).toContain("w-60");
    expect((col1 as HTMLElement).className).toContain("shrink-0");
    // Колонка 2: w-80 (этапы модуля)
    expect((col2 as HTMLElement).className).toContain("w-80");
    expect((col2 as HTMLElement).className).toContain("shrink-0");
    // Колонка 3: flex-1 (описание + обзор) — растягивается на остаток
    expect((col3 as HTMLElement).className).toContain("flex-1");
    expect((col3 as HTMLElement).className).toContain("min-w-0");
  });
});