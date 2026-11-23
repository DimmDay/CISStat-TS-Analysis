"""Per-page pixel/OCR acceptance and hash-bound operator review for PGV14."""
import base64,csv,html,io,json
from pathlib import Path
from scripts.pgv13accept import oracles as O


def _join_tsv(parts):
    rows=[];header=None
    for text in parts:
        lines=text.splitlines();O.require(lines,'Missing page OCR')
        if header is None:header=lines[0]
        O.require(lines[0]==header,'OCR headers differ');rows.extend(lines[1:])
    return header+'\n'+'\n'.join(rows)+'\n'


def unpack(case,raw,payload):
    from apps.api.print_page_sets import validate_page_set,validate_png
    metadata=base64.b64decode(case['metadata_base64'],validate=True)
    parsed=json.loads(metadata)
    O.require(parsed.get('source_payload')==payload,'Metadata frozen-input binding differs')
    if case['delivery_format']=='zip':
        import zipfile
        verified=validate_page_set(raw,payload)
        O.require(verified.metadata==metadata,'Archive/sidecar metadata differs')
        manifest=verified.manifest
        with zipfile.ZipFile(io.BytesIO(raw)) as z:pages=[(p,z.read(p['filename'])) for p in manifest['pages']]
    else:
        O.require(case['delivery_format']=='png' and parsed['page_count']==1,'Invalid single-page representation')
        validate_png(raw,*O.GEOMETRY[case['profile']])
        p=parsed['pages'][0];O.require(p['index']==1 and p['sha256']==O.sha(raw) and p['size_bytes']==len(raw),'PNG metadata differs')
        manifest={'schema_version':'pgv.page_set/1','page_count':1,'pages':[p]};pages=[(p,raw)]
    return manifest,metadata,pages


def process_case(case,out,executable):
    name=case['id'];raw=base64.b64decode(case.pop('download_base64'),validate=True);payload=case.pop('payload')
    target=out/(name+'.'+case['delivery_format']);target.write_bytes(raw)
    case.update(download=target.name,download_sha256=O.sha(raw))
    manifest,metadata,pages=unpack(case,raw,payload)
    (out/(name+'.metadata.json')).write_bytes(metadata);case['metadata_sha256']=O.sha(metadata)
    (out/(name+'.payload.json')).write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8')
    case['payload_sha256']=O.sha((out/(name+'.payload.json')).read_bytes())
    case['page_manifest']=manifest;case['pages']=[];texts=[];latins=[];cards=[]
    for i,(descriptor,data) in enumerate(pages):
        stem=name+f'-page-{i+1:03}';png=out/(stem+'.png');png.write_bytes(data)
        row={**descriptor,'png':png.name,'png_sha256':O.sha(data),'pixels':O.check_png(data,case['profile'])}
        rec=O.recognize_png(png,executable);text=rec.pop('tsv');latin=rec.pop('latin_tsv')
        row['ocr_input']=rec
        for suffix,value,key in [('.ocr.tsv',text,'ocr_tsv_sha256'),('.latin.ocr.tsv',latin,'latin_ocr_tsv_sha256')]:
            path=out/(stem+suffix);path.write_text(value,encoding='utf-8');row[key]=O.sha(path.read_bytes())
        row['ocr']=O.check_document_ocr(text,latin,['Паспорт','Источник','Стр'],[str(i+1),str(len(pages))],O.GEOMETRY[case['profile']])
        case['pages'].append(row);texts.append(text);latins.append(latin)
        cards.append('<section><h3>'+html.escape(stem)+'</h3><a href="'+png.name+'"><img src="'+png.name+'" style="max-width:100%"></a></section>')
    case.pop('metadata_base64',None)
    case['ocr']=O.check_document_ocr(_join_tsv(texts),_join_tsv(latins),case['expected_text'],case['expected_numbers'],O.GEOMETRY[case['profile']],case.get('expected_counts',{}))
    case['pixels']={'passed':all(p['pixels']['passed'] for p in case['pages'])}
    return '<section><h2>'+html.escape(name)+'</h2>'+''.join(cards)+'</section>'


def review_template(report):
    return {'schema_version':'pgv14.visual_review/1','reviewer':'','reviewed_at':'',
        'cases':{c['id']:{'pages':{p['png']:dict.fromkeys(O.REVIEW_CHECKS,False) for p in c['pages']}} for c in report['cases']}}


def validate_saved_case(case,folder):
    payload_path=folder/(case['id']+'.payload.json');meta_path=folder/(case['id']+'.metadata.json');download=folder/case['download']
    for path,digest in [(payload_path,case['payload_sha256']),(meta_path,case['metadata_sha256']),(download,case['download_sha256'])]:
        O.require(path.resolve().is_relative_to(folder.resolve()) and O.sha(path.read_bytes())==digest,'Page-set evidence changed')
    reconstruction={**case,'metadata_base64':base64.b64encode(meta_path.read_bytes()).decode()}
    manifest,metadata,members=unpack(reconstruction,download.read_bytes(),json.loads(payload_path.read_text(encoding='utf-8')))
    O.require(case['page_manifest']==manifest and len(case['pages'])==len(members),'Page manifest changed')
    texts=[];latins=[]
    for row,(descriptor,data) in zip(case['pages'],members):
        O.require(row['index']==descriptor['index'] and row['png_sha256']==O.sha(data),'Page order/hash changed')
        png=(folder/row['png']).resolve();O.require(png.is_relative_to(folder.resolve()) and png.read_bytes()==data,'PNG evidence changed')
        O.check_png(data,case['profile']);stem=png.stem
        text_path=folder/(stem+'.ocr.tsv');latin_path=folder/(stem+'.latin.ocr.tsv')
        for path,key in [(text_path,'ocr_tsv_sha256'),(latin_path,'latin_ocr_tsv_sha256')]:O.require(O.sha(path.read_bytes())==row[key],'Per-page OCR changed')
        text=text_path.read_text(encoding='utf-8');latin=latin_path.read_text(encoding='utf-8')
        O.require(row.get('ocr_input',{}).get('pipeline')==O.OCR_PIPELINE and row['ocr_input'].get('source_sha256')==row['png_sha256'],'OCR pixel source changed')
        O.check_document_ocr(text,latin,['Паспорт','Источник','Стр'],[str(row['index']),str(len(members))],O.GEOMETRY[case['profile']]);texts.append(text);latins.append(latin)
    O.check_document_ocr(_join_tsv(texts),_join_tsv(latins),case['expected_text'],case['expected_numbers'],O.GEOMETRY[case['profile']],case.get('expected_counts',{}))
