// packages/ui/components/MentorInlineWarning.test.tsx
//
// Тесты инлайн-баннера Наставника (Task PROGR-6, §7.2/§12 п.8):
// заметный цветной баннер, ВЕСЬ список предупреждений, «Продолжить всё
// равно» скрывает до нового preview, кнопка применения Мастера не
// блокируется (§12 п.8 -- видимость важнее принуждения).

import "@testing-library/jest-dom";
import { fireEvent, render, screen } from "@testing-library/react";
import { MentorInlineWarning } from "./MentorInlineWarning";
import type { SanityWarningInfo } from "../lib/mentor";

const WARNING_A: SanityWarningInfo = {
  rule_id: "no_effect",
  severity: "warning",
  message: "Выбранная стратегия не изменила ни одного значения.",
  suggested_action: "Проверьте параметр/порог метода.",
};

const WARNING_B: SanityWarningInfo = {
  rule_id: "excessive_data_loss",
  severity: "warning",
  message: "Стратегия удалит 40% строк датасета.",
  suggested_action: null,
};

describe("MentorInlineWarning", () => {
  it("рендерит весь список сработавших правил §7.2 с role=alert", () => {
    render(<MentorInlineWarning warnings={[WARNING_A, WARNING_B]} />);
    expect(screen.getByRole("alert")).toBeInTheDocument();
    expect(screen.getByText("Выбранная стратегия не изменила ни одного значения.")).toBeInTheDocument();
    expect(screen.getByText("Стратегия удалит 40% строк датасета.")).toBeInTheDocument();
    expect(screen.getByText("Проверьте параметр/порог метода.")).toBeInTheDocument();
  });

  it("«Продолжить всё равно» скрывает баннер (§12 п.8: не тихая подсказка)", () => {
    render(<MentorInlineWarning warnings={[WARNING_A]} />);
    expect(screen.getByText(WARNING_A.message)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Продолжить всё равно" }));
    expect(screen.queryByText(WARNING_A.message)).not.toBeInTheDocument();
  });

  it("новый preview (новый массив warnings) снова показывает баннер", () => {
    const { rerender } = render(<MentorInlineWarning warnings={[WARNING_A]} />);
    fireEvent.click(screen.getByRole("button", { name: "Продолжить всё равно" }));
    rerender(<MentorInlineWarning warnings={[WARNING_B]} />);
    expect(screen.getByText(WARNING_B.message)).toBeInTheDocument();
  });

  it("без предупреждений -- тихий null, ничего не рендерится", () => {
    const { container } = render(<MentorInlineWarning warnings={[]} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("severity=info отличается визуально от warning (чип «замечание»)", () => {
    render(
      <MentorInlineWarning
        warnings={[{ rule_id: "thrashing_detected", severity: "info", message: "Метания." }]}
      />,
    );
    expect(screen.getByText("замечание")).toBeInTheDocument();
  });
});
