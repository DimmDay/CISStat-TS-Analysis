/** @jest-environment node */
// Controlled browser adapter, NOT actual Chromium layout/screenshot evidence.
import {PrintRenderWorker,readConfig} from './renderWorker';
import {validateRenderPayload} from './rendererCore';
import {pngCrc32} from './pngCrc32';
import {deflateSync} from 'node:zlib';
const {payload}=require('../../../scripts/pgv13typocert/fixtures.js');

jest.mock('node:worker_threads',()=>({Worker:class extends require('node:events').EventEmitter {
  constructor(){super();queueMicrotask(()=>this.emit('message',{html:'controlled SSR bytes'}));}
  terminate(){return Promise.resolve(0);}
}}));

function png(){
  const chunk=(name:string,data:Buffer)=>{const b=Buffer.alloc(data.length+12);b.writeUInt32BE(data.length);b.write(name,4);data.copy(b,8);b.writeUInt32BE(pngCrc32(b.subarray(4,-4)),b.length-4);return b;};
  const ihdr=Buffer.alloc(13);ihdr.writeUInt32BE(2400);ihdr.writeUInt32BE(1500,4);ihdr[8]=8;ihdr[9]=2;
  return Buffer.concat([Buffer.from('89504e470d0a1a0a','hex'),chunk('IHDR',ihdr),chunk('IDAT',deflateSync(Buffer.alloc(1500*(1+2400*3)))),chunk('IEND',Buffer.alloc(0))]);
}
function setup(){
  const p=payload('figure-landscape');p.options={page_set:true};
  const plan={unit_count:2,pages:[0,1].map(i=>({surface_id:`pgv-page-${i+1}`,unit_ids:[`0:${i}`],source_refs:['rs-typo-independent-start'],role:'P01',section_index:0}))};
  const shot=jest.fn(async()=>png());
  const page={setDefaultTimeout:jest.fn(),route:jest.fn(),setContent:jest.fn(),
    evaluate:jest.fn().mockResolvedValueOnce(undefined).mockResolvedValueOnce(plan),locator:jest.fn(()=>({screenshot:shot}))};
  const context={newPage:jest.fn(async()=>page),close:jest.fn(async()=>{})};
  const worker:any=new PrintRenderWorker(readConfig({}));
  jest.spyOn(worker,'dependencyManifest').mockReturnValue({dependency_status:'available',checks:{browser:true,fonts:true,bundle:true}} as any);
  jest.spyOn(worker,'ensureBrowser').mockResolvedValue({newContext:async()=>context});
  return {p,page,shot,context,worker};
}
afterEach(()=>jest.restoreAllMocks());

test('one admitted job preflights then screenshots every page and builds the archive',async()=>{
  const {p,page,shot,context,worker}=setup();
  const result=await worker.renderPayload(p,1,1);
  expect(shot).toHaveBeenCalledTimes(2);expect(result.pageCount).toBe(2);
  expect(page.locator.mock.calls.map((c:any)=>c[0])).toEqual(['#pgv-page-1','#pgv-page-2']);
  expect(result.archive.subarray(0,4).toString('hex')).toBe('504b0304');
  expect(result.archive.toString()).toContain('pgv.print_manifest/1');
  expect(result.archive.toString()).toContain('metadata.json');
  expect(context.close).toHaveBeenCalledTimes(1);expect(worker.active).toBe(0);
});
test('preflight failure cannot emit even the first PNG',async()=>{
  const {p,page,shot,worker}=setup();
  page.evaluate.mockReset().mockResolvedValueOnce(undefined).mockRejectedValueOnce(new Error('export_too_large: page limit'));
  await expect(worker.renderPayload(p,1,1)).rejects.toMatchObject({code:'export_too_large',retryable:false});
  expect(shot).not.toHaveBeenCalled();expect(worker.active).toBe(0);
});
test('a later-page screenshot failure rejects the whole archive and closes the context',async()=>{
  const {p,shot,context,worker}=setup();
  shot.mockResolvedValueOnce(png()).mockRejectedValueOnce(new Error('second page failed'));
  await expect(worker.renderPayload(p,1,1)).rejects.toThrow('second page failed');
  expect(shot).toHaveBeenCalledTimes(2);expect(context.close).toHaveBeenCalled();expect(worker.active).toBe(0);
});
test('page-set cannot be used as a scaled probe or an arbitrary renderer option',()=>{
  const {p}=setup();p.options.scale=.05;
  expect(validateRenderPayload(p).violations.some(v=>v.path==='options.page_set')).toBe(true);
  p.options={page_set:'true'};
  expect(validateRenderPayload(p).violations.some(v=>v.path==='options.page_set')).toBe(true);
});
