// packages/ui/components/NavigatorPassportPreview.test.tsx
//
// Тесты статичной блок-схемы для окна «Обзор» пункта «Паспорт свойств
// ряда» (id="passport") секции «Этапы модуля» остановки «Загрузка» на
// странице Навигатор (10-й, последний пункт модуля «Загрузка»).
//
// Контракт:
//   - Визуализация — статичная информационная блок-схема фиксации
//     первичного снимка свойств ряда (v1.0): предусловия готовности,
//     пайплайн расчёта (prepare_passport_series → series_fingerprint →
//     calculate_ts_passport → append_passport_snapshot), группы свойств,
//     роль снимка в цепочке паспортов, отказы.
//   - Схема основана на РЕАЛЬНОЙ логике:
//       • packages/ui/components/TsAnalysisUpload.tsx (DatasetPassportPanel
//         stage="start", кнопка «Рассчитать паспорт на загрузке»)
//       • apps/api/routers/session.py::capture_dataset_passport
//         (POST /dataset/passport/{stage}; контроль порядка точек — 409;
//         отпечаток ряда — «Свойства ряда не изменились»)
//       • app/core/passport.py::calculate_ts_passport (частота
//         pd.infer_freq; ADF p<0.05; R² тренда ≥0.7; Ljung-Box p>0.05
//         при регулярной частоте; Jarque-Bera p>0.05; направление тренда
//         по slope; топ-3 корреляций; сила сезонности STL >0.6 и ≥2 цикла;
//         значимые лаги ACF; Хёрст 0.45/0.55; FFT/периодограмма/вейвлет
//         Морле — топ-3; basic_stats n/mean/std/min/max; минимум 30
//         валидных точек)
//       • apps/api/session_store.py (PassportSnapshot → passport_history;
//         PASSPORT_STAGES start/validation/exit/modeling_entry)
//   - Отображается ПРИ ЛЮБЫХ УСЛОВИЯХ — НЕ зависит от useAppShell,
//     activeDataset, fetch, сети, сессии.
//
// Архитектурно — родственник NavigatorSourceFileDbPreview
// (статичная Tailwind/CSS-блок-схема, role="img" + aria-label).

import React from "react";
import "@testing-library/jest-dom";
import { render, screen } from "@testing-library/react";
import { NavigatorPassportPreview } from "./NavigatorPassportPreview";

describe("NavigatorPassportPreview — rendering", () => {
  it("renders without AppShellProvider (no session dependency)", () => {
    // Если компонент попытается вызвать useAppShell() — упадёт.
    // Не оборачиваем в провайдер намеренно.
    const { container } = render(<NavigatorPassportPreview />);
    expect(container.firstChild).not.toBeNull();
  });

  it("renders the section heading «Паспорт свойств ряда»", () => {
    render(<NavigatorPassportPreview />);
    expect(
      screen.getByRole("heading", { level: 3, name: /паспорт свойств ряда/i })
    ).toBeInTheDocument();
  });

  it("renders the real capture endpoint POST /dataset/passport/start", () => {
    render(<NavigatorPassportPreview />);
    // Реальный эндпоинт фиксации снимка (session.py::capture_dataset_passport).
    expect(screen.getAllByText(/dataset\/passport\/start/i).length).toBeGreaterThanOrEqual(1);
  });

  it("renders the capture action label from the Upload page panel", () => {
    render(<NavigatorPassportPreview />);
    // DatasetPassportPanel STAGE_TEXT.start.action — точная строка.
    expect(screen.getByText(/Рассчитать паспорт на загрузке/i)).toBeInTheDocument();
  });

  it("renders the readiness preconditions (dataset, feature, date column)", () => {
    render(<NavigatorPassportPreview />);
    // Реальные причины блокировки кнопки (DatasetPassportPanel disabledReason).
    expect(screen.getByText(/Сначала загрузите датасет/i)).toBeInTheDocument();
    expect(screen.getByText(/Сначала выберите исследуемый признак/i)).toBeInTheDocument();
    expect(screen.getByText(/Выберите временную колонку/i)).toBeInTheDocument();
  });

  it("renders the minimum series length requirement (30 valid points)", () => {
    render(<NavigatorPassportPreview />);
    // calculate_ts_passport: «Недостаточно данных (нужно минимум 30 валидных точек)».
    // Фраза живёт и в готовности, и в ошибке — getAllByText.
    expect(
      screen.getAllByText(/минимум 30 валидных точек/i).length
    ).toBeGreaterThanOrEqual(1);
  });

  it("renders the real calculation pipeline steps", () => {
    render(<NavigatorPassportPreview />);
    // app/core/passport.py + session.py + session_store.py — реальные шаги.
    expect(screen.getByText(/prepare_passport_series/i)).toBeInTheDocument();
    expect(screen.getByText(/series_fingerprint/i)).toBeInTheDocument();
    expect(screen.getByText(/calculate_ts_passport/i)).toBeInTheDocument();
    expect(screen.getByText(/append_passport_snapshot/i)).toBeInTheDocument();
  });

  it("renders the series fingerprint change-control message", () => {
    render(<NavigatorPassportPreview />);
    // session.py: повторная фиксация при том же отпечатке — 409.
    expect(
      screen.getByText(/Свойства ряда не изменились с последнего расчёта/i)
    ).toBeInTheDocument();
  });

  it("renders the frequency check by pd.infer_freq (regular vs irregular)", () => {
    render(<NavigatorPassportPreview />);
    expect(screen.getByText(/infer_freq/i)).toBeInTheDocument();
    expect(screen.getByText(/Нерегулярная/i)).toBeInTheDocument();
  });

  it("renders the stationarity ADF block with the 0.05 threshold", () => {
    render(<NavigatorPassportPreview />);
    expect(screen.getByText(/ADF/i)).toBeInTheDocument();
    expect(screen.getAllByText(/0\.05/i).length).toBeGreaterThanOrEqual(1);
  });

  it("renders the trend determinism block with the R² 0.7 threshold", () => {
    render(<NavigatorPassportPreview />);
    // calculate_ts_passport: R² ≥ 0.7 → детерминирован.
    expect(screen.getByText(/0\.7/i)).toBeInTheDocument();
  });

  it("renders the trend direction block (up / down / flat)", () => {
    render(<NavigatorPassportPreview />);
    // calculate_ts_passport: slope > 0 → up, < 0 → down, иначе flat.
    expect(screen.getByText(/up/i)).toBeInTheDocument();
    expect(screen.getByText(/down/i)).toBeInTheDocument();
    expect(screen.getByText(/flat/i)).toBeInTheDocument();
  });

  it("renders the Ljung-Box autocorrelation block (white noise > 0.05)", () => {
    render(<NavigatorPassportPreview />);
    expect(screen.getByText(/Ljung-Box/i)).toBeInTheDocument();
    expect(screen.getByText(/белый шум/i)).toBeInTheDocument();
  });

  it("renders the Jarque-Bera normality block", () => {
    render(<NavigatorPassportPreview />);
    expect(screen.getByText(/Jarque-Bera/i)).toBeInTheDocument();
  });

  it("renders the STL seasonality block with 0.6 threshold and 2-cycle minimum", () => {
    render(<NavigatorPassportPreview />);
    expect(screen.getByText(/STL/i)).toBeInTheDocument();
    expect(screen.getByText(/0\.6/i)).toBeInTheDocument();
    expect(screen.getByText(/два полных цикла|2 цикла/i)).toBeInTheDocument();
  });

  it("renders the ACF seasonal periods block", () => {
    render(<NavigatorPassportPreview />);
    expect(screen.getByText(/ACF/i)).toBeInTheDocument();
  });

  it("renders the Hurst long-memory block with 0.45 / 0.55 bounds", () => {
    render(<NavigatorPassportPreview />);
    // calculate_ts_passport: < 0.45 антиперсистентный, > 0.55 персистентный.
    expect(screen.getByText(/Хёрст/i)).toBeInTheDocument();
    expect(screen.getByText(/0\.45/i)).toBeInTheDocument();
    expect(screen.getByText(/0\.55/i)).toBeInTheDocument();
  });

  it("renders the spectral blocks (FFT, periodogram, Morlet wavelet)", () => {
    render(<NavigatorPassportPreview />);
    expect(screen.getByText(/FFT/i)).toBeInTheDocument();
    expect(screen.getByText(/Периодограмма|периодограмма/i)).toBeInTheDocument();
    expect(screen.getByText(/Морле/i)).toBeInTheDocument();
  });

  it("renders the top-3 correlations block", () => {
    render(<NavigatorPassportPreview />);
    // calculate_ts_passport: топ-3 корреляции/периоды/лаги/масштабы —
    // встречается в нескольких группах свойств — getAllByText.
    expect(screen.getAllByText(/топ-3/i).length).toBeGreaterThanOrEqual(1);
  });

  it("renders the basic stats block (n, mean, std, min, max)", () => {
    render(<NavigatorPassportPreview />);
    expect(screen.getByText(/mean/i)).toBeInTheDocument();
    expect(screen.getByText(/std/i)).toBeInTheDocument();
    expect(screen.getByText(/min/i)).toBeInTheDocument();
    expect(screen.getByText(/max/i)).toBeInTheDocument();
  });

  it("renders the passport snapshot version v1.0 and the comparison chain", () => {
    render(<NavigatorPassportPreview />);
    // Роль снимка в цепочке: v1.0 (Загрузка) → v1.1 (Валидация) →
    // v1.2 (Предобработка) → v1.3 (EDA) — тексты navigator-stops.ts.
    expect(screen.getByText(/v1\.0/i)).toBeInTheDocument();
    expect(screen.getByText(/v1\.1/i)).toBeInTheDocument();
    expect(screen.getByText(/v1\.2/i)).toBeInTheDocument();
    expect(screen.getByText(/v1\.3/i)).toBeInTheDocument();
  });

  it("renders the stage order control notice (baseline is immutable after next point)", () => {
    render(<NavigatorPassportPreview />);
    // session.py: 409 «Нельзя менять start после следующей точки» +
    // DatasetPassportPanel: «Baseline нельзя менять после фиксации следующей точки».
    expect(
      screen.getByText(/Baseline нельзя менять после фиксации следующей точки/i)
    ).toBeInTheDocument();
  });

  it("renders the history reset notice (feature/date change resets the chain)", () => {
    render(<NavigatorPassportPreview />);
    // TsAnalysisUpload.tsx: «Смена исследуемого признака … сбросила цепочку паспортов».
    expect(screen.getByText(/сбросила цепочку паспортов|сброс цепочки паспортов/i)).toBeInTheDocument();
  });

  it("renders the irregular frequency honest status (part of metrics becomes n/a)", () => {
    render(<NavigatorPassportPreview />);
    // calculate_ts_passport: Ljung-Box/STL/ACF/FFT/периодограмма/вейвлет
    // требуют регулярной частоты — при нерегулярной честно «не применимо».
    expect(screen.getByText(/не примени/i)).toBeInTheDocument();
  });

  it("renders error messages of the calculation", () => {
    render(<NavigatorPassportPreview />);
    // calculate_ts_passport: ряд короче 30 точек — ошибка расчёта.
    expect(screen.getByText(/Недостаточно данных/i)).toBeInTheDocument();
  });

  it("renders without loading/empty state — always shows infographic", () => {
    const { container } = render(<NavigatorPassportPreview />);
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
      throw new Error("NavigatorPassportPreview must not call fetch");
    }) as unknown as typeof fetch;
    // @ts-expect-error — intentionally stub XHR
    global.XMLHttpRequest = function () {
      xhrCreated = true;
      throw new Error("NavigatorPassportPreview must not create XHR");
    };

    try {
      render(<NavigatorPassportPreview />);
      expect(fetchCalled).toBe(false);
      expect(xhrCreated).toBe(false);
    } finally {
      global.fetch = originalFetch;
      global.XMLHttpRequest = originalXHR;
    }
  });

  it("renders deterministically (no random content between renders)", () => {
    const { container: c1, rerender: r1 } = render(<NavigatorPassportPreview />);
    const text1 = c1.textContent;
    r1(<NavigatorPassportPreview />);
    const text2 = c1.textContent;
    expect(text2).toBe(text1);
  });

  it("renders arrows/indicators of flow (block-scheme, not flat list)", () => {
    render(<NavigatorPassportPreview />);
    const arrows = document.querySelectorAll(
      '[aria-label*="chevron" i], [aria-label*="arrow" i]'
    );
    expect(arrows.length).toBeGreaterThanOrEqual(1);
  });

  it("has role=img with informative aria-label on the root container", () => {
    const { container } = render(<NavigatorPassportPreview />);
    const root = container.firstChild as HTMLElement;
    expect(root.getAttribute("role")).toBe("img");
    expect(root.getAttribute("aria-label") ?? "").toMatch(
      /паспорт|свойств|ряда/i
    );
  });
});
