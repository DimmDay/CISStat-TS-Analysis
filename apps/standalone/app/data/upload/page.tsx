// apps/standalone/app/data/upload/page.tsx
import { DataUploadForm } from "@cisstat/ui";

export default function Page() {
  return (
    <div>
      <h1 className="text-xl font-semibold mb-4">Загрузка</h1>
      <DataUploadForm />
    </div>
  );
}
