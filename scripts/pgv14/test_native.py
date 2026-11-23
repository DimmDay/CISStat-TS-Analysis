"""Real PostgreSQL/AuthSession/jobs; controlled ZIP/PNG double, NOT Chromium."""
import io,json,os,subprocess,sys,tempfile,threading,unittest,hashlib,zipfile
from pathlib import Path
from http.server import BaseHTTPRequestHandler,HTTPServer
from uuid import uuid4
from PIL import Image,ImageDraw
ROOT=Path(__file__).resolve().parents[2]

class NativePageSets(unittest.TestCase):
    def test_all_eleven_real_managed_jobs_and_metadata_download(self):
        import psycopg
        from psycopg import sql
        from psycopg.conninfo import make_conninfo
        from scripts.pgv14.client import CASES
        from scripts.pgv13accept.oracles import GEOMETRY,sha
        admin=os.environ.get('CISSTAT_PGV13_CERT_DSN');self.assertTrue(admin,'Disposable native DSN required; no skip')
        database='pgv13accept_'+uuid4().hex
        with psycopg.connect(admin,autocommit=True) as c:c.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(database)))
        try:
            class Handler(BaseHTTPRequestHandler):
                def do_POST(self):
                    payload=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                    profile=payload['snapshot']['print']['profile_id'];width,height=GEOMETRY[profile]
                    from apps.api.print_schema import resolve_print_profile
                    spec=resolve_print_profile(profile);members={};pages=[]
                    for section,s in enumerate(payload['sections']):
                        # Two pages per section exercise ZIP + per-page validation.
                        for unit in range(2):
                            image=Image.new('RGB',(width,height),'white');ImageDraw.Draw(image).rectangle((100+len(pages)*20,100,500,200),fill='black')
                            out=io.BytesIO();image.save(out,format='PNG',dpi=(300,300));data=out.getvalue();name=f'page-{len(pages)+1:03}.png';members[name]=data
                            refs=[s['record']['snapshot_ref']] if s['kind']=='passport_record' else [r for r in s['comparison']['ordered_refs'] if r]
                            pages.append({'index':len(pages)+1,'filename':name,'size_bytes':len(data),'sha256':sha(data),'role':'P01' if s['kind']=='passport_record' else 'P02',
                                'section_index':section,'source_refs':refs,'unit_ids':[f'{section}:{unit}']})
                    for p in pages:p.update(page_role=p['role'],png_sha256=p['sha256'],width_px=width,height_px=height)
                    meta=json.dumps({'schema_version':'pgv.page_metadata/1','source_payload':payload,'page_count':len(pages),'pages':pages,
                        'renderer_version':'print-renderer/1','font_profile':'print-fonts-dejavu/1'}).encode()
                    manifest={'schema_version':'pgv.print_manifest/1','page_set_version':'pgv.page_set/1','set_id':payload['request_id'],'render_version':'print-renderer/1','metadata_filename':'metadata.json','data_included':False,'profile_id':profile,'width':width,'height':height,'ppi':300,'intended_size_mm':{'width':spec['width_mm'],'height':spec['height_mm']},
                        'dependencies':sorted({r for p in pages for r in p['source_refs']}),'unit_count':len(pages),'pages':pages,'page_count':len(pages),
                        'metadata':{'filename':'metadata.json','sha256':sha(meta),'size_bytes':len(meta)}}
                    members['metadata.json']=meta;members['manifest.json']=json.dumps(manifest).encode();buf=io.BytesIO()
                    with zipfile.ZipFile(buf,'w',zipfile.ZIP_STORED) as z:
                        for name,b in members.items():z.writestr(name,b)
                    raw=buf.getvalue();self.send_response(200);self.send_header('Content-Type','application/zip');self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
                def log_message(self,*args):pass
            with HTTPServer(('127.0.0.1',0),Handler) as server:
                thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
                cfg={'socket':'','renderer_url':'http://127.0.0.1:'+str(server.server_port),'api_sources':{'apps/api/passport_documents.py':sha((ROOT/'apps/api/passport_documents.py').read_bytes().replace(b'\r\n',b'\n'))}}
                env={k:v for k,v in os.environ.items() if k in ('PATH','LANG','LC_ALL','SYSTEMROOT','LD_LIBRARY_PATH','TMPDIR')}
                env.update(CISSTAT_PGV13_ACCEPT_DSN=make_conninfo(admin,dbname=database),OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='1',PYTHONUNBUFFERED='1')
                result=subprocess.run([sys.executable,'-c',"import json,sys;from scripts.pgv14.client import run;print(json.dumps(run(json.load(sys.stdin)),ensure_ascii=False))"],cwd=ROOT,env=env,input=json.dumps(cfg),capture_output=True,text=True,encoding='utf-8',timeout=300)
                server.shutdown();thread.join(timeout=3)
            self.assertEqual(result.returncode,0,result.stderr[-7000:]+result.stdout[-4000:]);report=json.loads(result.stdout)
            self.assertEqual([c['id'] for c in report['cases']],[c['id'] for c in CASES]);self.assertTrue(report['passed'])
            self.assertTrue(all(c['delivery_format']=='zip' for c in report['cases']))
            print(json.dumps({'native':'PASS','cases':len(CASES),'metadata':'authorized/hash-bound','transport':'controlled ZIP double, NOT Chromium/UDS/OCR'}))
        finally:
            with psycopg.connect(admin,autocommit=True) as c:c.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(database)))

if __name__=='__main__':unittest.main()
