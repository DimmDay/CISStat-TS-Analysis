"""Two deterministic real-renderer refusal controls, run in pinned API image."""
import copy
import json
import urllib.error

class AcceptanceFailure(ValueError):pass

def require(ok,message):
    if not ok:raise AcceptanceFailure(message)


def run(config):
    from apps.api.png_renderer_client import PngRendererClient, MAX_PNG_BYTES
    original=config['payload']
    require(original['sections'][0]['kind']=='passport_record','P01 control input required')
    client=PngRendererClient(ipc_socket=config['socket'],base_url='',timeout_s=65)
    checks={}
    for name in ('page_cap','oversized_atom'):
        p=copy.deepcopy(original);p['request_id']='pgv1314-limit-'+name;p['options']={'page_set':True,'timeout_s':60}
        if name=='page_cap':
            p['sections']=[{**copy.deepcopy(original['sections'][0]),'section_id':'limit-'+str(i)} for i in range(21)]
        else:
            p['sections']=p['sections'][:1]
            p['sections'][0]['record']['passport']['cert_indivisible']={'text':'длинный неделимый абзац '*10000}
        require(len(json.dumps(p).encode('utf-8'))<8*1024*1024,'Control exceeded request cap instead of page cap')
        try:client._unix_request('POST','/v1/render',json.dumps(p,ensure_ascii=False).encode('utf-8'),65,MAX_PNG_BYTES,None)
        except urllib.error.HTTPError as e:
            error=json.loads(e.read())['error']
            expected='export_too_large' if name=='page_cap' else 'render_content_overflow'
            require(e.code==413 and error['code']==expected and error['retryable'] is False and e.headers.get('X-Render-Retryable')=='false','Wrong native HTTP/error/retryability response')
            checks[name]={'passed':True,'code':error['code'],'retryable':error['retryable'],'http_status':e.code,'retryable_header':e.headers.get('X-Render-Retryable')}
        else:raise AcceptanceFailure('Page budget control incorrectly returned output')
    return {'passed':True,'checks':checks}
