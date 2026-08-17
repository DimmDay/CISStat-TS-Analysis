// packages/ui/components/Metric.tsx
//
// Карточка-метрика. Используется в Overview-блоках модулей анализа
// (валидация, EDA, навигатор и т.д.). value может быть длинным —
// например, имя файла активного датасета — поэтому переносим слово
// и зажимаем шрифт до text-base (был text-lg, вылезал за бейдж).
export function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="bg-brand-light rounded-lg px-3 py-2 min-w-0">
      <div className="text-xs text-neutral-500">{label}</div>
      <div
        className="text-sm font-normal text-neutral-900 break-words leading-tight"
        title={value}
      >
        {value}
      </div>
    </div>
  );
}
