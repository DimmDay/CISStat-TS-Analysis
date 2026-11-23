// Optional real Chromium audit. Exit 2 BLOCKED is never a certificate.
// No --no-sandbox, remote browser, external URLs, credentials or service mutation.
const fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto');
const {createRequire}=require('node:module');
const {profiles,payload}=require('./fixtures.js');
const {assess,measureDocument}=require('./measure.js');
async function main(){
 const argv=process.argv.slice(2),args={};
 while(argv.length){const k=argv.shift();if(!['--out','--root','--browser'].includes(k)||!argv.length)throw Error('Usage: native.js --out NEW_DIRECTORY [--root CHECKOUT] [--browser PINNED_EXECUTABLE]');args[k]=argv.shift();}
 if(!args['--out'])throw Error('--out is required');
 const root=path.resolve(args['--root']||path.join(__dirname,'../..')),out=path.resolve(args['--out']);
 if(fs.existsSync(out))throw Error('Output already exists; use a fresh directory');
 fs.mkdirSync(out,{recursive:true});
 const report={status:'RUNNING',full_pgv13_certified:false,final_container_verified:false,measurements:[]};
 const write=()=>fs.writeFileSync(path.join(out,'report.json'),JSON.stringify(report,null,2));write();
 let browser;
 try{
  const req=createRequire(path.join(root,'package.json'));
  const {chromium}=req('playwright-core');
  const core=req(path.join(root,'apps/print-renderer/dist/apps/print-renderer/src/rendererCore.js'));
  report.sources={};
  for(const f of ['packages/ui/print/printTheme.ts','packages/ui/print/printLayout.tsx','packages/ui/print/printPassport.tsx','packages/ui/print/printComparison.tsx','apps/print-renderer/src/renderWorker.ts','apps/print-renderer/src/rendererCore.tsx'])report.sources[f]=crypto.createHash('sha256').update(fs.readFileSync(path.join(root,f))).digest('hex');
  browser=await chromium.launch({headless:true,chromiumSandbox:true,timeout:15000,...(args['--browser']?{executablePath:args['--browser']}:{})});
  report.browser_version=browser.version();report.sandbox_requested=true;
  const context=await browser.newContext({deviceScaleFactor:1,javaScriptEnabled:false,locale:'ru-RU',timezoneId:'UTC'});
  await context.route('**/*',route=>route.abort());
  const page=await context.newPage();page.setDefaultTimeout(5000);
  const cases=[];
  for(const profile of profiles){for(const kind of ['p01','p02'])cases.push({profile,kind,rows:3});for(let rows=10;rows<=50;rows+=2)cases.push({profile,kind:'p01',rows});}
  for(const c of cases){
   const p=payload(c.profile,c.kind,c.rows),checked=core.validateRenderPayload(p);
   if(checked.violations.length)throw Error('Invalid audit fixture '+JSON.stringify(checked.violations));
   const html=core.buildPrintHtml(p,1,1);
   await page.setContent(html,{waitUntil:'load',timeout:5000});
   const m=await page.evaluate(measureDocument),a=assess(m);
   const name=c.kind+'-'+c.profile+'-'+c.rows;
   report.measurements.push({name,...m,...a});
   if(!a.passed)fs.writeFileSync(path.join(out,name+'.html'),html);
  }
  report.status=report.measurements.length===69&&report.measurements.every(m=>m.passed)?'PASS':'FAIL';
  report.boundary='compiled local Chromium layout; no HTTP/UDS/jobs/PNG/OCR or final image proof';
  process.exitCode=report.status==='PASS'?0:1;
 }catch(e){report.status='BLOCKED';report.error=String(e);process.exitCode=2;}
 finally{try{await browser?.close();}finally{write();}}
 console.log(JSON.stringify({status:report.status,cases:report.measurements.length,out,full_pgv13_certified:false}));
}
main().catch(e=>{console.error(String(e));process.exitCode=2;});
