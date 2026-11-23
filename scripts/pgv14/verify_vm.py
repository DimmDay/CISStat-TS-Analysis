#!/usr/bin/env python3
"""PGV14: the existing isolated VM acceptance, with all pages of all 11 cases.

Same release/source/native AuthSession/managed workers/download and cleanup gates.
No product data, no science, no service recreation. Uses explicit candidate images.
"""
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from scripts.pgv13accept.verify_vm import main
if __name__=='__main__':raise SystemExit(main(page_sets=True))
