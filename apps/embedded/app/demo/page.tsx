import { DemoEntry } from "@cisstat/ui/components/DemoEntry";
export const dynamic = "force-dynamic";
export const metadata = {
  title: "Демо-доступ — CISStat DataTime Lab",
  robots: { index: false, follow: false },
  referrer: "no-referrer",
};
export default function Page() {
  return <DemoEntry />;
}
