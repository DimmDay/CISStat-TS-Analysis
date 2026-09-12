// packages/ui/lib/homeFooter.ts
//
// Данные футера главной страницы standalone (Task w/n, 2026-09-13).
//
// Шаблон — футер главной страницы портала CISStat
// (https://cis-stat-portal-k9tu.vercel.app/), снят 1:1 из продового DOM
// (команда тимлида: «Забери шаблон футера с главной страницы портала.
// Блок с текстом под футером игнорируй. Пересобери заново»).
// Блок legal-дисклеймера портала (bg-footer-legal) в данные НЕ входит.
//
// Дата-дривен сознательно: контент (колонки, контакты, копирайт,
// поиск, юридические ссылки) собран в одном файле. Цвета шаблона
// (тёмная тема bg-footer #5B5B5B, text-white/text-neutral-300) в
// данные НЕ зашиваются — адаптацию в светлую тему делает компонент
// HomeFooter.tsx (фон — проп backgroundColor, на главной #CAD7F7;
// текст — чёрный).
//
// href "#" у большинства ссылок — как в шаблоне портала (заглушки);
// две внешние ссылки форм Google — боевые URL из шаблона.

export interface FooterLink {
  label: string;
  href: string;
  /** Внешняя ссылка: target="_blank" + rel="noopener noreferrer". */
  external?: boolean;
}

export interface FooterColumn {
  title: string;
  links: FooterLink[];
}

/** Абзац контактов: строки склеиваются через <br/> (адрес — 2 строки). */
export interface FooterContactItem {
  lines: string[];
}

// Колонки навигации — порядок и подписи 1:1 из шаблона портала.
export const FOOTER_COLUMNS: FooterColumn[] = [
  {
    title: "Проект",
    links: [
      { label: "О сервисе", href: "#" },
      { label: "Лицензии", href: "#" },
      { label: "Кейсы", href: "#" },
      { label: "Авторские права", href: "#" },
      { label: "Карта сайта", href: "#" },
    ],
  },
  {
    title: "Сотрудничество",
    links: [
      { label: "Госсектор", href: "#" },
      { label: "ВУЗы", href: "#" },
      { label: "Бизнес", href: "#" },
      { label: "Исследователи", href: "#" },
      { label: "AI-разработчики", href: "#" },
    ],
  },
  {
    title: "Поддержка",
    links: [
      { label: "Методическая", href: "#" },
      { label: "Техническая", href: "#" },
      {
        label: "Сообщить об ошибке",
        href: "https://docs.google.com/forms/d/1nxeKLnXPsboOnMWbjaa8Muy5dwd0xBvOppQKuyak3HY/viewform",
        external: true,
      },
      {
        label: "Предложить улучшения",
        href: "https://forms.gle/cPhpiWMRuMi25TX8A",
        external: true,
      },
      { label: "Релизы", href: "#" },
    ],
  },
];

// Колонка «Контакты» — обычные абзацы (в шаблоне НЕ ссылки).
export const FOOTER_CONTACTS: { title: string; items: FooterContactItem[] } = {
  title: "Контакты",
  items: [
    { lines: ["107450 Москва,", "ул. Мясницкая, 39/1"] },
    { lines: ["cisstat@cisstat.org"] },
    { lines: ["+7 (495) 624-30-92"] },
  ],
};

// Копирайт — как в шаблоне портала.
export const FOOTER_COPYRIGHT = "© 2026, СтатКомитет СНГ";

// Поиск по сайту — sr-only label и placeholder из шаблона портала.
export const FOOTER_SEARCH_LABEL = "Поиск по сайту";
export const FOOTER_SEARCH_PLACEHOLDER = "Поиск по сайту…";

// Юридические ссылки нижней строки — в шаблоне это НЕ <a>, а span
// с подчёркиванием (без href); сохраняем 1:1.
export const FOOTER_LEGAL_LINKS = [
  "Политика конфиденциальности",
  "Пользовательское соглашение",
  "Персональные данные",
];

// Фон футера главной страницы (постановка тимлида: «цвет футера на
// каждой странице будет свой, на главной странице — #CAD7F7»).
// Светлый лавандово-голубой, в палитре фоновых волн страницы.
export const FOOTER_HOME_BACKGROUND_COLOR = "#CAD7F7";