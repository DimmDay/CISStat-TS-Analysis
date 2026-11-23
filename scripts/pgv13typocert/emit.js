const fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto');
const {profiles,payload}=require('./fixtures.js');
const root=path.resolve(__dirname,'../..');
const core=require(path.join(root,'apps/print-renderer/dist/apps/print-renderer/src/rendererCore.js'));
const out=path.resolve(process.argv[2]||path.join(root,'../typo-evidence'));
fs.mkdirSync(out,{recursive:true});
let entries=[];
for(const profile of profiles) for(const kind of ['p01','p02']) {
  const p=payload(profile,kind); const v=core.validateRenderPayload(p);
  if(v.violations.length)throw Error(JSON.stringify(v.violations));
  entries.push({name:kind+'-'+profile,payload:p,html:core.buildPrintHtml(p,1,1)});
}
// Boundary sweep: synthetic P01s of increasing length; no fixed expected fit.
for(const profile of profiles)for(let rows=10;rows<=50;rows+=2) {
  const p=payload(profile,'p01',rows);
  entries.push({name:'boundary-'+profile+'-'+rows,payload:p,html:core.buildPrintHtml(p,1,1)});
}
const sources={};
for(const file of ['packages/ui/print/printTheme.ts','packages/ui/print/printLayout.tsx','packages/ui/print/printPassport.tsx','packages/ui/print/printComparison.tsx','apps/print-renderer/src/renderWorker.ts','apps/print-renderer/src/rendererCore.tsx'])
 sources[file]=crypto.createHash('sha256').update(fs.readFileSync(path.join(root,file))).digest('hex');
for(const e of entries){fs.writeFileSync(path.join(out,e.name+'.html'),e.html);fs.writeFileSync(path.join(out,e.name+'.json'),JSON.stringify(e.payload,null,2));}
fs.writeFileSync(path.join(out,'manifest.json'),JSON.stringify({source_revision:require('child_process').execFileSync('git',['rev-parse','HEAD'],{cwd:root,encoding:'utf8'}).trim(),sources,entries:entries.map(e=>({name:e.name,html_sha256:crypto.createHash('sha256').update(e.html).digest('hex')}))},null,2));
const esc=s=>s.replace(/&/g,'&amp;').replace(/"/g,'&quot;').replace(/</g,'&lt;');
fs.writeFileSync(path.join(out,'index.html'),'<!doctype html><meta charset="utf-8"><title>PGV13 typography independent boundary audit</title><h1>Independent compiled P01/P02 layout</h1><p>Synthetic frozen facts; original compiled HTML; not final-container certification.</p>'+entries.map(e=>'<section><h2>'+e.name+'</h2><iframe data-case="'+e.name+'" width="3550" height="3550" srcdoc="'+esc(e.html)+'"></iframe></section>').join(''));
console.log(JSON.stringify({out,cases:entries.length,sources}));
