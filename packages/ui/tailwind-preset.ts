// packages/ui/tailwind-preset.ts
//
// Общий Tailwind preset для ВСЕХ фронтендов (embedded и standalone).
// Токены — точно как в присланном tailwind.config.ts портала, вынесены
// сюда как переиспользуемый preset, а не продублированы в каждом apps/*.
import type { Config } from "tailwindcss";

const preset: Partial<Config> = {
  theme: {
    extend: {
      colors: {
        brand: {
          DEFAULT: "#2E3192", // официальный тёмно-синий логотипа Статкомитета СНГ
          light: "#E8EAF6",   // голубой фон шапок карточек (var(--bg-accent) в прототипе)
        },
        footer: {
          DEFAULT: "#5B5B5B",
          legal: "#E4E4E4",
        },
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
      },
      animation: {
        "pulse-dot": "pulse-dot 1.8s ease-in-out infinite",
        marquee: "marquee 90s linear infinite",
      },
    },
  },
  plugins: [],
};

export default preset;
