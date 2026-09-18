// packages/ui/lib/tasks.ts
//
// Типы и API-хелперы модуля «Задачи» (v2, вертикальный срез «Причины» —
// spec_tasks_ia_addendum_v1_1.md §10/§10.1). Контракт зеркалит
// apps/api/routers/tasks_session.py::GET /v1/session/tasks/causes 1:1 —
// расхождение ловит typecheck и тесты компонента.
//
// Честная маркировка (§9.1): методы без session-артефакта приходят со
// статусом "not_computed" и причиной; клиент не додумывает данные.

import { sessionApiUrl } from "./apiClient";

export type CausesMethodStatus = "available" | "not_computed";

export interface CausesFactorFoldValue {
  fold: number;
  importance: number;
  share: number;
  matrix_hash: string | null;
}

export interface CausesFactor {
  feature_name: string;
  mean_share: number;
  n_folds: number;
  fold_values: CausesFactorFoldValue[];
}

export interface CausesProvenance {
  backtest_run_id: string | null;
  plan_id: string | null;
  n_folds: number;
}

export interface CausesMethod {
  method_id: string;
  kind: string;
  title: string;
  status: CausesMethodStatus;
  reason: string | null;
  factors: CausesFactor[] | null;
  provenance: CausesProvenance | null;
}

export interface CausesCardBlock {
  card_id: string;
  model_id: string | null;
  model_name: string | null;
  selection_kind: string;
  created_at: string | null;
}

export interface TasksCausesResponse {
  card: CausesCardBlock;
  methods: CausesMethod[];
}

export async function fetchCauses(cardId?: string): Promise<TasksCausesResponse> {
  const query = cardId ? `?card_id=${encodeURIComponent(cardId)}` : "";
  const resp = await fetch(`${sessionApiUrl("/tasks/causes")}${query}`, {
    credentials: "include",
  });
  if (!resp.ok) {
    const detail = await resp
      .json()
      .then((body: { detail?: string }) => body.detail)
      .catch(() => undefined);
    throw new Error(detail || `Не удалось загрузить данные задачи «Причины» (${resp.status})`);
  }
  return (await resp.json()) as TasksCausesResponse;
}
