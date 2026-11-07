#!/usr/bin/env python3
"""Compare reviewed worktree with a real Git snapshot; never stage or commit.

HEAD (standalone default) checks the existing commit. INDEX supports local
precommit gates after an explicit git add, including unborn branches. The Git
write-tree result freezes the index; archive extraction never reads unstaged
files. Both snapshots must pass their own inventory drift/classification check,
then their full reviewed reports must match. This retains the ignored-page
protection from AUTH-07-HOTFIX1 and also catches unstaged guard/helper changes.
"""

from __future__ import annotations

import argparse
import importlib.util
import io
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _load_collector(root: Path, name: str):
    source = root / "scripts/auth00/inventory.py"
    if not source.is_file():
        raise ValueError("Missing inventory collector: scripts/auth00/inventory.py")
    spec = importlib.util.spec_from_file_location(name, source)
    collector = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(collector)
    return collector


def _git(root: Path, *args: str) -> bytes:
    result = subprocess.run(["git", *args], cwd=root, capture_output=True, check=False)
    if result.returncode:
        message = result.stderr.decode("utf-8", errors="replace").strip()
        raise ValueError("git " + " ".join(args) + ": " + message)
    return result.stdout


def _extract_snapshot(root: Path, target: str) -> Path:
    # write-tree creates only tree/blob objects, never a commit or a ref update.
    tree = (
        _git(root, "write-tree").decode("ascii").strip()
        if target == "index"
        else "HEAD"
    )
    archive = _git(root, "archive", "--format=tar", tree)
    snapshot = Path(tempfile.mkdtemp(prefix="auth00-" + target + "-parity-"))
    try:
        with tarfile.open(fileobj=io.BytesIO(archive), mode="r:") as tar:
            try:
                tar.extractall(snapshot, filter="data")
            except TypeError:  # Python 3.9/3.10 compatibility
                tar.extractall(snapshot)
        return snapshot
    except BaseException:
        shutil.rmtree(snapshot, ignore_errors=True)
        raise


def check(root: Path = ROOT, target: str = "head") -> int:
    if target not in {"head", "index"}:
        raise ValueError("Unknown Git snapshot target")
    root = Path(root)
    work = _load_collector(root, "auth00_worktree")
    current = work.check(root)
    snapshot = _extract_snapshot(root, target)
    try:
        stored = _load_collector(snapshot, "auth00_" + target)
        expected = stored.check(snapshot)
    finally:
        shutil.rmtree(snapshot, ignore_errors=True)
    if current != expected:
        work_ids = {entry["id"] for entry in current["entries"]}
        target_ids = {entry["id"] for entry in expected["entries"]}
        lines = ["Reviewed worktree differs from " + target.upper() + ":"]
        lines += [
            "  Worktree only: " + entry for entry in sorted(work_ids - target_ids)
        ]
        lines += [
            "  Snapshot only: " + entry for entry in sorted(target_ids - work_ids)
        ]
        fingerprints = current["source_fingerprints"]
        old = expected["source_fingerprints"]
        paths = sorted(
            path
            for path in fingerprints.keys() | old.keys()
            if fingerprints.get(path) != old.get(path)
        )
        lines += ["  Reviewed source differs: " + path for path in paths]
        if not paths and work_ids == target_ids:
            lines.append("  Reviewed catalogue/classification metadata differs.")
        raise ValueError("\n".join(lines))
    print(
        "auth00 "
        + target.upper()
        + "-parity: ok ("
        + str(len(work.discovery(root)))
        + " discovery surfaces; full reviewed inventory/source parity)"
    )
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--target",
        choices=("head", "index"),
        default="head",
        help="head: existing commit (default); index: staged precommit snapshot",
    )
    args = parser.parse_args(argv)
    try:
        return check(ROOT, args.target)
    except (ValueError, OSError, SyntaxError, tarfile.TarError) as exc:
        print(
            "auth00 " + args.target.upper() + "-parity: FAIL\n" + str(exc),
            file=sys.stderr,
        )
        if args.target == "index":
            print(
                "Review files, then git add them and retry. No automatic staging or commit was performed.",
                file=sys.stderr,
            )
        else:
            print(
                "For precommit use --target index after git add; HEAD mode checks the existing commit.",
                file=sys.stderr,
            )
        return 1


if __name__ == "__main__":
    sys.exit(main())
