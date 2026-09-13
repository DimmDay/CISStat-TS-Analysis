// packages/ui/lib/task-stops.test.ts
//
// Тесты реестра задач хаба «Задачи» и логики гейтинга по контракту входа
// (spec_tasks_ia.md §4-5, §8).
//
// Ключевые контракты:
//   - Реестр: 4 задачи v1 (Сценарии, Причины, Принятие решений, Мониторинг
//     прогноза), уникальные id/href, href начинаются с /tasks/, требуют
//     непустой контракт входа.
//   - Слой артефактов: stages -> TaskArtifact (артефакт существует, когда
//     его этап = "done").
//   - Три состояния: available (requires ⊆ artifacts) / awaiting (частично,
//     пайплайн начат) / blocked (свежая сессия).
//   - Причины некликабельных состояний называют этап-владелец недостающего
//     артефакта («…после этапа Моделирование» и т.п.).

import {
  TASK_ROUTES,
  TaskArtifact,
  ARTIFACT_STAGE,
  artifactsFromStages,
  pipelineStartedFromStages,
  deriveTaskGateState,
  taskGateReason,
} from "./task-stops";
import { STAGE_DEFS, StageStatus } from "./stages";

// ── Реестр задач (spec §5) ──────────────────────────────────────

describe("TASK_ROUTES registry", () => {
  it("contains exactly the 4 v1 tasks in pipeline-branching order", () => {
    expect(TASK_ROUTES.map((t) => t.id)).toEqual([
      "scenarios",
      "causes",
      "decisions",
      "monitoring",
    ]);
    expect(TASK_ROUTES.map((t) => t.title)).toEqual([
      "Сценарии",
      "Причины",
      "Принятие решений",
      "Мониторинг прогноза",
    ]);
  });

  it("every task has a unique href under /tasks/ with icon, title and description", () => {
    const hrefs = TASK_ROUTES.map((t) => t.href);
    expect(new Set(hrefs).size).toBe(TASK_ROUTES.length);
    TASK_ROUTES.forEach((t) => {
      expect(t.href).toMatch(/^\/tasks\/[a-z-]+$/);
      expect(t.title.length).toBeGreaterThan(0);
      expect(t.description.length).toBeGreaterThan(0);
      // LucideIcon в lucide-react — ForwardRef-компонент (объект, не функция).
      expect(t.icon).toBeTruthy();
    });
  });

  it("every task declares a non-empty input contract of valid artifacts", () => {
    const valid: TaskArtifact[] = ["validated", "model_card", "forecast_run"];
    TASK_ROUTES.forEach((t) => {
      expect(t.requires.length).toBeGreaterThan(0);
      t.requires.forEach((a) => expect(valid).toContain(a));
    });
  });

  it("contract encodes forecast-dependency analysis of spec_tasks_ia.md §2", () => {
    // Причины и Сценарии — от модели (прогноз НЕ гейтит);
    // Принятие решений и Мониторинг — от прогноза.
    const byId = Object.fromEntries(TASK_ROUTES.map((t) => [t.id, t]));
    expect(byId.causes.requires).toEqual(["model_card"]);
    expect(byId.scenarios.requires).toEqual(["model_card"]);
    expect(byId.decisions.requires).toEqual(["forecast_run"]);
    expect(byId.monitoring.requires).toEqual(["forecast_run"]);
  });

  it("ARTIFACT_STAGE maps every artifact to a real STAGE_DEFS key", () => {
    const stageKeys = STAGE_DEFS.map((s) => s.key);
    (Object.keys(ARTIFACT_STAGE) as TaskArtifact[]).forEach((a) => {
      expect(stageKeys).toContain(ARTIFACT_STAGE[a]);
    });
  });
});

// ── Слой артефактов: stages -> artifacts ────────────────────────

const stagesOf = (over: Record<string, StageStatus>) =>
  Object.fromEntries(STAGE_DEFS.map((s) => [s.key, over[s.key] ?? "pending"]));

describe("artifactsFromStages", () => {
  it("maps done stages to artifacts and ignores pending/in_progress", () => {
    const artifacts = artifactsFromStages(
      stagesOf({ validation: "done", modeling: "in_progress" })
    );
    expect(artifacts).toContain("validated");
    expect(artifacts).not.toContain("model_card");
    expect(artifacts).not.toContain("forecast_run");
  });

  it("full done pipeline yields all three artifacts", () => {
    const artifacts = artifactsFromStages(
      stagesOf({
        validation: "done",
        preprocessing: "done",
        eda: "done",
        modeling: "done",
        forecasting: "done",
      })
    );
    expect(artifacts).toEqual(["validated", "model_card", "forecast_run"]);
  });

  it("fresh session yields no artifacts", () => {
    expect(artifactsFromStages(stagesOf({}))).toEqual([]);
  });
});

describe("pipelineStartedFromStages", () => {
  it("is false for a fresh session and true once any stage is done", () => {
    expect(pipelineStartedFromStages(stagesOf({}))).toBe(false);
    expect(pipelineStartedFromStages(stagesOf({ upload: "in_progress" }))).toBe(false);
    expect(pipelineStartedFromStages(stagesOf({ upload: "done" }))).toBe(true);
  });
});

// ── Три состояния (spec §4) ─────────────────────────────────────

describe("deriveTaskGateState", () => {
  const MODEL_ONLY = ["model_card" as TaskArtifact];

  it("available when the whole contract is satisfied", () => {
    expect(
      deriveTaskGateState(MODEL_ONLY, ["model_card"], true)
    ).toBe("available");
    expect(
      deriveTaskGateState(MODEL_ONLY, ["validated", "model_card"], true)
    ).toBe("available");
  });

  it("awaiting when partially satisfied and the pipeline has started", () => {
    expect(deriveTaskGateState(MODEL_ONLY, [], true)).toBe("awaiting");
    // Даже нулевой прогресс ПО КОНТРАКТУ — awaiting, если пайплайн движется.
  });

  it("blocked when the contract is unsatisfied and the session is fresh", () => {
    expect(deriveTaskGateState(MODEL_ONLY, [], false)).toBe("blocked");
  });

  it("available wins over awaiting/blocked regardless of pipelineStarted", () => {
    expect(
      deriveTaskGateState(MODEL_ONLY, ["model_card"], false)
    ).toBe("available");
  });
});

describe("taskGateReason", () => {
  it("returns null for available tasks", () => {
    expect(
      taskGateReason(["model_card"], ["model_card"], true)
    ).toBeNull();
  });

  it("awaiting reason names the owning stage label of the first missing artifact", () => {
    const reason = taskGateReason(["model_card"], ["validated"], true);
    expect(reason).toContain("Моделирование");
    expect(reason).toMatch(/Станет доступна после этапа/);
  });

  it("awaiting reason for forecast-only tasks names Прогнозирование", () => {
    const reason = taskGateReason(["forecast_run"], ["validated"], true);
    expect(reason).toContain("Прогнозирование");
  });

  it("blocked reason points to the pipeline start (Загрузка)", () => {
    const reason = taskGateReason(["model_card"], [], false);
    expect(reason).toContain("Загрузка");
  });
});
