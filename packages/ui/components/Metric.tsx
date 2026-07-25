// packages/ui/components/Metric.tsx
export function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="bg-brand-light rounded-lg px-3 py-2">
      <div className="text-xs text-neutral-500">{label}</div>
      <div className="text-lg font-semibold text-neutral-900">{value}</div>
    </div>
  );
}
