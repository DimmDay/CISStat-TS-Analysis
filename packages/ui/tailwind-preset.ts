// packages/ui/tailwind-preset.ts
//
// Общий Tailwind preset для ВСЕХ фронтендов (embedded и standalone).
// Токены — точно как в присланном tailwind.config.ts портала, вынесены
// сюда как переиспользуемый preset, а не продублированы в каждом apps/*.
//
// ═══════════════════════════════════════════════════════════════════
// Task DKT-1 — токенизация палитры на CSS-переменные (тёмная тема).
// spec_dark_theme.md §3.3 (Вариант C), §4.1.
//
// КОНТРАКТ «имена классов не меняются — меняются значения»:
//   darkMode: "class" + каждый ЗАНЯТЫЙ шаг палитры отображается на
//   CSS-переменную формата rgb(var(--c-*) / <alpha-value>). Формат троек
//   сохраняет ~150 слэш-модификаторов прозрачности (bg-brand-light/50,
//   border-brand/30...). Значения переменных — в packages/ui/globals.css:
//   `:root` = точные текущие светлые значения (байт-инвариант светлой
//   темы), `.dark` = тёмная ревизия (каталог §6, калибровка DKT-2).
//
// СЛЕДСТВИЕ (осознанный контракт): одна и та же строка класса означает
// разные фактические цвета в разных темах. Роли закреплены за уровнями
// светлоты (лёгкий фон → тёмный фон, серый текст → светлый серый).
// Каталог-тест tailwind-preset.test.ts страхует соответствие.
//
// Отображены ТОЛЬКО программно занятые шаги (инвентарь rg по §2, замер
// DKT-2); не-занятые шаги сохраняют дефолты Tailwind. Исключения:
//   - black НЕ токенизируется в тёмную инверсию — роль «текст/оверлеи
//     на нетокенизированных поверхностях» (HomeFooter с проп-фоном,
//     подложка EventsLogDrawer) — см. globals.css;
//   - brand-bright (НОВЫЙ, R-3): светлая пара текста бренда, в тёмной
//     ревизии — светлое индиго #8F94F5 (текст/линии ~7:1 на тёмном);
//   - brand остаётся заливкой (bg-brand + text-white ~5.5:1 в тёмной).
import type { Config } from "tailwindcss";

// Формат var-троек: rgb(var(--c-шаг) / <alpha-value>)
const v = (step: string) => `rgb(var(--c-${step}) / <alpha-value>)`;

// Занятые шаги статусных семейств (программный инвентарь §2, DKT-2):
// имя var строится из семейства и шага (--c-green-50, --c-neutral-200...)
const vMap = (family: string, steps: readonly string[]) =>
  Object.fromEntries(steps.map((s) => [s, v(`${family}-${s}`)]));

const GREEN_STEPS = ["50", "100", "200", "400", "500", "600", "700", "800"] as const;
const AMBER_STEPS = ["50", "100", "200", "300", "400", "600", "700", "800", "900"] as const;
const RED_STEPS = ["50", "100", "200", "300", "600", "700", "800"] as const;
const BLUE_STEPS = ["50", "200", "300", "400", "600", "700", "800", "900"] as const;
const EMERALD_STEPS = ["50", "200", "600", "800"] as const;
const VIOLET_STEPS = ["50", "200", "950"] as const;
const SKY_STEPS = ["50", "100", "200", "800", "950"] as const;

const NEUTRAL_STEPS = [
  "50", "100", "200", "300", "400", "500", "600", "700", "800", "900", "950",
] as const;

const preset: Partial<Config> = {
  // Переключение тёмной темы классом .dark на <html> (§4.1; ставится
  // no-FOUC-скриптом до гидратации, далее — ThemeContext).
  darkMode: "class",
  theme: {
    extend: {
      colors: {
        white: v("white"),
        black: v("black"),
        neutral: vMap("neutral", NEUTRAL_STEPS),
        brand: {
          DEFAULT: v("brand"),
          light: v("brand-light"),
          bright: v("brand-bright"),
        },
        footer: {
          DEFAULT: v("footer"),
          legal: v("footer-legal"),
        },
        green: vMap("green", GREEN_STEPS),
        amber: vMap("amber", AMBER_STEPS),
        red: vMap("red", RED_STEPS),
        blue: vMap("blue", BLUE_STEPS),
        emerald: vMap("emerald", EMERALD_STEPS),
        violet: vMap("violet", VIOLET_STEPS),
        sky: vMap("sky", SKY_STEPS),
        cyan: { 500: v("cyan-500") },
      },
      fontFamily: {
        sans: ["var(--font-sans)", "system-ui", "sans-serif"],
      },
      keyframes: {
        "pulse-dot": {
          "0%, 100%": { opacity: "1", transform: "scale(1)" },
          "50%": { opacity: "0.4", transform: "scale(0.7)" },
        },
        // Бегущая строка stat-бейджей главной страницы (HomeCapabilities,
        // Задача M-02): трек шириной w-max состоит из двух одинаковых
        // групп, сдвиг на -50% = ровно одна группа → бесшовный цикл.
        // Скорость: 90s на группу из 14 бейджей ≈ 35-40 px/s — низкая.
        // linear — равномерное движение без ускорений; анимация одна на
        // весь трек, поэтому все бейджи движутся синхронно.
        marquee: {
          from: { transform: "translateX(0)" },
          to: { transform: "translateX(-50%)" },
        },
        // Зеркальная бегущая строка (NavigatorHero, секция «Ключевые этапы
        // исследования ряда», задача NAVSTG-1): движение СЛЕВА НАПРАВО.
        // Трек из двух одинаковых групп, старт с translateX(-50%) (= ровно
        // одна группа) до 0 — стык бесшовен по той же арифметике, что у
        // marquee. Скорость — та же 90s linear infinite (стандарт главной).
        marqueeReverse: {
          from: { transform: "translateX(-50%)" },
          to: { transform: "translateX(0)" },
        },
      },
      animation: {
        "pulse-dot": "pulse-dot 1.8s ease-in-out infinite",
        marquee: "marquee 90s linear infinite",
        "marquee-reverse": "marqueeReverse 90s linear infinite",
      },
    },
  },
  plugins: [],
};

export default preset;
