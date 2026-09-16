// packages/ui/components/NavigatorHero.test.tsx
//
// Тесты для NavigatorHero — верхняя часть страницы «Знакомство с платформой».
// Task 26: 6 бейджей трансформированы в chevron-стрелки; текст ниже.
//
// Задача NAVSTG-1 (2026-09-17): секция 3 «Ключевые этапы исследования ряда»
// переведена на паттерн бегущей строки главной страницы:
//   - первый ряд — ДИНАМИЧЕСКИЙ marquee шеврон-стрелок, движение СЛЕВА
//     НАПРАВО (animate-marquee-reverse — зеркальный keyframe к marquee
//     главной, та же скорость 90s linear); нижним слоем двигаются стрелки
//     (рамка индиго #2E3192, прозрачный фон — SVG-полигон fill=none);
//   - слой выше — цифры нумерации в зелёных кружках — СТАТИЧНЫ
//     (absolute-оверлей поверх трека, pointer-events-none);
//   - ряд заголовков/описаний этапов — поля 24px (px-6, паттерн первой
//     секции / паттерн главной страницы);
//   - «Для кого»/«Для чего» — из формата селектора (CollapsibleHalfBadge,
//     Task 21) в формат СТАТИЧНОГО бейджа: текст всегда виден, интерактивных
//     элементов нет; поля 24px (px-6).
//
// a11y-контракт:
//   - Обёртка этапов — aria-label="Этапы анализа"; цифры aria-hidden
//   - Клон marquee-группы — aria-hidden="true"
//   - Статичные бейджи — semantic текст без кнопок/aria-expanded

import "@testing-library/jest-dom";
import { render, screen } from "@testing-library/react";
import { NavigatorHero } from "./NavigatorHero";
import { HomeHero } from "./HomeHero";
import {
  NAVIGATOR_BADGES,
  NAVIGATOR_SECTION_ROUTES,
  AUDIENCE_LABEL,
  AUDIENCE_TEXT,
  PURPOSE_LABEL,
  PURPOSE_TEXT,
} from "../lib/navigator-stops";

describe("NavigatorHero", () => {
  // ── Вводная секция и маршруты по странице ─────────────────────────

  it("renders the page H1 title", () => {
    render(<NavigatorHero />);
    expect(
      screen.getByRole("heading", { level: 1, name: /Знакомство с платформой/i }),
    ).toBeInTheDocument();
  });

  it("renders the H1 title centered (Task 31)", () => {
    render(<NavigatorHero />);
    const h1 = screen.getByRole("heading", {
      level: 1,
      name: /Знакомство с платформой/i,
    });
    expect(h1.className).toContain("text-center");
  });

  it("renders three route badges with stable anchor links", () => {
    render(<NavigatorHero />);

    expect(
      screen.getByRole("navigation", { name: "Разделы знакомства с платформой" }),
    ).toBeInTheDocument();
    expect(NAVIGATOR_SECTION_ROUTES).toHaveLength(3);
    NAVIGATOR_SECTION_ROUTES.forEach((route) => {
      const link = screen.getByRole("link", { name: new RegExp(route.title, "i") });
      expect(link).toHaveAttribute("href", route.href);
    });
  });

  it("reuses the visual states of route cards from the home page", () => {
    const { container } = render(<NavigatorHero />);
    const links = container.querySelectorAll('nav[aria-label="Разделы знакомства с платформой"] > a');
    expect(links).toHaveLength(3);
    links.forEach((link) => {
      expect(link.className).toContain("border-brand/60");
      expect(link.className).toContain("bg-brand-light/60");
      expect(link.className).toContain("hover:border-brand/90");
      expect(link.className).toContain("hover:bg-brand-light/90");
    });
  });

  it("renders the applied tasks navigator and the research stages as anchor targets", () => {
    render(<NavigatorHero />);
    expect(document.getElementById("applied-tasks")).toBeInTheDocument();
    expect(document.getElementById("research-stages")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Предметная область" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Основная задача" })).toBeInTheDocument();
    expect(screen.queryByText(/Наполнение блока согласуем в следующей задаче/i)).toBeNull();
    expect(
      screen.getByRole("heading", { level: 2, name: /Ключевые этапы исследования ряда/i }),
    ).toBeInTheDocument();
  });

  // ── Черты над заголовками — фирменный индиго (Task NAVIG-1) ────────
  //
  // Паттерн главной страницы: разделители в токене brand (#2E3192,
  // фирменный индиго Статкомитета СНГ). Серые (border-neutral-200)
  // черты запрещены guard-ами ниже.

  it("renders the applied tasks title with only a full-width indigo rule above it", () => {
    render(<NavigatorHero />);

    const heading = screen.getByRole("heading", {
      level: 2,
      name: "Примеры прикладных задач",
    });
    expect(heading).toBeInTheDocument();
    expect(
      screen.queryByRole("heading", {
        level: 2,
        name: "Прикладные задачи, решаемые платформой",
      }),
    ).toBeNull();

    const ruledHeading = heading.parentElement;
    expect(ruledHeading).not.toBeNull();
    // Guard по токенам: "border-brand" содержит подстроку "border-b",
    // поэтому сравниваем отдельные классы, а не подстроки.
    const classes = (ruledHeading?.className ?? "").split(/\s+/);
    expect(classes).toContain("w-full");
    expect(classes).toContain("border-t");
    expect(classes).not.toContain("border-y");
    expect(classes).not.toContain("border-b");
    expect(classes).toContain("border-brand");
    expect(classes).not.toContain("border-neutral-200");
  });

  it("renders a full-width indigo rule above the research stages title", () => {
    render(<NavigatorHero />);

    const heading = screen.getByRole("heading", {
      level: 2,
      name: "Ключевые этапы исследования ряда",
    });
    const ruledHeading = heading.parentElement;

    expect(ruledHeading).not.toBeNull();
    expect(ruledHeading?.className).toContain("w-full");
    expect(ruledHeading?.className).toContain("border-t");
    expect(ruledHeading?.className).toContain("border-brand");
    expect(ruledHeading?.className).not.toContain("border-neutral-200");
  });

  // ── Боковые поля 24px первой секции (паттерн главной страницы) ─────
  //
  // Прецедент Task NAVBG-2: px-6 на сетке бейджей — собственные боковые
  // поля 24px от границ фоновой коробки; карточки соразмерно ужимаются.
  // Равенство бейджей по ширине/высоте гарантируется механикой CSS Grid
  // (fr-колонки + row stretch), поэтому гардируется на уровне
  // layout-классов сетки (кросс-тест с HomeHero — ниже).

  it("insets the section routes grid 24px from the page edges on both sides (px-6)", () => {
    const { container } = render(<NavigatorHero />);
    const grid = container.querySelector(
      'nav[aria-label="Разделы знакомства с платформой"]',
    )!;
    expect(grid).not.toBeNull();
    expect(grid.className).toContain("px-6");
  });

  it("keeps exactly three direct card children in one responsive grid (equal width and height by grid mechanics)", () => {
    const { container } = render(<NavigatorHero />);
    const grid = container.querySelector(
      'nav[aria-label="Разделы знакомства с платформой"]',
    )!;
    expect(grid).not.toBeNull();
    // Ровно три карточки — прямые дети сетки (одна строка на md+).
    expect(grid.querySelectorAll(":scope > a")).toHaveLength(3);
    // fr-колонки (md:grid-cols-3) => равная ширина; дефолтный stretch
    // строки => равная высота; gap-5 не меняется — сжатие соразмерное.
    expect(grid.className).toContain("grid-cols-1");
    expect(grid.className).toContain("md:grid-cols-3");
    expect(grid.className).toContain("gap-5");
  });

  it("matches the home page inset pattern (gap-5 + px-6 identical to the HomeHero routes grid)", () => {
    const { container } = render(<NavigatorHero />);
    const navGrid = container.querySelector(
      'nav[aria-label="Разделы знакомства с платформой"]',
    )!;
    const hero = render(<HomeHero />);
    const heroGrid = hero.container.querySelector('[aria-label="Маршруты"]')!;
    expect(navGrid).not.toBeNull();
    expect(heroGrid).not.toBeNull();
    // Одинаковые классы зазоров => одинаковый отступ бейджей от границ
    // страницы на / и /navigator при любой ширине вьюпорта. Брейкпоинты
    // колонок (md:grid-cols-3 против sm/lg у главной) — существующее
    // различие, в паттерн зазоров не входят.
    for (const cls of ["gap-5", "px-6"]) {
      expect(navGrid.className).toContain(cls);
      expect(heroGrid.className).toContain(cls);
    }
  });

  // ── Ряд 1: бегущая строка шеврон-стрелок (задача NAVSTG-1) ─────────
  //
  // Паттерн бегущей строки главной страницы (HomeCapabilities, M-02):
  //   - вьюпорт overflow-hidden, трек w-max из ДВУХ одинаковых групп,
  //     анимация одним transform на весь трек; сдвиг -50% = ровно одна
  //     группа => бесшовный цикл;
  //   - скорость/характер движения как у главной: 90s linear infinite,
  //     пауза на hover, motion-reduce отключает анимацию;
  //   - НАПРАВЛЕНИЕ — слева направо: зеркальный keyframe
  //     (animate-marquee-reverse, translateX(-50%) -> 0) вместо
  //     animate-marquee главной (справа налево);
  //   - дизайн стрелки по стандарту главной marquee: РАМКА — фирменный
  //     индиго #2E3192, ФОН — прозрачный (SVG-полигон fill="none" +
  //     stroke; рамка CSS-border на clip-path обрезалась бы по
  //     диагоналям стрелки).
  // Стрелки — чистая декорация: весь слой aria-hidden.

  it("renders the chevron marquee viewport full-bleed with a w-max animated track", () => {
    const { container } = render(<NavigatorHero />);
    const viewport = container.querySelector('[data-testid="chevron-marquee-viewport"]');
    expect(viewport).not.toBeNull();
    expect(viewport?.className).toContain("overflow-hidden");

    const track = container.querySelector('[data-testid="chevron-marquee-track"]');
    expect(track).not.toBeNull();
    expect(track?.className).toContain("w-max");
    expect(track?.className).toContain("flex");
  });

  it("moves left-to-right: the track uses the reverse marquee variant, not the home-page one", () => {
    const { container } = render(<NavigatorHero />);
    const track = container.querySelector('[data-testid="chevron-marquee-track"]')!;
    const classes = track.className.split(/\s+/);

    // Зеркальный keyframe (translateX(-50%) -> 0) — движение слева направо.
    expect(classes).toContain("animate-marquee-reverse");
    // Класс главной (translateX(0) -> -50%, справа налево) НЕ применён.
    expect(classes).not.toContain("animate-marquee");
  });

  it("keeps the home marquee motion standard: hover pause and prefers-reduced-motion opt-out", () => {
    const { container } = render(<NavigatorHero />);
    const track = container.querySelector('[data-testid="chevron-marquee-track"]')!;
    const classes = track.className.split(/\s+/);

    expect(classes).toContain("hover:[animation-play-state:paused]");
    expect(classes).toContain("motion-reduce:animate-none");
  });

  it("is seamless: exactly two identical chevron groups, the clone aria-hidden", () => {
    const { container } = render(<NavigatorHero />);
    const track = container.querySelector('[data-testid="chevron-marquee-track"]')!;

    const real = track.querySelector(':scope > [data-testid="chevron-group-real"]');
    const clone = track.querySelector(':scope > [data-testid="chevron-group-clone"]');
    expect(real).not.toBeNull();
    expect(clone).not.toBeNull();

    // Клон — aria-hidden (скринридер не читает дублирующую группу);
    // реальная группа без aria-hidden... стрелки декоративны и скрываются
    // на уровне каждой стрелки, но группа-клон скрыта ЦЕЛИКОМ.
    expect(clone).toHaveAttribute("aria-hidden", "true");
    expect(real).not.toHaveAttribute("aria-hidden", "true");

    // Ровно две группы — прямые дети трека.
    const groups = track.querySelectorAll(":scope > div");
    expect(groups).toHaveLength(2);

    // Группы идентичны по составу: по 14 стрелок (как 14 бейджей главной —
    // гарантирует покрытие вьюпорта и бесшовный стык на широких экранах:
    // 14 × 280px = 3920px >= 3840px).
    const realArrows = real!.querySelectorAll(":scope > div");
    const cloneArrows = clone!.querySelectorAll(":scope > div");
    expect(realArrows.length).toBe(14);
    expect(cloneArrows.length).toBe(14);
  });

  it("styles each chevron arrow per the home marquee standard: indigo frame, transparent fill", () => {
    const { container } = render(<NavigatorHero />);
    const arrows = container.querySelectorAll(
      '[data-testid="chevron-group-real"] > div > svg',
    );
    expect(arrows.length).toBe(14);

    arrows.forEach((svg) => {
      const polygon = svg.querySelector("polygon");
      expect(polygon).not.toBeNull();
      // Рамка — фирменный индиго (тот же токен, что border-brand главной).
      expect(polygon!.getAttribute("stroke")).toBe("#2E3192");
      // Фон — прозрачный: заливки нет (сквозь стрелку виден фон страницы).
      expect(polygon!.getAttribute("fill")).toBe("none");
      // Толщина рамки стабильна при неравномерном растяжении контейнера.
      expect(polygon!.getAttribute("vector-effect")).toBe("non-scaling-stroke");
    });
  });

  // ── Ряд 1, слой выше: цифры нумерации СТАТИЧНЫ (задача NAVSTG-1) ───
  //
  // Нижним слоем двигаются стрелки; цифры в зелёных кружках — отдельный
  // абсолютный слой ПОВЕРХ трека: не анимируется, не перехватывает hover
  // (pointer-events-none — пауза строки работает сквозь цифры), геометрия
  // кружков прежняя (h-7 w-7 rounded-full bg-green-50 text-green-700).

  it("renders the stage numbers as a STATIC overlay above the moving track", () => {
    const { container } = render(<NavigatorHero />);
    const overlay = container.querySelector('[data-testid="stage-numbers-overlay"]');
    expect(overlay).not.toBeNull();

    // Статичность: оверлей НЕ внутри анимируемого трека и сам не анимируется.
    const track = container.querySelector('[data-testid="chevron-marquee-track"]')!;
    expect(track.contains(overlay as Node)).toBe(false);
    expect(overlay!.className).not.toMatch(/animate-/);

    // Слой ВЫШЕ: оверлей идёт ПОСЛЕ вьюпорта в DOM (later positioned
    // element paints above) и абсолютен относительно общей обёртки.
    expect(overlay!.className).toContain("absolute");
    expect(overlay!.className).toContain("inset-0");

    // Не перехватывает указатель: hover-пауза трека работает сквозь цифры.
    expect(overlay!.className).toContain("pointer-events-none");
  });

  it("keeps the number circle design unchanged: 6 green circles, one per stage", () => {
    const { container } = render(<NavigatorHero />);
    const overlay = container.querySelector('[data-testid="stage-numbers-overlay"]')!;

    const circles = overlay.querySelectorAll(".rounded-full.bg-green-50");
    expect(circles).toHaveLength(6);

    NAVIGATOR_BADGES.forEach((badge, idx) => {
      const circle = circles[idx];
      expect(circle.textContent).toBe(String(badge.num));
      expect(circle.className).toContain("text-green-700");
      expect(circle.className).toContain("h-7");
      expect(circle.className).toContain("w-7");
      // Цифры — aria-hidden (контракт a11y шеврон-ряда, Task 26).
      expect(circle).toHaveAttribute("aria-hidden", "true");
    });
  });

  it("distributes static numbers evenly across the page width (grid-cols-6)", () => {
    const { container } = render(<NavigatorHero />);
    const overlay = container.querySelector('[data-testid="stage-numbers-overlay"]')!;
    expect(overlay.className).toContain("grid");
    expect(overlay.className).toContain("grid-cols-6");
  });

  // ── Ряд 2: заголовки и описания этапов — поля 24px (NAVSTG-1) ──────

  it("insets the stage titles/subtitles grid 24px from the page edges (px-6)", () => {
    const { container } = render(<NavigatorHero />);
    const grid = container.querySelector('[data-testid="stages-text-grid"]')!;
    expect(grid).not.toBeNull();
    expect(grid.className).toContain("px-6");
    // Адаптивная геометрия ряда сохранена (сжатие соразмерное — механикой Grid).
    expect(grid.className).toContain("grid-cols-2");
    expect(grid.className).toContain("sm:grid-cols-3");
    expect(grid.className).toContain("md:grid-cols-6");
    expect(grid.className).toContain("gap-y-2");
  });

  it("keeps the moving arrows OUT of the text grid (text row is static)", () => {
    const { container } = render(<NavigatorHero />);
    const grid = container.querySelector('[data-testid="stages-text-grid"]')!;
    expect(grid.querySelectorAll("svg")).toHaveLength(0);
  });

  // ── Заголовки БЕЗ нумерации (Task 26, обновлено) ─────────────────

  it("renders badge titles below the chevron row WITHOUT numbering", () => {
    render(<NavigatorHero />);
    // Заголовки без «N. » — только текст label
    expect(screen.getByText("Структура данных", { selector: "p" })).toBeInTheDocument();
    expect(screen.getByText("Качество данных", { selector: "p" })).toBeInTheDocument();
    expect(screen.getByText("Подготовка к исследованию", { selector: "p" })).toBeInTheDocument();
    expect(screen.getByText("Свойства ряда", { selector: "p" })).toBeInTheDocument();
    expect(screen.getByText("Семейство моделей", { selector: "p" })).toBeInTheDocument();
    expect(screen.getByText("Строим прогноз", { selector: "p" })).toBeInTheDocument();
  });

  it("renders subtitle text below each badge title", () => {
    render(<NavigatorHero />);
    NAVIGATOR_BADGES.forEach((badge) => {
      if (badge.subtitle) {
        expect(screen.getByText(badge.subtitle)).toBeInTheDocument();
      }
    });
  });

  it("does NOT render old long badge labels", () => {
    // Регрессионный тест: старые формулировки с глаголами больше не показываются
    render(<NavigatorHero />);
    expect(screen.queryByText("Определяем структуру данных")).toBeNull();
    expect(screen.queryByText("Проверяем качество данных")).toBeNull();
    expect(screen.queryByText("Осуществляем подготовку данных к исследованию")).toBeNull();
  });

  it("does NOT render numbered titles (e.g. '1. Структура данных')", () => {
    // Регрессионный тест: нумерация убрана из заголовков
    render(<NavigatorHero />);
    expect(screen.queryByText("1. Структура данных")).toBeNull();
    expect(screen.queryByText("2. Качество данных")).toBeNull();
    expect(screen.queryByText("3. Подготовка к исследованию")).toBeNull();
    expect(screen.queryByText("4. Свойства ряда")).toBeNull();
    expect(screen.queryByText("5. Семейство моделей")).toBeNull();
    expect(screen.queryByText("6. Строим прогноз")).toBeNull();
  });

  // ── Ряд 3: «Для кого» / «Для чего» — СТАТИЧНЫЕ бейджи (NAVSTG-1) ───
  //
  // Прежний формат селектора (CollapsibleHalfBadge, Task 21: кнопка с
  // aria-expanded/aria-controls, раскрывающийся текст) заменён на статичный
  // бейдж: заголовок с зелёной галочкой + текст ВСЕГДА виден. Визуальная
  // DNA карточки сохранена (rounded-lg, border-brand/20, bg-brand-light/40).
  // Сетка — поля 24px (px-6, паттерн главной страницы).

  it("renders 'Для кого:' and 'Для чего:' labels inside the static badges (always visible)", () => {
    render(<NavigatorHero />);
    expect(screen.getByText(AUDIENCE_LABEL)).toBeInTheDocument();
    expect(screen.getByText(PURPOSE_LABEL)).toBeInTheDocument();
  });

  it("keeps both audience and purpose texts ALWAYS visible (no collapsing)", () => {
    render(<NavigatorHero />);
    expect(screen.getByText(AUDIENCE_TEXT)).toBeInTheDocument();
    expect(screen.getByText(PURPOSE_TEXT)).toBeInTheDocument();

    // Тексты — постоянное содержимое бейджей: скрыть один, не задев другой,
    // невозможно — семантика селектора устранена.
    // Локатор — data-testid корня бейджа: closest(".rounded-lg") от метки
    // в старом селекторе возвращал бы саму кнопку (класс rounded-lg есть
    // и у неё) — ложный guard исключён точным тестидом.
    const audienceBadge = screen.getByTestId("badge-audience");
    const purposeBadge = screen.getByTestId("badge-purpose");
    expect(audienceBadge.textContent).toContain(AUDIENCE_TEXT);
    expect(purposeBadge.textContent).toContain(PURPOSE_TEXT);
  });

  it("converts the selector format to a static badge: no trigger buttons, no aria-expanded/aria-controls", () => {
    render(<NavigatorHero />);

    const audienceBadge = screen.getByTestId("badge-audience");
    const purposeBadge = screen.getByTestId("badge-purpose");

    // Внутри статичных бейджей нет интерактивных элементов-селекторов.
    expect(audienceBadge.querySelectorAll("button")).toHaveLength(0);
    expect(purposeBadge.querySelectorAll("button")).toHaveLength(0);

    // Атрибуты раскрывающегося селектора устранены.
    expect(audienceBadge.querySelector("[aria-expanded]")).toBeNull();
    expect(audienceBadge.querySelector("[aria-controls]")).toBeNull();
    expect(purposeBadge.querySelector("[aria-expanded]")).toBeNull();
    expect(purposeBadge.querySelector("[aria-controls]")).toBeNull();
  });

  it("renders exactly 2 static badges keeping the card visual DNA (indigo frame, light fill, green check)", () => {
    render(<NavigatorHero />);

    const audienceBadge = screen.getByTestId("badge-audience");
    const purposeBadge = screen.getByTestId("badge-purpose");
    expect(audienceBadge).not.toBe(purposeBadge);

    [audienceBadge, purposeBadge].forEach((badge) => {
      expect(badge.className).toContain("rounded-lg");
      expect(badge.className).toContain("border-brand/20");
      expect(badge.className).toContain("bg-brand-light/40");
      // Зелёная галочка заголовка сохранена (иконка Check → svg).
      const check = badge.querySelector("svg.text-green-700");
      expect(check).not.toBeNull();
    });
  });

  it("removes the expand/collapse chevron icons from the badges entirely", () => {
    render(<NavigatorHero />);
    // Прежние стрелки-селекторы (aria-label "chevron up"/"chevron down")
    // в статичном бейдже не существуют.
    expect(screen.queryAllByLabelText(/chevron up/i)).toHaveLength(0);
    expect(screen.queryAllByLabelText(/chevron down/i)).toHaveLength(0);
  });

  it("insets the audience/purpose grid 24px from the page edges (px-6)", () => {
    const { container } = render(<NavigatorHero />);
    const grid = container.querySelector('[data-testid="audience-purpose-grid"]')!;
    expect(grid).not.toBeNull();
    expect(grid.className).toContain("px-6");
    // Два полубейджа в один ряд на md+ — геометрия ряда сохранена.
    expect(grid.className).toContain("grid-cols-1");
    expect(grid.className).toContain("md:grid-cols-2");
    expect(grid.className).toContain("gap-3");
  });

  // ── a11y: обёртка этапов и семантика цифр ──────────────────────────

  it("keeps the stages wrapper accessible label with numbers present in DOM", () => {
    render(<NavigatorHero />);
    const ariaContainer = document.querySelector('[aria-label="Этапы анализа"]');
    expect(ariaContainer).not.toBeNull();
    // Цифры остаются в DOM (aria-hidden — не видны скринридеру, как и прежде).
    const hiddenNums = ariaContainer!.querySelectorAll("[aria-hidden='true']");
    expect(hiddenNums.length).toBeGreaterThanOrEqual(6);
    NAVIGATOR_BADGES.forEach((badge) => {
      expect(ariaContainer!.textContent).toContain(String(badge.num));
    });
  });
});
