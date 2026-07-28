// apps/embedded/app/analytics/ts-analysis/page.tsx
// Старый путь -- оставлен как редирект на унифицированный /preprocessing,
// чтобы не сломать уже существующие ссылки/закладки.
import { redirect } from "next/navigation";

export default function Page() {
  redirect("/preprocessing");
}
