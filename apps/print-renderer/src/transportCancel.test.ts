/** @jest-environment node */
import * as http from 'node:http';
import {createRendererServer} from './server';
import {PrintRenderWorker,readConfig} from './renderWorker';
import {cyrillicScenario} from './smokeScenarios';

afterEach(()=>jest.restoreAllMocks());
test('HTTP disconnect reaches only this request AbortSignal',async()=>{
  jest.spyOn(PrintRenderWorker.prototype,'dependencyManifest').mockReturnValue({dependency_status:'available',checks:{browser:true,fonts:true,bundle:true}} as any);
  let admitted!:()=>void;const started=new Promise<void>(r=>{admitted=r;});
  let aborted!:()=>void;const stopped=new Promise<void>(r=>{aborted=r;});
  jest.spyOn(PrintRenderWorker.prototype,'renderPayload').mockImplementation((async(_p:any,_i:any,_n:any,signal:any)=>{
    admitted();
    return await new Promise((_resolve,reject)=>signal?.addEventListener('abort',()=>{aborted();reject(new Error('cancelled'));},{once:true}));
  }) as any);
  const server=createRendererServer();await new Promise<void>(r=>server.listen(0,'127.0.0.1',r));
  const port=(server.address() as any).port;
  const request=http.request({host:'127.0.0.1',port,path:'/v1/render',method:'POST',headers:{'Content-Type':'application/json'}},()=>{});
  request.on('error',()=>{});request.end(JSON.stringify(cyrillicScenario()));
  try {
    await started;request.destroy();
    await Promise.race([stopped,new Promise((_,reject)=>setTimeout(()=>reject(new Error('abort not propagated')),500))]);
  } finally {request.destroy();server.closeAllConnections();await new Promise<void>(r=>server.close(()=>r()));}
});
test('abort ends admitted worker promptly and frees its slot',async()=>{
  jest.useFakeTimers();
  const worker:any=new PrintRenderWorker(readConfig({}));
  jest.spyOn(worker,'doRender').mockImplementation(async()=>new Promise(()=>{}));
  const cancel=new AbortController();const payload=cyrillicScenario();payload.options={timeout_s:1};
  let result:any;
  const pending=worker.renderPayload(payload,1,1,cancel.signal).catch((e:any)=>e).then((r:any)=>{result=r;});
  try {
    cancel.abort();await jest.advanceTimersByTimeAsync(0);
    expect(result?.message).toContain('render_cancelled');
    expect(worker.active).toBe(0);
  } finally {await jest.advanceTimersByTimeAsync(1000);await pending;jest.useRealTimers();}
});
test('HTTP limits are finite independently of Chromium',()=>{
  const server=createRendererServer();
  expect(server.maxConnections).toBe(32);
  expect(server.requestTimeout).toBe(10000);
  expect(server.headersTimeout).toBeLessThanOrEqual(10000);
});
test('operator config cannot remove the transport budgets',()=>{
  const config=readConfig({CISSTAT_PRINT_RENDERER_HARD_TIMEOUT_S:'9999',CISSTAT_PRINT_RENDERER_MAX_BODY_BYTES:'999999999',CISSTAT_PRINT_RENDERER_MAX_CONCURRENT:'999'});
  expect(config.hardTimeoutS).toBeLessThanOrEqual(60);
  expect(config.maxBodyBytes).toBeLessThanOrEqual(8388608);
  expect(config.maxConcurrent).toBeLessThanOrEqual(2);
});
test('receiver enforces body cap before worker admission',async()=>{
  const render=jest.spyOn(PrintRenderWorker.prototype,'renderPayload');
  const server=createRendererServer();await new Promise<void>(r=>server.listen(0,'127.0.0.1',r));
  try {
    const status=await new Promise<number>((resolve,reject)=>{
      let received=false;
      const req=http.request({host:'127.0.0.1',port:(server.address() as any).port,path:'/v1/render',method:'POST'},res=>{
        received=true;res.resume();res.on('end',()=>resolve(res.statusCode!));
      });
      req.on('error',error=>{if(!received)reject(error);});req.end(Buffer.alloc(8388609,120));
    });
    expect(status).toBe(413);expect(render).not.toHaveBeenCalled();
  }finally{server.closeAllConnections();await new Promise<void>(r=>server.close(()=>r()));}
});
