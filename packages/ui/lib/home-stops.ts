// packages/ui/lib/home-stops.ts
//
// Источник истины для исследовательской карты главной страницы (/).
// 6 маршрутов — каждый с заголовком, пояснением, иконкой и ссылкой.
// Живёт отдельно от NAVIGATOR_STOPS (navigator-stops.ts), потому что
// эти данные описывают исследовательскую навигацию (маршруты
// знакомства/обучения/доступа), а не этапы пайплайна анализа.

// ── Типы ──────────────────────────────────────────────────────

import type { LucideIcon } from "lucide-react";

export interface HomeRoute {
  /** Короткий заголовок — название маршрута. */
  title: string;
  /** Одна поясняющая строка — что пользователь получает. */
  description: string;
  /** Пиктограмма из lucide-react. */
  icon: LucideIcon;
  /** Куда ведёт клик. */
  href: string;
}

// ── 6 маршрутов исследовательской карты ────────────────────────

import {
  Compass,
  BookOpen,
  BarChart3,
  Key,
  Cable,
  TrendingUp,
} from "lucide-react";

export const HOME_ROUTES: HomeRoute[] = [
  {
    title: "Знакомство с платформой",
    description: "быстро понять возможности и логику работы",
    icon: Compass,
    href: "/navigator",
  },
  {
    title: "Обучение и база знаний",
    description: "освоить методы, термины и лучшие практики",
    icon: BookOpen,
    href: "/docs",
  },
  {
    title: "Отраслевые исследования",
    description: "изучать прикладные сценарии и контекст рынков",
    icon: BarChart3,
    href: "/research",
  },
  {
    title: "Доступ и тарифы",
    description: "выбрать подходящий уровень работы с платформой",
    icon: Key,
    href: "/pricing",
  },
  {
    title: "Документация API",
    description: "подключить данные и встроить анализ в собственные процессы",
    icon: Cable,
    href: "/docs",
  },
  {
    title: "Приступить к анализу данных",
    description: "перейти к рабочему пространству без лишних шагов",
    icon: TrendingUp,
    href: "/upload",
  },
];
