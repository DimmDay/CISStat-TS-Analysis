// packages/ui/components/auth-kabinet-demo.test.tsx
//
// AUTH-KABINET-DEMO (2026-11-15): самообслуживаемый демо-режим.
//   1. «Запустить демо-режим» — prepare + enter с публичной парой из env
//      (publicDemoCredentials); пара ходит только в теле POST (AC22),
//      в URL не попадает.
//   2. Без env-пары кнопка честно отключена (никаких fallback-пар),
//      форма кампаний организатора доступна.
//   3. Resume остаётся credential-free.
//   4. DemoLanding описывает условия без «флаер»-лексики.
//   5. NAVIGATOR_SECTION_ROUTES: 4-й маршрут «Попробовать в демо-режиме»
//      → /demo (страница), первые три — якоря.
import React from "react";
import { render, screen, fireEvent } from "@testing-library/react";
import { DemoEntry } from "./DemoEntry";
import { DemoLanding } from "./DemoLanding";
import { demoRequest, publicDemoCredentials } from "../lib/demo";
import { NAVIGATOR_SECTION_ROUTES } from "../lib/navigator-stops";

jest.mock("../lib/demo", () => ({
  demoRequest: jest.fn(),
  publicDemoCredentials: jest.fn(() => null),
}));
const request = demoRequest as jest.Mock;
const pair = publicDemoCredentials as jest.Mock;
beforeEach(() => {
  request.mockReset();
  pair.mockReset();
  pair.mockReturnValue(null);
});

test("self-service start posts the published pair in the body, never in a URL", async () => {
  pair.mockReturnValue({ login: "demo", password: "demo-public" });
  request
    .mockResolvedValueOnce({}) // prepare
    .mockRejectedValueOnce(new Error("Сервис временно недоступен.")); // enter
  render(<DemoEntry />);
  fireEvent.click(screen.getByRole("button", { name: "Запустить демо-режим" }));
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Сервис временно недоступен.",
  );
  expect(request).toHaveBeenNthCalledWith(1, "auth/demo/prepare", "POST");
  expect(request).toHaveBeenNthCalledWith(2, "auth/demo/enter", "POST", {
    login: "demo",
    password: "demo-public",
  });
});

test("public start is honestly disabled without the env pair; organizer form stays available", () => {
  render(<DemoEntry />);
  expect(
    screen.getByRole("button", { name: "Запустить демо-режим" }),
  ).toBeDisabled();
  expect(
    screen.getByText(/Публичный демо-доступ временно недоступен/),
  ).toBeInTheDocument();
  expect(screen.getByLabelText("Логин кампании")).toBeInTheDocument();
  expect(screen.getByLabelText("Пароль кампании")).toBeInTheDocument();
  expect(screen.queryByText(/флаер/i)).toBeNull();
});

test("resume remains credential-free", async () => {
  request.mockRejectedValue(new Error("Демо-доступ завершён."));
  render(<DemoEntry />);
  fireEvent.click(
    screen.getByRole("button", { name: "Продолжить свой демо-доступ" }),
  );
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Демо-доступ завершён.",
  );
  expect(request).toHaveBeenCalledWith("auth/demo/resume", "POST");
  expect(request).not.toHaveBeenCalledWith("auth/demo/enter", "POST", expect.anything());
});

test("landing describes conditions without flyer wording and mounts the entry", () => {
  render(<DemoLanding />);
  expect(screen.getByRole("heading", { name: "Демо-режим платформы", level: 1 })).toBeInTheDocument();
  expect(screen.getByText("Условия демо-режима")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Запустить демо-режим" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Войти в кампанию" })).toBeInTheDocument();
  expect(screen.queryByText(/флаер/i)).toBeNull();
});

test("navigator section routes gain the 4th demo page badge, anchors intact", () => {
  expect(NAVIGATOR_SECTION_ROUTES).toHaveLength(4);
  const [tasks, stages, platform, demo] = NAVIGATOR_SECTION_ROUTES;
  for (const route of [tasks, stages, platform]) expect(route.href).toMatch(/^#/);
  expect(demo.title).toBe("Попробовать в демо-режиме");
  expect(demo.href).toBe("/demo");
});
