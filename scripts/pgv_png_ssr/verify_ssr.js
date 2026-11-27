/* Real compiled PGV-07 -> htmlWorker boundary, no Jest/worker mocks. */
const fs=require('node:fs');
const path=require('node:path');
const assert=require('node:assert/strict');
const root=path.resolve(__dirname,'../..');
const core=require(path.join(root,'apps/print-renderer/dist/apps/print-renderer/src/rendererCore.js'));
const {renderHtmlInWorker}=require(path.join(root,'apps/print-renderer/dist/apps/print-renderer/src/renderWorker.js'));
async function main(){
 const files=process.argv.slice(2);
 if(!files.length)throw new Error('No payloads tested');
 for(const file of files){
  const raw=JSON.parse(fs.readFileSync(file,'utf8'));
  const before=JSON.stringify(raw);
  const {payload,violations}=core.validateRenderPayload(raw);
  assert.deepEqual(violations,[]);assert.ok(payload);
  const controller=new AbortController();
  const timer=setTimeout(()=>controller.abort(),10000);
  let html;
  try{html=await renderHtmlInWorker(payload,1,payload.snapshot.print.page_count,controller.signal);}
  finally{clearTimeout(timer);}
  assert.ok(html.includes('data-testid="print-page-surface"'));
  assert.ok(html.includes('data-testid="print-page-content"'));
  assert.equal(JSON.stringify(raw),before);
  console.log(JSON.stringify({view:raw.snapshot.view_id,ssr:'ok',html_bytes:Buffer.byteLength(html)}));
 }
}
main().catch(error=>{console.error('Compiled SSR check failed: '+error.constructor.name);process.exitCode=1;});
