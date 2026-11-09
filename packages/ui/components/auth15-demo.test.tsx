import React from "react";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { DemoEntry } from "./DemoEntry";
import { DemoCampaignAdmin } from "./DemoCampaignAdmin";
import { demoRequest } from "../lib/demo";
jest.mock("../lib/demo", () => ({ demoRequest: jest.fn() }));
const request = demoRequest as jest.Mock;
beforeEach(() => request.mockReset());
test("entry never reports success on unavailable service and clears busy state", async () => {
  request.mockRejectedValue(new Error("Сервис временно недоступен."));
  render(<DemoEntry />);
  fireEvent.change(screen.getByLabelText("Логин кампании"), {
    target: { value: "forum" },
  });
  fireEvent.change(screen.getByLabelText("Пароль с флаера"), {
    target: { value: "secret" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Войти в демо" }));
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Сервис временно недоступен.",
  );
  expect(
    screen.getByRole("button", { name: "Войти в демо" }),
  ).not.toBeDisabled();
  expect(request).toHaveBeenCalledWith("auth/demo/prepare", "POST");
  expect(request).not.toHaveBeenCalledWith(
    "auth/demo/enter",
    expect.anything(),
    expect.anything(),
  );
});
test("resume uses its own credential endpoint without sending the flyer password", async () => {
  request.mockRejectedValue(new Error("Демо-доступ завершён."));
  render(<DemoEntry />);
  fireEvent.click(
    screen.getByRole("button", { name: "Продолжить свой демо-доступ" }),
  );
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Демо-доступ завершён.",
  );
  expect(request).toHaveBeenCalledWith("auth/demo/resume", "POST");
});
test("admin shows empty state and requires a reason and explicit finite input", async () => {
  request.mockResolvedValue({ campaigns: [] });
  render(<DemoCampaignAdmin />);
  expect(await screen.findByText("Кампаний пока нет.")).toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: "Создать черновик" }),
  ).toBeDisabled();
  expect(screen.getByLabelText("Бюджет кампании, micro-CU")).toHaveValue(null);
  expect(
    screen.getByLabelText("Разрешить собственные данные"),
  ).not.toBeChecked();
});
test("admin handles server refusal without exposing an empty success", async () => {
  request.mockRejectedValue(new Error("Доступ запрещён."));
  render(<DemoCampaignAdmin />);
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Доступ запрещён.",
  );
});
