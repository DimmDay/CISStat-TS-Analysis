"""Actual compiled HTTP + Playwright process-launch cleanup, no Chromium claim."""
import errno,json,os,shlex,signal,subprocess,time,urllib.error,urllib.request
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'scripts/pgv08fix/protocols'; OUT.mkdir(exist_ok=True)
DIST=ROOT/'apps/print-renderer/dist/apps/print-renderer/src'
TMP=ROOT.parent/'pgv08-tmp';TMP.mkdir(exist_ok=True)
PAYLOAD=json.loads(subprocess.check_output(['node','-e',f"console.log(JSON.stringify(require({json.dumps(str(DIST/'smokeScenarios.js'))}).cyrillicScenario()))"],cwd=ROOT,text=True))
OPENER=urllib.request.build_opener(urllib.request.ProxyHandler({}))
results=[]
def request(port,path,body=None):
 data=None if body is None else json.dumps(body).encode()
 req=urllib.request.Request(f'http://127.0.0.1:{port}{path}',data=data,headers={'Content-Type':'application/json'})
 try:
  with OPENER.open(req,timeout=8) as r:return r.status,json.load(r)
 except urllib.error.HTTPError as e:return e.code,json.load(e)
def check(name,ok,detail):
 results.append({'id':name,'passed':bool(ok),'detail':detail}); assert ok,(name,detail)
def server(port,browser,logname,smoke_entry=False):
 env=dict(os.environ,CISSTAT_PRINT_RENDERER_PORT=str(port),CISSTAT_PRINT_RENDERER_BROWSER_PATH=str(browser),CISSTAT_PRINT_RENDERER_TMP_DIR=str(TMP),TMPDIR=str(TMP),CISSTAT_PRINT_RENDERER_HARD_TIMEOUT_S='1')
 log=(ROOT/'scripts/pgv08/protocols'/logname).open('w')
 args=['node',str(DIST/('smoke.js' if smoke_entry else 'server.js'))]+(['--serve'] if smoke_entry else [])
 p=subprocess.Popen(args,cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT)
 for _ in range(80):
  try:
   if request(port,'/healthz')[0]==200:return p,log
  except Exception:pass
  if p.poll() is not None:break
  time.sleep(.05)
 raise RuntimeError('server did not become live')
def stop(p,log):
 p.terminate()
 try:p.wait(timeout=6)
 except subprocess.TimeoutExpired:p.kill();p.wait()
 log.close()
try:
 p,log=server(8987,'/nonexistent/chrome','server_dependency.log',smoke_entry=True)
 try:
  code,body=request(8987,'/readyz');check('missing-dependency',code==503 and body.get('unavailable_reason')=='missing_browser',body)
  bad=dict(PAYLOAD,options={'scale':3});code,body=request(8987,'/v1/render',bad);check('scale-before-browser',code==422,body)
  code,body=request(8987,'/v1/render',PAYLOAD);check('render-dependency',code==503 and body['error']['code']=='render_dependency_unavailable',body)
 finally:stop(p,log)
 pidfile=OUT/'cold_launch.pid';pidfile.unlink(missing_ok=True)
 wrapper=OUT/'cold_launch.sh'
 wrapper.write_text('#!/bin/sh\nprintf "%s" "$$" > '+shlex.quote(str(pidfile))+'\n/bin/sleep 8\n')
 wrapper.chmod(0o700)
 p,log=server(8988,wrapper,'server_main.log')
 try:
  start=time.monotonic();code,body=request(8988,'/v1/render',PAYLOAD)
  check('cold-timeout',code==503 and body['error']['code']=='render_timeout',{'status':code,'body':body,'seconds':time.monotonic()-start})
  check('cold-executable-started',pidfile.exists(), 'actual Playwright subprocess wrote its own PID')
  child=int(pidfile.read_text());alive=True
  for _ in range(40):
   try:os.kill(child,0)
   except ProcessLookupError:alive=False;break
   time.sleep(.05)
  check('cold-child-reaped',not alive,{'pid':child,'probe':'kill(pid,0) after actual Playwright launch timeout'})
  code,body=request(8988,'/healthz');check('server-survives',code==200,body)
 finally:stop(p,log)
 report={'verdict':'PASS','results':results,'boundary':'launch uses a deliberately slow shell executable, not Chromium; Docker/PNG pixels/OCR are not certified'}
except Exception as e:
 report={'verdict':'FAIL','results':results,'error':repr(e)}
finally:
 (OUT/'http_runtime.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
 print(json.dumps(report,ensure_ascii=False,indent=2))
raise SystemExit(0 if report['verdict']=='PASS' else 1)
