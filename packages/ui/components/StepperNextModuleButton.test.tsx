// packages/ui/components/StepperNextModuleButton.test.tsx
import { render, screen, fireEvent } from "@testing-library/react";
import "@testing-library/jest-dom";
import { StepperNextModuleButton } from "./StepperNextModuleButton";

describe("StepperNextModuleButton", () => {
  it("рендерит переданный текст приглашения и ссылку на следующий модуль", () => {
    render(<StepperNextModuleButton label="Перейти к валидации" href="/validation" />);

    const link = screen.getByRole("link", { name: /Перейти к валидации/ });
    expect(link).toBeInTheDocument();
    expect(link).toHaveAttribute("href", "/validation");
  });

  it("в состоянии по умолчанию использует статичный пастельный фон (bg-brand-light), а не фирменный индиго", () => {
    render(<StepperNextModuleButton label="Перейти к валидации" href="/validation" />);

    const link = screen.getByRole("link", { name: /Перейти к валидации/ });
    expect(link.className).toContain("bg-brand-light");
    expect(link.className).not.toMatch(/(?<!hover:)bg-brand(?!-light)/);
  });

  it("имеет hover-классы фирменного индиго и белого текста, не окрашенные в состоянии по умолчанию", () => {
    render(<StepperNextModuleButton label="Перейти к валидации" href="/validation" />);

    const link = screen.getByRole("link", { name: /Перейти к валидации/ });
    expect(link.className).toContain("hover:bg-brand");
    expect(link.className).toContain("hover:text-white");
  });

  it("использует ту же рамку (border + rounded-md), что и кнопки степпера", () => {
    render(<StepperNextModuleButton label="Перейти к валидации" href="/validation" />);

    const link = screen.getByRole("link", { name: /Перейти к валидации/ });
    expect(link.className).toContain("rounded-md");
    expect(link.className).toContain("border");
  });

  it("отделяется от предыдущего элемента списка светло-серой чертой-разделителем", () => {
    const { container } = render(<StepperNextModuleButton label="Перейти к валидации" href="/validation" />);

    const wrapper = container.firstElementChild;
    expect(wrapper?.className).toContain("border-t");
    expect(wrapper?.className).toContain("border-neutral-200");
  });
});
