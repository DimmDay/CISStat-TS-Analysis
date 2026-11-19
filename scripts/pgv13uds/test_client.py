"""UDS client protocol oracles. Actual HTTP wire; AF_UNIX replaced by TCP.
Filesystem validation is separately tested. This is NOT native UDS acceptance.
"""
import json
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace

import pytest

PATH = '/run/cisstat-renderer/render.sock'
PNG = b'\x89PNG\r\n\x1a\n' + b'wire-test-not-browser'


@pytest.fixture
def wire(monkeypatch):
    import apps.api.png_renderer_client as C
    state = SimpleNamespace(mode='png', requests=[], closed=threading.Event())
    class Handler(BaseHTTPRequestHandler):
        protocol_version = 'HTTP/1.1'
        def log_message(self, *args): pass
        def do_GET(self): self.reply()
        def do_POST(self): self.reply()
        def reply(self):
            data = self.rfile.read(int(self.headers.get('Content-Length', 0)))
            state.requests.append((self.command, self.path, dict(self.headers), data))
            status, body, content = 200, PNG, 'image/png'
            if self.path == '/readyz': body, content = b'{"status":"ready"}', 'application/json'
            if state.mode == 'redirect':
                status, body, content = 302, b'', 'text/plain'
            if state.mode in ('busy','dependency','payload','timeout'):
                status, code = {'busy':(429,'renderer_busy'),'dependency':(503,'render_dependency_unavailable'),
                                'payload':(422,'invalid_payload'),'timeout':(503,'render_timeout')}[state.mode]
                body, content = json.dumps({'error':{'code':code}}).encode(), 'application/json'
            if state.mode == 'bad': body = b'not png'
            if state.mode == 'huge': body = PNG + b'x' * 1024
            self.send_response(status)
            self.send_header('Content-Type', content)
            self.send_header('Connection', 'close')
            self.send_header('Location', 'http://127.0.0.1:1/forbidden')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            try:
                if state.mode == 'trickle':
                    for byte in PNG:
                        self.wfile.write(bytes([byte]));self.wfile.flush();time.sleep(.03)
                else: self.wfile.write(body);self.wfile.flush()
            except OSError: state.closed.set()
    server = ThreadingHTTPServer(('127.0.0.1',0), Handler)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever,daemon=True).start()
    class TcpSocket(socket.socket):
        def __init__(self): super().__init__(socket.AF_INET,socket.SOCK_STREAM)
        def connect(self, endpoint):
            assert endpoint == PATH
            super().connect(server.server_address)
    monkeypatch.setattr(C,'_new_unix_socket',TcpSocket,raising=False)
    monkeypatch.setattr(C,'_validate_unix_endpoint',lambda p:None,raising=False)
    state.client = lambda **kw:C.PngRendererClient(ipc_socket=PATH,base_url='http://must-not-be-used:1',**kw)
    yield state
    server.shutdown();server.server_close()


def test_explicit_ipc_config_is_preserved():
    from apps.api.png_renderer_client import PngRendererClient
    c=PngRendererClient(env={'CISSTAT_PNG_RENDERER_IPC':PATH})
    assert c.ipc_socket==PATH


def test_finite_timeout():
    from apps.api.png_renderer_client import renderer_timeout_from_env
    for value in ('nan','inf','-2','1000'):
        timeout=renderer_timeout_from_env({'CISSTAT_PNG_RENDERER_TIMEOUT_S':value})
        assert 0 < timeout <= 60


def test_wire_png_ready_and_no_credentials(wire):
    c=wire.client()
    assert c.render_page({'request_id':'wire','text':'Кириллица'})==PNG
    assert c.readiness()['status']=='ready'
    assert [(r[0],r[1]) for r in wire.requests]==[('POST','/v1/render'),('GET','/readyz')]
    headers={k.lower():v for k,v in wire.requests[0][2].items()}
    assert not set(headers)&{'cookie','authorization','x-api-key','proxy-authorization'}
    assert headers['host']=='renderer.local'
    assert json.loads(wire.requests[0][3])['text']=='Кириллица'


@pytest.mark.parametrize('mode,error',[('busy','RendererBusy'),('dependency','RendererDependencyUnavailable'),
    ('payload','RendererPayloadInvalid'),('timeout','RendererTimeout'),('bad','RendererBadOutput'),('redirect','RendererUnavailable')])
def test_error_taxonomy_and_no_redirect(wire,mode,error):
    import apps.api.png_renderer_client as C
    wire.mode=mode
    with pytest.raises(getattr(C,error)): wire.client().render_page({'request_id':'errors'})
    assert len(wire.requests)==1


def test_body_limit_before_connect(wire,monkeypatch):
    import apps.api.png_renderer_client as C
    monkeypatch.setattr(C,'MAX_REQUEST_BYTES',30)
    with pytest.raises(C.RendererPayloadTooLarge):wire.client().render_page({'text':'x'*100})
    assert not wire.requests


def test_response_bound(wire,monkeypatch):
    import apps.api.png_renderer_client as C
    monkeypatch.setattr(C,'MAX_PNG_BYTES',50)
    wire.mode='huge'
    with pytest.raises(C.RendererBadOutput):wire.client().render_page({'request_id':'oversize'})


def test_absolute_deadline_stops_trickle(wire):
    import apps.api.png_renderer_client as C
    wire.mode='trickle';start=time.monotonic()
    with pytest.raises(C.RendererTimeout):wire.client(timeout_s=.13).render_page({'request_id':'slow'})
    assert time.monotonic()-start < .7


def test_cancel_closes_inflight_socket(wire):
    import apps.api.png_renderer_client as C
    wire.mode='trickle';cancel=threading.Event();timer=threading.Timer(.1,cancel.set);timer.start()
    start=time.monotonic()
    try:
        with pytest.raises(C.RendererCancelled):wire.client().render_page({'request_id':'cancel'},cancel_event=cancel)
    finally:timer.cancel()
    assert time.monotonic()-start < .7
    assert wire.closed.wait(1)


def test_invalid_json_is_terminal_before_io(wire):
    import apps.api.png_renderer_client as C
    with pytest.raises(C.RendererPayloadInvalid):wire.client().render_page({'x':float('nan')})
    assert not wire.requests


def test_missing_socket_never_falls_back(monkeypatch):
    import apps.api.png_renderer_client as C
    monkeypatch.setattr(C.urllib.request,'urlopen',lambda *a,**k:pytest.fail('TCP fallback forbidden'))
    with pytest.raises(C.RendererUnavailable):C.PngRendererClient(ipc_socket=PATH).render_page({'request_id':'absent'})


@pytest.mark.parametrize('bad', ['relative.sock','/tmp/../sock','/tmp/\0sock','/'+'x'*120])
def test_bad_path_is_configuration_failure(bad):
    import apps.api.png_renderer_client as C
    with pytest.raises(C.RendererDependencyUnavailable):C.PngRendererClient(ipc_socket=bad).render_page({})


def test_managed_child_preserves_ipc_without_env_secrets(monkeypatch):
    import apps.api.png_renderer_client as C
    from apps.api.workers.render import print_bytes
    seen=[]
    def send(self,payload,**kw):seen.append((self.ipc_socket,self.enabled));return PNG
    monkeypatch.setattr(C.PngRendererClient,'render_page',send)
    assert print_bytes({},'http://unused',1,ipc_socket=PATH,enabled=False)==PNG
    assert seen==[(PATH,False)]


@pytest.mark.parametrize('bad', ['owner','group','directory_mode','socket_mode','symlink'])
def test_endpoint_filesystem_admission(monkeypatch,bad):
    import stat
    from pathlib import Path
    import apps.api.png_renderer_client as C
    directory=SimpleNamespace(st_mode=stat.S_IFDIR|0o750,st_uid=10001,st_gid=10001)
    endpoint=SimpleNamespace(st_mode=stat.S_IFSOCK|0o660,st_uid=10001,st_gid=10001)
    if bad=='owner':endpoint.st_uid=0
    if bad=='group':directory.st_gid=0
    if bad=='directory_mode':directory.st_mode=stat.S_IFDIR|0o777
    if bad=='socket_mode':endpoint.st_mode=stat.S_IFSOCK|0o666
    if bad=='symlink':endpoint.st_mode=stat.S_IFLNK|0o777
    monkeypatch.setattr(Path,'resolve',lambda p,**k:p)
    monkeypatch.setattr(Path,'lstat',lambda p:directory)
    monkeypatch.setattr(C.os,'lstat',lambda p:endpoint)
    with pytest.raises(C.RendererDependencyUnavailable):C._validate_unix_endpoint(PATH)


def test_worker_soft_timeout_aborts_real_client(wire):
    from apps.api.document_render_worker import DocumentRenderWorker
    from apps.api.png_renderer_client import RendererTimeout
    wire.mode='trickle'
    worker=DocumentRenderWorker(png_renderer=wire.client(),render_timeout=.1)
    with pytest.raises((RendererTimeout, __import__('apps.api.document_render_worker',fromlist=['RenderTimeoutError']).RenderTimeoutError)):
        worker._render_print_with_timeout({'request_id':'worker-deadline'})
    assert wire.closed.wait(1), 'soft timeout must close IPC, not abandon a live request'


def test_worker_job_cancel_aborts_transport(wire):
    from apps.api.document_render_worker import DocumentRenderWorker
    from apps.api.png_renderer_client import RendererCancelled
    wire.mode='trickle'
    registry=SimpleNamespace(get_job=lambda ref:SimpleNamespace(state='cancelled' if wire.requests else 'rendering'))
    worker=DocumentRenderWorker(service=SimpleNamespace(registry=registry),png_renderer=wire.client(),render_timeout=2)
    with pytest.raises(RendererCancelled):worker._render_print_with_timeout({'request_id':'job-cancel'},job_id='only-this-job')
    assert wire.closed.wait(1)


def test_ipc_ignores_even_malformed_tcp_configuration(wire,monkeypatch):
    import apps.api.png_renderer_client as C
    monkeypatch.setenv('HTTP_PROXY','http://must-not-contact:1')
    client=C.PngRendererClient(ipc_socket=PATH,base_url='malformed legacy URL')
    assert client.render_page({'request_id':'ipc-only'})==PNG


def test_rejected_response_reader_is_closed(wire,monkeypatch):
    import apps.api.png_renderer_client as C
    wire.mode='huge';monkeypatch.setattr(C,'MAX_PNG_BYTES',50)
    observed=[];original=C._UnixHTTPConnection.getresponse
    def tracked(connection):
        response=original(connection);observed.append(response);return response
    monkeypatch.setattr(C._UnixHTTPConnection,'getresponse',tracked)
    with pytest.raises(C.RendererBadOutput):wire.client().render_page({'request_id':'close-rejected-reader'})
    assert observed and observed[0].isclosed(), 'over-limit body must not retain a buffered socket FD'
