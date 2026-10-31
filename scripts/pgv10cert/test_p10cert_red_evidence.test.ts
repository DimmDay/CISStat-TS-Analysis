/**
 * PGV-10-CERT — Class B: RED-свидетельство R1b находки F-P10C2
 * (по задумке RED на цели 5e0920e; GREEN после исправления).
 *
 * R1b: sanitizeFrozenSvg (второй слой защиты, контейнер PGV-08)
 * НЕ распознаёт namespace-форму <svg:script> — элемент остаётся в
 * отданном DOM (контракт «<script> удаляются» нарушен для ns-формы;
 * исполнение предотвращено javaScriptEnabled=false + CSP script-src
 * 'none' — как в F-P8C4, расхождение контракт/код при сниженном
 * риске).
 *
 * ГЕЙТ-НЕЙТРАЛЬНОСТЬ (Task ID: PGV10CERT-GATEFIX, 2026-10-31): файл
 * попадает в стандартный testMatch jest (glob на любой *.test.ts или
 * *.test.tsx файл дерева), поэтому
 * будучи RED по замыслу, он детерминированно ломал гейт jest
 * (jest.yml / local_gates.py) на ЛЮБОЙ машине до выполнения будущей
 * FIX-задачи PGV-10 — дефект поставки PGV-10-RECERT (гейт обязан быть
 * зелёным на дереве с применённой поставкой). По умолчанию suite
 * помечен describe.skip: гейт видит «2 skipped», остаётся зелёным;
 * режим свидетельства включается ЯВНО:
 *
 *   P10CERT_RED_EVIDENCE=1 npx jest scripts/pgv10cert/test_p10cert_red_evidence.test.ts
 *
 * В этом режиме тесты исполняются и RED, пока F-P10C2 не исправлена;
 * после FIX-задачи они GREEN (свидетельство становится регрессионным
 * пином — включить флаг и убедиться, что тесты проходят).
 *
 * Без commit/push (AGENTS.md).
 */
import { sanitizeFrozenSvg } from "../../apps/print-renderer/src/rendererCore";

const HOSTILE_NS = [
  "<svg xmlns='http://www.w3.org/2000/svg' width='10' height='10'>"
    + "<svg:script>alert('p10cert-ns')</svg:script>"
    + "<rect width='10' height='10'/></svg>",
  "<svg xmlns='http://www.w3.org/2000/svg' width='10' height='10'>"
    + "<svg:foreignObject><body xmlns='http://www.w3.org/1999/xhtml'><p>x</p></body></svg:foreignObject>"
    + "<rect width='10' height='10'/></svg>",
];

// describe.skip по умолчанию (гейт-нейтральность); явный режим — флаг
// P10CERT_RED_EVIDENCE=1 (см. шапку файла).
const describeEvidence =
  process.env.P10CERT_RED_EVIDENCE === "1" ? describe : describe.skip;

describeEvidence("p10cert RED R1b: sanitizeFrozenSvg против namespace-форм", () => {
  it("удаляет <svg:script> из замороженного SVG (ns-форма script-элемента)", () => {
    const out = sanitizeFrozenSvg(HOSTILE_NS[0]);
    expect(out.xml.toLowerCase()).not.toContain("<svg:script");
    expect(
      out.warnings.some((w) => w.toLowerCase().includes("script")),
    ).toBe(true);
  });

  it("удаляет <svg:foreignObject> из замороженного SVG (ns-форма)", () => {
    const out = sanitizeFrozenSvg(HOSTILE_NS[1]);
    expect(out.xml.toLowerCase()).not.toContain("foreignobject");
  });
});
