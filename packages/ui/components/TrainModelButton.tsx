// packages/ui/components/TrainModelButton.tsx
//
// ПРИМЕР использования контракта plans.ts. Кнопка скрывается для планов
// без can_train_models -- но это UX-удобство, НЕ защита: реальная
// проверка -- на бэкенде (apps/api/auth.py::require_capability).

import { getCapabilities, type Role, type PlanName } from "../lib/plans";
import { Button } from "./Button";

export function TrainModelButton({ role, plan }: { role: Role; plan: PlanName | null }) {
  const caps = getCapabilities(role, plan);

  if (!caps.canTrainModels) {
    return (
      <p className="text-xs text-neutral-500">
        Обучение моделей недоступно на текущем плане.{" "}
        <a href="/pricing" className="text-brand hover:underline">
          Обновить план →
        </a>
      </p>
    );
  }

  return <Button>Обучить модель</Button>;
}
