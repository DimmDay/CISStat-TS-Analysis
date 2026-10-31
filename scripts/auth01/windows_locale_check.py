#!/usr/bin/env python3
"""Run the AUTH-01 corpus with Windows default text encodings on any OS.

This models Path.read_text's locale default, not a native Windows kernel.
Explicit encodings remain intact; no generated file is rewritten. Test both
Russian and Western Windows code pages even if the host enables UTF-8 mode.
"""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def main():
    original = Path.read_text
    for code_page in ("cp1251", "cp1252"):
        def locale_read_text(self, encoding=None, errors=None, **kwargs):
            selected = code_page if encoding in (None, "locale") else encoding
            return original(self, encoding=selected, errors=errors, **kwargs)

        print(f"AUTH-01 Path.read_text default encoding={code_page}", flush=True)
        with patch.object(Path, "read_text", locale_read_text):
            suite = unittest.defaultTestLoader.discover(
                str(ROOT / "tests/unit"), pattern="test_auth01_registry.py"
            )
            result = unittest.TextTestRunner(verbosity=2).run(suite)
        if not result.wasSuccessful():
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
