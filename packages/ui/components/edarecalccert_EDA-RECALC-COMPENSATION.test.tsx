// packages/ui/components/edarecalccert_EDA-RECALC-COMPENSATION.test.tsx
//
// НЕЗАВИСИМАЯ СЕРТИФИКАЦИЯ задачи EDA-RECALC-COMPENSATION (d0eb261, база
// 539284e; сертификация на df7ecee). Оракулы сертификатора на СВОИХ
// данных — корпус дизъюнктен репо-сюитам:
//   • свои колонки/датасет: temp_c / humidity / day_stamp / shift_start,
//     dataset_id "edarecalccert-meteo-1";
//   • свои тексты ошибок/причин («Сбой расчёта метео-профиля…»);
//   • свои транспортные средства для каждого пункта компенсирующего
//     набора ①–⑤ (репо-сюит использует Price/Volume/Date и одноточечные
//     vehicle: correlation для фокуса, structural для ретрая, stats для
//     даты; здесь — цикл по ВСЕМ 10 остановкам для ① и ③, seasonality
//     для ②, standalone-рендер EdaDescriptiveOverview для ④).
//
// Пинируемый контракт (worklog10.md, задача d0eb261):
//   T1  постоянных кнопок «Пересчитать…» и мёртвого fallback
//       «Запустить анализ» нет ни на одной из 10 остановок;
//   T2  ① фокус-рефетч: возврат фокуса бампит ВСЕ 10 остановок
//       (каждая остановка — vehicle в отдельном тесте: её эндпоинт +1,
//       descriptive (stats) +1);
//   T3  ③ «Повторить» ТОЛЬКО в error-ветке, ретрай бампит РОВНО свою
//       остановку (свой эндпоинт +1, stats +0 — запрет retryAll), все
//       10 кейсов switch retryStop;
//   T4  кнопка «Повторить» в DOM РАНЬШЕ «Метрики и алгоритм» своей
//       остановки (контракт «до „Метрики и алгоритм"»);
//   T5  ② подтверждение временной колонки в панели паспорта бампит
//       остановки (active seasonality +1, stats +1) после успешного
//       POST /date-column;
//   T6  пара событий (visibilitychange→visible + focus) в пределах окна
//       дедупликации даёт РОВНО одну волну (дедуп useWindowFocusRefetch);
//   T7  ④ mount-scope ревизии графика распределения: 3-сегментный
//       контракт <mount>:<refreshKey>:<feature>, бампы внутри
//       монтирования меняют только средний сегмент, перемонтирование —
//       префикс (standalone-рендер EdaDescriptiveOverview).

import "@testing-library/jest-dom";
import { render, screen, fireEvent, waitFor, renderHook } from "@testing-library/react";
import { TsAnalysisEDA } from "./TsAnalysisEDA";
import { EdaDescriptiveOverview, type DescriptiveStatsResponse } from "./EdaDescriptiveOverview";
import edaChecksJson from "../../../shared/pipeline_nodes/eda_checks.json";

// ── СВОИ данные (дизъюнктны репо-корпусу Year/Price/Volume/Date) ──

jest.mock("../context/AppShellContext", () => ({
  useAppShell: () => ({ activeDataset: mockActiveDataset }),
}));

let mockActiveDataset: { datasetId?: string; name: string; rows: number; sizeLabel: string } | null = {
  datasetId: "edarecalccert-meteo-1",
  name: "edarecalccert_meteo.csv",
  rows: 120,
  sizeLabel: "12 КБ",
};

const OWN_TARGET = "temp_c";
const OWN_ERROR_TEXT = "Сбой расчёта метео-профиля edarecalccert";
const OWN_REASON_TEXT = "Метео-остановка edarecalccert неприменима для синтетического корпуса";

interface StopDef { id: string; label: string }
const STOP_DEFS: StopDef[] = (edaChecksJson.nodes as StopDef[]).map((n) => ({
  id: n.id,
  label: n.label,
}));

// СВОЯ карта остановка → эндпоинт (независимо от репо-тестов).
const STOP_ENDPOINT: Record<string, string> = {
  descriptive: "/dataset/stats",
  correlation: "/dataset/eda-correlation",
  ih_analysis: "/dataset/eda-ih",
  seasonality: "/dataset/eda-seasonality",
  stationarity: "/dataset/eda-stationarity",
  distribution: "/dataset/eda-distribution",
  structural: "/dataset/eda-structural-breaks",
  feature_select: "/dataset/eda-feature-selection",
  validation_strategy: "/dataset/eda-validation-strategy",
  model_matrix: "/dataset/eda-model-matrix",
};

const OWN_STATS: DescriptiveStatsResponse = {
  min_non_null_for_stats: 2,
  columns: [
    {
      name: OWN_TARGET,
      non_null_count: 120,
      stats: {
        mean: 14.2, median: 14.0, std: 4.1, skewness: 0.2, kurtosis: -0.8,
        q1: 11.5, q3: 17.2, iqr: 5.7, distribution_hint: "Близко к нормальному",
      },
    },
    {
      name: "humidity",
      non_null_count: 118,
      stats: {
        mean: 62.5, median: 61.0, std: 9.9, skewness: 0.5, kurtosis: -0.3,
        q1: 55.0, q3: 70.0, iqr: 15.0, distribution_hint: "Умеренная асимметрия",
      },
    },
  ],
};

// Минимальные ВАЛИДНЫЕ ответы 9 не-descriptive остановок: applicable:false
// рендерится всеми обзорами ранней веткой role="status" без графиков.
// ВАЖНО (сертификационное наблюдение): центральная панель метрик TsAnalysisEDA
// обращается к вложенным контейнерам профиля вне гейта applicable
// (ihProfile?.results[0], stationarityProfile?.tests.find, structuralProfile?.cusum,
// featureSelectionProfile?.kept_features, validationStrategyProfile?.warnings[0],
// modelMatrixProfile?.summary.blocked) — ответы обязаны нести пустые контейнеры,
// как реальные ответы backend (контракт схем): форма соответствует минимуму,
// при котором остановка честно рендерит «неприменимо» без краша.
function inapplicable(column: string, extra: Record<string, unknown> = {}) {
  return { column, applicable: false, reason: OWN_REASON_TEXT, ...extra };
}

const OWN_DISTRIBUTION_CHART = {
  column: OWN_TARGET,
  non_null_count: 120,
  min: 4,
  max: 26,
  scatter: [{ x: 0, y: 12 }, { x: 1, y: 15 }],
  scatter_sampled: false,
  scatter_sampling_method: null,
  scatter_original_count: 120,
  histogram: [{ x0: 10, x1: 14, count: 30 }],
  kde: [{ x: 12, y: 0.08 }],
};

const ownResponses: Record<string, unknown> = {
  "/dataset/eda-correlation": inapplicable(OWN_TARGET, {
    n_observations: 0, acf: [], pacf: [], significant_acf_lags: [], significant_pacf_lags: [],
  }),
  "/dataset/eda-ih": inapplicable(OWN_TARGET, {
    n_observations: 0, results: [], synergies: [], recommendations: [],
  }),
  "/dataset/eda-seasonality": inapplicable(OWN_TARGET, {
    n_observations: 0, recommendations: [],
  }),
  "/dataset/eda-stationarity": inapplicable(OWN_TARGET, {
    n_observations: 0, tests: [], recommendations: [], warnings: [],
  }),
  "/dataset/eda-distribution": inapplicable(OWN_TARGET, {
    n_observations: 0, tests: [], recommendations: [], warnings: [],
  }),
  "/dataset/eda-structural-breaks": inapplicable(OWN_TARGET, {
    n_observations: 0, candidates: [], segments: [], series: [], cusum_path: [],
    sensitivity: [], cusum: { statistic: 0, p_value: null, reject_stability: false, critical_values: {} },
    recommendations: [], warnings: [],
  }),
  "/dataset/eda-feature-selection": inapplicable(OWN_TARGET, {
    n_observations: 0, features: [], kept_features: [], review_features: [],
    low_signal_features: [], excluded_features: [], applicability_status: null,
    recommendations: [], warnings: [],
  }),
  "/dataset/eda-validation-strategy": inapplicable(OWN_TARGET, {
    n_observations: 0, folds: [], alternatives: [], warnings: [], recommendations: [],
  }),
  "/dataset/eda-model-matrix": inapplicable(OWN_TARGET, {
    models: [], families: [], shortlist: [], runnable_shortlist: [],
    summary: { total_models: 0, candidates: 0, conditional: 0, blocked: 0, ready: 0, catalog_only: 0 },
    warnings: [], recommendation: null,
  }),
};

interface StubResponse {
  ok: boolean;
  status: number;
  json: () => Promise<unknown>;
}

function ownRouteFetch(
  failPlan?: (url: string, callIndex: number) => StubResponse | undefined,
) {
  const calls = new Map<string, number>();
  return jest.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const callIndex = (calls.get(url) ?? 0) + 1;
    calls.set(url, callIndex);

    if (url.includes("/dataset/passport/status")) {
      const emptyPoint = { captured: false, captured_at: null, is_stale: null, fingerprint: null, history_count: 0 };
      return Promise.resolve({
        ok: true, status: 200,
        json: () => Promise.resolve({
          has_dataset: true,
          target_column: OWN_TARGET,
          date_column: "day_stamp",
          series_ready: true,
          reason: null,
          current_fingerprint: "cert-current",
          start: { ...emptyPoint, captured: true, is_stale: false, fingerprint: "cert-current", history_count: 1 },
          validation: emptyPoint,
          exit: emptyPoint,
          modeling_entry: { ...emptyPoint, checkpoint_id: null, snapshot_id: null, source_stage: null, reused_snapshot: null },
        }),
      });
    }
    if (url.includes("/date-column")) {
      return Promise.resolve({
        ok: true, status: 200,
        json: () => Promise.resolve({
          date_column: "day_stamp",
          suggested_column: "day_stamp",
          candidates: [
            { name: "day_stamp", score: 1 },
            { name: "shift_start", score: 0.8 },
          ],
          has_dataset: true,
          passport_history_reset: false,
        }),
      });
    }
    if (url.includes("/target-column")) {
      const selected = init?.method === "POST"
        ? JSON.parse(String(init.body)).column
        : OWN_TARGET;
      return Promise.resolve({
        ok: true, status: 200,
        json: () => Promise.resolve({
          target_column: selected,
          target_column_source: "user",
          suggested_column: OWN_TARGET,
          available_columns: ["temp_c", "humidity"],
          has_dataset: true,
        }),
      });
    }
    if (url.includes("/dataset/stats")) {
      const failed = failPlan?.(url, callIndex);
      if (failed) return Promise.resolve(failed);
      return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(OWN_STATS) });
    }
    if (url.includes("/dataset/distribution?")) {
      return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(OWN_DISTRIBUTION_CHART) });
    }
    for (const [endpoint, body] of Object.entries(ownResponses)) {
      if (url.includes(endpoint)) {
        const failed = failPlan?.(url, callIndex);
        if (failed) return Promise.resolve(failed);
        return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(body) });
      }
    }
    // Прогресс-контур (/v1/progress/*) не входит в скоуп оракулов: ретрай
    // delivery-хука и отчёт просмотров обрабатывают отказ самостоятельно
    // (прецедент routeFetch репо-сюиты).
    return Promise.reject(new Error(`edarecalccert: unexpected fetch ${url}`));
  }) as jest.Mock;
}

function callCount(mock: jest.Mock, substring: string): number {
  return mock.mock.calls.filter(([url]) => String(url).includes(substring)).length;
}

function articleOf(label: string): HTMLElement {
  const articles = screen.getAllByRole("article");
  const found = articles.find((a) => a.textContent?.includes(`Исследование: ${label}`));
  if (!found) throw new Error(`edarecalccert: статья остановки «${label}» не найдена`);
  return found;
}

async function openStop(label: string) {
  // Метки содержат regex-метасимволы («Корреляция (ACF/PACF)») — экранируем.
  const escaped = label.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  fireEvent.click(screen.getByRole("button", { name: new RegExp(`^${escaped}`) }));
}

// СВОИ ответы об успехе после ретрая: descriptive — таблица статистик,
// остальные — раняя ветка applicable:false (role="status" со своим reason).
async function awaitStopRecovered(label: string, id: string) {
  if (id === "descriptive") {
    await screen.findByRole("table", { name: "Описательные статистики по числовым признакам" });
  } else {
    await waitFor(() => {
      expect(articleOf(label).textContent).toContain(OWN_REASON_TEXT);
    });
  }
}

// ── T1: постоянные кнопки отсутствуют на КАЖДОЙ из 10 остановок ──

describe("edarecalccert — T1: удалённые кнопки отсутствуют на каждой из 10 остановок", () => {
  it("обход всех 10 статей: нет «Пересчитать…», нет «Запустить анализ», нет «Повторить» вне ошибки; инфо-кнопки на месте", async () => {
    global.fetch = ownRouteFetch();
    render(<TsAnalysisEDA />);
    await screen.findByRole("table", { name: "Описательные статистики по числовым признакам" });

    expect(STOP_DEFS).toHaveLength(10);
    for (const stop of STOP_DEFS) {
      const article = articleOf(stop.label);
      expect(article.textContent).toContain(`Исследование: ${stop.label}`);
      // Ни одной кнопки с «Пересчитать…» в подписи.
      const buttons = Array.from(article.querySelectorAll("button"));
      expect(buttons.some((b) => /Пересчитать/.test(b.textContent ?? ""))).toBe(false);
      expect(buttons.some((b) => /Запустить анализ/.test(b.textContent ?? ""))).toBe(false);
      // В отсутствие ошибки кнопки восстановления быть не должно.
      expect(buttons.some((b) => (b.textContent ?? "").trim() === "Повторить")).toBe(false);
      // Информационные кнопки остановки сохранены.
      expect(buttons.some((b) => (b.textContent ?? "").trim() === "Метрики и алгоритм")).toBe(true);
      expect(buttons.some((b) => (b.textContent ?? "").trim() === "Полный пайплайн")).toBe(true);
    }
  });
});

// ── T2: ① фокус-рефетч — цикл по всем 10 остановкам ──

describe("edarecalccert — T2: ① фокус-рефетч бампит каждую из 10 остановок", () => {
  it.each(STOP_DEFS.map((stop) => [stop.id, stop.label]))(
    "фокус при активной остановке %s перезапрашивает её эндпоинт и descriptive",
    async (id, label) => {
      global.fetch = ownRouteFetch();
      render(<TsAnalysisEDA />);
      await screen.findByRole("table", { name: "Описательные статистики по числовым признакам" });

      if (id !== "descriptive") {
        await openStop(label);
        await waitFor(() => {
          expect(callCount(global.fetch as jest.Mock, STOP_ENDPOINT[id])).toBeGreaterThanOrEqual(1);
        });
      }
      const stopBefore = callCount(global.fetch as jest.Mock, STOP_ENDPOINT[id]);
      const statsBefore = callCount(global.fetch as jest.Mock, "/dataset/stats");

      fireEvent(window, new Event("focus"));

      await waitFor(() => {
        expect(callCount(global.fetch as jest.Mock, STOP_ENDPOINT[id])).toBe(stopBefore + 1);
      });
      await waitFor(() => {
        expect(callCount(global.fetch as jest.Mock, "/dataset/stats")).toBe(statsBefore + 1);
      });
    },
    90000,
  );
});

// ── T6: дедуп пары событий фокуса ──

describe("edarecalccert — T6: пара visibilitychange+focus даёт ровно одну волну", () => {
  it("двойная волна не возникает (дедуп useWindowFocusRefetch на паре событий)", async () => {
    global.fetch = ownRouteFetch();
    render(<TsAnalysisEDA />);
    await screen.findByRole("table", { name: "Описательные статистики по числовым признакам" });

    await openStop("IH-анализ");
    await waitFor(() => {
      expect(callCount(global.fetch as jest.Mock, "/dataset/eda-ih")).toBeGreaterThanOrEqual(1);
    });
    const ihBefore = callCount(global.fetch as jest.Mock, "/dataset/eda-ih");
    const statsBefore = callCount(global.fetch as jest.Mock, "/dataset/stats");

    // Браузерная пара: возврат во вкладку (visibilitychange→visible), затем focus.
    fireEvent(document, new Event("visibilitychange"));
    Object.defineProperty(document, "visibilityState", { value: "visible", configurable: true });
    fireEvent(document, new Event("visibilitychange"));
    fireEvent(window, new Event("focus"));

    await waitFor(() => {
      expect(callCount(global.fetch as jest.Mock, "/dataset/eda-ih")).toBe(ihBefore + 1);
    });
    await waitFor(() => {
      expect(callCount(global.fetch as jest.Mock, "/dataset/stats")).toBe(statsBefore + 1);
    });
    // Окно дедупликации: новая волна не приходит.
    await new Promise((resolve) => setTimeout(resolve, 150));
    expect(callCount(global.fetch as jest.Mock, "/dataset/eda-ih")).toBe(ihBefore + 1);
    expect(callCount(global.fetch as jest.Mock, "/dataset/stats")).toBe(statsBefore + 1);
  }, 90000);
});

// ── T3: ③ «Повторить» — цикл по всем 10 остановкам, ретрай точечный ──

describe("edarecalccert — T3: ③ «Повторить» на каждой из 10 остановок (switch retryStop)", () => {
  it.each(STOP_DEFS.map((stop) => [stop.id, stop.label]))(
    "сбой GET на %s: «Повторить» в своей статье, ретрай перезапрашивает РОВНО свою остановку",
    async (id, label) => {
      const failingEndpoint = STOP_ENDPOINT[id];
      global.fetch = ownRouteFetch((url, callIndex) => {
        if (url.includes(failingEndpoint) && callIndex === 1) {
          return {
            ok: false,
            status: 500,
            json: () => Promise.resolve({ detail: OWN_ERROR_TEXT }),
          } as StubResponse;
        }
        return undefined;
      });
      render(<TsAnalysisEDA />);
      if (id === "descriptive") {
        // Первая волна stats по сценарию падает — таблицы ждать нельзя:
        // ждём error-состояние остановки с СВОИМ текстом.
        await waitFor(() => {
          expect(articleOf(label).textContent).toContain(OWN_ERROR_TEXT);
        });
      } else {
        await screen.findByRole("table", { name: "Описательные статистики по числовым признакам" });
        await openStop(label);
        await waitFor(() => {
          expect(articleOf(label).textContent).toContain(OWN_ERROR_TEXT);
        });
      }

      // Кнопка восстановления — ВНУТРИ своей статьи (error-ветка остановки).
      const article = articleOf(label);
      const retryInArticle = Array.from(article.querySelectorAll("button"))
        .find((b) => (b.textContent ?? "").trim() === "Повторить");
      expect(retryInArticle).toBeDefined();

      const stopBefore = callCount(global.fetch as jest.Mock, failingEndpoint);
      const statsBefore = callCount(global.fetch as jest.Mock, "/dataset/stats");

      fireEvent.click(retryInArticle as HTMLElement);

      // Ретрай перезапрашивает РОВНО свою остановку (запрет retryAll: stats
      // не перечитывается — кроме случая, когда сама остановка и есть descriptive).
      await waitFor(() => {
        expect(callCount(global.fetch as jest.Mock, failingEndpoint)).toBe(stopBefore + 1);
      });
      await awaitStopRecovered(label, id);
      if (id !== "descriptive") {
        expect(callCount(global.fetch as jest.Mock, "/dataset/stats")).toBe(statsBefore);
      }
      // После восстановления кнопка исчезла (статус покинул error).
      expect(
        Array.from(articleOf(label).querySelectorAll("button"))
          .some((b) => (b.textContent ?? "").trim() === "Повторить"),
      ).toBe(false);
    },
    90000,
  );
});

// ── T4: DOM-порядок «Повторить» до «Метрики и алгоритм» + единственность ──

describe("edarecalccert — T4: «Повторить» только в error-ветке и до «Метрики и алгоритм»", () => {
  it("при единственной ошибке кнопка одна на экране и стоит раньше «Метрики и алгоритм» своей статьи", async () => {
    global.fetch = ownRouteFetch((url, callIndex) => {
      if (url.includes("/dataset/eda-stationarity") && callIndex === 1) {
        return { ok: false, status: 500, json: () => Promise.resolve({ detail: OWN_ERROR_TEXT }) };
      }
      return undefined;
    });
    render(<TsAnalysisEDA />);
    await screen.findByRole("table", { name: "Описательные статистики по числовым признакам" });

    await openStop("Верификация стационарности");
    await waitFor(() => {
      expect(articleOf("Верификация стационарности").textContent).toContain(OWN_ERROR_TEXT);
    });

    // Ровно одна кнопка «Повторить» на весь экран (только error-ветка).
    const retries = screen.getAllByRole("button", { name: "Повторить" });
    expect(retries).toHaveLength(1);

    // DOM-порядок: раньше кнопки «Метрики и алгоритм» той же статьи.
    const article = articleOf("Верификация стационарности");
    const metricsButton = Array.from(article.querySelectorAll("button"))
      .find((b) => (b.textContent ?? "").trim() === "Метрики и алгоритм") as HTMLElement;
    expect(retries[0].compareDocumentPosition(metricsButton) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  }, 90000);
});

// ── T5: ② дата-бамп через панель паспорта (свой vehicle — seasonality) ──

describe("edarecalccert — T5: ② подтверждение временной колонки бампит остановки", () => {
  it("после успешного POST /date-column перечитываются активная seasonality и descriptive", async () => {
    global.fetch = ownRouteFetch();
    render(<TsAnalysisEDA />);
    await screen.findByRole("table", { name: "Описательные статистики по числовым признакам" });

    await openStop("Сезонность и периодичность");
    await waitFor(() => {
      expect(callCount(global.fetch as jest.Mock, "/dataset/eda-seasonality")).toBeGreaterThanOrEqual(1);
    });
    const seasonBefore = callCount(global.fetch as jest.Mock, "/dataset/eda-seasonality");
    const statsBefore = callCount(global.fetch as jest.Mock, "/dataset/stats");

    // Внутри-EDA мутация: своя пара кандидатов day_stamp → shift_start.
    fireEvent.change(screen.getByRole("combobox", { name: "Временная колонка паспорта" }), {
      target: { value: "shift_start" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Подтвердить паспорт для моделирования" }));

    await waitFor(() => {
      expect(global.fetch).toHaveBeenCalledWith(
        expect.stringContaining("/v1/session/date-column"),
        expect.objectContaining({ method: "POST", body: JSON.stringify({ column: "shift_start" }) }),
      );
    });
    await waitFor(() => {
      expect(callCount(global.fetch as jest.Mock, "/dataset/eda-seasonality")).toBe(seasonBefore + 1);
    });
    await waitFor(() => {
      expect(callCount(global.fetch as jest.Mock, "/dataset/stats")).toBe(statsBefore + 1);
    });
  }, 90000);
});

// ── T7: ④ mount-scope ревизии распределения (standalone EdaDescriptiveOverview) ──

describe("edarecalccert — T7: ④ mount-scope ревизии графика распределения", () => {
  function revisions(mock: jest.Mock): string[] {
    return mock.mock.calls
      .map(([url]) => String(url))
      .filter((url) => url.includes("/dataset/distribution?"))
      .map((url) => new URL(url).searchParams.get("revision") ?? "");
  }

  function mountOverview(props?: { refreshKey?: number; activeFeature?: string }) {
    return render(
      <EdaDescriptiveOverview
        profile={OWN_STATS}
        activeFeature={props?.activeFeature ?? OWN_TARGET}
        loading={false}
        error={null}
        noDataset={false}
        refreshKey={props?.refreshKey ?? 0}
      />,
    );
  }

  async function openHistogram() {
    fireEvent.click(await screen.findByRole("tab", { name: "Гистограмма" }));
    await waitFor(() => expect(revisions(global.fetch as jest.Mock)).toHaveLength(1));
  }

  it("формат: ровно 3 сегмента <mount>:<refreshKey>:<feature>, mount-префикс случайный base36", async () => {
    global.fetch = ownRouteFetch();
    mountOverview();
    await openHistogram();

    const [revision] = revisions(global.fetch as jest.Mock);
    const segments = revision.split(":");
    expect(segments).toHaveLength(3);
    expect(segments[0]).toMatch(/^[a-z0-9]{1,12}$/);
    expect(segments[0]).not.toBe("");
    expect(segments[1]).toBe("0");
    expect(segments[2]).toBe(OWN_TARGET);
  }, 90000);

  it("бамп refreshKey внутри монтирования: префикс и признак неизменны, средний сегмент сменяется", async () => {
    global.fetch = ownRouteFetch();
    const view = mountOverview({ refreshKey: 0 });
    await openHistogram();
    const [revision0] = revisions(global.fetch as jest.Mock);

    view.rerender(
      <EdaDescriptiveOverview
        profile={OWN_STATS}
        activeFeature={OWN_TARGET}
        loading={false}
        error={null}
        noDataset={false}
        refreshKey={1}
      />,
    );
    await waitFor(() => expect(revisions(global.fetch as jest.Mock)).toHaveLength(2));
    const [revision1] = revisions(global.fetch as jest.Mock).slice(-1);

    const seg0 = revision0.split(":")[0];
    expect(revision1.split(":")[0]).toBe(seg0);
    expect(revision1.split(":")[1]).not.toBe(revision0.split(":")[1]);
    expect(revision1.split(":")[2]).toBe(OWN_TARGET);
  }, 90000);

  it("смена признака внутри монтирования: префикс сохраняется, третий сегмент — новый признак", async () => {
    global.fetch = ownRouteFetch();
    const view = mountOverview({ refreshKey: 3, activeFeature: OWN_TARGET });
    await openHistogram();
    const [revision0] = revisions(global.fetch as jest.Mock);

    view.rerender(
      <EdaDescriptiveOverview
        profile={OWN_STATS}
        activeFeature="humidity"
        loading={false}
        error={null}
        noDataset={false}
        refreshKey={3}
      />,
    );
    await waitFor(() => expect(revisions(global.fetch as jest.Mock)).toHaveLength(2));
    const [revision1] = revisions(global.fetch as jest.Mock).slice(-1);

    expect(revision1.split(":")[0]).toBe(revision0.split(":")[0]);
    expect(revision1.split(":")[1]).toBe(revision0.split(":")[1]);
    expect(revision1.split(":")[2]).toBe("humidity");
  }, 90000);

  it("перемонтирование: mount-префикс обязан смениться при тех же refreshKey и признаке", async () => {
    global.fetch = ownRouteFetch();
    const first = mountOverview();
    await openHistogram();
    const [revisionA] = revisions(global.fetch as jest.Mock);
    first.unmount();

    global.fetch = ownRouteFetch();
    mountOverview();
    await openHistogram();
    const [revisionB] = revisions(global.fetch as jest.Mock);

    expect(revisionB.split(":")[0]).not.toBe(revisionA.split(":")[0]);
    expect(revisionB.split(":")[1]).toBe(revisionA.split(":")[1]);
    expect(revisionB.split(":")[2]).toBe(revisionA.split(":")[2]);
  }, 90000);
});
