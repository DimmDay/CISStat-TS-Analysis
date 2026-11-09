import { AdminGate } from "@cisstat/ui/components/AdminGate";
import { DemoCampaignAdmin } from "@cisstat/ui/components/DemoCampaignAdmin";
export const dynamic = "force-dynamic";
export const metadata = {
  title: "Демо-кампании — CISStat DataTime Lab",
  robots: { index: false, follow: false },
  referrer: "no-referrer",
};
export default function Page() {
  return (
    <AdminGate returnTo="/admin/demo-campaigns">
      <DemoCampaignAdmin />
    </AdminGate>
  );
}
