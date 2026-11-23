// Opt-in independent acceptance; raw RED is preserved, never xfail.
const test=require('node:test'),assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const {JSDOM}=require('jsdom'),ts=require('typescript');
const {profiles,payload}=require('./fixtures.js');
const ROOT=path.resolve(__dirname,'../..');
const compiled=path.join(ROOT,'apps/print-renderer/dist');
const core=require(path.join(compiled,'apps/print-renderer/src/rendererCore.js'));
const theme=require(path.join(compiled,'packages/ui/print/printTheme.js'));
const sizes={'figure-landscape':[2400,1500],'a4-landscape':[3508,2480],'a4-portrait':[2480,3508]};
const close=(a,b)=>assert.ok(Math.abs(a-b)<0.001,`${a} != ${b}`);
for(const profile of profiles) for(const kind of ['p01','p02']) {
 test(`${kind} ${profile}: physical fonts, page geometry, table padding and footer`,()=>{
  const p=payload(profile,kind);assert.equal(core.validateRenderPayload(p).violations.length,0);
  const doc=new JSDOM(core.buildPrintHtml(p,1,1)).window.document;
  const surface=doc.querySelector('[data-testid="print-page-surface"]');
  close(parseFloat(surface.style.width),sizes[profile][0]);close(parseFloat(surface.style.height),sizes[profile][1]);
  close(parseFloat(doc.querySelector('h1').style.fontSize)*72/300,16);
  close(parseFloat(doc.querySelector('table').style.fontSize)*72/300,9.5);
  close(parseFloat(doc.querySelector('td').style.paddingTop)*25.4/300,1);
  close(parseFloat(doc.querySelector('td').style.paddingRight)*25.4/300,1.2);
  close(parseFloat(doc.querySelector('[data-testid="print-page-body"]').style.paddingTop)*25.4/300,12);
  const footer=doc.querySelector('[data-testid="print-footer"]');
  assert.match(footer.textContent,/Стр\. 1 из 1/);
  for(const span of footer.querySelectorAll('span'))if(span.textContent.trim())close(parseFloat(span.style.fontSize)*72/300,8.5);
  assert.match(doc.body.textContent,kind==='p01'?/БЕРЁЗА КИРИЛЛИЦА 2/:/\+7 \(\+700 %\)/);
 });
}
test('physical conversion is independent of screen CSS 96 dpi',()=>{
 close(theme.ptToPx(72),300);close(theme.mmToPx(25.4),300);
 for(const role of ['body','small','micro'])close(theme.PRINT_TYPE_SCALE[role]*72/300,role==='body'?9.5:role==='small'?8.5:8);
 assert.equal(core.ppiToPixelsPerMeter(300),11811);
});
test('P01 long refs and long table labels request wrapping',()=>{
 const p=payload('a4-portrait');p.sections[0].record.session_snapshot_id='СверхдлинныйИдентификатор'.repeat(20);
 const doc=new JSDOM(core.buildPrintHtml(p,1,1)).window.document;
 const el=[...doc.querySelectorAll('span')].find(e=>e.textContent===p.sections[0].record.session_snapshot_id);
 assert.equal(el.style.overflowWrap,'anywhere');
 for(const td of doc.querySelectorAll('tbody td:not([colspan])'))assert.equal(td.style.overflowWrap,'anywhere');
});
test('outer overflow and 1 px rounding controls retain terminal 413 semantics',()=>{
 assert.equal(core.detectSurfaceOverflow({scrollWidth:2481,clientWidth:2480,scrollHeight:3509,clientHeight:3508}),false);
 assert.equal(core.detectSurfaceOverflow({scrollWidth:2482,clientWidth:2480,scrollHeight:3508,clientHeight:3508}),true);
 assert.equal(core.detectSurfaceOverflow({scrollWidth:2480,clientWidth:2480,scrollHeight:3510,clientHeight:3508}),true);
 assert.equal(core.RENDER_CONTENT_OVERFLOW_HTTP_STATUS,413);
 assert.equal(core.buildErrorBody('render_content_overflow','fixture').error.retryable,false);
});
function actualMeasurement(){
 const source=fs.readFileSync(path.join(ROOT,'apps/print-renderer/src/renderWorker.ts'),'utf8');
 const ast=ts.createSourceFile('renderWorker.ts',source,ts.ScriptTarget.Latest,true);
 let fn;
 function visit(n){if(ts.isCallExpression(n)&&n.expression.getText(ast)==='surface.evaluate')fn=n.arguments[0].getText(ast);ts.forEachChild(n,visit);}
 visit(ast);assert.ok(fn,'real worker surface evaluation must exist');
 return vm.runInNewContext(ts.transpile('('+fn+')',{target:ts.ScriptTarget.ES2022}));
}
// A finite DOM measurement model, NOT a claim of native Chromium layout.
// An implementation observing the content slot/footer would see the collision.
test('F-TYPO-01: content exceeding its body slot must not pass merely because surface fits',()=>{
 const body={clientHeight:3000,scrollHeight:3090,clientWidth:2196,scrollWidth:2196,
   getBoundingClientRect:()=>({top:142,bottom:3142,left:142,right:2338})};
 const footer={getBoundingClientRect:()=>({top:3189,bottom:3366,left:142,right:2338})};
 const content={getBoundingClientRect:()=>({top:142,bottom:3232,left:142,right:2338})};
 const surface={clientHeight:3508,scrollHeight:3508,clientWidth:2480,scrollWidth:2480,
   querySelector:(s)=>s.includes('probe-content')?null:s.includes('footer')?footer:body,
   querySelectorAll:()=>[content],children:[body,footer],getBoundingClientRect:()=>({top:0,bottom:3508,left:0,right:2480})};
 assert.ok(content.getBoundingClientRect().bottom>footer.getBoundingClientRect().top,'model really has overlap');
 const measured=actualMeasurement()(surface);
 assert.equal(core.detectSurfaceOverflow(measured),true,'outer fits; inner overflow is invisible to actual callback+guard');
});
test('F-TYPO-02: local sample runner covers the complete existing 11-case acceptance corpus',()=>{
 const source=fs.readFileSync(path.join(ROOT,'scripts/pgv13vis01/render_samples.mjs'),'utf8');
 const ast=ts.createSourceFile('render_samples.mjs',source,ts.ScriptTarget.Latest,true,ts.ScriptKind.JS);
 let names;
 function visit(n){if(ts.isVariableDeclaration(n)&&n.name.getText(ast)==='names')names=n.initializer.elements.map(e=>e.text);ts.forEachChild(n,visit);}
 visit(ast);assert.ok(names);assert.equal(new Set(names).size,names.length);
 const expected=['p01-figure-landscape','p01-a4-landscape','p01-a4-portrait','p01-reused','p01-missing','p01-corrupt','p02-figure-landscape','p02-a4-landscape','p02-a4-portrait','p02-reused','p02-missing'];
 assert.deepEqual(names.slice().sort(),expected.sort());
});
test('F-TYPO-03: sample runner must reject a wrong 413 code/retryable response',async()=>{
 const source=fs.readFileSync(path.join(ROOT,'scripts/pgv13vis01/render_samples.mjs'),'utf8');
 const code=ts.transpile(source,{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022,esModuleInterop:true});
 const events=require('node:events'),logs=[];
 const proc={argv:['node','runner','/fake/out','/fake/input'],env:{},execPath:'node',exitCode:undefined,
   stdout:{write:x=>logs.push(x)},stderr:{write:x=>logs.push(x)},exit:n=>{throw Error('unexpected exit '+n);}};
 const fakeFs={mkdirSync(){},writeFileSync(){},existsSync(){return true;},readFileSync(file){
   const name=path.basename(file).replace('.payload.json','');
   const p=payload(name.includes('figure-landscape')?'figure-landscape':name.includes('a4-landscape')?'a4-landscape':'a4-portrait',name.startsWith('p02')?'p02':'p01');
   p.request_id=name;if(name==='p01-reused')p.sections=[0,1,2].map(i=>({...p.sections[0],section_id:'record-'+i}));return Buffer.from(JSON.stringify(p));
 }};
 const fakeHttp={request(opts,callback){
   let body='';const req=new events.EventEmitter();req.write=x=>body+=x;req.destroy=()=>{};
   req.end=()=>queueMicrotask(()=>{
     let status=200;
     if(opts.method==='POST'){
       const p=JSON.parse(body);
       if(p.snapshot.print.profile_id==='figure-landscape'||(p.request_id==='p01-reused'&&p.sections.length===3)||p.sections[0]?.record?.passport?.overflow_probe_group)status=413;
     }
     const res=new events.EventEmitter();res.statusCode=status;
     res.headers={'x-render-retryable':'true'};
     callback(res);
     // Wrong error family + wrong retryability MUST NOT count as overflow proof.
     res.emit('data',status===413?Buffer.from('{"error":{"code":"payload_too_large","retryable":true}}'):opts.method==='GET'?Buffer.from('{}'):Buffer.from('89504e470d0a1a0a','hex'));
     res.emit('end');
   });return req;
 }};
 const child={exitCode:null,stdout:{on(){}},stderr:{on(){}},kill(){}};
 const requireMock=n=>{
   if(n==='node:fs')return fakeFs;if(n==='node:http')return fakeHttp;
   if(n==='node:child_process')return {spawn:()=>child};throw Error('unapproved require '+n);
 };
 vm.runInNewContext(code,{require:requireMock,exports:{},process:proc,Buffer,console:{log:(...s)=>logs.push(s.join(' ')),error:(...s)=>logs.push(s.join(' '))},queueMicrotask,setTimeout});
 for(let i=0;i<25&&proc.exitCode===undefined;i++)await new Promise(resolve=>setImmediate(resolve));
 assert.notEqual(proc.exitCode,undefined,'runner must complete, not time out');
 assert.ok(logs.some(s=>s==='VIS01_LOCAL_RENDER_OK'||s==='VIS01_LOCAL_RENDER_FAILED'),'runner must complete all renders: '+logs.join('\n'));
 assert.equal(logs.filter(s=>s.startsWith('RENDER ')).length,10,'all ten original cases must run');
 assert.ok(logs.filter(s=>s.startsWith('RENDER ')).every(s=>JSON.parse(s.slice(7)).match),'HTTP mock must match every declared status');
 assert.equal(proc.exitCode,1,'runner accepted wrong 413 body and retryable=true: '+logs.at(-1));
});
