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
  awaitStageInfo,
  ctaStageInfo,
  taskRecommendedHint,
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

// ── Мультиартефактные контракты: детерминизм порядка пайплайна (R4) ──
// Для v1-реестра все контракты одноартефактные; ветка «первый недостающий
// в порядке пайплайна» исполняется только синтетическими контрактами.
// Эти тесты оживляют сортировку ДО появления первого мультиартефактного
// контракта (мутант M7 аудита IA-1: удаление сортировки -> алфавитный
// порядок -> forecast_run выигрывает у model_card/validated).

describe("multi-artifact contracts: pipeline-order determinism (R4)", () => {
  it("first missing artifact follows pipeline order, not alphabetical", () => {
    // Все три артефакта недостающие -> первый по пайплайну validated.
    // Алфавитный порядок дал бы forecast_run («Прогнозирование»).
    const reason = taskGateReason(
      ["validated", "model_card", "forecast_run"],
      [],
      true
    );
    expect(reason).toContain("Валидация");
    expect(reason).not.toContain("Прогнозирование");
  });

  it("model_card beats forecast_run when both are missing", () => {
    const reason = taskGateReason(
      ["model_card", "forecast_run"],
      ["validated"],
      true
    );
    expect(reason).toContain("Моделирование");
    expect(reason).not.toContain("Прогнозирование");
  });

  it("pipeline order wins even when the contract is declared out of order", () => {
    // Контракт объявлен задом наперёд: sorting по requires-порядку
    // (или отсутствие компаратора) дал бы «Прогнозирование».
    const reason = taskGateReason(
      ["forecast_run", "model_card"],
      ["validated"],
      true
    );
    expect(reason).toContain("Моделирование");
    expect(reason).not.toContain("Прогнозирование");
    expect(reason).not.toContain("Валидация");
  });

  it("awaitStageInfo honours pipeline order for out-of-order contracts", () => {
    expect(
      awaitStageInfo(["forecast_run", "validated"], [], true)?.key
    ).toBe("validation");
  });

  it("present artifacts satisfy their part of a multi-artifact contract", () => {
    expect(
      deriveTaskGateState(
        ["validated", "forecast_run"],
        ["validated", "model_card", "forecast_run"],
        true
      )
    ).toBe("available");
    expect(
      deriveTaskGateState(["validated", "forecast_run"], ["validated"], true)
    ).toBe("awaiting");
  });
});

// ── awaitStageInfo: указатель этапа для микро-CTA (R5) ──────────

describe("awaitStageInfo", () => {
  it("returns the owner-stage pointer for an awaiting contract", () => {
    expect(awaitStageInfo(["model_card"], ["validated"], true)).toEqual({
      key: "modeling",
      label: "Моделирование",
      href: "/modeling",
    });
  });

  it("returns null for available and blocked states", () => {
    expect(awaitStageInfo(["model_card"], ["model_card"], true)).toBeNull();
    expect(awaitStageInfo(["model_card"], [], false)).toBeNull();
  });

  it("multi-artifact: pointer follows the first missing artifact in pipeline order", () => {
    expect(awaitStageInfo(["validated", "forecast_run"], [], true)?.key).toBe(
      "validation"
    );
    expect(
      awaitStageInfo(["model_card", "forecast_run"], ["validated"], true)?.href
    ).toBe("/modeling");
  });
});

// ── ctaStageInfo: СИММЕТРИЧНЫЙ микро-CTA (awaiting + blocked) ────
// Follow-up R5 (заказ тимлида): blocked-карточка получает тот же
// микро-CTA «Перейти к этапу …», что и awaiting. Ключевая семантика:
// в blocked пайплайн ещё НЕ начат, поэтому единственный осмысленный
// шаг — этап «Загрузка» (вход в пайплайн), а НЕ этап-владелец
// недостающего артефакта (до Загрузки он нереализуем).

describe("ctaStageInfo (symmetric micro-CTA: awaiting + blocked)", () => {
  it("blocked: points to Загрузка — the pipeline entry, not the artifact owner", () => {
    expect(ctaStageInfo(["model_card"], [], false)).toEqual({
      key: "upload",
      label: "Загрузка",
      href: "/upload",
    });
  });

  it("blocked: upload pointer regardless of the contract (even forecast-only)", () => {
    // Указывать на владельца недостающего артефакта («Прогнозирование»)
    // в blocked нельзя: до Загрузки ни один последующий этап недостижим.
    expect(ctaStageInfo(["forecast_run"], [], false)?.href).toBe("/upload");
    expect(
      ctaStageInfo(["validated", "model_card", "forecast_run"], [], false)
        ?.key
    ).toBe("upload");
  });

  it("awaiting: delegates to awaitStageInfo (owner stage of first missing)", () => {
    expect(ctaStageInfo(["model_card"], ["validated"], true)).toEqual(
      awaitStageInfo(["model_card"], ["validated"], true)
    );
    expect(ctaStageInfo(["model_card"], ["validated"], true)?.href).toBe(
      "/modeling"
    );
  });

  it("available: null — CTA не нужен", () => {
    expect(ctaStageInfo(["model_card"], ["model_card"], true)).toBeNull();
    expect(
      ctaStageInfo(["validated", "forecast_run"], ["validated", "model_card", "forecast_run"], false)
    ).toBeNull();
  });

  it("every registry task in a fresh session gets the upload pointer (hub symmetry)", () => {
    TASK_ROUTES.forEach((t) => {
      expect(ctaStageInfo(t.requires, [], false)).toEqual({
        key: "upload",
        label: "Загрузка",
        href: "/upload",
      });
    });
  });
});

// ── taskRecommendedHint: подсказка «рекомендуемый, не гейтящий» (R2) ──

describe("taskRecommendedHint", () => {
  it("returns null when the recommended artifact already exists", () => {
    expect(
      taskRecommendedHint(["forecast_run"], ["model_card", "forecast_run"])
    ).toBeNull();
  });

  it("returns null when nothing is recommended", () => {
    expect(taskRecommendedHint([], [])).toBeNull();
    expect(taskRecommendedHint([], ["model_card"])).toBeNull();
  });

  it("names the recommended stage when the artifact is missing", () => {
    expect(taskRecommendedHint(["forecast_run"], ["model_card"])).toBe(
      "Рекомендуется также этап Прогнозирование"
    );
  });

  it("scenarios registry entry declares forecast_run as recommendedWith (spec §2)", () => {
    const scenarios = TASK_ROUTES.find((t) => t.id === "scenarios");
    expect(scenarios?.recommendedWith).toEqual(["forecast_run"]);
    // Остальные задачи v1 подсказок не объявляют.
    TASK_ROUTES.filter((t) => t.id !== "scenarios").forEach((t) =>
      expect(t.recommendedWith).toBeUndefined()
    );
  });
});
