import { AccountScreen } from "@cisstat/ui/components/AccountScreen";
export const dynamic = "force-dynamic";
export const metadata = {
  title: "Аккаунт и команда — CISStat DataTime Lab",
  robots: { index: false, follow: false },
  referrer: "no-referrer",
};
export default function Page() {
  return <AccountScreen />;
}
