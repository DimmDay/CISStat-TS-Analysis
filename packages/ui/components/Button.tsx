// packages/ui/components/Button.tsx
import { ButtonHTMLAttributes } from "react";

type Variant = "primary" | "secondary";

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
}

const VARIANT_CLASSES: Record<Variant, string> = {
  primary: "bg-brand text-white hover:bg-brand/90",
  secondary: "bg-brand-light text-neutral-800 hover:bg-brand-light/70",
};

export function Button({ variant = "primary", className = "", ...props }: ButtonProps) {
  return (
    <button
      className={`rounded px-4 py-2 text-sm font-medium transition-colors ${VARIANT_CLASSES[variant]} ${className}`}
      {...props}
    />
  );
}
