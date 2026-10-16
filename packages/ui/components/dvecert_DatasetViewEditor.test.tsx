// packages/ui/components/dvecert_DatasetViewEditor.test.tsx
//
// НЕЗАВИСИМЫЕ оракулы сертификации DATASET-VIEW-EDITOR-1-CERT (2026-10-16):
// свои данные сертификатора, корпус ДИЗЪЮНКТЕН repo-тестам задачи
// (DatasetViewEditor.test.tsx -- «метеостанция»; здесь -- «порт-звонки»).
//
// Префикс dvecert_ (в отличие от repo-сюит) -- по прецеденту
// PROGR-25-B-CERT (progr25bcert_*): свои оракулы не копируют repo-тесты,
// ключевые проверки несут СОБСТВЕННЫЕ дискриминаторы:
//   V2 -- реестр несёт ghost-колонку, которой НЕТ в rows.columns:
//         фронт не имеет права выдумывать колонку из реестра
//         (аналог серверного «реестр ∩ кадр» на стороне отображения);
//   V6 -- порядок очереди удаления в теле POST (порядок скрытия);
//   V7 -- стейтфул-мок: состав реестра/строк ПОСЛЕ удаления + УМЕНЬШЕННЫЙ
//         total_rows -- сетка обязана показать перечитанный состав;
//   V9 -- отказ сети (fetch reject) -- не путать с HTTP-отказом V8.
//
// Запуск: npx jest dvecert_DatasetViewEditor (из корня монорепо).
// Правила AGENTS.md: артефакт сертификации, commit/push НЕ выполняются.

import "@testing-library/jest-dom";
import { render, screen, fireEvent, waitFor, within } from "@testing-library/react";
import { DatasetViewEditor } from "./DatasetViewEditor";

// ── СВОЙ корпус: «порт-звонки» (port_calls_2023.csv) ─────────────────
const DERIVED_FULL = {
  columns: [
    { column: "calls_ma3", stage: "smoothing", source: "smoothing:ma:calls", created_at: "2026-10-16T10:00:00+00:00" },
    { column: "calls_outlier_flag", stage: "outliers", source: "outlier_correction:flag:calls", created_at: "2026-10-16T11:00:00+00:00" },
    { column: "calls_ghost", stage: "ghost", source: "ghost:demo", created_at: "2026-10-16T12:00:00+00:00" },
  ],
  total: 3,
};

const COLUMNS = ["month", "calls", "cargo_kt", "calls_ma3", "calls_outlier_flag"];

function rowsPage(offset: number) {
  const base = ["2023-03-01", "12", "305.5", "11.8", "0"];
  return {
    columns: COLUMNS,
    rows: [base.map((v, i) => (i === 0 ? `2023-03-${String(offset + 1).padStart(2, "0")}` : v))],
    offset,
    limit: 200,
    total_rows: 6,
    returned: 1,
    has_more: offset + 1 < 6,
  };
}

function simpleFetch() {
  return jest.fn((url: string) => {
    if (typeof url === "string" && url.includes("/dataset/derived-columns")) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve(DERIVED_FULL) });
    }
    if (typeof url === "string" && url.includes("/dataset/rows")) {
      const offset = Number(new URLSearchParams(url.split("?")[1]).get("offset") ?? 0);
      return Promise.resolve({ ok: true, json: () => Promise.resolve(rowsPage(offset)) });
    }
    return Promise.resolve({ ok: false, status: 404, json: () => Promise.resolve({ detail: "no dataset" }) });
  }) as unknown as typeof fetch;
}

function renderEditor() {
  global.fetch = simpleFetch();
  return render(<DatasetViewEditor />);
}

describe("dvecert: DatasetViewEditor -- свои оракулы сертификации («порт-звонки»)", () => {
  beforeEach(() => {
    global.ResizeObserver = class ResizeObserver {
      observe() {}
      unobserve() {}
      disconnect() {}
    } as unknown as typeof ResizeObserver;
  });

  afterEach(() => {
    jest.restoreAllMocks();
  });

  it("CERT-V1 (guard): дефолт «Весь датасет» -- открытие делает ровно 2 исходных GET (реестр + страница 0 строк)", async () => {
    const mock = simpleFetch() as unknown as jest.Mock;
    global.fetch = mock as unknown as typeof fetch;
    render(<DatasetViewEditor />);
    await screen.findByText("month");
    const calls = mock.mock.calls.map((c) => String(c[0]));
    expect(calls.some((u) => u.includes("/dataset/derived-columns"))).toBe(true);
    expect(calls.some((u) => u.includes("/dataset/rows") && u.includes("offset=0"))).toBe(true);
    expect(screen.getByRole("region", { name: "Редактор датасета" })).toBeInTheDocument();
  });

  it("CERT-V2: ghost-колонка реестра, которой НЕТ в rows.columns, не рендерится (фронт не выдумывает колонки из реестра: реестр ∩ кадр на стороне отображения)", async () => {
    renderEditor();
    await screen.findByText("month");
    // В сетке -- только фактические колонки кадра; ghost -- нигде.
    expect(screen.queryByText("calls_ghost")).toBeNull();
    // Бейджи/×-кнопки -- только у пересечения реестра с кадром (2 derived).
    expect(screen.getAllByText("добавлена")).toHaveLength(2);
    expect(screen.getAllByRole("button", { name: /Скрыть колонку/ })).toHaveLength(2);
  });

  it("CERT-V3: бейдж «добавлена» и title «stage · source» только у производных; канонические -- нейтральны", async () => {
    renderEditor();
    await screen.findByText("month");
    const ma3 = screen.getByText("calls_ma3").closest("div")!;
    expect(ma3.textContent).toContain("добавлена");
    expect(ma3.getAttribute("title")).toContain("smoothing");
    expect(ma3.getAttribute("title")).toContain("smoothing:ma:calls");
    const canonical = screen.getByText("cargo_kt").closest("div")!;
    expect(canonical.textContent).not.toContain("добавлена");
    expect(screen.getAllByRole("button", { name: /Скрыть колонку/ })).toHaveLength(2);
  });

  it("CERT-V4: × скрывает колонку БЕЗ сети; чип + счётчик + бейдж «датасет не изменён» + подсказка про «Сохранить»", async () => {
    const mock = simpleFetch() as unknown as jest.Mock;
    global.fetch = mock as unknown as typeof fetch;
    render(<DatasetViewEditor />);
    await screen.findByText("month");

    const before = mock.mock.calls.length;
    fireEvent.click(screen.getByRole("button", { name: "Скрыть колонку calls_ma3 из просмотра" }));

    const grid = screen.getByTestId("view-editor-spacer");
    await waitFor(() => expect(within(grid).queryByText("calls_ma3")).toBeNull());
    expect(within(grid).getByText("calls_outlier_flag")).toBeInTheDocument();
    expect(mock.mock.calls.length).toBe(before); // ноль новых fetch
    expect(screen.getByText("Скрыто из просмотра: 1")).toBeInTheDocument();
    expect(screen.getByTestId("view-editor-unchanged-badge")).toBeInTheDocument();
    expect(screen.getByText("Удаление применится кнопкой «Сохранить»")).toBeInTheDocument();
  });

  it("CERT-V5: возврат по ×-чипа возвращает колонку в сетку БЕЗ сети", async () => {
    const mock = simpleFetch() as unknown as jest.Mock;
    global.fetch = mock as unknown as typeof fetch;
    render(<DatasetViewEditor />);
    await screen.findByText("month");
    fireEvent.click(screen.getByRole("button", { name: "Скрыть колонку calls_outlier_flag из просмотра" }));
    expect(await screen.findByText("Скрыто из просмотра: 1")).toBeInTheDocument();

    const before = mock.mock.calls.length;
    fireEvent.click(screen.getByRole("button", { name: "Вернуть колонку calls_outlier_flag в просмотр" }));
    expect(await screen.findByText("calls_outlier_flag")).toBeInTheDocument();
    expect(screen.queryByText(/Скрыто из просмотра/)).toBeNull();
    expect(mock.mock.calls.length).toBe(before); // ноль новых fetch
  });

  it("CERT-V6: очередь из ДВУХ скрытых -- «Сохранить» отправляет РОВНО ОДИН POST с телом {columns} В ПОРЯДКЕ скрытия", async () => {
    const posts: Array<{ url: string; body: unknown }> = [];
    global.fetch = jest.fn((url: string, init?: RequestInit) => {
      const method = (init?.method ?? "GET").toUpperCase();
      if (method === "POST" && url.includes("/dataset/derived-columns/delete")) {
        posts.push({ url: String(url), body: JSON.parse(String(init?.body ?? "{}")) });
        return Promise.resolve({ ok: true, json: () => Promise.resolve({ deleted: [], remaining_total: 3 }) });
      }
      if (typeof url === "string" && url.includes("/dataset/derived-columns")) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve(DERIVED_FULL) });
      }
      if (typeof url === "string" && url.includes("/dataset/rows")) {
        const offset = Number(new URLSearchParams(url.split("?")[1]).get("offset") ?? 0);
        return Promise.resolve({ ok: true, json: () => Promise.resolve(rowsPage(offset)) });
      }
      return Promise.resolve({ ok: false, status: 404, json: () => Promise.resolve({ detail: "no dataset" }) });
    }) as unknown as typeof fetch;
    render(<DatasetViewEditor />);
    await screen.findByText("month");

    // Скрываем в НАМЕРЕННО неалфавитном порядке: flag, потом ma3.
    fireEvent.click(screen.getByRole("button", { name: "Скрыть колонку calls_outlier_flag из просмотра" }));
    fireEvent.click(screen.getByRole("button", { name: "Скрыть колонку calls_ma3 из просмотра" }));
    expect(screen.getByText("Скрыто из просмотра: 2")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Сохранить" }));
    await waitFor(() => expect(posts).toHaveLength(1));
    expect(posts[0].url).toContain("/dataset/derived-columns/delete");
    expect(posts[0].body).toEqual({ columns: ["calls_outlier_flag", "calls_ma3"] });
  });

  it("CERT-V7: успех -- стейтфул-мок отдаёт состав ПОСЛЕ удаления (и меньший total реестра): честный статус, чипов нет, обе кнопки disabled, реестр и строки перечитаны", async () => {
    const deleted: string[] = [];
    const posts: string[] = [];
    global.fetch = jest.fn((url: string, init?: RequestInit) => {
      const method = (init?.method ?? "GET").toUpperCase();
      if (method === "POST" && url.includes("/dataset/derived-columns/delete")) {
        posts.push(String(url));
        deleted.push(...(JSON.parse(String(init?.body ?? "{}")).columns ?? []));
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({ deleted: [...(JSON.parse(String(init?.body ?? "{}")).columns ?? [])], remaining_total: 1 }),
        });
      }
      if (typeof url === "string" && url.includes("/dataset/derived-columns")) {
        const now = DERIVED_FULL.columns.filter((e) => !deleted.includes(e.column));
        return Promise.resolve({ ok: true, json: () => Promise.resolve({ columns: now, total: now.length }) });
      }
      if (typeof url === "string" && url.includes("/dataset/rows")) {
        const offset = Number(new URLSearchParams(url.split("?")[1]).get("offset") ?? 0);
        const page = rowsPage(offset);
        const keep = COLUMNS.filter((name) => !deleted.includes(name));
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({ ...page, columns: keep, rows: page.rows.map((r) => r.filter((_, i) => keep.includes(COLUMNS[i]))) }),
        });
      }
      return Promise.resolve({ ok: false, status: 404, json: () => Promise.resolve({ detail: "no dataset" }) });
    }) as unknown as typeof fetch;
    render(<DatasetViewEditor />);
    await screen.findByText("month");

    fireEvent.click(screen.getByRole("button", { name: "Скрыть колонку calls_ma3 из просмотра" }));
    fireEvent.click(screen.getByRole("button", { name: "Скрыть колонку calls_outlier_flag из просмотра" }));
    fireEvent.click(screen.getByRole("button", { name: "Сохранить" }));

    expect(await screen.findByText("Сохранено: удалено колонок: 2")).toBeInTheDocument();
    expect(screen.queryByText(/Скрыто из просмотра/)).toBeNull();
    expect(screen.queryByTestId("view-editor-unchanged-badge")).toBeNull();

    // Сетка -- перечитанный состав ПОСЛЕ удаления (стейтфул-мок).
    await waitFor(() => {
      const grid = screen.getByTestId("view-editor-spacer");
      expect(within(grid).queryByText("calls_ma3")).toBeNull();
      expect(within(grid).queryByText("calls_outlier_flag")).toBeNull();
      expect(within(grid).getByText("month")).toBeInTheDocument();
    });
    expect(screen.getByRole("button", { name: "Сохранить" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Вернуть все колонки" })).toBeDisabled();

    // Перечитка: как минимум второй GET реестра и второй GET страницы 0.
    const mock = global.fetch as unknown as jest.Mock;
    const calls = mock.mock.calls.map((c) => String(c[0]));
    expect(calls.filter((u) => u.includes("/dataset/derived-columns")).length).toBeGreaterThanOrEqual(2);
    expect(calls.filter((u) => u.includes("/dataset/rows") && u.includes("offset=0")).length).toBeGreaterThanOrEqual(2);
    expect(posts).toHaveLength(1);
  });

  it("CERT-V8: HTTP-отказ бэкенда (422) -- alert с detail, скрытие СОХРАНЕНО, повтор успешен", async () => {
    let fail = true;
    const deleted: string[] = [];
    global.fetch = jest.fn((url: string, init?: RequestInit) => {
      const method = (init?.method ?? "GET").toUpperCase();
      if (method === "POST" && url.includes("/dataset/derived-columns/delete")) {
        if (fail) {
          return Promise.resolve({ ok: false, status: 422, json: () => Promise.resolve({ detail: "Удалять можно только добавленные колонки (исходные не удаляются): calls_ma3" }) });
        }
        deleted.push(...(JSON.parse(String(init?.body ?? "{}")).columns ?? []));
        return Promise.resolve({ ok: true, json: () => Promise.resolve({ deleted, remaining_total: 1 }) });
      }
      if (typeof url === "string" && url.includes("/dataset/derived-columns")) {
        const now = DERIVED_FULL.columns.filter((e) => !deleted.includes(e.column));
        return Promise.resolve({ ok: true, json: () => Promise.resolve({ columns: now, total: now.length }) });
      }
      if (typeof url === "string" && url.includes("/dataset/rows")) {
        const offset = Number(new URLSearchParams(url.split("?")[1]).get("offset") ?? 0);
        return Promise.resolve({ ok: true, json: () => Promise.resolve(rowsPage(offset)) });
      }
      return Promise.resolve({ ok: false, status: 404, json: () => Promise.resolve({ detail: "no dataset" }) });
    }) as unknown as typeof fetch;
    render(<DatasetViewEditor />);
    await screen.findByText("month");
    fireEvent.click(screen.getByRole("button", { name: "Скрыть колонку calls_ma3 из просмотра" }));
    expect(await screen.findByText("Скрыто из просмотра: 1")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Сохранить" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Удалять можно только добавленные колонки");
    expect(screen.getByText("Скрыто из просмотра: 1")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Сохранить" })).toBeEnabled();

    fail = false;
    fireEvent.click(screen.getByRole("button", { name: "Сохранить" }));
    expect(await screen.findByText("Сохранено: удалено колонок: 1")).toBeInTheDocument();
  });

  it("CERT-V9: сетевой сбой POST (fetch reject) -- честная ошибка, скрытие сохранено (не путать с HTTP-отказом)", async () => {
    let rejectPost = true;
    global.fetch = jest.fn((url: string, init?: RequestInit) => {
      const method = (init?.method ?? "GET").toUpperCase();
      if (method === "POST" && url.includes("/dataset/derived-columns/delete")) {
        if (rejectPost) return Promise.reject(new Error("network down"));
        return Promise.resolve({ ok: true, json: () => Promise.resolve({ deleted: ["calls_ma3"], remaining_total: 2 }) });
      }
      if (typeof url === "string" && url.includes("/dataset/derived-columns")) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve(DERIVED_FULL) });
      }
      if (typeof url === "string" && url.includes("/dataset/rows")) {
        const offset = Number(new URLSearchParams(url.split("?")[1]).get("offset") ?? 0);
        return Promise.resolve({ ok: true, json: () => Promise.resolve(rowsPage(offset)) });
      }
      return Promise.resolve({ ok: false, status: 404, json: () => Promise.resolve({ detail: "no dataset" }) });
    }) as unknown as typeof fetch;
    render(<DatasetViewEditor />);
    await screen.findByText("month");
    fireEvent.click(screen.getByRole("button", { name: "Скрыть колонку calls_ma3 из просмотра" }));
    expect(await screen.findByText("Скрыто из просмотра: 1")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Сохранить" }));
    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(screen.getByText("Скрыто из просмотра: 1")).toBeInTheDocument();

    rejectPost = false;
    fireEvent.click(screen.getByRole("button", { name: "Сохранить" }));
    expect(await screen.findByText("Сохранено: удалено колонок: 1")).toBeInTheDocument();
  });

  it("CERT-V10: «Вернуть все колонки» ДО сохранения -- полная отмена очереди, POST не отправляется", async () => {
    const posts: string[] = [];
    global.fetch = jest.fn((url: string, init?: RequestInit) => {
      const method = (init?.method ?? "GET").toUpperCase();
      if (method === "POST" && url.includes("/dataset/derived-columns/delete")) {
        posts.push(String(url));
        return Promise.resolve({ ok: true, json: () => Promise.resolve({ deleted: [], remaining_total: 3 }) });
      }
      if (typeof url === "string" && url.includes("/dataset/derived-columns")) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve(DERIVED_FULL) });
      }
      if (typeof url === "string" && url.includes("/dataset/rows")) {
        const offset = Number(new URLSearchParams(url.split("?")[1]).get("offset") ?? 0);
        return Promise.resolve({ ok: true, json: () => Promise.resolve(rowsPage(offset)) });
      }
      return Promise.resolve({ ok: false, status: 404, json: () => Promise.resolve({ detail: "no dataset" }) });
    }) as unknown as typeof fetch;
    render(<DatasetViewEditor />);
    await screen.findByText("month");
    fireEvent.click(screen.getByRole("button", { name: "Скрыть колонку calls_ma3 из просмотра" }));
    fireEvent.click(screen.getByRole("button", { name: "Скрыть колонку calls_outlier_flag из просмотра" }));
    expect(screen.getByText("Скрыто из просмотра: 2")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Вернуть все колонки" }));
    expect(await screen.findByText("calls_ma3")).toBeInTheDocument();
    expect(screen.queryByText(/Скрыто из просмотра/)).toBeNull();
    expect(posts).toHaveLength(0);
  });

  it("CERT-V11 (guard): пустой реестр -- честная плашка и ноль кнопок скрытия", async () => {
    global.fetch = jest.fn((url: string) => {
      if (url.includes("/dataset/derived-columns")) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve({ columns: [], total: 0 }) });
      }
      if (url.includes("/dataset/rows")) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve(rowsPage(0)) });
      }
      return Promise.resolve({ ok: false, status: 404, json: () => Promise.resolve(null) });
    }) as unknown as typeof fetch;
    render(<DatasetViewEditor />);
    expect(await screen.findByText("Добавленных колонок нет — датасет в исходном составе")).toBeInTheDocument();
    expect(screen.queryAllByRole("button", { name: /Скрыть колонку/ })).toHaveLength(0);
  });

  it("CERT-V12: read-only сетка -- ячеек input/textarea нет; чекбоксы только в строке фильтра (2 шт.)", async () => {
    renderEditor();
    await screen.findByText("month");
    const region = screen.getByRole("region", { name: "Редактор датасета" });
    expect(region.querySelector("input[type='text']")).toBeNull();
    expect(region.querySelector("textarea")).toBeNull();
    expect(region.querySelectorAll("input[type='checkbox']")).toHaveLength(2);
  });
});
