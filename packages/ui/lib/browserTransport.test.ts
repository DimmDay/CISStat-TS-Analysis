import { apiFetch } from "./browserTransport";
const proof = "c1.1234." + "A".repeat(32) + "." + "b".repeat(64);
function reply(status: number, body: unknown, local = false): Response {
  return {
    ok: status < 400,
    status,
    json: async () => body,
    headers: {
      get: (name: string) =>
        name === "x-cisstat-csrf" && local ? "required" : null,
    },
  } as unknown as Response;
}
beforeEach(() => {
  global.fetch = jest.fn();
});
test("one resend only after guaranteed local refusal, never backend/network errors", async () => {
  const fetch = global.fetch as jest.Mock;
  fetch
    .mockResolvedValueOnce(reply(403, {}, true))
    .mockResolvedValueOnce(reply(200, { csrf_token: proof }))
    .mockResolvedValueOnce(reply(200, { done: true }));
  expect(
    (await apiFetch("/api/v1/session/stage", { method: "POST", body: "{}" }))
      .status,
  ).toBe(200);
  expect(fetch).toHaveBeenCalledTimes(3);
  expect(new Headers(fetch.mock.calls[2][1].headers).get("x-csrf-token")).toBe(
    proof,
  );
  fetch
    .mockReset()
    .mockResolvedValue(reply(403, { detail: { code: "csrf_invalid" } }));
  await apiFetch("/api/v1/session/stage", { method: "POST" });
  expect(fetch).toHaveBeenCalledTimes(1);
  fetch.mockReset().mockRejectedValue(new Error("timeout"));
  await expect(
    apiFetch("/api/v1/session/stage", { method: "POST" }),
  ).rejects.toThrow("timeout");
  expect(fetch).toHaveBeenCalledTimes(1);
});
test("no injected CSRF to another origin", async () => {
  const fetch = global.fetch as jest.Mock;
  fetch.mockResolvedValue(reply(403, {}, true));
  await apiFetch("https://evil.example/api/v1/auth/login", { method: "POST" });
  expect(fetch).toHaveBeenCalledTimes(1);
  expect(fetch.mock.calls[0][1].headers).toBeUndefined();
});
test("invalid proof aborts before business resend", async () => {
  (global.fetch as jest.Mock)
    .mockResolvedValueOnce(reply(403, {}, true))
    .mockResolvedValueOnce(reply(200, { csrf_token: "forged" }));
  await expect(
    apiFetch("/api/v1/auth/login", { method: "POST" }),
  ).rejects.toThrow();
  expect(global.fetch).toHaveBeenCalledTimes(2);
});
