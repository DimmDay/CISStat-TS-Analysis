// packages/ui/components/NavigatorSourceFileDbPreview.test.tsx
//
// Тесты статичной блок-схемы для окна «Обзор» пункта «Источник: файл или
// БД» (id="source") секции «Этапы модуля» остановки «Загрузка» на странице
// Навигатор (Task NAVDET-5).
//
// Контракт:
//   - Визуализация — статичная информационная блок-схема источника данных:
//     переключатель «Файл / База данных (SQL)», файловая дорожка
//     (drag-and-drop → POST /v1/internal/upload → read_uploaded_file →
//     DataFrame), дорожка БД (форма PostgreSQL/ClickHouse, тест
//     подключения, pd.read_sql / query_df), общий результат
//     (датасет в сессии), ошибки обеих дорожек.
//   - Схема основана на РЕАЛЬНОЙ логике:
//       • packages/ui/components/TsAnalysisUpload.tsx (радио «Файл …» /
//         «База данных (SQL)», dropzone, 4 демо-датасета через doUpload)
//       • app/data/file_loader.py::init_db_connection (PostgreSQL —
//         SQLAlchemy + SELECT 1; ClickHouse — clickhouse_connect + ping;
//         таймауты connect 10s / statement-query 60s; ConnectionError)
//       • app.py (форма подключения: Тип БД, Host, Port 5432/8123,
//         Database, User, Password, SQL Query с LIMIT; pd.read_sql /
//         query_df; robust_datetime_detector; drop_service_columns)
//       • apps/api/upload_common.py::handle_upload (UploadResponse →
//         SessionStore)
//   - Отображается ПРИ ЛЮБЫХ УСЛОВИЯХ — НЕ зависит от useAppShell,
//     activeDataset, fetch, сети, сессии.
//
// Архитектурно — родственник NavigatorFormatsVolumePreview
// (статичная Tailwind/CSS-блок-схема, role="img" + aria-label).

import React from "react";
import "@testing-library/jest-dom";
import { render, screen } from "@testing-library/react";
import { NavigatorSourceFileDbPreview } from "./NavigatorSourceFileDbPreview";

describe("NavigatorSourceFileDbPreview — rendering", () => {
  it("renders without AppShellProvider (no session dependency)", () => {
    // Если компонент попытается вызвать useAppShell() — упадёт.
    // Не оборачиваем в провайдер намеренно.
    const { container } = render(<NavigatorSourceFileDbPreview />);
    expect(container.firstChild).not.toBeNull();
  });

  it("renders the section heading «Источник: файл или БД»", () => {
    render(<NavigatorSourceFileDbPreview />);
    expect(
      screen.getByRole("heading", { level: 3, name: /источник: файл или бд/i })
    ).toBeInTheDocument();
  });

  it("renders both source options of the Upload page radio switch", () => {
    render(<NavigatorSourceFileDbPreview />);
    // Точные подписи радио-переключателя из TsAnalysisUpload.tsx.
    expect(screen.getByText(/Файл \.xlsx, \.xls, \.csv, \.json/)).toBeInTheDocument();
    expect(screen.getByText(/База данных \(SQL\)/)).toBeInTheDocument();
  });

  it("renders drag-and-drop as the file input method (single file)", () => {
    render(<NavigatorSourceFileDbPreview />);
    expect(screen.getByText(/drag-and-drop/i)).toBeInTheDocument();
  });

  it("renders all 4 accepted formats in the file lane (.csv .xls .xlsx .json)", () => {
    render(<NavigatorSourceFileDbPreview />);
    // Каждый формат — отдельный узел (бейдж): точные совпадения,
    // .xls не матчится с .xlsx.
    expect(screen.getByText(".csv")).toBeInTheDocument();
    expect(screen.getByText(".xls")).toBeInTheDocument();
    expect(screen.getByText(".xlsx")).toBeInTheDocument();
    expect(screen.getByText(".json")).toBeInTheDocument();
  });

  it("renders the file upload endpoint POST /v1/internal/upload", () => {
    render(<NavigatorSourceFileDbPreview />);
    // Реальный бэкенд-эндпоинт приёма файла (шапка + файловая дорожка).
    expect(screen.getAllByText(/\/v1\/internal\/upload/i).length).toBeGreaterThanOrEqual(1);
  });

  it("renders the read_uploaded_file step of the file lane", () => {
    render(<NavigatorSourceFileDbPreview />);
    // file_loader.py::read_uploaded_file — чтение по расширению.
    expect(screen.getByText(/read_uploaded_file/i)).toBeInTheDocument();
  });

  it("renders 4 demo datasets going through the same file pipeline", () => {
    render(<NavigatorSourceFileDbPreview />);
    // TsAnalysisUpload.tsx: демо-датасеты идут через ТОТ ЖЕ doUpload.
    expect(screen.getByText(/демо-датасет/i)).toBeInTheDocument();
  });

  it("renders both supported DB types (PostgreSQL / ClickHouse)", () => {
    render(<NavigatorSourceFileDbPreview />);
    // init_db_connection поддерживает ровно два типа БД.
    expect(screen.getByText("PostgreSQL")).toBeInTheDocument();
    expect(screen.getByText("ClickHouse")).toBeInTheDocument();
  });

  it("renders the default ports 5432 / 8123", () => {
    render(<NavigatorSourceFileDbPreview />);
    // app.py: default_port = 5432 (PostgreSQL) / 8123 (ClickHouse).
    expect(screen.getByText(/5432/)).toBeInTheDocument();
    expect(screen.getByText(/8123/)).toBeInTheDocument();
  });

  it("renders the DB connection form fields (Host, Database, User, Password)", () => {
    render(<NavigatorSourceFileDbPreview />);
    // Поля формы подключения из app.py (expander «Настройки подключения»).
    expect(screen.getByText(/^Host$/)).toBeInTheDocument();
    expect(screen.getByText(/^Database$/)).toBeInTheDocument();
    expect(screen.getByText(/^User$/)).toBeInTheDocument();
    expect(screen.getByText(/^Password$/)).toBeInTheDocument();
  });

  it("renders the SQL query step with the LIMIT recommendation", () => {
    render(<NavigatorSourceFileDbPreview />);
    // app.py: дефолтный запрос «SELECT * FROM your_table LIMIT 1000»,
    // help-текст «Рекомендуется использовать LIMIT для тестов.»
    // LIMIT встречается минимум в узле запроса — getAllByText.
    expect(screen.getByText(/SELECT \* FROM your_table LIMIT 1000/)).toBeInTheDocument();
    expect(screen.getAllByText(/LIMIT/i).length).toBeGreaterThanOrEqual(1);
  });

  it("renders the connection test step (SELECT 1 / ping)", () => {
    render(<NavigatorSourceFileDbPreview />);
    // init_db_connection: PostgreSQL → engine.connect() + SELECT 1;
    // ClickHouse → client.ping().
    expect(screen.getByText(/SELECT 1/)).toBeInTheDocument();
    expect(screen.getByText(/ping/i)).toBeInTheDocument();
  });

  it("renders the DB data loading methods (pd.read_sql / query_df)", () => {
    render(<NavigatorSourceFileDbPreview />);
    // app.py: PostgreSQL → pd.read_sql(query, conn_obj);
    // ClickHouse → conn_obj.query_df(query).
    expect(screen.getByText(/read_sql/i)).toBeInTheDocument();
    expect(screen.getByText(/query_df/i)).toBeInTheDocument();
  });

  it("renders the connection timeouts (connect 10s, statement/query 60s)", () => {
    render(<NavigatorSourceFileDbPreview />);
    // file_loader.py: connect_timeout 10; statement_timeout 60000 (PG) /
    // send_receive_timeout 60 (CH).
    expect(screen.getByText(/10 с|10s|10 сек/i)).toBeInTheDocument();
    expect(screen.getByText(/60 с|60s|60 сек/i)).toBeInTheDocument();
  });

  it("renders the DB post-processing steps (date detection, service columns cleanup)", () => {
    render(<NavigatorSourceFileDbPreview />);
    // app.py: robust_datetime_detector(df_db) + drop_service_columns(df_db).
    expect(screen.getByText(/robust_datetime_detector/i)).toBeInTheDocument();
    expect(screen.getByText(/drop_service_columns/i)).toBeInTheDocument();
  });

  it("renders the common result block: dataset lands in the session", () => {
    render(<NavigatorSourceFileDbPreview />);
    // Файловый путь: UploadResponse → SessionStore;
    // БД-путь: датасет в сессии (session_state.df / SessionStore).
    expect(screen.getByText(/UploadResponse/i)).toBeInTheDocument();
    expect(screen.getByText(/SessionStore/i)).toBeInTheDocument();
  });

  it("renders error messages of both lanes", () => {
    render(<NavigatorSourceFileDbPreview />);
    // Файл (dropzone + read_uploaded_file):
    expect(screen.getByText(/Файл слишком большой/i)).toBeInTheDocument();
    expect(screen.getByText(/Неподдерживаемый формат/i)).toBeInTheDocument();
    // БД (init_db_connection / app.py):
    expect(screen.getByText(/Не удалось подключиться/i)).toBeInTheDocument();
    expect(screen.getByText(/psycopg2-binary/i)).toBeInTheDocument();
    expect(screen.getByText(/clickhouse-connect/i)).toBeInTheDocument();
    expect(screen.getByText(/Введите SQL-запрос/i)).toBeInTheDocument();
  });

  it("renders the honest status note: DB form on the Upload page is a placeholder", () => {
    render(<NavigatorSourceFileDbPreview />);
    // TsAnalysisUpload.tsx: «(форма подключения к БД — заглушка)».
    // Честный статус функционала — часть исчерпывающей информации.
    expect(screen.getByText(/заглушка/i)).toBeInTheDocument();
  });

  it("renders without loading/empty state — always shows infographic", () => {
    const { container } = render(<NavigatorSourceFileDbPreview />);
    expect(screen.queryByText(/загрузка\.\.\./i)).toBeNull();
    expect(screen.queryByText(/нет данных/i)).toBeNull();
    expect(container.firstChild).not.toBeNull();
  });

  it("does not make any network call (no fetch, no XMLHttpRequest)", () => {
    const originalFetch = global.fetch;
    const originalXHR = global.XMLHttpRequest;
    let fetchCalled = false;
    let xhrCreated = false;
    global.fetch = (() => {
      fetchCalled = true;
      throw new Error("NavigatorSourceFileDbPreview must not call fetch");
    }) as unknown as typeof fetch;
    // @ts-expect-error — intentionally stub XHR
    global.XMLHttpRequest = function () {
      xhrCreated = true;
      throw new Error("NavigatorSourceFileDbPreview must not create XHR");
    };

    try {
      render(<NavigatorSourceFileDbPreview />);
      expect(fetchCalled).toBe(false);
      expect(xhrCreated).toBe(false);
    } finally {
      global.fetch = originalFetch;
      global.XMLHttpRequest = originalXHR;
    }
  });

  it("renders deterministically (no random content between renders)", () => {
    const { container: c1, rerender: r1 } = render(<NavigatorSourceFileDbPreview />);
    const text1 = c1.textContent;
    r1(<NavigatorSourceFileDbPreview />);
    const text2 = c1.textContent;
    expect(text2).toBe(text1);
  });

  it("renders arrows/indicators of flow (block-scheme, not flat list)", () => {
    render(<NavigatorSourceFileDbPreview />);
    const arrows = document.querySelectorAll(
      '[aria-label*="chevron" i], [aria-label*="arrow" i]'
    );
    expect(arrows.length).toBeGreaterThanOrEqual(1);
  });

  it("has role=img with informative aria-label on the root container", () => {
    const { container } = render(<NavigatorSourceFileDbPreview />);
    const root = container.firstChild as HTMLElement;
    expect(root.getAttribute("role")).toBe("img");
    expect(root.getAttribute("aria-label") ?? "").toMatch(
      /источник|файл|бд/i
    );
  });
});
