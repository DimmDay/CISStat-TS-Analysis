// packages/ui/components/HomeFooter.tsx
//
// Футер главной страницы standalone (Task w/n, 2026-09-13).
//
// Шаблон — футер главной страницы портала CISStat
// (https://cis-stat-portal-k9tu.vercel.app/), команда тимлида: «Забери
// шаблон футера с главной страницы портала. Блок с текстом под футером
// игнорируй. Пересобери заново». Структура 1:1 из продового DOM портала:
//   1) сетка grid-cols-4 gap-5: Проект / Сотрудничество / Поддержка /
//      Контакты — заголовки mb-2 text-xs font-semibold uppercase
//      tracking-wide, ссылки mb-1 block text-[12.5px], контакты —
//      обычные <p>, адрес в 2 строки через <br/>;
//   2) внутренний разделитель my-3 border-t — ЧАСТЬ шаблона (убранная
//      по постановке черта — это разделитель МЕЖДУ контентом страницы
//      и футером, его гасит HomeCapabilities, правка 8);
//   3) нижняя строка flex pb-3: копирайт + поиск (role="search",
//      sr-only label, input, иконки lucide search / corner-down-left —
//      скопированы из шаблона) + 3 юридических span с underline.
// Блок legal-дисклеймера портала (bg-footer-legal) — ИГНОРИРУЕТСЯ
// по прямой команде тимлида.
//
// Адаптация тёмной темы шаблона под постановку standalone (фон/текст):
//   - bg-footer #5B5B5B → проп backgroundColor (на главной #CAD7F7);
//   - text-white / text-neutral-300 → чёрный текст (text-black);
//   - border-white/20 → border-black/20; bg-white/10 формы → bg-white/40;
//   - hover:text-white → hover:underline (светлая тема);
//   - decoration-white/30 → decoration-black/30.
// Плюс требования главной страницы standalone: углы rounded-2xl по
// паттерну фоновой коробки HomeWavesBackground; футер подключён только
// на главной (apps/standalone/app/page.tsx), embedded не затронут.
//
// Контент дата-дривен из lib/homeFooter.ts. Без "use client":
// компонент полностью статичен, форма поиска — нативная (как в
// шаблоне, без action), интерактивность — только нативные ссылки.

import { Fragment } from "react";
import {
  FOOTER_COLUMNS,
  FOOTER_CONTACTS,
  FOOTER_COPYRIGHT,
  FOOTER_SEARCH_LABEL,
  FOOTER_SEARCH_PLACEHOLDER,
  FOOTER_LEGAL_LINKS,
  FOOTER_HOME_BACKGROUND_COLOR,
} from "../lib/homeFooter";

export function HomeFooter({
  backgroundColor = FOOTER_HOME_BACKGROUND_COLOR,
}: {
  /** Фон футера — свой для каждой страницы; на главной — #CAD7F7. */
  backgroundColor?: string;
}) {
  return (
    <footer
      aria-label="Подвал сайта"
      className="rounded-2xl px-7 pt-4 text-black"
      style={{ backgroundColor }}
    >
      <div className="grid grid-cols-4 gap-5">
        {FOOTER_COLUMNS.map((column) => (
          <div key={column.title}>
            <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-black">
              {column.title}
            </p>
            {column.links.map((link) =>
              link.external ? (
                <a
                  key={link.label}
                  href={link.href}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="mb-1 block text-[12.5px] text-black hover:underline focus-visible:underline"
                >
                  {link.label}
                </a>
              ) : (
                <a
                  key={link.label}
                  href={link.href}
                  className="mb-1 block text-[12.5px] text-black hover:underline focus-visible:underline"
                >
                  {link.label}
                </a>
              ),
            )}
          </div>
        ))}
        <div>
          <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-black">
            {FOOTER_CONTACTS.title}
          </p>
          {FOOTER_CONTACTS.items.map((item, index) => (
            <p
              key={item.lines[0]}
              className={
                index < FOOTER_CONTACTS.items.length - 1
                  ? "mb-1 text-[12.5px] text-black"
                  : "text-[12.5px] text-black"
              }
            >
              {item.lines.map((line, lineIndex) => (
                <Fragment key={line}>
                  {lineIndex > 0 && <br />}
                  {line}
                </Fragment>
              ))}
            </p>
          ))}
        </div>
      </div>
      <div className="my-3 border-t border-black/20" aria-hidden="true" />
      <div className="flex flex-wrap items-center gap-3 pb-3">
        <span className="flex-shrink-0 whitespace-nowrap text-xs text-black">
          {FOOTER_COPYRIGHT}
        </span>
        <div className="min-w-[160px] flex-1">
          <form
            role="search"
            className="flex w-full items-center gap-2 rounded-md border border-black/20 bg-white/40 px-3 py-1.5"
          >
            <svg
              stroke="currentColor"
              fill="none"
              strokeWidth="2"
              viewBox="0 0 24 24"
              strokeLinecap="round"
              strokeLinejoin="round"
              className="flex-shrink-0 text-black/50"
              aria-hidden="true"
              height="15"
              width="15"
              xmlns="http://www.w3.org/2000/svg"
            >
              <circle cx="11" cy="11" r="8"></circle>
              <path d="m21 21-4.3-4.3"></path>
            </svg>
            <label htmlFor="footer-search" className="sr-only">
              {FOOTER_SEARCH_LABEL}
            </label>
            <input
              id="footer-search"
              type="text"
              placeholder={FOOTER_SEARCH_PLACEHOLDER}
              className="flex-1 bg-transparent text-[12.5px] text-black placeholder:text-black/50 outline-none"
            />
            <svg
              stroke="currentColor"
              fill="none"
              strokeWidth="2"
              viewBox="0 0 24 24"
              strokeLinecap="round"
              strokeLinejoin="round"
              className="flex-shrink-0 text-black/40"
              aria-hidden="true"
              height="13"
              width="13"
              xmlns="http://www.w3.org/2000/svg"
            >
              <polyline points="9 10 4 15 9 20"></polyline>
              <path d="M20 4v7a4 4 0 0 1-4 4H4"></path>
            </svg>
          </form>
        </div>
        <div className="flex flex-shrink-0 flex-wrap gap-4">
          {FOOTER_LEGAL_LINKS.map((label) => (
            <span
              key={label}
              className="whitespace-nowrap text-xs text-black underline decoration-black/30"
            >
              {label}
            </span>
          ))}
        </div>
      </div>
    </footer>
  );
}