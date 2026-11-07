import { restoreResearchRun } from "./researchOwnership";
import { apiFetch } from "./browserTransport";
jest.mock("./browserTransport", () => ({ apiFetch: jest.fn() }));
beforeEach(() => jest.clearAllMocks());
test("restore uses governed POST and rejects path injection", async () => {
  (apiFetch as jest.Mock).mockResolvedValue({ok:true,json:async()=>({run_id:"RUN-A0900001"})});
  expect(await restoreResearchRun("RUN-A0900001")).toEqual({run_id:"RUN-A0900001"});
  expect(apiFetch).toHaveBeenCalledWith("/api/v1/progress/runs/RUN-A0900001/restore",{method:"POST",cache:"no-store"});
  await expect(restoreResearchRun("RUN-A0900001/../../other")).rejects.toThrow();
  expect(apiFetch).toHaveBeenCalledTimes(1);
});
test("denied restore reports failure", async () => {
  (apiFetch as jest.Mock).mockResolvedValue({ok:false,status:404});
  await expect(restoreResearchRun("RUN-A0900001")).rejects.toThrow("404");
});
