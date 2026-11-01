#!/usr/bin/env python3
"""Read-only baseline diagnosis: XLSX modified metadata depends on wall clock.

Not an AUTH-04 fix or a default gate. Two controlled clocks, one frozen snapshot.
"""
import argparse
from datetime import datetime,timezone
import io
import json
import os
from pathlib import Path
import runpy
import sys
import tempfile
from types import SimpleNamespace
from unittest.mock import patch
import zipfile


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--root',type=Path,required=True)
    root=p.parse_args().root.resolve();sys.path.insert(0,str(root));os.chdir(root)
    with tempfile.TemporaryDirectory(prefix='auth04-xlsx-',dir=root.parent) as tmp:
        os.environ['CISSTAT_DATA_DIR']=tmp
        for key in ('DATABASE_URL','REDIS_URL','CISSTAT_IDENTITY_MODE','CISSTAT_RUNS_BACKEND','CISSTAT_ARTIFACTS_BACKEND','CISSTAT_SNAPSHOTS_BACKEND'):
            os.environ.pop(key,None)
        module=runpy.run_path(str(root/'tests/api/test_doclog5_formats_worker.py'))
        snapshot=module['_seed_snapshot']()
        from apps.api.document_renditions import render_snapshot_xlsx
        def clock(second):
            class Fixed(datetime):
                @classmethod
                def now(cls,tz=None):return cls(2026,10,31,0,0,second,tzinfo=tz)
            return SimpleNamespace(datetime=Fixed,timezone=timezone)
        values=[]
        for second in (0,2):
            with patch('openpyxl.writer.excel.datetime',clock(second)):values.append(render_snapshot_xlsx(snapshot))
        with zipfile.ZipFile(io.BytesIO(values[0])) as a,zipfile.ZipFile(io.BytesIO(values[1])) as b:
            different=[name for name in a.namelist() if a.read(name)!=b.read(name)]
        assert values[0]!=values[1] and 'docProps/core.xml' in different
        print(json.dumps({'baseline_xlsx_determinism_defect_reproduced':True,'different_members':different,
            'same_frozen_snapshot':True,'only_clock_advanced':True,'auth04_source_used':False}))


if __name__=='__main__':main()
