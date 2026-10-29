/** PGV-07-CERT проба мёртвой ветки и вложенного applicable:true (p7cert-probe-dead). */
import { flattenPassportGroup } from "../../packages/ui/print/printPassport";

describe("p7cert-probe-dead", () => {
  test("D1 вложенный applicable:false — фактические строки", () => {
    const rows = flattenPassportGroup({ nested: { applicable: false, reason: "R", value: null } });
    // eslint-disable-next-line no-console
    console.log(`D1: ${JSON.stringify(rows)}`);
  });
  test("D2 вложенный applicable:true — фактические строки", () => {
    const rows = flattenPassportGroup({ nested: { value: 1.5, applicable: true } });
    // eslint-disable-next-line no-console
    console.log(`D2: ${JSON.stringify(rows)}`);
  });
  test("D3 вложенный БЕЗ applicable — рекурсия", () => {
    const rows = flattenPassportGroup({ nested: { a: 1, deep: { b: 2 } } });
    // eslint-disable-next-line no-console
    console.log(`D3: ${JSON.stringify(rows)}`);
  });
});
