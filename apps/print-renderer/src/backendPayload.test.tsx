import { buildPrintHtml, validateRenderPayload } from './rendererCore';
const chart=require('../../../tests/fixtures/pgv_png_ssr/upload.chart.series.json');
const histogram=require('../../../tests/fixtures/pgv_png_ssr/upload.distribution.histogram.json');
const table=require('../../../tests/fixtures/pgv_png_ssr/upload.overview.tech_table.json');

test.each([['chart',chart],['histogram',histogram],['table',table]])('backend %s snapshot renders without optional warnings',(_,raw)=>{
 const before=JSON.stringify(raw);
 expect(raw.snapshot).not.toHaveProperty('warnings');
 const accepted=validateRenderPayload(raw);
 expect(accepted.violations).toEqual([]);
 const html=buildPrintHtml(accepted.payload!,1,1);
 expect(html).toContain('print-page-surface');
 expect(html).toContain(raw.snapshot.display.title);
 expect(html).not.toContain('data-testid="print-warnings"');
 expect(JSON.stringify(raw)).toBe(before);
});
test('explicit warning is preserved and escaped',()=>{
 const raw=JSON.parse(JSON.stringify(chart));
 raw.snapshot.warnings=['Проверить <script>значение</script>'];
 const html=buildPrintHtml(validateRenderPayload(raw).payload!,1,1);
 expect(html).toContain('print-warnings');
 expect(html).toContain('Проверить &lt;script&gt;значение&lt;/script&gt;');
 expect(raw.snapshot.warnings).toEqual(['Проверить <script>значение</script>']);
});
test.each([null,'warning',42,{},[null],[1]])('malformed warnings rejected before SSR: %j',(warnings)=>{
 const raw=JSON.parse(JSON.stringify(chart));raw.snapshot.warnings=warnings;
 const accepted=validateRenderPayload(raw);
 expect(accepted.payload).toBeNull();
 expect(accepted.violations).toEqual(expect.arrayContaining([expect.objectContaining({path:'snapshot.warnings'})]));
});
