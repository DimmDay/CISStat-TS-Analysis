import Link from "next/link";
import type { LucideIcon } from "lucide-react";

export interface RouteCardProps {
  title: string;
  description: string;
  icon: LucideIcon;
  href: string;
}

/** Единая карточка маршрута для главной страницы и внутренних оглавлений. */
export function RouteCard({ title, description, icon: Icon, href }: RouteCardProps) {
  return (
    <Link
      href={href}
      className="group flex items-start gap-4 rounded-xl border border-brand/60 bg-brand-light/60 p-6 transition-colors hover:border-brand/90 hover:bg-brand-light/90 focus:outline-none focus-visible:ring-2 focus-visible:ring-brand/50 focus-visible:ring-offset-2"
    >
      <span
        className="flex h-11 w-11 shrink-0 items-center justify-center rounded-full bg-brand-light text-brand transition-colors group-hover:bg-brand group-hover:text-white"
        aria-hidden="true"
      >
        <Icon size={20} />
      </span>
      <span className="min-w-0">
        <span className="block text-sm font-semibold text-neutral-900 leading-snug">
          {title}
        </span>
        <span className="mt-1 block text-sm text-neutral-500 leading-relaxed">
          {description}
        </span>
      </span>
    </Link>
  );
}
