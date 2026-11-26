type ErrorFields = { code: string | null; message: string | null };
const record = (value: unknown): Record<string, unknown> =>
  value !== null && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown> : {};

/** PGV flat errors and the existing trusted FastAPI authority envelope. */
export function parseExportErrorBody(value: unknown): ErrorFields {
  const body = record(value);
  for (const item of [body, record(body.error), record(body.detail)]) {
    if (typeof item.code === "string" || typeof item.message === "string") {
      return {
        code: typeof item.code === "string" ? item.code : null,
        message: typeof item.message === "string" ? item.message : null,
      };
    }
  }
  return { code: null, message: null };
}

export function exportAuthorityErrorText(code: string | null): string | null {
  const messages: Record<string, string> = {
    worker_service_unavailable: "Сервис печати не настроен — обратитесь к администратору.",
    budget_not_configured: "Лимиты печати не настроены — обратитесь к администратору.",
    concurrency_exceeded: "Достигнут лимит одновременных операций — дождитесь завершения текущей задачи и повторите экспорт.",
    authentication_required: "Для экспорта необходимо войти в аккаунт.",
    invalid_credential: "Сеанс входа завершён — войдите снова и повторите экспорт.",
    capability_not_included: "Экспорт недоступен в текущем плане.",
  };
  return code && Object.prototype.hasOwnProperty.call(messages, code) ? messages[code] : null;
}
