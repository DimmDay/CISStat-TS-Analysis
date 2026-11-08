/** Human-readable policy errors; never stringify opaque server/input objects. */
export function scientificErrorMessage(detail: unknown): string | null {
  if (typeof detail === "string") return detail.trim() || null;
  if (detail && typeof detail === "object" && !Array.isArray(detail)) {
    const message = (detail as Record<string, unknown>).message;
    if (typeof message === "string") return message.trim() || null;
  }
  return null;
}
