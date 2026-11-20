"""Actual PostgreSQL/AuthSession/jobs/worker test with a PNG transport double.

This is NOT Chromium/OCR/VM evidence. No skips: an absent test DSN is an error.
Run explicitly, never against a production DSN. Each run creates/drops its DB.
"""
import base64
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from uuid import uuid4

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[2]


class NativeTests(unittest.TestCase):
    def test_real_postgres_auth_managed_jobs_and_download(self):
        import psycopg
        from psycopg import sql
        from psycopg.conninfo import make_conninfo
        from scripts.pgv13accept.oracles import GEOMETRY, sha
        from scripts.pgv13accept.client import CASES
        admin = os.environ.get('CISSTAT_PGV13_CERT_DSN')
        self.assertTrue(admin, 'Explicit disposable CISSTAT_PGV13_CERT_DSN required; no skip')
        database = 'pgv13accept_'+uuid4().hex
        with psycopg.connect(admin,autocommit=True) as connection:
            connection.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(database)))
        try:
            with tempfile.TemporaryDirectory(prefix='p13-native-',dir=ROOT.parent) as temp:
                pngs = {}
                for profile,size in GEOMETRY.items():
                    image = Image.new('RGB',size,'white')
                    ImageDraw.Draw(image).rectangle((100,100,500,200),fill='black')
                    out = io.BytesIO();image.save(out,format='PNG',dpi=(300,300))
                    pngs[profile] = out.getvalue()
                class Handler(BaseHTTPRequestHandler):
                    def do_POST(self):
                        payload = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                        data = pngs[payload['snapshot']['print']['profile_id']]
                        self.send_response(200)
                        self.send_header('Content-Type','image/png')
                        self.send_header('Content-Length',str(len(data)))
                        self.end_headers();self.wfile.write(data)
                    def log_message(self,*args):
                        pass
                with HTTPServer(('127.0.0.1',0),Handler) as server:
                    thread = threading.Thread(target=server.serve_forever,daemon=True)
                    thread.start()
                    cfg = {'socket':'','renderer_url':'http://127.0.0.1:'+str(server.server_port),
                           'api_sources':{'apps/api/passport_documents.py':sha((ROOT/'apps/api/passport_documents.py').read_bytes().replace(b'\r\n',b'\n'))}}
                    env = {k:v for k,v in os.environ.items() if k in ('PATH','LANG','LC_ALL','SYSTEMROOT','LD_LIBRARY_PATH')}
                    env.update(CISSTAT_PGV13_ACCEPT_DSN=make_conninfo(admin,dbname=database),
                               OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='1',PYTHONUNBUFFERED='1')
                    code = "import json,sys;from scripts.pgv13accept.client import run;print(json.dumps(run(json.load(sys.stdin)),ensure_ascii=False))"
                    result = subprocess.run([sys.executable,'-c',code],cwd=ROOT,env=env,
                        input=json.dumps(cfg),capture_output=True,text=True,encoding='utf-8',timeout=240)
                    server.shutdown();thread.join(timeout=3)
                self.assertEqual(result.returncode,0,result.stderr[-7000:]+result.stdout[-3000:])
                report = json.loads(result.stdout)
                self.assertTrue(report['passed'])
                self.assertEqual([c['id'] for c in report['cases']],[c['id'] for c in CASES])
                for case in report['cases']:
                    self.assertTrue(all(case['checks'].values()))
                    self.assertEqual(base64.b64decode(case['png_base64']),pngs[case['profile']])
                print(json.dumps({'native_test':'PASS','cases':len(CASES),'backend':'PostgreSQL',
                    'transport':'controlled PNG double, NOT Chromium/OCR acceptance'},ensure_ascii=False))
        finally:
            with psycopg.connect(admin,autocommit=True) as connection:
                connection.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(database)))


if __name__ == '__main__':
    unittest.main()
