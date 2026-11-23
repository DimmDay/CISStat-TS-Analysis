import { paginatePassportDocument, buildPageArchive } from './pageSet';

describe('PGV14 page set: complete coverage, repeated labels, bounded output',()=>{
  function install(rows:number, height=80){
    document.body.innerHTML=`<div data-testid="print-page-surface"><div data-testid="print-page-body"><header style="display:none"></header><div data-testid="print-page-content"><article data-testid="print-passport-page"><header>Паспорт источника rs-test</header><div><table><tbody><tr><th colspan="2" scope="colgroup">Группа</th></tr>${Array.from({length:rows},(_,i)=>`<tr><td>Строка ${i}</td><td>${i}</td></tr>`).join('')}</tbody></table></div><footer>schema/1</footer></article></div><footer data-testid="print-footer">Стр. 1 из 1</footer></div></div>`;
    document.querySelector<HTMLElement>('article')!.dataset.printSourceRefs=JSON.stringify(['rs-test']);
    // Finite layout model, NOT native Chromium. Exercises algorithm/coverage.
    jest.spyOn(HTMLElement.prototype,'clientHeight','get').mockImplementation(function(this:HTMLElement){return this.dataset.testid==='print-page-content'?height:100;});
    jest.spyOn(HTMLElement.prototype,'clientWidth','get').mockReturnValue(100);
    jest.spyOn(HTMLElement.prototype,'scrollWidth','get').mockReturnValue(100);
    jest.spyOn(HTMLElement.prototype,'scrollHeight','get').mockImplementation(function(this:HTMLElement){return this.dataset.testid==='print-page-content'?20+Array.from(this.querySelectorAll('tr')).filter(r=>!r.querySelector('[colspan]')).length*15:100;});
    jest.spyOn(HTMLElement.prototype,'getBoundingClientRect').mockImplementation(function(this:HTMLElement){
      const top=this.dataset.testid==='print-footer'?90:0;
      const bottom=this.tagName==='ASIDE'?20:this.dataset.testid==='print-page-content'?height:this.tagName==='ARTICLE'?20+Array.from(this.querySelectorAll('tr')).filter(r=>!r.querySelector('[colspan]')).length*15:100;
      return {x:0,y:top,top,bottom,left:0,right:100,width:100,height:bottom-top,toJSON(){}} as DOMRect;
    });
  }
  afterEach(()=>jest.restoreAllMocks());
  test('rows are complete and unique and table/group labels repeat',()=>{
    install(10);const plan=paginatePassportDocument({maxPages:20});
    expect(plan.pages.length).toBe(3);
    expect(plan.pages.flatMap(p=>p.unit_ids)).toEqual(Array.from({length:10},(_,i)=>`0:${i}`));
    for(const p of plan.pages){expect(document.getElementById(p.surface_id)!.textContent).toContain('rs-test');expect(document.getElementById(p.surface_id)!.textContent).toContain('Группа');}
    expect(document.querySelectorAll('[id^="pgv-page-"]')).toHaveLength(3);
  });
  test('page cap refuses whole set',()=>{install(10);expect(()=>paginatePassportDocument({maxPages:2})).toThrow(/export_too_large/);});
  test('a single indivisible row cannot be clipped into a page',()=>{install(1,25);expect(()=>paginatePassportDocument({maxPages:20})).toThrow(/render_content_overflow/);});
  test('comparison identity, table headings, numbered folios and confirmation repeat on every page',()=>{
    install(10);
    const article=document.querySelector<HTMLElement>('article')!;
    article.dataset.printRole='P02';article.dataset.printSourceRefs=JSON.stringify(['rs-a','rs-b']);
    article.querySelector('table')!.insertAdjacentHTML('afterbegin','<thead><tr><th>Сравнение этапов</th></tr></thead>');
    document.querySelector('[data-testid="print-page-content"]')!.insertAdjacentHTML('afterbegin','<aside>Checkpoint reused</aside>');
    document.querySelector('[data-testid="print-footer"]')!.innerHTML='<span>Стр. 1 из 1</span>';
    const plan=paginatePassportDocument({maxPages:20});
    expect(plan.pages.length).toBeGreaterThan(1);
    plan.pages.forEach((p,i)=>{
      expect(p.role).toBe('P02');expect(p.source_refs).toEqual(['rs-a','rs-b']);
      const text=document.getElementById(p.surface_id)!.textContent;
      expect(text).toContain('Источник: rs-a ; rs-b');expect(text).toContain('Сравнение этапов');
      expect(text).toContain('Checkpoint reused');expect(text).toContain(`Стр. ${i+1} из ${plan.pages.length}`);
    });
  });
  test('empty groups are preserved as indivisible units and failure removes partial pages',()=>{
    install(1);
    document.querySelector('tbody')!.insertAdjacentHTML('beforeend','<tr><th colspan="2" scope="colgroup">Пустая группа</th></tr>');
    const plan=paginatePassportDocument({maxPages:20});
    expect(plan.unit_count).toBe(2);expect(document.getElementById(plan.pages[0].surface_id)!.textContent).toContain('Пустая группа');
    jest.restoreAllMocks();install(10);
    expect(()=>paginatePassportDocument({maxPages:1})).toThrow(/export_too_large/);
    expect(document.querySelector('[id^="pgv-page-"]')).toBeNull();
    expect((document.querySelector('[data-testid="print-page-surface"]') as HTMLElement).style.display).toBe('');
  });
  test('unknown-group hint is content, while its group heading repeats with every slice',()=>{
    install(10);
    document.querySelector('tbody tr')!.insertAdjacentHTML('afterend','<tr><td colspan="2">Группа вне известного набора</td></tr>');
    const plan=paginatePassportDocument({maxPages:20});
    expect(plan.unit_count).toBe(11);
    expect(plan.pages.map(p=>document.getElementById(p.surface_id)!.textContent).filter(t=>t!.includes('Группа вне известного набора'))).toHaveLength(1);
    expect(plan.pages.every(p=>document.getElementById(p.surface_id)!.textContent!.includes('Группа'))).toBe(true);
  });
  test('ZIP contains explicit member hashes without circular archive hash',()=>{
    const archive=buildPageArchive([{name:'page-001.png',data:Buffer.from('png')}],Buffer.from('{}'),{schema_version:'pgv.page_set/1'});
    expect(archive.readUInt32LE(0)).toBe(0x04034b50);
    expect(archive.toString()).toContain('manifest.json');expect(archive.toString()).toContain('metadata.json');expect(archive.toString()).toContain('page-001.png');
  });
});
