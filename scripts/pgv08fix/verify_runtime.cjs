// Real worker-thread SSR with the compiled production bundle (no browser mock).
const assert = require('node:assert/strict');
const { renderHtmlInWorker, RenderTimeoutError } = require('../../apps/print-renderer/dist/apps/print-renderer/src/renderWorker');
const { cyrillicScenario } = require('../../apps/print-renderer/dist/apps/print-renderer/src/smokeScenarios');
(async () => {
  const html = await renderHtmlInWorker(cyrillicScenario(), 1, 1, new AbortController().signal);
  assert.ok(html.includes('Оборот розничной торговли'));
  assert.ok(html.includes('print-page-surface'));
  const abort = new AbortController();
  const payload = cyrillicScenario();
  payload.sections = [{section_id:'heavy',kind:'html_table',headings:{row:['x'],column:[]},rows:Array.from({length:50000},()=>['heavy'])}];
  const start=Date.now();
  const work=renderHtmlInWorker(payload,1,1,abort.signal).catch(e=>e);
  setTimeout(()=>abort.abort(), 5);
  const error=await work;
  assert.ok(error instanceof RenderTimeoutError);
  assert.ok(Date.now()-start<1500, 'CPU-bound SSR must not block the parent deadline');
  console.log(JSON.stringify({ssr:'PASS',cyrillic:true,abort:'PASS',elapsed_ms:Date.now()-start,renderer:'actual compiled worker thread'}));
})().catch(e=>{console.error(e);process.exitCode=1;});
