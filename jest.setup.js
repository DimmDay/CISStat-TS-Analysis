// jest.setup.js
//
// Polyfills для jsdom-окружения, в котором по умолчанию отсутствуют
// браузерные API, на которые опираются тестируемые компоненты:
//
//   • ResizeObserver — используется в TsAnalysisPreprocessing.tsx:152
//     и TsAnalysisEDA.tsx:152 для отслеживания переполнения центрального
//     текстового окна «Описание» (показ/скрытие chevron-раскрытия).
//     Без polyfill — `ReferenceError: ResizeObserver is not defined`
//     и 9 тестов в каждом из Preprocessing/EDA падают ещё до рендера.
//
//   • IntersectionObserver — нужен recharts ResponsiveContainer в
//     тестах, рендерящих чарты (BacktestComparisonChart, DistributionCharts,
//     ValidationCheckChart, TimeSeriesLineChart). Без polyfill recharts
//     падает с warn "width(0) and height(0)" и тесты таймаутятся.
//
//   • matchMedia — стандартный polyfill (некоторые UI-компоненты могут
//     использовать media queries для адаптивности).
//
//   • TextEncoder/TextDecoder (PGV-08) — react-dom/server в jsdom-среде
//     резолвится в browser-сборку (react-dom/server.browser), которой
//     нужен TextEncoder для потока рендера. В Node-рантайме рендерера
//     (apps/print-renderer) TextEncoder глобален; polyfill нужен только
//     jest-оракулам SSR (rendererCore.test.ts).
//
// setupFilesAfterEnv запускается ПОСЛЕ установки Jest-глобалов
// (beforeEach и т.д. доступны), но ДО первого теста в каждом файле —
// это правильное место для полифилов, см.
// https://jestjs.io/docs/configuration#setupfilesafterenv-array

// NB: фиксация таймзоны тестов (process.env.TZ = "UTC") живёт в
// jest.config.js, НЕ здесь: jest-runtime даёт тестам и setup-файлам КОПИЮ
// process.env (createProcessObject) -- запись отсюда не меняет реальное
// окружение воркера, и V8/ICU продолжают резолвить таймзону хоста. Конфиг
// же исполняется в главном процессе ДО форка воркеров -- они наследуют
// реальный TZ=UTC (Task FIX: PROGR-5.1, 2026-09-26).

require("@testing-library/jest-dom");

class ResizeObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
}

class IntersectionObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
  takeRecords() {
    return [];
  }
}

global.ResizeObserver = ResizeObserverStub;
global.IntersectionObserver = IntersectionObserverStub;

// TextEncoder/TextDecoder: browser-сборка react-dom/server требует
// TextEncoder (PGV-08 SSR-оракулы); в свежих Node он глобален, но
// jsdom-окружение его не экспортирует в window-скоуп.
if (typeof global.TextEncoder === "undefined") {
  const { TextEncoder, TextDecoder } = require("node:util");
  global.TextEncoder = TextEncoder;
  global.TextDecoder = TextDecoder;
}

// matchMedia: jsdom не реализует, но отдельные компоненты могут звать.
window.matchMedia =
  window.matchMedia ||
  ((query) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: () => {},
    removeListener: () => {},
    addEventListener: () => {},
    removeEventListener: () => {},
    dispatchEvent: () => false,
  }));
