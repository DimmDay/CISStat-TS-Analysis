#!/usr/bin/env python3
"""Run the full CI procedure from local_gates too; retain evidence outside checkout."""
import argparse
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile

ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT))
from scripts.pgv1314cert.local import run_local


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--out',type=Path)
    args=p.parse_args(argv)
    try:
        version=subprocess.check_output(['node','--version'],text=True,encoding='utf-8').strip()
        if not re.fullmatch(r'v22\.\d+\.\d+',version):
            raise ValueError('Full CI parity requires Node22, as pgv1314cert.yml; found '+version)
        out=args.out.resolve() if args.out else Path(tempfile.mkdtemp(prefix='pgv1314-local-',dir=ROOT.parent))/'evidence'
        print(json.dumps({'node':version,'local_evidence':str(out),'scope':'complete CI procedure, not controls only'}),flush=True)
        return run_local(out)
    except (OSError,ValueError,subprocess.SubprocessError) as error:
        print(json.dumps({'state':'FAIL','passed':False,'error_type':type(error).__name__,
            'detail':str(error) if isinstance(error,ValueError) else 'Node22 and a writable new evidence directory are required'}))
        return 2


if __name__=='__main__':raise SystemExit(main())
