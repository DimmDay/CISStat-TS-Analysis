// apps/standalone/components/DevNoticeBar.test.tsx
//
// Task UI-DEVNOTICE-1 (2026-11-09): dismissible-полоса «Платформа в
// активной разработке» (вариант A постановки тимлида) + чип «β» у бренда.
//
// Дизайн-гвардейлы постановки: одна строка ≤80 символов, 13px,
// нейтральные токены (это информация, а не алерт — без warning-жёлтого),
// закрытие навсегда с запоминанием в localStorage (паттерн ключа темы
// cisstat-theme), без анимаций и блокировки контента.
//
// ГИДРАЦИЯ (контракт компонента): до монтирования полоса НЕ рендерится —
// SSR-вывод пуст, закрывшие пользователи не видят ни мигания, ни сдвига
// макета на каждой загрузке (обратная стратегия «SSR-рендер + скрытие
// в эффекте» давала бы сдвиг у каждого вернувшегося).
//
// ЯЗЫК: html lang="ru", переключатель «РУС / ENG» в шапке статичен
// (i18n-контекста в standalone нет) — рендерится RU-строка; ENG-строка
// закреплена константой как контракт будущего переключателя (пин ниже).
//
// Корпус дизъюнктен существующим сюитам (практика brand-rename.test.tsx).

import "@testing-library/jest-dom";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { renderToString } from "react-dom/server";
import {
  DevNoticeBar,
  DEV_NOTICE_TEXTS,
  DEV_NOTICE_DISMISS_KEY,
} from "./DevNoticeBar";

describe("UI-DEVNOTICE-1: DevNoticeBar — показ и закрытие", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  it("показывает RU-текст по умолчанию (уведомление не закрыто)", async () => {
    render(<DevNoticeBar />);
    expect(await screen.findByText(DEV_NOTICE_TEXTS.ru)).toBeInTheDocument();
  });

  it("тексты RU/ENG закреплены контрактом задачи (точные строки)", () => {
    expect(DEV_NOTICE_TEXTS.ru).toBe(
      "Платформа в активной разработке — данные и функциональность могут меняться"
    );
    expect(DEV_NOTICE_TEXTS.eng).toBe(
      "Under active development — data and features may change"
    );
  });

  it("закрытая полоса не рендерится: localStorage-ключ помнит выбор", async () => {
    window.localStorage.setItem(DEV_NOTICE_DISMISS_KEY, "1");
    render(<DevNoticeBar />);
    await waitFor(() => {
      expect(screen.queryByTestId("dev-notice-bar")).toBeNull();
    });
  });

  it("кнопка закрытия скрывает полосу и записывает ключ в localStorage", async () => {
    render(<DevNoticeBar />);
    const bar = await screen.findByTestId("dev-notice-bar");
    fireEvent.click(screen.getByRole("button", { name: "Скрыть уведомление" }));
    expect(bar).not.toBeInTheDocument();
    expect(window.localStorage.getItem(DEV_NOTICE_DISMISS_KEY)).toBe("1");
  });

  it("SSR-вывод пуст: до гидратации полосы нет (нет сдвига у закрывших)", () => {
    window.localStorage.setItem(DEV_NOTICE_DISMISS_KEY, "1");
    expect(renderToString(<DevNoticeBar />)).toBe("");
  });
});

describe("UI-DEVNOTICE-1: DevNoticeBar — аккуратность и a11y", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  it("полоса — семантическое уведомление role=status (не alert)", async () => {
    render(<DevNoticeBar />);
    expect(await screen.findByRole("status")).toBeInTheDocument();
  });

  it("кнопка закрытия имеет внятное доступное имя", async () => {
    render(<DevNoticeBar />);
    expect(
      await screen.findByRole("button", { name: "Скрыть уведомление" })
    ).toBeInTheDocument();
  });

  it("нейтральные токены DKT: bg-white и text-neutral-600, без произвольных цветов", async () => {
    render(<DevNoticeBar />);
    const bar = await screen.findByTestId("dev-notice-bar");
    expect(bar).toHaveClass("bg-white");
    expect(bar.querySelector("p")).toHaveClass("text-neutral-600");
    expect(bar.innerHTML).not.toContain("#");
  });

  it("иконка закрытия скрыта от скринридеров (имя даёт aria-label кнопки)", async () => {
    render(<DevNoticeBar />);
    await screen.findByRole("status");
    const icon = screen.getByRole("button", { name: "Скрыть уведомление" }).querySelector("svg");
    expect(icon).toHaveAttribute("aria-hidden", "true");
  });
});
