// packages/ui/lib/serializeChartSvg.ts
//
// PGV-10 (spec_passport_graphics_visual.md §4.1/§10.1/§13, строка
// PGV-10): сериализация ЭКРАННОЙ геометрии конкретного view для
// frozen print input'а.
//
// КРИТЕРИЙ «не первый SVG»: экспорт каждого chart-view несёт
// сериализацию СВОЕГО chart-узла (контейнер, переданный кнопке),
// а не первый <svg> документа (legacy-дефект ForecastExportMenu,
// spec §2). Сериализация -- чистый клиентский доступ к уже
// отрисованному recharts-SVG; данные не пересчитываются (AC06):
// бэкенд морозить печатный вход из durable-результата (PGV-03).

/**
 * Сериализовать SVG chart-узла КОНКРЕТНОГО контейнера.
 *
 * Возвращает строку SVG (с xmlns -- required для standalone-рендера
 * в контейнере PGV-08) либо null (узел не найден/нет SVG -- кнопка
 * честно откажет с screen_svg_required, подмена геометрии запрещена).
 *
 * @param container HTML-узел, ВНУТРИ которого отрисован chart view
 *   (ref на обёртку графика этого view -- не document.body).
 */
export function serializeChartSvg(container: HTMLElement | null | undefined): string | null {
  if (!container) return null;
  const svg = container.querySelector("svg");
  if (!svg) return null;
  const clone = svg.cloneNode(true) as SVGSVGElement;
  // recharts пишет width/height атрибутами; xmlns обязателен для
  // standalone-рендера (page CSP: img-src data:, foreignObject и так
  // вырезается санитайзером контейнера, AC19).
  if (!clone.getAttribute("xmlns")) {
    clone.setAttribute("xmlns", "http://www.w3.org/2000/svg");
  }
  return new XMLSerializer().serializeToString(clone);
}

/**
 * Обёртка над serializeChartSvg для ref-геттеров кнопки: null-безопасно
 * и без исключений (неканоничный DOM -- честный null, не краш).
 */
export function serializeChartSvgSafe(
  getContainer: () => HTMLElement | null | undefined,
): string | null {
  try {
    return serializeChartSvg(getContainer());
  } catch {
    return null;
  }
}
