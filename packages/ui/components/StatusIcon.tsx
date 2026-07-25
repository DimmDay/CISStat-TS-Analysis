// packages/ui/components/StatusIcon.tsx
export type CheckStatus = "done" | "warning" | "pending";

const STATUS_ICON: Record<CheckStatus, string> = {
  done: "✅",
  warning: "⚠️",
  pending: "⬜",
};

export function StatusIcon({ status }: { status: CheckStatus }) {
  return <span aria-hidden>{STATUS_ICON[status]}</span>;
}

export { STATUS_ICON };
