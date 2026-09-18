// packages/ui/lib/chartVars.ts

// Task DKT-3 §6.4 — световая карта графовых/статусных/волновых переменных
// для резолва var() при PNG-экспорте («всегда светлый» артефакт, §10.1).
//
// Единственный источник значений — packages/ui/globals.css (:root-блок);
// синхронизация карты с globals.css страхуется тестом
// ForecastExportMenu.vars.test.ts (зеркало, культура DKT-2).
//
// Тёмные значения для будущего режима «как на экране» берутся из .dark-
// блока globals.css (пин-таблица — dkt3-chart-vars.test.ts).

export const CHART_VARS_LIGHT: Record<string, string> = {
  "chart-axis": "#171717",
  "chart-axis-muted": "#A3A3A3",
  "chart-axis-text": "#737373",
  "chart-blue": "#2563EB",
  "chart-blue-pale": "#93C5FD",
  "chart-blue-soft": "#60A5FA",
  "chart-border": "#E5E5E5",
  "chart-brand": "#2E3192",
  "chart-brand-soft": "#E8EAF6",
  "chart-cyan": "#0891B2",
  "chart-grid": "#F0F0F0",
  "chart-neutral": "#9CA3AF",
  "chart-reference": "#D4D4D4",
  "chart-slate": "#94A3B8",
  "chart-surface": "#FFFFFF",
  "chart-violet": "#7C3AED",
  "status-error": "#DC2626",
  "status-error-bright": "#F87171",
  "status-error-strong": "#EF4444",
  "status-success": "#16A34A",
  "status-success-bright": "#4ADE80",
  "status-warning": "#D97706",
  "status-warning-bright": "#FBBF24",
  "status-warning-mid": "#F59E0B",
  "wave-home-1": "#F8FCFF",
  "wave-home-2": "#EFF6FD",
  "wave-home-3": "#E9EEFF",
  "wave-home-4": "#DCEBFA",
  "wave-home-5": "#D4E3FA",
  "wave-home-6": "#D8E0FA",
  "wave-home-7": "#D9E9FA",
  "wave-home-8": "#C8DDF7",
  "wave-home-9": "#C7D5F7",
  "wave-home-10": "#E7F2FC",
  "wave-home-11": "#D6E7FA",
  "wave-home-12": "#D9E2FC",
  "wave-home-13": "#D7E8FA",
  "wave-home-14": "#D2DBFA",
  "wave-home-stroke": "#FFFFFF",
  "wave-nav-1": "#F7FBFE",
  "wave-nav-2": "#EEF6FD",
  "wave-nav-3": "#E7EEFF",
  "wave-nav-4": "#DDECFB",
  "wave-nav-5": "#D4E5FB",
  "wave-nav-6": "#D0DAF8",
  "wave-nav-7": "#D6E8FA",
  "wave-nav-8": "#C9DCF8",
  "wave-nav-9": "#C8D6F7",
  "wave-nav-10": "#E5F1FC",
  "wave-nav-11": "#D7E7FA",
  "wave-nav-12": "#D8E1FB",
  "wave-nav-13": "#D9EAFB",
  "wave-nav-14": "#CBDDF8",
  "wave-nav-15": "#C8D7F8",
  "wave-nav-16": "#D9EAFB",
  "wave-nav-17": "#D1DBFA",
  "wave-nav-18": "#FFFFFF",
  "wave-nav-19": "#FFFFFF",
  "wave-nav-20": "#FFFFFF",
};

/**
 * Атрибуты SVG, подлежащие резолву var() перед сериализацией (§6.4):
 * сериализованный SVG теряет контекст стилей документа, поэтому
 * var() в файле не разрешается ни во что (прозрачный/чёрный рендер).
 */
const RESOLVED_ATTRS = ["fill", "stroke", "stop-color", "color", "background-color"] as const;

/** Подстановка значений светлой карты вместо var(--name); вне карты — как есть. */
function resolveVarString(value: string): string {
  return value.replace(/var\((--[a-z0-9-]+)\)/g, (m, name: string) =>
    CHART_VARS_LIGHT[name.replace(/^--/, "")] ?? m,
  );
}

/**
 * §6.4: клон SVG с резолвом var() в конкретные светлые значения.
 * Исходный элемент не мутируется; переменные вне карты остаются
 * var()-ссылками (fail-visible — видны в артефакте, не молча чёрные).
 * Артефакт «всегда светлый» (§10.1): карта не зависит от активной темы.
 */
export function resolveSvgVarsLight<T extends Element>(svg: T): T {
  const clone = svg.cloneNode(true) as T;

  const walk = (src: Element, dst: Element): void => {
    for (const attr of RESOLVED_ATTRS) {
      const value = src.getAttribute(attr);
      if (value && value.includes("var(--")) {
        dst.setAttribute(attr, resolveVarString(value));
      }
    }
    const style = src.getAttribute("style");
    if (style && style.includes("var(--")) {
      dst.setAttribute("style", resolveVarString(style));
    }
    const srcKids = Array.from(src.children);
    const dstKids = Array.from(dst.children);
    for (let i = 0; i < srcKids.length; i += 1) walk(srcKids[i], dstKids[i]);
  };
  walk(svg, clone);
  return clone;
}
