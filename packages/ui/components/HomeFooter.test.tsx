// packages/ui/components/HomeFooter.test.tsx
//
// Тесты футера главной страницы standalone (Task w/n, 2026-09-13).
//
// Контракт (постановка тимлида):
//   - шаблон — футер главной страницы портала CISStat
//     (https://cis-stat-portal-k9tu.vercel.app/), снят 1:1 из продового
//     DOM: 4 колонки (Проект / Сотрудничество / Поддержка / Контакты),
//     внутренний разделитель, нижняя строка (копирайт + поиск +
//     юридические ссылки);
//   - блок legal-текста под футером портала (bg-footer-legal,
//     дисклеймер об интеллектуальной собственности) — ИГНОРИРУЕТСЯ
//     по прямой команде тимлида;
//   - футер пока ТОЛЬКО на главной странице standalone (подключает
//     apps/standalone/app/page.tsx; embedded не трогается);
//   - фон футера — свой для каждой страницы; на главной — #CAD7F7
//     (проп backgroundColor с дефолтом главной страницы);
//   - цвет текста — чёрный (text-black): тёмная тема шаблона
//     (text-white/text-neutral-300) адаптирована в светлую;
//   - углы сглажены ПО ПАТТЕРНУ ФОНА страницы — тот же токен
//     rounded-2xl, что и у коробки HomeWavesBackground;
//   - между нижней границей страницы и футером нет черты (черту
//     после Block B гасит HomeCapabilities — правка 8, её тесты);
//     ВНУТРЕННИЙ разделитель шаблона (my-3 border-t) сохранён.

import "@testing-library/jest-dom";
import { render, screen, within } from "@testing-library/react";
import { HomeFooter } from "./HomeFooter";
import {
  FOOTER_COLUMNS,
  FOOTER_CONTACTS,
  FOOTER_COPYRIGHT,
  FOOTER_SEARCH_LABEL,
  FOOTER_SEARCH_PLACEHOLDER,
  FOOTER_LEGAL_LINKS,
  FOOTER_HOME_BACKGROUND_COLOR,
} from "../lib/homeFooter";

describe("HomeFooter", () => {
  it("renders a <footer> landmark labelled «Подвал сайта»", () => {
    render(<HomeFooter />);
    const footer = screen.getByRole("contentinfo");
    expect(footer).toHaveAttribute("aria-label", "Подвал сайта");
  });

  it("uses the main-page background color #CAD7F7 by default (inline style)", () => {
    const { container } = render(<HomeFooter />);
    const footer = container.querySelector("footer")!;
    // jsdom нормализует hex к rgb(...); #CAD7F7 === rgb(202, 215, 247)
    expect(footer.style.backgroundColor).toBe("rgb(202, 215, 247)");
    expect(FOOTER_HOME_BACKGROUND_COLOR).toBe("#CAD7F7");
  });

  it("accepts a per-page background color prop (each page will have its own)", () => {
    const { container } = render(<HomeFooter backgroundColor="#FFEEDD" />);
    const footer = container.querySelector("footer")!;
    // jsdom нормализует hex к rgb(...); #FFEEDD === rgb(255, 238, 221)
    expect(footer.style.backgroundColor).toBe("rgb(255, 238, 221)");
  });

  it("smooths corners by the page-background pattern: rounded-2xl (same token as HomeWavesBackground)", () => {
    const { container } = render(<HomeFooter />);
    const footer = container.querySelector("footer")!;
    expect(footer.className).toContain("rounded-2xl");
  });

  it("renders text in black (text-black on the footer root)", () => {
    const { container } = render(<HomeFooter />);
    const footer = container.querySelector("footer")!;
    expect(footer.className).toContain("text-black");
  });

  it("follows the portal template: 4 columns «Проект», «Сотрудничество», «Поддержка», «Контакты»", () => {
    render(<HomeFooter />);
    for (const column of FOOTER_COLUMNS) {
      expect(screen.getByText(column.title)).toBeInTheDocument();
    }
    expect(screen.getByText(FOOTER_CONTACTS.title)).toBeInTheDocument();
  });

  it("styles column headings like the template (mb-2 text-xs font-semibold uppercase tracking-wide)", () => {
    const { container } = render(<HomeFooter />);
    const heading = Array.from(container.querySelectorAll("p")).find(
      (p) => p.textContent === FOOTER_COLUMNS[0].title,
    )!;
    expect(heading.className).toContain("mb-2");
    expect(heading.className).toContain("text-xs");
    expect(heading.className).toContain("font-semibold");
    expect(heading.className).toContain("uppercase");
    expect(heading.className).toContain("tracking-wide");
  });

  it("renders all 15 template links of the three nav columns with their hrefs", () => {
    render(<HomeFooter />);
    const footer = screen.getByRole("contentinfo");
    const allLinks = FOOTER_COLUMNS.flatMap((column) => column.links);
    expect(allLinks).toHaveLength(15);
    for (const link of allLinks) {
      const anchor = screen.getByRole("link", { name: link.label });
      expect(anchor).toHaveAttribute("href", link.href);
    }
    // Ровно 15 ссылок в футере: контакты — обычные <p>, не <a>.
    expect(footer.querySelectorAll("a")).toHaveLength(15);
  });

  it("styles nav links like the template (mb-1 block text-[12.5px])", () => {
    render(<HomeFooter />);
    const first = screen.getByRole("link", { name: "О сервисе" });
    expect(first.className).toContain("mb-1");
    expect(first.className).toContain("block");
    expect(first.className).toContain("text-[12.5px]");
  });

  it("keeps the two external form links with target=_blank and rel=noopener noreferrer", () => {
    render(<HomeFooter />);
    for (const label of ["Сообщить об ошибке", "Предложить улучшения"]) {
      const anchor = screen.getByRole("link", { name: label });
      expect(anchor).toHaveAttribute("target", "_blank");
      expect(anchor.getAttribute("rel")).toContain("noopener");
      expect(anchor.getAttribute("rel")).toContain("noreferrer");
    }
  });

  it("renders contacts as plain paragraphs (address in two lines, email, phone), NOT links", () => {
    const { container } = render(<HomeFooter />);
    const footer = screen.getByRole("contentinfo");
    const paragraphs = Array.from(footer.querySelectorAll("p"));
    // Адрес — две строки через <br/>, как в шаблоне портала.
    const address = paragraphs.find(
      (p) => p.textContent === "107450 Москва,ул. Мясницкая, 39/1",
    );
    expect(address).toBeDefined();
    expect(address!.querySelectorAll("br")).toHaveLength(1);
    expect(
      paragraphs.some((p) => p.textContent === "cisstat@cisstat.org"),
    ).toBe(true);
    expect(
      paragraphs.some((p) => p.textContent === "+7 (495) 624-30-92"),
    ).toBe(true);
    // Контакты не сделаны ссылками (в шаблоне портала — простой текст).
    expect(container.querySelector('a[href^="mailto:"]')).toBeNull();
    expect(container.querySelector('a[href^="tel:"]')).toBeNull();
  });

  it("keeps the template's internal divider (my-3 border-t border-black/20) and no h-px dashes", () => {
    const { container } = render(<HomeFooter />);
    const footer = container.querySelector("footer")!;
    const divider = Array.from(footer.querySelectorAll("div")).find((d) =>
      d.className.includes("border-t"),
    );
    expect(divider).toBeDefined();
    expect(divider!.className).toContain("my-3");
    expect(divider!.className).toContain("border-black/20");
    expect(footer.querySelectorAll(".h-px")).toHaveLength(0);
  });

  it("renders the template copyright line «© 2026, СтатКомитет СНГ»", () => {
    render(<HomeFooter />);
    expect(screen.getByText(FOOTER_COPYRIGHT)).toBeInTheDocument();
    expect(FOOTER_COPYRIGHT).toBe("© 2026, СтатКомитет СНГ");
  });

  it("renders the template site search (role=search, sr-only label, placeholder «Поиск по сайту…»)", () => {
    render(<HomeFooter />);
    const form = screen.getByRole("search");
    const input = within(form).getByLabelText(FOOTER_SEARCH_LABEL);
    expect(input).toHaveAttribute("id", "footer-search");
    expect(input).toHaveAttribute("type", "text");
    expect(input).toHaveAttribute("placeholder", FOOTER_SEARCH_PLACEHOLDER);
    expect(FOOTER_SEARCH_PLACEHOLDER).toBe("Поиск по сайту…");
  });

  it("renders the three legal spans with underline (decoration adapted to black)", () => {
    const { container } = render(<HomeFooter />);
    const footer = container.querySelector("footer")!;
    for (const label of FOOTER_LEGAL_LINKS) {
      expect(screen.getByText(label)).toBeInTheDocument();
    }
    const legalSpans = Array.from(footer.querySelectorAll("span")).filter(
      (s) => s.className.includes("underline"),
    );
    expect(legalSpans).toHaveLength(FOOTER_LEGAL_LINKS.length);
    expect(legalSpans[0].className).toContain("decoration-black/30");
  });

  it("IGNORES the portal legal-text block under the footer (no bg-footer-legal disclaimer content)", () => {
    render(<HomeFooter />);
    expect(screen.queryByText(/интеллектуальной собственностью/)).toBeNull();
    expect(screen.queryByText(/СтатКомитет СНГ разрешает/)).toBeNull();
  });
});