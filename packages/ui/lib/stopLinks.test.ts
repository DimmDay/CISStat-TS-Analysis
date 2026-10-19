// packages/ui/lib/stopLinks.test.ts
//
// Тест-гвард узловых deep-link Наставника (Task MNS-LINK-3, план
// docs/mentor_next_step_review_2026-10-19.md §6; контракт --
// spec_mentor_next_step.md §5.3, решение Q6).
//
// Пины:
// - DEEP_LINK_STOP_STAGES -- ровно три warning-способные стадии канона
//   mns_canon_v2 (Q3/Q4: eda/modeling/forecasting excluded), в порядке
//   STAGES; узловый deep-link существует только для них (риск-строка
//   плана: «сначала только три warning-способные стадии»);
// - покрытие -- РОВНО 25 остановок (5 + 10 + 10), whitelist -- единый
//   источник PROGRESS_STAGE_NODES (копий нет; sync с бэкенд-графом
//   страхует test_progress_panel.py, читающий живой исходник progress.ts);
// - stopFromHash -- fail-closed (паттерн allowlist-перехвата PROGR-3):
//   неизвестный/чужой/пустой узел -> null, без угадывания и исключений.

import {
  DEEP_LINK_STOP_STAGES,
  GOTO_STOP_EVENT,
  dispatchGotoStop,
  stopAnchor,
  stopFromHash,
} from "./stopLinks";
import { PROGRESS_STAGE_NODES } from "./progress";

describe("DEEP_LINK_STOP_STAGES (канон mns_canon_v2: Q3/Q4)", () => {
  it("ровно три warning-способные стадии в порядке STAGES", () => {
    expect(DEEP_LINK_STOP_STAGES).toEqual(["upload", "validation", "preprocessing"]);
  });

  it("EDA/Моделирование/Прогнозирование в deep-link не входят (решения Q3/Q4)", () => {
    expect(DEEP_LINK_STOP_STAGES).not.toContain("eda");
    expect(DEEP_LINK_STOP_STAGES).not.toContain("modeling");
    expect(DEEP_LINK_STOP_STAGES).not.toContain("forecasting");
  });

  it("покрытие deep-link -- РОВНО 25 остановок (5 + 10 + 10), без копий реестра", () => {
    const total = DEEP_LINK_STOP_STAGES.reduce(
      (sum, stage) => sum + (PROGRESS_STAGE_NODES[stage]?.length ?? -1),
      0,
    );
    expect(total).toBe(25);
    // Каждая deep-link-стадия обязана быть известна единому реестру узлов:
    for (const stage of DEEP_LINK_STOP_STAGES) {
      expect(PROGRESS_STAGE_NODES[stage]).toBeDefined();
    }
  });
});

describe("stopAnchor", () => {
  it("якорь остановки -- «#stop=<node_id>» (контракт MNS-LINK-3)", () => {
    expect(stopAnchor("regularity")).toBe("#stop=regularity");
    expect(stopAnchor("overview")).toBe("#stop=overview");
    expect(stopAnchor("variance_stab")).toBe("#stop=variance_stab");
  });

  it("узел честно кодируется (encodeURIComponent)", () => {
    expect(stopAnchor("a b")).toBe("#stop=a%20b");
  });
});

describe("stopFromHash (fail-closed whitelist)", () => {
  it("известный узел своей стадии -- возвращается", () => {
    expect(stopFromHash("#stop=missing", "preprocessing")).toBe("missing");
    expect(stopFromHash("#stop=ranges", "validation")).toBe("ranges");
    expect(stopFromHash("#stop=quality", "upload")).toBe("quality");
  });

  it("закодированный узел декодируется; неизвестный декодированный — fail-closed", () => {
    expect(stopFromHash("#stop=feature_eng", "preprocessing")).toBe("feature_eng");
    // Декодирование происходит, но whitelist по РЕЕСТРУ узлов: «a b» --
    // не остановка, null (без исключений и угадывания).
    expect(stopFromHash("#stop=a%20b", "preprocessing")).toBeNull();
  });

  it("неизвестный узел -- null (степпер остаётся на дефолте)", () => {
    expect(stopFromHash("#stop=nope", "preprocessing")).toBeNull();
  });

  it("узел ЧУЖОЙ стадии -- null (whitelist по своей стадии)", () => {
    // "overview" -- остановка Загрузки, не Предобработки.
    expect(stopFromHash("#stop=overview", "preprocessing")).toBeNull();
    expect(stopFromHash("#stop=missing", "validation")).toBeNull();
  });

  it("пустое значение/нет ключа/мусор -- null без исключений", () => {
    expect(stopFromHash("#stop=", "validation")).toBeNull();
    expect(stopFromHash("#other=1", "validation")).toBeNull();
    expect(stopFromHash("", "validation")).toBeNull();
    expect(stopFromHash("stop=ranges", "validation")).toBeNull();
    expect(stopFromHash(undefined, "validation")).toBeNull();
    expect(stopFromHash(null, "validation")).toBeNull();
  });

  it("стадия вне реестра узлов -- null; известный узел ЛЮБОЙ стадии реестра -- возвращается (helper реестровый; ограничение тремя стадиями -- в resolveRecommendationLink)", () => {
    expect(stopFromHash("#stop=x", "not_a_stage")).toBeNull();
    // PROGRESS_STAGE_NODES содержит все 6 стадий (единый реестр графа):
    // helper отвечает за whitelist УЗЛА своей стадии, а не за состав
    // deep-link-стадий (тот пин -- в DEEP_LINK_STOP_STAGES выше и в
    // тестах resolveRecommendationLink: modeling.backtest -- фолбэк).
    expect(stopFromHash("#stop=backtest", "modeling")).toBe("backtest");
  });
});

describe("GOTO_STOP_EVENT (same-route переход из MentorPanel)", () => {
  it("константа события -- «cisstat:goto-stop»", () => {
    expect(GOTO_STOP_EVENT).toBe("cisstat:goto-stop");
  });

  it("dispatchGotoStop диспатчит CustomEvent с detail {stage, node_id}", () => {
    const spy = jest.fn();
    window.addEventListener(GOTO_STOP_EVENT, spy);
    try {
      dispatchGotoStop("validation", "uniqueness");
      expect(spy).toHaveBeenCalledTimes(1);
      const event = spy.mock.calls[0][0] as CustomEvent;
      expect(event.detail).toEqual({ stage: "validation", node_id: "uniqueness" });
    } finally {
      window.removeEventListener(GOTO_STOP_EVENT, spy);
    }
  });
});
