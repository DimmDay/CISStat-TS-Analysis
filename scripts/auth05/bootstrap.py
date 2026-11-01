#!/usr/bin/env python3
"""Operator-only bootstrap; secrets/passwords never accepted via argv or logs."""

import argparse
import json
import sys
from getpass import getpass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from apps.api.authentication.mfa import MfaService


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["prepare", "create"])
    parser.add_argument("--login")
    args = parser.parse_args()
    if not sys.stdin.isatty():
        parser.error("Use a protected interactive operator terminal")
    try:
        service = MfaService()
        if args.command == "prepare":
            print(
                service.prepare_bootstrap()
            )  # one-time intentional operator disclosure
        else:
            if not args.login:
                parser.error("--login is required")
            secret = getpass("Provisioning secret: ")
            password = getpass("Named admin passphrase: ")
            if getpass("Repeat passphrase: ") != password:
                raise ValueError("mismatch")
            print(json.dumps(service.bootstrap(secret, args.login, password)))
        return 0
    except Exception:  # noqa: BLE001 — operator boundary must redact all authority errors
        print(json.dumps({"ok": False, "code": "bootstrap_failed"}))
        return 1


if __name__ == "__main__":
    sys.exit(main())
