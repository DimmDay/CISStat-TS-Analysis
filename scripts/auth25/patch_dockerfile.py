#!/usr/bin/env python3
"""AUTH-25-HOTFIX-02: add or repair the AUTH-25 CLI COPY in apps/api/Dockerfile.

Why: the AUTH-25 delivery (base f6dbec9) shipped scripts/auth25/ but no COPY
line in apps/api/Dockerfile, so the CLI is missing inside the image
(WORKDIR /app + relative path -> "can't open file '/app/scripts/auth25/reconcile.py'").
The HOTFIX-01 patcher mirrored the last scripts/authNN COPY line verbatim;
when that line was auth20's file-list style, it produced
  COPY scripts/auth25/migrate.py scripts/auth25/reconcile.py ./scripts/auth25/
but AUTH-25 has no migrate.py (no migrations), so the build failed with
"not found". This version parses the anchor line, keeps only source paths
that actually exist in the build context (falling back to the canonical
scripts/auth25/reconcile.py), and REPAIRS an already-inserted invalid
auth25 line in place.

The only in-container CLI of AUTH-25 is reconcile.py (verify_postgres.py /
package_delivery.py are dev-side gates; requirements.txt is gate-side).

Usage:
  python scripts/auth25/patch_dockerfile.py [--check] [DOCKERFILE_PATH]
Exit codes: 0 patched / repaired / already valid / check done,
            1 Dockerfile not found, 2 no anchor / no build context (no change).
"""

import argparse
import difflib
import re
import shlex
import sys
from pathlib import Path

COPY_RE = re.compile(r"^\s*COPY\b")
ANCHOR_RE = re.compile(r"\bscripts/auth2\d\b")
AUTH_TOKEN_RE = re.compile(r"auth2\d")
CMD_ENTRY_RE = re.compile(r"^\s*(CMD|ENTRYPOINT)\b")
INDENT_RE = re.compile(r"^\s*")
CLI = "scripts/auth25/reconcile.py"  # must exist in the build context
PLAIN_LINE = "COPY scripts/auth25 ./scripts/auth25"


def find_context_root(dockerfile_path):
    """Repo root = first ancestor of the Dockerfile (or of this script) that
    contains scripts/auth25/reconcile.py — the compose build context."""
    for cand in list(dockerfile_path.parents) + [Path(__file__).resolve().parents[2]]:
        if (cand / CLI).is_file():
            return cand
    return None


def parse_copy(line):
    """Return (indent, flags, sources, dest) or None for non-parseable COPY."""
    try:
        tokens = shlex.split(line)
    except ValueError:
        return None
    if not tokens or tokens[0] != "COPY":
        return None
    rest = tokens[1:]
    flags = [t for t in rest if t.startswith("--")]
    args = [t for t in rest if not t.startswith("--")]
    if len(args) < 2:
        return None
    return INDENT_RE.match(line).group(0), flags, args[:-1], args[-1]


def join_copy(indent, flags, sources, dest):
    return indent + " ".join(["COPY"] + flags + list(sources) + [dest])


def source_is_copyable(root, rel):
    p = root / rel
    if p.is_file():
        return True
    if p.is_dir():
        return any(x.is_file() for x in p.iterdir())
    return False


def build_line(anchor, root):
    """Mirror the anchor COPY line for auth25, keeping only sources that exist
    in the build context; None if the anchor cannot be mirrored safely."""
    if anchor.rstrip().endswith("\\"):
        return None  # multi-line COPY continuation — not safe to mirror
    parsed = parse_copy(anchor)
    if parsed is None:
        return None
    indent, flags, sources, dest = parsed
    mapped = [AUTH_TOKEN_RE.sub("auth25", t) for t in sources]
    dst = AUTH_TOKEN_RE.sub("auth25", dest)

    # whole-directory style: single source that IS the auth25 dir itself
    if len(mapped) == 1 and mapped[0].rstrip("/") == "scripts/auth25":
        return join_copy(indent, flags, mapped, dst)

    # file-list style: keep only sources present in the build context
    existing = [s for s in mapped if source_is_copyable(root, s)]
    if not existing:
        existing = [CLI]
    if len(existing) > 1 and not dst.endswith("/"):
        dst = dst.rsplit("/", 1)[0] + "/" if "/" in dst else "./"
    return join_copy(indent, flags, existing, dst)


def line_is_valid(line, root):
    """True if an existing auth25 COPY line would build (all sources exist)."""
    parsed = parse_copy(line)
    if parsed is None:
        return False
    _, _, sources, dest = parsed
    if not any("auth25" in s for s in sources + [dest]):
        return False
    if len(sources) > 1 and not dest.endswith("/"):
        return False
    return all(source_is_copyable(root, s) for s in sources)


def apply_changes(lines, changes):
    """changes: list of (index, new_line, insert_before_original)."""
    out = list(lines)
    for index, new_line, insert in sorted(changes, reverse=True):
        if insert:
            out.insert(index, new_line)
        else:
            out[index] = new_line
    return out


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

    root = find_context_root(path)
    if root is None:
        print(
            "FAIL: %s not found near %s — unpack the AUTH-25 delivery into the repo first"
            % (CLI, path)
        )
        return 2

    lines = path.read_text(encoding="utf-8").splitlines()

    # 1) existing auth25 COPY lines: valid -> OK; invalid -> repair in place
    targets = [i for i, ln in enumerate(lines) if COPY_RE.match(ln) and "scripts/auth25" in ln]
    changes = []
    for i in targets:
        if line_is_valid(lines[i], root):
            continue
        new_line = build_line(lines[i], root)
        if new_line is None:
            print(
                "FAIL: cannot repair invalid auth25 COPY at line %d in %s — fix manually"
                % (i + 1, path)
            )
            return 2
        changes.append((i, new_line, False))

    if targets and not changes:
        print("OK: scripts/auth25 COPY lines are valid in %s" % path)
        for i in targets:
            print("  %s" % lines[i].strip())
        return 0

    # 2) no auth25 line: insert one next to the last scripts/authNN COPY
    if not targets:
        anchor_idx = None
        for i, ln in enumerate(lines):
            if COPY_RE.match(ln) and ANCHOR_RE.search(ln):
                anchor_idx = i
        new_line = build_line(lines[anchor_idx], root) if anchor_idx is not None else None
        if new_line is not None:
            changes.append((anchor_idx + 1, new_line, True))
        else:
            insert_at = None
            for i, ln in enumerate(lines):
                if CMD_ENTRY_RE.match(ln) and (anchor_idx is None or i > anchor_idx):
                    insert_at = i
                    break
            if insert_at is None:
                print(
                    "FAIL: no scripts/authNN COPY anchor and no CMD/ENTRYPOINT found "
                    "in %s — patch manually next to the other COPY lines" % path
                )
                return 2
            changes.append((insert_at, PLAIN_LINE, True))

    out = apply_changes(lines, changes)
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
