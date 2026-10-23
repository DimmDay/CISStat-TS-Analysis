// packages/ui/components/doclog6-lifecycle-ui.test.tsx
//
// DOCLOG-6 (спека §11, §12.2, §12.3, AC07/AC17): панель жизненного
// цикла в DocumentationWorkspace -- состояния текстом (цвет НЕ
// единственный носитель), действия по состоянию (§11: draft ->
// ready_for_review -> approved -> published; терминальные -- без
// действий), честные тексты отказов (403/409/422/503), история
// append-only, diff без пересчётов.
//
// Оракулы на СВОИХ данных: клиенты lib/documentation мокаются; корпус
// дизъюнктен серверным репо-сюитам (tests/api).

import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { DocumentationWorkspace, lifecycleErrorText, LIFECYCLE_STATE_LABELS } from "./DocumentationWorkspace";
import * as documentation from "../lib/documentation";

jest.mock("../lib/documentation", () => {
  const actual = jest.requireActual("../lib/documentation");
  return {
    ...actual,
    listDocuments: jest.fn(),
    getRevision: jest.fn(),
    getLifecycle: jest.fn(),
    requestApproval: jest.fn(),
    decideApproval: jest.fn(),
    publishRevision: jest.fn(),
    retractRevision: jest.fn(),
    getRevisionDiff: jest.fn(),
    requestRendition: jest.fn(),
    createDraft: jest.fn(),
    cancelJob: jest.fn(),
    getJob: jest.fn(),
  };
});

const mocked = documentation as jest.Mocked<typeof documentation>;

const REVISION_ID = "drev-d6aaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";
const PREV_REVISION_ID = "drev-d6bbbbbbbbbbbbbbbbbbbbbbbbbbbbbb";

function documentWithRevisions(): documentation.DocumentSummary {
  return {
    document_id: "doc-d6aaaaaaaaaaaaaaaaaaaaaaaaaaaaaa01",
    run_id: "RUN-D6A00001",
    kind_code: "D02",
    title: "Паспорт источника",
    current_revision_id: REVISION_ID,
    created_by: null,
    created_at: "2026-10-23T10:00:00Z",
    revisions: [
      {
        revision_id: PREV_REVISION_ID,
        document_id: "doc-d6aaaaaaaaaaaaaaaaaaaaaaaaaaaaaa01",
        snapshot_id: "rs-d6bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
        run_id: "RUN-D6A00001",
        version_no: 1,
        created_by: null,
        created_at: "2026-10-23T09:00:00Z",
        lifecycle_state: "superseded",
        renditions: [],
      },
      {
        revision_id: REVISION_ID,
        document_id: "doc-d6aaaaaaaaaaaaaaaaaaaaaaaaaaaaaa01",
        snapshot_id: "rs-d6aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        run_id: "RUN-D6A00001",
        version_no: 2,
        created_by: null,
        created_at: "2026-10-23T10:00:00Z",
        lifecycle_state: "draft",
        renditions: [],
      },
    ],
  };
}

function snapshotPayload(): documentation.SnapshotPayload {
  return {
    schema_version: "doclog.report_snapshot/1",
    snapshot_id: "rs-d6aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    research_run_id: "RUN-D6A00001",
    context_id: "ctx-d6-1",
    data_revision: 2,
    data_ref: null,
    data_digest: null,
    source_cutoff: {},
    captured_at: "2026-10-23T10:00:00Z",
    template: { id: "research-report", version: "1.0" },
    knowledge_version: null,
    locale: "ru-RU",
    display_timezone: "Europe/Moscow",
    classification: "private",
    redaction_profile: "owner-v1",
    completeness: { status: "complete", missing_refs: [] },
    reproducibility: { status: "ready", reasons: [] },
    sections: [],
    dependencies: [],
    approval: null,
  };
}

async function renderWorkspace(lifecycleState: string) {
  const doc = documentWithRevisions();
  doc.revisions[1].lifecycle_state = lifecycleState as documentation.LifecycleState;
  mocked.listDocuments.mockResolvedValue({
    ok: true,
    status: 200,
    data: { run_id: "RUN-D6A00001", documents: [doc] },
  });
  mocked.getRevision.mockResolvedValue({
    ok: true,
    status: 200,
    data: {
      revision: doc.revisions[1],
      document: doc,
      snapshot: snapshotPayload(),
      renditions: [],
    },
  });
  mocked.getLifecycle.mockResolvedValue({
    ok: true,
    status: 200,
    data: {
      revision_id: REVISION_ID,
      records: [
        {
          record_id: "dlc-d6aaaaaaaaaaaaaaaaaaaaaaaaaaaaaa01",
          document_id: doc.document_id,
          revision_id: REVISION_ID,
          run_id: "RUN-D6A00001",
          event: "approval_requested",
          actor_subject: "subj-d6",
          reason: "",
          details: {},
          created_at: "2026-10-23T10:05:00Z",
        },
      ],
    },
  });
  render(<DocumentationWorkspace runId="RUN-D6A00001" />);
  await waitFor(() => {
    expect(screen.getByTestId("doclog6-lifecycle-panel")).toBeInTheDocument();
  });
}

describe("DOCLOG-6 lifecycle panel", () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  test("виды D10/D11 присутствуют в левом списке", async () => {
    await renderWorkspace("draft");
    expect(screen.getByTestId("doclog4-kind-D10")).toBeInTheDocument();
    expect(screen.getByTestId("doclog4-kind-D11")).toBeInTheDocument();
    expect(screen.getByText("Рекомендации и ограничения")).toBeInTheDocument();
    expect(screen.getByText("Итоговый отчёт")).toBeInTheDocument();
  });

  test("состояние draft -- текстовая метка + кнопка запроса согласования", async () => {
    await renderWorkspace("draft");
    expect(screen.getByTestId("doclog6-lifecycle-state")).toHaveTextContent(
      "Черновик (draft)",
    );
    expect(screen.getByTestId("doclog6-action-request")).toBeInTheDocument();
    expect(
      screen.queryByTestId("doclog6-action-approve"),
    ).not.toBeInTheDocument();
  });

  test("запрос согласования: вызов клиента и перечитывание состояния", async () => {
    await renderWorkspace("draft");
    mocked.requestApproval.mockResolvedValue({
      ok: true,
      status: 200,
      data: { revision: documentWithRevisions().revisions[1] },
    });
    fireEvent.click(screen.getByTestId("doclog6-action-request"));
    await waitFor(() => {
      expect(mocked.requestApproval).toHaveBeenCalledWith(REVISION_ID);
    });
    // После успеха -- перечитывание версии и истории (сервер -- истина).
    await waitFor(() => {
      expect(mocked.getRevision).toHaveBeenCalledTimes(2);
    });
  });

  test("состояние ready_for_review -- Утвердить/Отклонить", async () => {
    await renderWorkspace("ready_for_review");
    expect(screen.getByTestId("doclog6-lifecycle-state")).toHaveTextContent(
      "На согласовании (ready_for_review)",
    );
    expect(screen.getByTestId("doclog6-action-approve")).toBeInTheDocument();
    expect(screen.getByTestId("doclog6-action-reject")).toBeInTheDocument();
  });

  test("состояние approved -- Опубликовать", async () => {
    await renderWorkspace("approved");
    expect(screen.getByTestId("doclog6-action-publish")).toBeInTheDocument();
  });

  test("состояние published -- Отозвать с причиной", async () => {
    await renderWorkspace("published");
    expect(screen.getByTestId("doclog6-action-retract")).toBeInTheDocument();
    expect(screen.getByTestId("doclog6-retract-reason")).toBeInTheDocument();
    mocked.retractRevision.mockResolvedValue({
      ok: true,
      status: 200,
      data: { revision: documentWithRevisions().revisions[1] },
    });
    fireEvent.change(screen.getByTestId("doclog6-retract-reason"), {
      target: { value: "ошибка входных данных" },
    });
    fireEvent.click(screen.getByTestId("doclog6-action-retract"));
    await waitFor(() => {
      expect(mocked.retractRevision).toHaveBeenCalledWith(
        REVISION_ID,
        "ошибка входных данных",
      );
    });
  });

  test.each(["rejected", "retracted", "superseded"] as const)(
    "терминальное состояние %s -- без действий, честная подпись",
    async (state) => {
      await renderWorkspace(state);
      expect(screen.queryByTestId("doclog6-action-request")).not.toBeInTheDocument();
      expect(screen.queryByTestId("doclog6-action-approve")).not.toBeInTheDocument();
      expect(screen.queryByTestId("doclog6-action-publish")).not.toBeInTheDocument();
      expect(
        screen.getByText(LIFECYCLE_STATE_LABELS[state]),
      ).toBeInTheDocument();
    },
  );

  test("отказ 403 -- честный текст insufficient_scope (role=alert)", async () => {
    await renderWorkspace("draft");
    mocked.requestApproval.mockResolvedValue({ ok: false, status: 403 });
    fireEvent.click(screen.getByTestId("doclog6-action-request"));
    await waitFor(() => {
      const alert = screen.getByTestId("doclog6-lifecycle-error");
      expect(alert).toHaveAttribute("role", "alert");
      expect(alert).toHaveTextContent("insufficient_scope");
    });
  });

  test("отказ 409 -- честный текст approval_not_applicable (AC07)", async () => {
    await renderWorkspace("approved");
    mocked.publishRevision.mockResolvedValue({ ok: false, status: 409 });
    fireEvent.click(screen.getByTestId("doclog6-action-publish"));
    await waitFor(() => {
      expect(screen.getByTestId("doclog6-lifecycle-error")).toHaveTextContent(
        "approval_not_applicable",
      );
    });
  });

  test("отказ 503 -- fail-closed аудит", async () => {
    await renderWorkspace("draft");
    mocked.requestApproval.mockResolvedValue({ ok: false, status: 503 });
    fireEvent.click(screen.getByTestId("doclog6-action-request"));
    await waitFor(() => {
      expect(screen.getByTestId("doclog6-lifecycle-error")).toHaveTextContent(
        "fail-closed",
      );
    });
  });

  test("история append-only рендерится (§12.2 «История»)", async () => {
    await renderWorkspace("draft");
    const history = screen.getByTestId("doclog6-lifecycle-history");
    expect(history).toHaveTextContent("Запрошено согласование");
  });

  test("diff с предыдущей версией -- без пересчётов", async () => {
    await renderWorkspace("draft");
    mocked.getRevisionDiff.mockResolvedValue({
      ok: true,
      status: 200,
      data: {
        revision_id: REVISION_ID,
        against_revision_id: PREV_REVISION_ID,
        metadata: {
          captured_at: { from: "2026-10-23T09:00:00Z", to: "2026-10-23T10:00:00Z" },
        },
        claims: {
          added: [{ code: "D02", text: "новое утверждение", validity: "current" }],
          removed: [],
          validity_changed: [],
        },
        recalculated: false,
      },
    });
    fireEvent.click(screen.getByTestId("doclog6-diff-button"));
    await waitFor(() => {
      expect(screen.getByTestId("doclog6-diff-panel")).toHaveTextContent(
        "без пересчётов",
      );
      expect(screen.getByTestId("doclog6-diff-panel")).toHaveTextContent(
        "Добавлено утверждений: 1",
      );
    });
  });

  test("lifecycleErrorText -- честные тексты по статусам", () => {
    expect(lifecycleErrorText(403)).toContain("insufficient_scope");
    expect(lifecycleErrorText(409)).toContain("approval_not_applicable");
    expect(lifecycleErrorText(503)).toContain("fail-closed");
    expect(lifecycleErrorText(null)).toContain("недоступен");
  });
});
