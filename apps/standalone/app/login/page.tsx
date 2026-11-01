import type { Metadata } from "next";
import { LoginScreen } from "@cisstat/ui/components/LoginScreen";
import { safeReturnTo } from "@cisstat/ui/lib/authClient";
export const dynamic = "force-dynamic";
export const metadata: Metadata = { title: "Вход — CISStat DataTime Lab", robots: { index: false, follow: false }, referrer: "no-referrer" };
export default function Page({searchParams}: {searchParams?: {return_to?: string | string[]}}) {
  return <LoginScreen returnTo={safeReturnTo(searchParams?.return_to)} />;
}
