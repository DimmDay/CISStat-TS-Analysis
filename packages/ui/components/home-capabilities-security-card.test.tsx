// packages/ui/components/home-capabilities-security-card.test.tsx
//
// Task UI-DEVNOTICE-1 (2026-11-09): карточка «Безопасность данных» —
// факт-апдейт текста. Сессии слоя 1 с V2.3 (2026-11-06) живут в
// PostgreSQL (PostgresSessionStore, миграция 0022, /health/ops
// session_backend=postgres), упоминание «Redis кэширует на бэкенде»
// устарело и вводило в заблуждение о контуре данных.
//
// Корпус дизъюнктен HomeCapabilities.test.tsx (практика синхронного
// ведения пинов — UI-HOME-BRAND-1): здесь пинится ТОЛЬКО текст/факты
// карточки, вид секции не затрагивается.

import "@testing-library/jest-dom";
import { CAPABILITIES } from "../lib/capabilities";

const SECURITY_CARD = CAPABILITIES.find(
  (card) => card.title === "Безопасность данных"
);

describe("UI-DEVNOTICE-1: карточка «Безопасность данных»", () => {
  it("карточка существует в CAPABILITIES", () => {
    expect(SECURITY_CARD).toBeDefined();
  });

  it("описание = точный новый текст: durable-состояние сессий в PostgreSQL", () => {
    expect(SECURITY_CARD!.description).toBe(
      "Данные не покидают контур: cookie-сессия в браузере, durable-состояние сессий — в PostgreSQL на бэкенде. Pre-signed и LTTB-сэмплинг для больших файлов."
    );
  });

  it("устаревшее упоминание Redis удалено из ВСЕХ карточек секции", () => {
    for (const card of CAPABILITIES) {
      expect(card.description).not.toContain("Redis");
    }
  });

  it("остальное в карточке не тронуто: заголовок и иконка прежние", () => {
    expect(SECURITY_CARD!.title).toBe("Безопасность данных");
    expect(SECURITY_CARD!.icon).toBeDefined();
  });
});
