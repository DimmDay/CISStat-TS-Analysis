import "@testing-library/jest-dom";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { DbConnectionForm } from "./DbConnectionForm";

const uploaded = { dataset_id: "db-test", name: "SQL: audit", rows: 2, columns: 2,
  preview: { head: [["date", "value"], ["2026-01-01", "3"]], tail: [] },
  columns_info: [], quality: null, size_label: "1 KB", parse_warnings: [] };
const reply = (body: unknown, ok = true) => Promise.resolve({ ok, status: ok ? 200 : 422, json: async () => body });
function fillServer() {
  fireEvent.change(screen.getByLabelText("Хост"), { target: { value: "db.example" } });
  fireEvent.change(screen.getByLabelText("База данных"), { target: { value: "audit" } });
  fireEvent.change(screen.getByLabelText("Пользователь"), { target: { value: "reader" } });
  fireEvent.change(screen.getByLabelText("Пароль"), { target: { value: "owned-secret" } });
}
beforeEach(() => { global.fetch = jest.fn(() => reply({ ok: true, server_version: "PostgreSQL test", latency_ms: 12 })) as jest.Mock; });
afterEach(() => jest.restoreAllMocks());

it.each([["postgresql", 5432], ["clickhouse", 8123], ["mysql", 3306], ["mssql", 1433]])("probes canonical %s with default port %s", async (kind, port) => {
  render(<DbConnectionForm onLoaded={jest.fn()} />);
  fireEvent.change(screen.getByLabelText("Тип БД"), { target: { value: kind } });
  fillServer();
  fireEvent.click(screen.getByRole("button", { name: "Тест подключения" }));
  await waitFor(() => expect(screen.getByRole("status")).toBeInTheDocument());
  const body = JSON.parse((fetch as jest.Mock).mock.calls[0][1].body);
  expect(body.connection.db_type).toBe(kind);
  expect(body.connection.port).toBe(port);
});

it("rejects an invalid port and empty SQL before network", () => {
  render(<DbConnectionForm onLoaded={jest.fn()} />); fillServer();
  fireEvent.change(screen.getByLabelText("Порт"), { target: { value: "0" } });
  fireEvent.click(screen.getByRole("button", { name: "Тест подключения" }));
  expect(screen.getByRole("alert")).toHaveTextContent("Порт");
  fireEvent.change(screen.getByLabelText("Порт"), { target: { value: "5432" } });
  fireEvent.change(screen.getByLabelText("SQL-запрос"), { target: { value: "" } });
  fireEvent.click(screen.getByRole("button", { name: "Загрузить из БД" }));
  expect(screen.getByRole("alert")).toHaveTextContent("SQL-запрос");
  expect(fetch).not.toHaveBeenCalled();
});

it("offers all six sources, defaults ports, clears credentials on mode switch", () => {
  render(<DbConnectionForm onLoaded={jest.fn()} />);
  const select = screen.getByLabelText("Тип БД");
  expect(select.querySelectorAll("option")).toHaveLength(6);
  fillServer();
  expect(screen.getByLabelText("Порт")).toHaveValue(5432);
  fireEvent.change(select, { target: { value: "mssql" } });
  expect(screen.getByLabelText("Порт")).toHaveValue(1433);
  expect((screen.getByLabelText("SQL-запрос") as HTMLTextAreaElement).value).toContain("TOP");
  expect(screen.getByLabelText("Пароль")).toHaveValue("");
  fireEvent.change(select, { target: { value: "sqlite" } });
  expect(screen.queryByLabelText("Хост")).toBeNull();
  expect(screen.getByLabelText("Путь к файлу")).toBeInTheDocument();
  fireEvent.change(select, { target: { value: "postgresql" } });
  expect(screen.getByLabelText("Хост")).toHaveValue("");
});

it("200 ok:false is a failed probe and never loads a dataset", async () => {
  global.fetch = jest.fn(() => reply({ ok: false, error: "Access denied" })) as jest.Mock;
  const loaded = jest.fn(); render(<DbConnectionForm onLoaded={loaded} />); fillServer();
  fireEvent.click(screen.getByRole("button", { name: "Тест подключения" }));
  await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("Access denied"));
  expect(loaded).not.toHaveBeenCalled();
  expect(fetch).toHaveBeenCalledWith(expect.stringContaining("/internal/upload/db/test"), expect.objectContaining({ credentials: "include" }));
  const options = (fetch as jest.Mock).mock.calls[0][1];
  expect(JSON.parse(options.body)).toEqual({ connection: { db_type: "postgresql", host: "db.example", port: 5432, database: "audit", user: "reader", password: "owned-secret", ssl: false } });
});

it("shows probe facts, invalidates them on edits, and loads with the same credentials", async () => {
  const loaded = jest.fn(); render(<DbConnectionForm onLoaded={loaded} />); fillServer();
  fireEvent.click(screen.getByRole("button", { name: "Тест подключения" }));
  await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("PostgreSQL test"));
  fireEvent.change(screen.getByLabelText("SQL-запрос"), { target: { value: "SELECT 1 AS value" } });
  (fetch as jest.Mock).mockImplementationOnce(() => reply(uploaded));
  fireEvent.change(screen.getByLabelText("Лимит строк"), { target: { value: "25" } });
  fireEvent.click(screen.getByRole("button", { name: "Загрузить из БД" }));
  await waitFor(() => expect(loaded).toHaveBeenCalledWith(uploaded));
  const args = (fetch as jest.Mock).mock.calls.at(-1);
  expect(args[0]).toContain("/upload/db/load");
  expect(JSON.parse(args[1].body)).toEqual(expect.objectContaining({ sql: "SELECT 1 AS value", row_limit: 25 }));
});

it.each(["sqlite", "duckdb"])("sends only path fields for %s", async (kind) => {
  global.fetch = jest.fn(() => reply(uploaded)) as jest.Mock;
  const loaded = jest.fn(); render(<DbConnectionForm onLoaded={loaded} />);
  fireEvent.change(screen.getByLabelText("Тип БД"), { target: { value: kind } });
  fireEvent.change(screen.getByLabelText("Путь к файлу"), { target: { value: kind === "duckdb" ? "/data/a.csv" : "/data/a.sqlite" } });
  fireEvent.click(screen.getByRole("button", { name: "Загрузить из БД" }));
  await waitFor(() => expect(loaded).toHaveBeenCalled());
  const body = JSON.parse((fetch as jest.Mock).mock.calls[0][1].body);
  expect(body.connection).toEqual({ db_type: kind, path: kind === "duckdb" ? "/data/a.csv" : "/data/a.sqlite" });
  expect(body.row_limit).toBe(1_000_000); // S4: same default as the API.
  if (kind === "duckdb") expect(body.sql).toContain("'/data/a.csv'");
});

it("renders validation/network errors and never echoes the password", async () => {
  global.fetch = jest.fn(() => reply({ detail: [{ msg: "rejected owned-secret" }] }, false)) as jest.Mock;
  render(<DbConnectionForm onLoaded={jest.fn()} />); fillServer();
  fireEvent.click(screen.getByRole("button", { name: "Загрузить из БД" }));
  await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("rejected"));
  expect(screen.getByRole("alert")).not.toHaveTextContent("owned-secret");
  (fetch as jest.Mock).mockRejectedValueOnce(new Error("network"));
  fireEvent.click(screen.getByRole("button", { name: "Тест подключения" }));
  await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent(/соединение|сеть/i));
});

it("blocks duplicate submissions and ignores a response after unmount", async () => {
  let resolve!: (value: unknown) => void;
  global.fetch = jest.fn(() => new Promise(r => { resolve = r; })) as jest.Mock;
  const loaded = jest.fn(); const { unmount } = render(<DbConnectionForm onLoaded={loaded} />); fillServer();
  fireEvent.click(screen.getByRole("button", { name: "Загрузить из БД" }));
  expect(screen.getByLabelText("Тип БД")).toBeDisabled();
  expect(screen.getByRole("button", { name: "Тест подключения" })).toBeDisabled();
  unmount();
  await act(async () => resolve({ ok: true, json: async () => uploaded }));
  expect(loaded).not.toHaveBeenCalled();
  expect((fetch as jest.Mock).mock.calls[0][1].signal.aborted).toBe(true);
});
