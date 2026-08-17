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
// setupFilesAfterEnv запускается ПОСЛЕ установки Jest-глобалов
// (beforeEach и т.д. доступны), но ДО первого теста в каждом файле —
// это правильное место для полифилов, см.
// https://jestjs.io/docs/configuration#setupfilesafterenv-array

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