// packages/ui/components/DatasetViewEditor.test.tsx
//
// Оракулы generic read-only редактора датасета «Редактор датасета»
// (задача DATASET-VIEW-EDITOR-1, 2026-10-16, проект решения в
// worklog10.md; постановка тимлида: кнопка в Мастерах остановок,
// добавляющих колонки; бокс -- просмотр ВСЕГО датасета по умолчанию
// с удалением (скрытием) ТОЛЬКО добавленных колонок БЕЗ изменения
// входящей глубокой копии датасета).
//
// Контракт:
// (1) дефолт «Весь датасет» применён сразу: при монтировании грузится
//     страница 0 /dataset/rows?offset=0&limit=... + реестр
//     /dataset/derived-columns (два GET на открытие);
// (2) производные колонки -- бейдж «добавлена» + кнопка × в шапке;
//     канонические -- без;
// (3) × скрывает колонку БЕЗ сетевых вызовов (мок-пин: за сессию
//     компонента только 2 исходных GET -- скрытие/возврат локальны,
//     ни один байтовый контракт бэкенда не мутируется);
// (4) скрытые -- чипы с индивидуальной возвратной × + честная строка
//     «Скрыто из просмотра: N» и бейдж «датасет не изменён»;
// (5) «Вернуть все колонки» disabled при пустом скрытии;
// (6) фильтр «Только добавленные колонки» + «Выбрать» -- сетка только
//     из производных; «Весь датасет» возвращает полный состав;
// (7) виртуализация: страницы /dataset/rows догружаются по мере
//     прокрутки, кэш страниц переживает обратную прокрутку;
// (8) пустой реестр -- «Добавленных колонок нет -- датасет в исходном
//     составе» (честное отсутствие, не ноль);
// (9) read-only: в сетке нет input/textarea (ячеечные правки --
//     эксклюзив MANUAL-редакторов, P1 проекта решения);
// (10) aria-label региона «Редактор датасета»;
// (11) ошибка сети -- error-стейт с «Повторить», уже загруженные
//      страницы сохранены.
//
// Корпус дизъюнктен: страницы «метеостанции» manual-meteo-1 (два GET
// page 0/page 1), derived-реестр sv-view-editor-1 (2 производные).

import "@testing-library/jest-dom";
import { render, screen, fireEvent, waitFor, within } from "@testing-library/react";
import { DatasetViewEditor } from "./DatasetViewEditor";

const DERIVED = {
  columns: [
    { column: "temp_c_smoothed", stage: "smoothing", source: "smoothing:ema:temp_c", created_at: "2026-10-16T09:00:00+00:00" },
    { column: "temp_c_missing_flag", stage: "missing", source: "missing_correction:flag:temp_c", created_at: "2026-10-16T08:00:00+00:00" },
  ],
  total: 2,
};

const COLUMNS = ["recorded_at", "temp_c", "humidity", "temp_c_smoothed", "temp_c_missing_flag"];

function rowsPage(offset: number) {
  const base = ["2024-06-01", "10.5", "60", "10.4", "0"];
  return {
    columns: COLUMNS,
    rows: [base.map((v, i) => (i === 0 ? `2024-06-${String(offset + 1).padStart(2, "0")}` : v))],
    offset,
    limit: 200,
    total_rows: 250,
    returned: 1,
    has_more: offset + 1 < 250,
  };
}

function routeFetch() {
  const calls: string[] = [];
  const fn = jest.fn((url: string) => {
    calls.push(String(url));
    if (typeof url === "string" && url.includes("/dataset/derived-columns")) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve(DERIVED) });
    }
    if (typeof url === "string" && url.includes("/dataset/rows")) {
      const offset = Number(new URLSearchParams(url.split("?")[1]).get("offset") ?? 0);
      return Promise.resolve({ ok: true, json: () => Promise.resolve(rowsPage(offset)) });
    }
    return Promise.resolve({ ok: false, status: 404, json: () => Promise.resolve({ detail: "no dataset" }) });
  }) as unknown as jest.Mock & { calls: string[] };
  // Expose call log через замыкание: тесты читают (fn as any).mock.calls.
  void calls;
  return fn;
}

function renderEditor() {
  global.fetch = routeFetch() as unknown as typeof fetch;
  return render(<DatasetViewEditor />);
}

describe("DatasetViewEditor -- generic read-only просмотр датасета (DATASET-VIEW-EDITOR-1)", () => {
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

  it("регион с aria-label «Редактор датасета»", async () => {
    renderEditor();
    expect(screen.getByRole("region", { name: "Редактор датасета" })).toBeInTheDocument();
    await screen.findByText("recorded_at");
  });

  it("дефолт «Весь датасет» применён сразу: открытие грузит страницу 0 /dataset/rows и реестр derived-columns", async () => {
    const fetchMock = routeFetch();
    global.fetch = fetchMock as unknown as typeof fetch;
    render(<DatasetViewEditor />);
    await screen.findByText("recorded_at");
    const calls = (fetchMock as jest.Mock).mock.calls.map((c) => String(c[0]));
    expect(calls.some((u) => u.includes("/dataset/derived-columns"))).toBe(true);
    expect(calls.some((u) => u.includes("/dataset/rows") && u.includes("offset=0"))).toBe(true);
  });

  it("производные колонки несут бейдж «добавлена» и кнопку ×, канонические -- без", async () => {
    renderEditor();
    await screen.findByText("recorded_at");

    const smoothedHeader = screen.getByText("temp_c_smoothed").closest("div")!.parentElement!;
    expect(smoothedHeader.textContent).toContain("добавлена");
    expect(smoothedHeader.querySelector("button")).toBeTruthy();

    const flagHeader = screen.getByText("temp_c_missing_flag").closest("div")!.parentElement!;
    expect(flagHeader.textContent).toContain("добавлена");

    const canonicalHeader = screen.getByText("temp_c").closest("div")!;
    expect(canonicalHeader.textContent).not.toContain("добавлена");
    expect(screen.getAllByRole("button", { name: /Скрыть колонку/ })).toHaveLength(2);
  });

  it("× скрывает колонку БЕЗ сетевых вызовов (за сессию компонента только 2 исходных GET)", async () => {
    const fetchMock = routeFetch();
    global.fetch = fetchMock as unknown as typeof fetch;
    render(<DatasetViewEditor />);
    await screen.findByText("recorded_at");

    const initialCalls = (fetchMock as jest.Mock).mock.calls.length;
    fireEvent.click(screen.getByRole("button", { name: "Скрыть колонку temp_c_smoothed из просмотра" }));

    // Колонка исчезла из СЕТКИ (не из чипа скрытых), чип появился -- без
    // единого нового fetch.
    const grid = screen.getByTestId("view-editor-spacer");
    await waitFor(() => expect(within(grid).queryByText("temp_c_smoothed")).toBeNull());
    expect(within(grid).getByText("temp_c_missing_flag")).toBeInTheDocument();
    expect((fetchMock as jest.Mock).mock.calls.length).toBe(initialCalls);
  });

  it("скрытые -- чипы с индивидуальной возвратной ×, честная строка «Скрыто из просмотра: N» и бейдж «датасет не изменён»", async () => {
    renderEditor();
    await screen.findByText("recorded_at");
    fireEvent.click(screen.getByRole("button", { name: "Скрыть колонку temp_c_smoothed из просмотра" }));

    expect(screen.getByText("Скрыто из просмотра: 1")).toBeInTheDocument();
    expect(screen.getByText("датасет не изменён")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Вернуть колонку temp_c_smoothed в просмотр" })).toBeInTheDocument();
  });

  it("«Вернуть все колонки» disabled при пустом скрытии и возвращает скрытые после клика", async () => {
    renderEditor();
    await screen.findByText("recorded_at");

    const restoreAll = screen.getByRole("button", { name: "Вернуть все колонки" });
    expect(restoreAll).toBeDisabled();

    fireEvent.click(screen.getByRole("button", { name: "Скрыть колонку temp_c_smoothed из просмотра" }));
    fireEvent.click(screen.getByRole("button", { name: "Скрыть колонку temp_c_missing_flag из просмотра" }));
    expect(restoreAll).toBeEnabled();
    expect(screen.getByText("Скрыто из просмотра: 2")).toBeInTheDocument();

    fireEvent.click(restoreAll);
    expect(await screen.findByText("temp_c_smoothed")).toBeInTheDocument();
    expect(screen.queryByText(/Скрыто из просмотра/)).toBeNull();
  });

  it("фильтр «Только добавленные колонки» + «Выбрать» -- сетка только из производных; «Весь датасет» возвращает полный состав", async () => {
    renderEditor();
    await screen.findByText("recorded_at");

    // Взаимоисключающие чекбоксы, дефолт -- «Весь датасет» (применён сразу).
    fireEvent.click(screen.getByRole("checkbox", { name: "Только добавленные колонки" }));
    fireEvent.click(screen.getByRole("button", { name: "Выбрать" }));

    expect(await screen.findByText("temp_c_smoothed")).toBeInTheDocument();
    expect(screen.getByText("temp_c_missing_flag")).toBeInTheDocument();
    expect(screen.queryByText("recorded_at")).toBeNull();
    expect(screen.queryByText("temp_c")).toBeNull();

    fireEvent.click(screen.getByRole("checkbox", { name: "Весь датасет" }));
    fireEvent.click(screen.getByRole("button", { name: "Выбрать" }));
    expect(await screen.findByText("recorded_at")).toBeInTheDocument();
    expect(screen.getByText("temp_c_smoothed")).toBeInTheDocument();
  });

  it("виртуализация: страницы /dataset/rows догружаются по прокрутке и кэшируются (обратная прокрутка не перезапрашивает)", async () => {
    const fetchMock = routeFetch();
    global.fetch = fetchMock as unknown as typeof fetch;
    render(<DatasetViewEditor />);
    const region = screen.getByRole("region", { name: "Редактор датасета" });
    const scroller = region.querySelector('[data-testid="view-editor-scroll"]') as HTMLElement;
    await screen.findByText("2024-06-01");

    // Прокрутка вниз (страница 1 -- строки 200+), затем обратно.
    Object.defineProperty(scroller, "clientHeight", { value: 480, configurable: true });
    Object.defineProperty(scroller, "scrollHeight", { value: 250 * 32, configurable: true });
    Object.defineProperty(scroller, "scrollTop", { value: 200 * 32, configurable: true });
    fireEvent.scroll(scroller);
    await waitFor(() =>
      expect((fetchMock as jest.Mock).mock.calls.some((c) => String(c[0]).includes("offset=200"))).toBe(true),
    );

    const callsAfterDown = (fetchMock as jest.Mock).mock.calls.length;
    Object.defineProperty(scroller, "scrollTop", { value: 0, configurable: true });
    fireEvent.scroll(scroller);
    await screen.findByText("2024-06-01");
    expect((fetchMock as jest.Mock).mock.calls.length).toBe(callsAfterDown);
  });

  it("пустой реестр -- честное «Добавленных колонок нет -- датасет в исходном составе», кнопок × нет", async () => {
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

  it("read-only: в сетке нет input и textarea", async () => {
    renderEditor();
    await screen.findByText("recorded_at");
    const region = screen.getByRole("region", { name: "Редактор датасета" });
    expect(region.querySelector("input[type='text']")).toBeNull();
    expect(region.querySelector("textarea")).toBeNull();
  });

  it("ошибка сети -- error-стейт с «Повторить», уже загруженные страницы сохранены", async () => {
    const calls: string[] = [];
    global.fetch = jest.fn((url: string) => {
      calls.push(String(url));
      if (calls.length === 1 && url.includes("/dataset/rows")) {
        // Первая страница строк загрузилась, реестр упал -- сетка уже видна.
        return Promise.resolve({ ok: true, json: () => Promise.resolve(rowsPage(0)) });
      }
      if (url.includes("/dataset/rows")) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve(rowsPage(0)) });
      }
      return Promise.resolve({ ok: false, status: 500, json: () => Promise.resolve({ detail: "boom" }) });
    }) as unknown as typeof fetch;
    render(<DatasetViewEditor />);

    // Страница 0 загрузилась (кэш сохранён), реестр производных упал в error.
    await screen.findByText("recorded_at");
    const retry = await screen.findByRole("button", { name: "Повторить" });
    expect(screen.getByRole("alert")).toBeInTheDocument();

    // Восстановление -- перечитка без потери уже загруженных строк.
    global.fetch = jest.fn((url: string) => {
      if (url.includes("/dataset/derived-columns")) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve(DERIVED) });
      }
      if (url.includes("/dataset/rows")) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve(rowsPage(0)) });
      }
      return Promise.resolve({ ok: false, status: 404, json: () => Promise.resolve(null) });
    }) as unknown as typeof fetch;
    fireEvent.click(retry);
    expect(await screen.findByText("temp_c_smoothed")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).toBeNull();
  });
});

// ── «Сохранить» -- persist удаления добавленных колонок ─────────────
//
// Дефект-репорт тимлида к DATASET-VIEW-EDITOR-1 (2026-10-16): стратегия 1
// добавляет в датасет 3 колонки, аналитик идёт на следующую остановку,
// стратегия 2 рекомендует удалить одну из добавленных; аналитик удаляет её
// в «Редакторе датасета» (×), но СОХРАНИТЬ не может -- справа от «Вернуть
// все колонки» нет кнопки «Сохранить», и ни один контракт не мутирует.
//
// Контракт сохранения:
// (S1) кнопка «Сохранить» стоит ПРАВЕЕ «Вернуть все колонки» (правый
//      край), disabled при пустом скрытии;
// (S2) скрытые колонки -- очередь удаления: подсказка «Удаление применится
//      кнопкой «Сохранить»»; «Сохранить» отправляет РОВНО ОДИН POST
//      /dataset/derived-columns/delete со списком скрытых имён;
// (S3) успех: скрытие сброшено, чипы/бейдж исчезли, показано «Сохранено:
//      удалено колонок: N», реестр и страница 0 строк перечитаны --
//      удалённая колонка исчезла из сетки (мок отдаёт состав после
//      удаления), «Вернуть все колонки» снова disabled;
// (S4) отказ бэкенда: alert с detail, скрытие СОХРАНЕНО (можно повторить);
// (S5) «Вернуть все колонки» до «Сохранить» отменяет скрытие БЕЗ сети
//      (POST не отправляется);
// (S6) само скрытие по-прежнему без сети -- POST уходит только от
//      «Сохранить».
describe("DatasetViewEditor -- «Сохранить»: persist удаления добавленных колонок (дефект-репорт)", () => {
  let deletedColumns: string[] = [];
  let posts: Array<{ url: string; body: unknown }>;
  let failSave: { status: number; detail: string } | null;

  beforeEach(() => {
    global.ResizeObserver = class ResizeObserver {
      observe() {}
      unobserve() {}
      disconnect() {}
    } as unknown as typeof ResizeObserver;
    deletedColumns = [];
    posts = [];
    failSave = null;
  });

  afterEach(() => {
    jest.restoreAllMocks();
  });

  function statefulFetch() {
    const registryNow = () => ({
      columns: DERIVED.columns.filter((entry) => !deletedColumns.includes(entry.column)),
      total: DERIVED.total - deletedColumns.length,
    });
    const rowsNow = (offset: number) => {
      const base = rowsPage(offset);
      const keep = COLUMNS.filter((name) => !deletedColumns.includes(name));
      return {
        ...base,
        columns: keep,
        rows: base.rows.map((row) => row.filter((_, i) => COLUMNS[i] !== undefined && keep.includes(COLUMNS[i]))),
      };
    };
    return jest.fn((url: string, init?: RequestInit) => {
      const method = (init?.method ?? "GET").toUpperCase();
      if (method === "POST" && url.includes("/dataset/derived-columns/delete")) {
        const body = JSON.parse(String(init?.body ?? "{}")) as { columns?: string[] };
        posts.push({ url: String(url), body });
        if (failSave) {
          return Promise.resolve({ ok: false, status: failSave.status, json: () => Promise.resolve({ detail: failSave.detail }) });
        }
        deletedColumns = [...deletedColumns, ...(body.columns ?? [])];
        return Promise.resolve({
          ok: true,
          json: () =>
            Promise.resolve({
              deleted: body.columns ?? [],
              remaining_total: DERIVED.total - deletedColumns.length,
            }),
        });
      }
      if (url.includes("/dataset/derived-columns")) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve(registryNow()) });
      }
      if (url.includes("/dataset/rows")) {
        const offset = Number(new URLSearchParams(url.split("?")[1]).get("offset") ?? 0);
        return Promise.resolve({ ok: true, json: () => Promise.resolve(rowsNow(offset)) });
      }
      return Promise.resolve({ ok: false, status: 404, json: () => Promise.resolve({ detail: "no dataset" }) });
    }) as unknown as typeof fetch;
  }

  async function renderWithHiddenColumn() {
    global.fetch = statefulFetch();
    render(<DatasetViewEditor />);
    await screen.findByText("recorded_at");
    fireEvent.click(screen.getByRole("button", { name: "Скрыть колонку temp_c_smoothed из просмотра" }));
    expect(await screen.findByText("Скрыто из просмотра: 1")).toBeInTheDocument();
  }

  function topRow() {
    // Верхняя строка бокса -- родитель кнопки «Выбрать».
    return screen.getByRole("button", { name: "Выбрать" }).parentElement as HTMLElement;
  }

  it("S1: «Сохранить» стоит правее «Вернуть все колонки», disabled при пустом скрытии", async () => {
    await renderWithHiddenColumn();

    const buttons = Array.from(topRow().querySelectorAll("button")).map((b) => b.textContent?.trim());
    const restoreIdx = buttons.indexOf("Вернуть все колонки");
    const saveIdx = buttons.findIndex((name) => name?.startsWith("Сохранить"));
    expect(restoreIdx).toBeGreaterThan(-1);
    expect(saveIdx).toBeGreaterThan(-1);
    expect(saveIdx).toBeGreaterThan(restoreIdx);

    // Пустое скрытие -- «Сохранить» заблокирован.
    fireEvent.click(screen.getByRole("button", { name: "Вернуть колонку temp_c_smoothed в просмотр" }));
    expect(screen.getByRole("button", { name: "Сохранить" })).toBeDisabled();
  });

  it("S2+S3: клик «Сохранить» -- один POST со списком скрытых; успех: чипы сброшены, «Сохранено: удалено колонок: 1», реестр и страница 0 перечитаны, колонки нет в сетке", async () => {
    await renderWithHiddenColumn();
    expect(screen.getByText("Удаление применится кнопкой «Сохранить»")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Сохранить" }));

    // РОВНО ОДИН POST с телом-списком скрытых.
    await waitFor(() => expect(posts).toHaveLength(1));
    expect(posts[0].url).toContain("/dataset/derived-columns/delete");
    expect(posts[0].body).toEqual({ columns: ["temp_c_smoothed"] });

    // Скрытие сброшено, честный статус сохранения, чипов нет.
    expect(await screen.findByText("Сохранено: удалено колонок: 1")).toBeInTheDocument();
    expect(screen.queryByText(/Скрыто из просмотра/)).toBeNull();
    expect(screen.queryByTestId("view-editor-unchanged-badge")).toBeNull();

    // Реестр и страница 0 перечитаны (мок отдаёт состав ПОСЛЕ удаления).
    await waitFor(() => {
      const grid = screen.getByTestId("view-editor-spacer");
      expect(within(grid).queryByText("temp_c_smoothed")).toBeNull();
      expect(within(grid).getByText("temp_c_missing_flag")).toBeInTheDocument();
    });
    expect(screen.getByRole("button", { name: "Сохранить" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Вернуть все колонки" })).toBeDisabled();

    const fetchMock = global.fetch as unknown as jest.Mock;
    const calls = fetchMock.mock.calls.map((c) => String(c[0]));
    expect(calls.filter((u) => u.includes("/dataset/derived-columns")).length).toBeGreaterThanOrEqual(2);
    expect(calls.filter((u) => u.includes("/dataset/rows") && u.includes("offset=0")).length).toBeGreaterThanOrEqual(2);
  });

  it("S4: отказ бэкенда -- alert с detail, скрытие сохранено, повтор возможен", async () => {
    await renderWithHiddenColumn();
    failSave = { status: 422, detail: "Удалять можно только добавленные колонки" };

    fireEvent.click(screen.getByRole("button", { name: "Сохранить" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Удалять можно только добавленные колонки");
    expect(screen.getByText("Скрыто из просмотра: 1")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Сохранить" })).toBeEnabled();

    // Повтор после восстановления сервиса -- успех.
    failSave = null;
    fireEvent.click(screen.getByRole("button", { name: "Сохранить" }));
    expect(await screen.findByText("Сохранено: удалено колонок: 1")).toBeInTheDocument();
  });

  it("S5+S6: «Вернуть все колонки» отменяет скрытие без сети; POST уходит только от «Сохранить»", async () => {
    await renderWithHiddenColumn();
    expect(posts).toHaveLength(0);

    fireEvent.click(screen.getByRole("button", { name: "Вернуть все колонки" }));
    expect(await screen.findByText("temp_c_smoothed")).toBeInTheDocument();
    expect(screen.queryByText(/Скрыто из просмотра/)).toBeNull();
    expect(posts).toHaveLength(0);
  });
});
