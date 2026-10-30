#!/usr/bin/env python3
"""RED: воспроизведение отказа auth00-сьюта на Windows без настоящей Windows.

Патчит pathlib.Path.open так, что любая запись (write_text/open('w'/'a')
с newline=None) переводит '\n' -> '\r\n' — ровно то, что делает
TextIOWrapper(newline=None) на настоящей Windows (os.linesep='\r\n').
Чтения остаются universal-newlines, как на реальной Windows.

Ожидание (гипотеза): падает ровно один тест —
test_crlf_checkout_does_not_change_source_fingerprints (Inventory drift).
"""
import io
import pathlib
import sys
import unittest

_orig_open = pathlib.Path.open


def win_open(self, mode="r", buffering=-1, encoding=None, errors=None, newline=None):
    if "b" not in mode and newline is None and any(m in mode for m in ("w", "a", "x")):
        newline = "\r\n"  # на Windows newline=None пишет через os.linesep='\r\n'
    return _orig_open(self, mode, buffering, encoding, errors, newline)


pathlib.Path.open = win_open

sys.argv = ["unittest", "discover", "-s", "tests/unit",
            "-p", "test_auth00_inventory.py", "-v"]
unittest.main(module=None, argv=sys.argv, exit=True)
