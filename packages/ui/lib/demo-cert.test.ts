import { publicDemoCredentials } from "./demo";
const saved = {
  login: process.env.NEXT_PUBLIC_DEMO_LOGIN,
  password: process.env.NEXT_PUBLIC_DEMO_PASSWORD,
};
afterEach(() => {
  for (const [key, value] of [
    ["NEXT_PUBLIC_DEMO_LOGIN", saved.login],
    ["NEXT_PUBLIC_DEMO_PASSWORD", saved.password],
  ]) {
    if (value === undefined) delete process.env[key!];
    else process.env[key!] = value;
  }
});
test.each([
  [undefined, undefined],
  ["public-fixture", undefined],
  [undefined, "public-fixture"],
  ["", ""],
])("missing/partial public pair disables entry (%s, %s)", (login, password) => {
  if (login === undefined) delete process.env.NEXT_PUBLIC_DEMO_LOGIN;
  else process.env.NEXT_PUBLIC_DEMO_LOGIN = login;
  if (password === undefined) delete process.env.NEXT_PUBLIC_DEMO_PASSWORD;
  else process.env.NEXT_PUBLIC_DEMO_PASSWORD = password;
  expect(publicDemoCredentials()).toBeNull();
});
test("only explicit complete public pair enables entry", () => {
  process.env.NEXT_PUBLIC_DEMO_LOGIN = "public-fixture";
  process.env.NEXT_PUBLIC_DEMO_PASSWORD = "fixture-not-personal";
  expect(publicDemoCredentials()).toEqual({
    login: "public-fixture",
    password: "fixture-not-personal",
  });
});
