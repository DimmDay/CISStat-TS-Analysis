// packages/ui/components/StepperNextModuleButton.tsx
//
// Паттерн платформы "Ведём исследователя за руку": после прохождения
// пайплайна текущего модуля логично пригласить аналитика перейти
// к следующему шагу общего исследования (Загрузка → Валидация →
// Предобработка → Разведочный EDA → Моделирование → Прогнозирование).
//
// Один переиспользуемый компонент для ВСЕХ степперов платформы --
// каждая вкладка передаёт только текст приглашения и ссылку на
// следующий модуль; разметка и стили общие, не дублируются по вкладкам.
// Размещается непосредственно под последней кнопкой степпера, как
// логическое продолжение того же списка остановок, но визуально
// отделено светло-серой чертой (bordter-t) -- это переход к другому
// модулю, а не ещё одна остановка текущего.
//
// Стилевой контракт (см. обсуждение задачи "Загрузка → кнопка
// 'Перейти к валидации'"):
//   1. Тот же размер, что и кнопки степпера -- те же rounded-md/border/
//      px-3 py-2/text-sm.
//   2. Отделяется от последней кнопки степпера светло-серой чертой
//      (border-t border-neutral-200 у обёртки).
//   3. Та же рамка, что у кнопок степпера, но статичный пастельный
//      оттенок фона -- тот же bg-brand-light/50, что и у окна "Описание"
//      (НЕ рамка "Описания" -- rounded-lg там; рамка здесь -- степпера).
//   4. При наведении -- фирменный индиго (bg-brand) и белый текст.
//   5. Переход по next/link на следующий модуль.
import Link from "next/link";
import { ArrowRight } from "lucide-react";

interface StepperNextModuleButtonProps {
  /** Текст приглашения, например "Перейти к валидации". */
  label: string;
  /** Путь следующего модуля, например "/validation". */
  href: string;
}

export function StepperNextModuleButton({ label, href }: StepperNextModuleButtonProps) {
  return (
    <div className="w-full mt-1 pt-2 border-t border-neutral-200">
      <Link
        href={href}
        className="w-full flex items-center justify-center gap-2 rounded-md border border-neutral-200 bg-brand-light/50 px-3 py-2 text-sm font-medium text-neutral-800 transition-colors hover:bg-brand hover:border-brand hover:text-white"
      >
        <span className="truncate">{label}</span>
        <ArrowRight size={14} className="shrink-0" aria-hidden="true" />
      </Link>
    </div>
  );
}
