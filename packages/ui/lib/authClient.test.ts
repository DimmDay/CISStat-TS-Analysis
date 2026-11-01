import { safeReturnTo, authMe, AuthFailure } from "./authClient";
test("return_to is an exact local allowlist without query/hash/token", () => {
  for (const value of [
    "//evil.example",
    "https://evil.example",
    "/\\evil.example",
    "/%2f%2fevil.example",
    "/admin?token=secret",
    "/admin#secret",
    "javascript:alert(1)",
    null,
    ["/admin", "//evil"],
  ])
    expect(safeReturnTo(value)).toBe("/");
  expect(safeReturnTo("/admin")).toBe("/admin");
  expect(safeReturnTo("/upload")).toBe("/upload");
});
test("me projects safe fields; 503 is unavailable, only 401 is anonymous", async () => {
  const data = {
    subject_id: "person",
    account_id: "account",
    auth_method: "auth_session",
    token: "SECRET",
  };
  global.fetch = jest
    .fn()
    .mockResolvedValue({ ok: true, status: 200, json: async () => data });
  expect(await authMe()).not.toHaveProperty("token");
  (global.fetch as jest.Mock).mockResolvedValue({
    ok: false,
    status: 503,
    json: async () => ({ detail: { code: "unavailable", message: "PRIVATE" } }),
  });
  await expect(authMe()).rejects.toBeInstanceOf(AuthFailure);
  (global.fetch as jest.Mock).mockResolvedValue({ ok: false, status: 401 });
  expect(await authMe()).toBeNull();
});
