import React from "react";
import { render, screen } from "@testing-library/react";
import { PersonalDemoEntry } from "./PersonalDemoEntry";
import { demoRequest } from "../lib/demo";
jest.mock("../lib/demo", () => ({ demoRequest: jest.fn() }));
const request = demoRequest as jest.Mock;
beforeEach(() => request.mockReset());
test("personal entry shows server limits and a fixed upload destination", async () => {
  request.mockResolvedValue({ available: true, limits: { days: 14, micro_cu: 100000000, analyses: 10, concurrency: 1, max_rows: 50000 } });
  render(<PersonalDemoEntry />);
  expect(await screen.findByRole("link", { name: "Получить личный демо-доступ" })).toHaveAttribute("href", "/login?return_to=/upload");
  expect(screen.getByText(/До 10 исследований и 100 CU/)).toBeInTheDocument();
  expect(request).toHaveBeenCalledWith("auth/personal-demo");
});
test.each([false, true])("closed pool or unavailable backend never offers new signup (%s)", async (outage) => {
  outage ? request.mockRejectedValue(new Error("offline")) : request.mockResolvedValue({ available: false });
  render(<PersonalDemoEntry />);
  expect(await screen.findByText(/Личная регистрация сейчас недоступна/)).toBeInTheDocument();
  expect(screen.queryByRole("link", { name: "Получить личный демо-доступ" })).toBeNull();
  expect(screen.getByRole("link", { name: "Войти в существующий личный аккаунт" })).toHaveAttribute("href", "/login?return_to=/upload");
});
