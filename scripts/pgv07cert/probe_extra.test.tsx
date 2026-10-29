/** PGV-07-CERT доп. пробы (p7cert-extra). */
import { formatNumberRu, formatPrintTime } from "../../packages/ui/print/printLayout";
import { heatColor } from "../../packages/ui/print/printSections";

function signedNumber(value: number, digits = 1): string {
  const sign = value > 0 ? "+" : value < 0 ? "−" : "";
  return `${sign}${formatNumberRu(Math.abs(value), digits)}`;
}

describe("p7cert-extra пробы", () => {
  test("E1 signedNumber малых значений", () => {
    // eslint-disable-next-line no-console
    console.log(`E1: signed(-0.04)="${signedNumber(-0.04)}" signed(0)="${signedNumber(0)}" signed(-50)="${signedNumber(-50)}"`);
  });
  test("E2 heatColor перевернутый домен", () => {
    // eslint-disable-next-line no-console
    console.log(`E2: domain[10,0] v=5 → "${heatColor(5, [10, 0])}" (ожидалось промежуточное, got white if span<=0)`);
  });
  test("E3 formatPrintTime длина 15/16", () => {
    // eslint-disable-next-line no-console
    console.log(`E3: 16-чар ISO "${formatPrintTime("2026-10-27T12:34", null)}"; 15-чар "${formatPrintTime("2026-10-27T1:34", null)}"`);
  });
  test("E4 formatNumberRu округление вверх с группировкой", () => {
    // eslint-disable-next-line no-console
    console.log(`E4: 999.999(2)=${formatNumberRu(999.999, 2)}; -1234567.891(2)=${formatNumberRu(-1234567.891, 2)}`);
  });
});
