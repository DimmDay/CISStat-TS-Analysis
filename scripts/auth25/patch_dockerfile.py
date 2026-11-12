#!/usr/bin/env python3
"""AUTH-25-HOTFIX-01: add the AUTH-25 ops CLI to the api image (apps/api/Dockerfile).

The AUTH-25 delivery (base f6dbec9) shipped scripts/auth25/ into the repo but
did not extend apps/api/Dockerfile with a COPY line (every earlier delivery
did: AUTH-20 "COPY auth20", AUTH-21 "COPY CLI", ...). The image therefore
builds fine, but the CLI is missing inside the container:
  docker compose exec api python scripts/auth25/reconcile.py --report
  -> python: can't open file '/app/scripts/auth25/reconcile.py'
(docker compose exec starts in the image WORKDIR, /app; the relative path is
resolved from there, and the file was never baked into the image).

The patch inserts ONE line for scripts/auth25 next to the existing
scripts/authNN COPY lines, mirroring their exact style (--chown flags,
relative/absolute destination). Idempotent: re-running is a no-op. A
.bak backup is written next to the Dockerfile before the first change.

Usage:
  python scripts/auth25/patch_dockerfile.py [--check] [DOCKERFILE_PATH]
Exit codes: 0 patched / already present / check done,
            1 Dockerfile not found, 2 no safe anchor found (no change).
"""

import argparse
import difflib
import re
import sys
from pathlib import Path

COPY_RE = re.compile(r"^\s*COPY\b")
ANCHOR_RE = re.compile(r"\bscripts/auth2\d\b")
AUTH_TOKEN_RE = re.compile(r"auth2\d")
CMD_ENTRY_RE = re.compile(r"^\s*(CMD|ENTRYPOINT)\b")
PLAIN_LINE = "COPY scripts/auth25 ./scripts/auth25"


def build_line(anchor):
    """Mirror the anchor COPY line for auth25, or None if unsafe."""
    if anchor.rstrip().endswith("\\"):
        return None  # multi-line COPY continuation — not safe to mirror
    candidate = AUTH_TOKEN_RE.sub("auth25", anchor).rstrip()
    if "scripts/auth25" in candidate:
        return candidate
    return None


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "dockerfile",
        nargs="?",
        default=None,
        help="path to apps/api/Dockerfile (default: <repo-root>/apps/api/Dockerfile)",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="print the diff only; do not write anything",
    )
    args = parser.parse_args(argv)

    if args.dockerfile:
        path = Path(args.dockerfile)
    else:
        path = Path(__file__).resolve().parents[2] / "apps" / "api" / "Dockerfile"
    if not path.is_file():
        print("NOT FOUND: %s" % path)
        return 1

    lines = path.read_text(encoding="utf-8").splitlines()

    for line in lines:
        if COPY_RE.match(line) and "scripts/auth25" in line:
            print("OK: scripts/auth25 is already copied in %s:\n  %s" % (path, line.strip()))
            return 0

    anchor_idx = None
    for i, line in enumerate(lines):
        if COPY_RE.match(line) and ANCHOR_RE.search(line):
            anchor_idx = i  # last match wins
    new_line = None
    insert_at = None
    if anchor_idx is not None:
        new_line = build_line(lines[anchor_idx])
        if new_line is not None:
            insert_at = anchor_idx + 1
    if new_line is None:
        for i, line in enumerate(lines):
            if CMD_ENTRY_RE.match(line) and (anchor_idx is None or i > anchor_idx):
                insert_at = i
                break
        if insert_at is None:
            print(
                "FAIL: no scripts/authNN COPY anchor and no CMD/ENTRYPOINT found "
                "in %s — patch manually next to the other COPY lines" % path
            )
            return 2
        new_line = PLAIN_LINE

    out = lines[:insert_at] + [new_line] + lines[insert_at:]
    diff = "\n".join(
        difflib.unified_diff(
            lines,
            out,
            fromfile=str(path) + " (before)",
            tofile=str(path) + " (after)",
            lineterm="",
        )
    )
    print(diff)
    if args.check:
        print("CHECK: patch needed (re-run without --check to apply)")
        return 0

    backup = path.with_name(path.name + ".auth25-hotfix.bak")
    if not backup.exists():
        backup.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    path.write_text("\n".join(out) + "\n", encoding="utf-8")
    print("PATCHED: %s (backup: %s)\nNext: docker compose build api" % (path, backup))
    return 0


if __name__ == "__main__":
    sys.exit(main())
