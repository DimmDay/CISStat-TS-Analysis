"""Pixel/OCR oracles and hash-bound human review. Never use SSR as OCR input."""
import csv
from datetime import datetime
import hashlib
import io
import json
import math
from pathlib import Path
import re
import subprocess
import tempfile
import unicodedata

from PIL import Image
from scripts.pgv13uds.verify_vm import png_checks

GEOMETRY = {'figure-landscape': (2400, 1500), 'a4-portrait': (2480, 3508),
            'a4-landscape': (3508, 2480)}
REVIEW_CHECKS = ('legible', 'cyrillic_correct', 'no_overlap', 'no_clipping', 'values_and_reasons_correct')
OCR_PIPELINE = 'pgv13.pixel_bands_bilingual/1'
OCR_MAX_PIXELS = 24_000_000


def require(ok, message):
    if not ok:
        raise ValueError(message)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def capture(args, **kwargs):
    p = subprocess.run(args, capture_output=True, text=True, encoding='utf-8', timeout=120, **kwargs)
    require(p.returncode == 0, 'OCR command failed; inspect local dependencies')
    return p.stdout


def check_png(data, profile):
    require(profile in GEOMETRY, 'Unknown geometry profile')
    checks = png_checks(data, GEOMETRY[profile])
    require(checks['dimensions'], 'PNG dimensions differ from profile geometry')
    require(all(checks.values()), 'PNG structure/CRC/300ppi failed')
    with Image.open(io.BytesIO(data)) as image:
        image.load()
        rgba = image.convert('RGBA')
        require(rgba.getchannel('A').getextrema() == (255,255), 'PNG must be opaque; alpha differs')
        gray = rgba.convert('RGB').convert('L')
        histogram = gray.histogram()
        ink = sum(histogram[:200]) / (gray.width * gray.height)
        require(.0005 < ink < .60, 'PNG is blank or has implausible ink coverage')
    return {'passed': True, 'structure': checks, 'size': list(GEOMETRY[profile]), 'ink_fraction': ink}


def normalized(text):
    text = unicodedata.normalize('NFKC', text).casefold().replace('ё', 'е').replace('_',' ')
    return ' '.join(re.findall(r'[\w]+', text, flags=re.UNICODE))


def recognize_png(path, executable='tesseract'):
    """Recognize every ink band once, with no payload/expected-text input.

    Split only on >=64 entirely ink-free rows, retaining the distant footer.
    Disjoint crops prevent duplicate words/counts. Upscaling helps segmentation
    of small source glyphs; it is not evidence of human print legibility.
    """
    raw = Path(path).read_bytes()
    with Image.open(io.BytesIO(raw)) as opened:
        source = opened.convert('RGB')
    ink = source.convert('L').point(lambda p: 255 if p < 200 else 0)
    _, rows = ink.getprojection()
    occupied = [y for y, value in enumerate(rows) if value]
    require(occupied, 'OCR source contains no ink')
    bands = []
    start = last = occupied[0]
    for y in occupied[1:]:
        if y-last > 64:
            bands.append((start,last+1))
            start = y
        last = y
    bands.append((start,last+1))
    fields = ['left','top','width','height','conf','text']
    outputs = {language:io.StringIO() for language in ('rus+eng','eng')}
    writers = {language:csv.DictWriter(output,fields,delimiter='\t',lineterminator='\n')
               for language,output in outputs.items()}
    for writer in writers.values():
        writer.writeheader()
    regions = []
    with tempfile.TemporaryDirectory(prefix='pgv13-pixel-ocr-') as temp:
        for index,(top,bottom) in enumerate(bands):
            left,_,right,_ = ink.crop((0,top,source.width,bottom)).getbbox()
            box = (max(0,left-8), max(0,top-8), min(source.width,right+8), min(source.height,bottom+8))
            crop = source.crop(box)
            scale = next(n for n in (3,2,1) if crop.width*crop.height*n*n <= OCR_MAX_PIXELS)
            crop = crop.resize((crop.width*scale,crop.height*scale),Image.Resampling.LANCZOS)
            target = Path(temp)/(str(index)+'.png')
            crop.save(target,format='PNG',dpi=(300*scale,300*scale))
            raw_hashes = {}
            for language,writer in writers.items():
                text = capture([executable,str(target),'stdout','-l',language,'--psm','6',
                                '-c','tessedit_create_tsv=1'])
                raw_hashes[language] = sha(text.encode())
                reader = csv.DictReader(io.StringIO(text),delimiter='\t')
                require(reader.fieldnames and set(fields) <= set(reader.fieldnames),'OCR TSV is malformed')
                for row in reader:
                    if not (row.get('text') or '').strip():
                        continue
                    try:
                        x,y,w,h = (int(row[k]) for k in fields[:4])
                        conf = float(row['conf'])
                    except (ValueError,TypeError,KeyError):
                        raise ValueError('OCR TSV contains malformed word geometry') from None
                    require(math.isfinite(conf) and x>=0 and y>=0 and w>0 and h>0 and
                            x+w<=crop.width and y+h<=crop.height,'OCR crop word bounds failure')
                    # Enclose the recognized pixels in original PNG coordinates.
                    ox,oy = box[0]+x//scale, box[1]+y//scale
                    ex,ey = box[0]+math.ceil((x+w)/scale), box[1]+math.ceil((y+h)/scale)
                    writer.writerow(dict(zip(fields,[ox,oy,ex-ox,ey-oy,row['conf'],row['text']])))
            regions.append({'box':list(box),'scale':scale,'input_sha256':sha(target.read_bytes()),
                            'raw_tsv_sha256':raw_hashes})
    return {'pipeline':OCR_PIPELINE,'source_sha256':sha(raw),'regions':regions,
            'tsv':outputs['rus+eng'].getvalue(),'latin_tsv':outputs['eng'].getvalue()}


def check_document_ocr(tsv, latin_tsv, needles, numbers, size, counts=None):
    """Fixed script routing, never combine words to complete a missing phrase.

    Tesseract's Russian model reads Latin FFT as Cyrillic ЕЕТ with confidence.
    ASCII labels are therefore checked in the independent English pixel pass;
    Russian/mixed phrases, numbers and occurrence counts use rus+eng only.
    """
    latin = lambda text: bool(re.search('[A-Za-z]',text)) and not re.search('[А-Яа-яЁё]',text)
    result = check_ocr(tsv,[s for s in needles if not latin(s)],numbers,size,
                       {s:n for s,n in (counts or {}).items() if not latin(s)})
    result['latin'] = check_ocr(latin_tsv,[s for s in needles if latin(s)],[],size,
                               {s:n for s,n in (counts or {}).items() if latin(s)})
    return result


def check_ocr(tsv, needles, numbers, size, counts=None):
    reader = csv.DictReader(io.StringIO(tsv), delimiter='\t')
    require(reader.fieldnames and {'left','top','width','height','conf','text'} <= set(reader.fieldnames), 'OCR TSV is malformed')
    words = []
    for row in reader:
        if not (row.get('text') or '').strip():
            continue
        try:
            confidence = float(row['conf'])
            x,y,w,h = (int(row[k]) for k in ('left','top','width','height'))
        except (ValueError,TypeError,KeyError):
            raise ValueError('OCR TSV contains malformed word geometry') from None
        require(x >= 0 and y >= 0 and w > 0 and h > 0 and x+w <= size[0] and y+h <= size[1], 'OCR word bounds/clipping failure')
        if confidence >= 20:
            words.append({'text':row['text'],'box':[x,y,w,h],'confidence':confidence})
    require(words, 'OCR returned no confident text')
    text = normalized(' '.join(w['text'] for w in words))
    for needle in needles:
        require(normalized(needle) in text, 'OCR missing required text: '+needle)
    tokens = text.split()
    for value in numbers:
        require(normalized(str(value)) in tokens, 'OCR missing required numeric value: '+str(value))
    for needle,count in (counts or {}).items():
        require(text.count(normalized(needle))==count,'OCR occurrence count differs: '+needle)
    return {'passed':True, 'word_count':len(words), 'text_sha256':sha(text.encode()), 'words':words}


def ocr_environment(executable='tesseract'):
    languages = capture([executable, '--list-langs']).splitlines()
    require({'rus','eng'} <= set(l.strip() for l in languages), 'Tesseract rus and eng language data required; no fallback')
    location=re.search(r'in "([^"]+)"',languages[0])
    require(location,'Tesseract language data location unavailable')
    traineddata={name:sha((Path(location[1])/(name+'.traineddata')).read_bytes()) for name in ('rus','eng')}
    version = capture([executable, '--version']).splitlines()[0]
    return {'version':version,'languages':['rus','eng'],'traineddata_sha256':traineddata,
            'input':'downloaded PNG pixels; no HTML text layer'}


def validate_review(report_path, review):
    report_path = Path(report_path).resolve()
    raw = report_path.read_bytes()
    report = json.loads(raw)
    require(report.get('schema_version') == 'pgv13.documents/1' and report.get('automated_passed') is True, 'Automated acceptance must pass before visual review')
    require(review.get('schema_version') == 'pgv13.visual_review/1', 'Unknown review schema')
    require(review.get('report_sha256') == sha(raw), 'Review report hash changed')
    require(isinstance(review.get('reviewer'),str) and review['reviewer'].strip(), 'Named operator review required')
    try:
        timestamp = datetime.fromisoformat(review.get('reviewed_at','').replace('Z','+00:00'))
    except (ValueError, TypeError):
        raise ValueError('Aware review timestamp required') from None
    require(timestamp.tzinfo is not None, 'Aware review timestamp required')
    cases = report.get('cases') or []
    ids = [c['id'] for c in cases]
    require(ids and len(ids) == len(set(ids)) and set(review.get('cases',{})) == set(ids), 'Exact visual review case coverage required')
    for case in cases:
        flags = review['cases'][case['id']]
        require(set(flags) == set(REVIEW_CHECKS) and all(v is True for v in flags.values()), 'Every visual criterion must be explicitly true')
        path = (report_path.parent / case['png']).resolve()
        require(path.is_relative_to(report_path.parent) and path.is_file(), 'Review image path must remain in the evidence directory')
        require(sha(path.read_bytes()) == case['png_sha256'], 'Reviewed image hash changed')
    return {'p01_p02_accepted':True, 'pgv13_certified':False, 'reviewer':review['reviewer'], 'report_sha256':sha(raw)}
