// packages/ui/components/ModulePlaceholder.tsx
export function ModulePlaceholder({ title }: { title: string }) {
  return (
    <div className="text-center py-24 text-neutral-500">
      <h1 className="text-xl font-semibold text-neutral-800 mb-2">{title}</h1>
      <p>Модуль в разработке.</p>
    </div>
  );
}
