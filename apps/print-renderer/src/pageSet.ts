import { createHash } from 'node:crypto';
import { pngCrc32 } from './pngCrc32';

export class PageSetError extends Error {
  readonly retryable = false;
  constructor(readonly code: 'export_too_large' | 'render_content_overflow', message: string) {
    super(`${code}: ${message}`); this.name='PageSetError';
  }
}
export interface PlannedPage { surface_id:string; unit_ids:string[]; source_refs:string[]; role:string; section_index:number; }
/** Runs inside Chromium. Self-contained (serialized by Playwright); no imports,
 * network or scientific recomputation. The DOM is our trusted compiled SSR. */
export function paginatePassportDocument({maxPages}: {maxPages:number}): {pages:PlannedPage[]; unit_count:number} {
  const original=document.querySelector<HTMLElement>('[data-testid="print-page-surface"]');
  if(!original)throw new Error('render_content_overflow: missing print surface');
  const template=original.cloneNode(true) as HTMLElement;
  const originalSlot=original.querySelector<HTMLElement>('[data-testid="print-page-content"]');
  if(!originalSlot)throw new Error('render_content_overflow: missing content slot');
  const articles=Array.from(originalSlot.children).filter(el=>el.matches('article')) as HTMLElement[];
  if(!articles.length)throw new Error('render_content_overflow: missing document sections');
  const prefix=Array.from(originalSlot.children).filter(el=>!el.matches('article'));
  const pages:PlannedPage[]=[],made:HTMLElement[]=[];
  let total=0;
  const fail=(code:string):never=>{throw new Error(code);};
  const makePage=():HTMLElement=>{
    if(made.length>=maxPages)fail('export_too_large: page limit');
    const page=template.cloneNode(true) as HTMLElement;
    page.id=`pgv-page-${made.length+1}`;page.style.display='';
    original.parentNode!.appendChild(page);made.push(page);return page;
  };
  const fit=(page:HTMLElement)=>{
    const slot=page.querySelector<HTMLElement>('[data-testid="print-page-content"]')!;
    const footer=page.querySelector<HTMLElement>('[data-testid="print-footer"]')!;
    const box=slot.getBoundingClientRect(),foot=footer.getBoundingClientRect();
    return slot.scrollHeight<=slot.clientHeight+1 && slot.scrollWidth<=slot.clientWidth+1 &&
      Array.from(slot.children).every(el=>{const b=el.getBoundingClientRect();return b.bottom<=Math.min(box.bottom,foot.top)+1 && b.left>=box.left-1 && b.right<=box.right+1;});
  };
  // Reserve the widest folio before fitting, so crossing page 9 cannot
  // unexpectedly grow the footer after preflight.
  for(const span of Array.from(template.querySelectorAll('[data-testid="print-footer"] span')))
    if(/^Стр\. \d+ из \d+$/.test(span.textContent||''))span.textContent=`Стр. ${maxPages} из ${maxPages}`;
  original.style.display='none';
  try{
    articles.forEach((article,section)=>{
      const source=article.cloneNode(true) as HTMLElement;
      const ids:string[]=[],bands=new Map<string,string[]>();
      let group='';
      function atom(el:HTMLElement){const id=`${section}:${ids.length}`;el.dataset.pgvUnit=id;ids.push(id);if(group)bands.get(group)!.push(id);}
      function visit(el:HTMLElement){
        if(el.tagName==='HEADER'||el.tagName==='FOOTER'||/^H[1-6]$/.test(el.tagName))return;
        if(el.tagName==='TABLE'){
          const rows=Array.from(el.querySelectorAll<HTMLElement>('tbody > tr'));
          const band=(r:HTMLElement)=>r.children.length===1&&Boolean(r.querySelector('th[scope="colgroup"][colspan]'));
          rows.forEach((row,i)=>{
            if(band(row)){
              group='';
              if(i===rows.length-1||band(rows[i+1]))atom(row); // Empty groups remain visible.
              else {group=`g${bands.size}`;bands.set(group,[]);row.dataset.pgvBand=group;}
            } else atom(row);
          });
          group='';return;
        }
        if(['P','LI'].includes(el.tagName)||el.dataset.printKeep==='true'){atom(el);return;}
        if(!el.querySelector('table,p,li,section,div')){atom(el);return;}
        for(const child of Array.from(el.children))visit(child as HTMLElement);
      }
      for(const child of Array.from(source.children))visit(child as HTMLElement);
      for(const el of Array.from(source.querySelectorAll<HTMLElement>('*')))
        if(el.querySelector('[data-pgv-unit]'))el.dataset.pgvContainer='true';
      const refs=JSON.parse(source.dataset.printSourceRefs||'[]') as string[];
      const role=source.dataset.printRole|| (source.dataset.testid==='print-comparison-page'?'P02':'P01');
      function fill(page:HTMLElement,selected:string[]){
        const keep=new Set(selected),fragment=source.cloneNode(true) as HTMLElement;
        for(const el of Array.from(fragment.querySelectorAll<HTMLElement>('[data-pgv-unit]')))if(!keep.has(el.dataset.pgvUnit!))el.remove();
        for(const el of Array.from(fragment.querySelectorAll<HTMLElement>('[data-pgv-band]')))
          if(!(bands.get(el.dataset.pgvBand!)||[]).some(id=>keep.has(id)))el.remove();
        for(const el of Array.from(fragment.querySelectorAll<HTMLElement>('[data-pgv-container]')).reverse())if(!el.querySelector('[data-pgv-unit]'))el.remove();
        if(refs.length){const identity=document.createElement('div');identity.dataset.testid='print-page-source';identity.style.cssText=`font-size:${8.5*300/72}px;line-height:1.2;overflow-wrap:anywhere`;identity.textContent='Источник: '+refs.join(' ; ');fragment.querySelector('header')?.appendChild(identity);}
        const slot=page.querySelector<HTMLElement>('[data-testid="print-page-content"]')!;
        slot.replaceChildren(...prefix.map(el=>el.cloneNode(true)),fragment);
      }
      let page=makePage(),selected:string[]=[];
      const save=()=>pages.push({surface_id:page.id,unit_ids:selected.slice(),source_refs:refs.slice(),role,section_index:section});
      if(!ids.length){fill(page,[]);if(!fit(page))fail('render_content_overflow: indivisible document header');save();}
      for(const id of ids){
        fill(page,[...selected,id]);
        if(!fit(page)){
          if(!selected.length)fail('render_content_overflow: indivisible row/block or header');
          fill(page,selected);save();page=makePage();selected=[];fill(page,[id]);
          if(!fit(page))fail('render_content_overflow: indivisible row/block or header');
        }
        selected.push(id);
      }
      if(ids.length)save();total+=ids.length;
    });
    pages.forEach((p,i)=>{
      const page=document.getElementById(p.surface_id)!;
      const footer=page.querySelector('[data-testid="print-footer"]')!;
      for(const span of Array.from(footer.querySelectorAll('span')))if(/^Стр\. \d+ из \d+$/.test(span.textContent||''))span.textContent=`Стр. ${i+1} из ${pages.length}`;
      if(!fit(page))fail('render_content_overflow: final numbered page');
    });
    const all=pages.flatMap(p=>p.unit_ids);
    if(all.length!==total||new Set(all).size!==total)fail('render_content_overflow: incomplete unit coverage');
    return {pages,unit_count:total};
  }catch(e){for(const el of made)el.remove();original.style.display='';throw e;}
}

const sha=(b:Buffer)=>createHash('sha256').update(b).digest('hex');
/** Small ZIP STORE writer: no dependencies, fixed timestamps, no arbitrary paths. */
export function buildPageArchive(pages:{name:string;data:Buffer}[],metadata:Buffer,base:Record<string,unknown>):Buffer {
  if(!pages.length||pages.length>20)throw new PageSetError('export_too_large','page count');
  const manifest={...base,dependencies:Array.from(new Set(((base.pages as any[])||[]).flatMap(p=>p.source_refs||[]))),metadata:{filename:'metadata.json',sha256:sha(metadata),size_bytes:metadata.length},
    pages:pages.map((p,i)=>({...((base.pages as any[])?.[i]||{}),page_role:(base.pages as any[])?.[i]?.role,width_px:base.width,height_px:base.height,index:i+1,filename:p.name,sha256:sha(p.data),png_sha256:sha(p.data),size_bytes:p.data.length})),page_count:pages.length};
  const files=[...pages,{name:'metadata.json',data:metadata},{name:'manifest.json',data:Buffer.from(JSON.stringify(manifest))}];
  const chunks:Buffer[]=[],central:Buffer[]=[];let offset=0;
  for(const file of files){
    if(!/^(page-\d{3}\.png|metadata\.json|manifest\.json)$/.test(file.name))throw new PageSetError('export_too_large','unsafe member');
    const name=Buffer.from(file.name),crc=pngCrc32(file.data),local=Buffer.alloc(30),entry=Buffer.alloc(46);
    local.writeUInt32LE(0x04034b50,0);local.writeUInt16LE(20,4);local.writeUInt16LE(0x21,12);
    local.writeUInt32LE(crc,14);local.writeUInt32LE(file.data.length,18);local.writeUInt32LE(file.data.length,22);local.writeUInt16LE(name.length,26);
    entry.writeUInt32LE(0x02014b50,0);entry.writeUInt16LE(20,4);entry.writeUInt16LE(20,6);entry.writeUInt16LE(0x21,14);
    entry.writeUInt32LE(crc,16);entry.writeUInt32LE(file.data.length,20);entry.writeUInt32LE(file.data.length,24);entry.writeUInt16LE(name.length,28);entry.writeUInt32LE(offset,42);
    chunks.push(local,name,file.data);central.push(entry,name);offset+=local.length+name.length+file.data.length;
    if(offset>50*1024*1024)throw new PageSetError('export_too_large','output bytes');
  }
  const cd=Buffer.concat(central),end=Buffer.alloc(22);end.writeUInt32LE(0x06054b50,0);end.writeUInt16LE(files.length,8);end.writeUInt16LE(files.length,10);end.writeUInt32LE(cd.length,12);end.writeUInt32LE(offset,16);
  if(offset+cd.length+end.length>50*1024*1024)throw new PageSetError('export_too_large','output bytes');
  return Buffer.concat([...chunks,cd,end]);
}
