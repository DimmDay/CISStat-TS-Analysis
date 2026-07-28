// apps/standalone/app/dashboard/ts-analysis/page.tsx
// Старый путь -- оставлен как редирект на унифицированный /preprocessing.
import { redirect } from "next/navigation";

export default function Page() {
  redirect("/preprocessing");
}
