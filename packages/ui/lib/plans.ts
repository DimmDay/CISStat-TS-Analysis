// AUTH-01: generated Pydantic/OpenAPI contract. UX only, server authorizes.
import {
  ACCESS_REGISTRY, INTERNAL_CAPABILITIES, PLAN_DEFINITIONS, REGISTRY_VERSION,
  type CapabilitiesUX, type PlanName, type Role,
} from "./access-contract.generated";

export { ACCESS_REGISTRY, PLAN_DEFINITIONS, REGISTRY_VERSION, capabilitiesFromDTO } from "./access-contract.generated";
export type { PlanName, Role, CapabilitiesDTO, OperationId } from "./access-contract.generated";
export type Capabilities = CapabilitiesUX;

/** Legacy UX adapter. Account-effective capabilities come from AUTH-08/me.
 * Never use the role argument to authorize admin, object or billing access.
 */
export function getCapabilities(role: Role, plan: PlanName | null): Capabilities {
  const value = role === "admin" || role === "internal_analyst"
    ? INTERNAL_CAPABILITIES : plan ? PLAN_DEFINITIONS[plan] : undefined;
  if (!value) throw new Error(`У роли ${role} нет плана, но getCapabilities вызван без него`);
  return { ...value, restrictedStageIds: [...value.restrictedStageIds], baselineLimits: { ...value.baselineLimits } };
}

/** Stage visibility only; soon/readiness and entitlement are separate concerns. */
export function hasStageAccess(caps: Capabilities, namespace: string, stageId: string): boolean {
  if (caps.registryVersion !== REGISTRY_VERSION) return false;
  if (!ACCESS_REGISTRY.stages.some(s => s.namespace === namespace && s.stage_id === stageId)) return false;
  return namespace !== "application" || !caps.restrictedStageIds.some(id => id === stageId);
}
