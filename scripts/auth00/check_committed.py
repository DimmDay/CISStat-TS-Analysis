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
import json
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


class InventorySnapshotError(ValueError):
    """Name the failing snapshot rather than blaming every failure on staging."""

    def __init__(self, snapshot, message):
        self.snapshot = snapshot
        super().__init__(snapshot + " inventory check failed:\n" + message)


def _drift_details(collector, root):
    # Read-only diagnostics. Never rewrite the map, stage sources or import API code.
    try:
        declared = json.loads(
            (root / "docs/auth00/inventory.json").read_text(encoding="utf-8")
        )
    except (ValueError, OSError):
        return ["Declared inventory JSON is invalid or unavailable."]
    if not isinstance(declared, dict):
        return ["Declared inventory JSON is invalid: expected an object."]
    actual = collector.build(root)
    lines = []
    expected_hashes = declared.get("source_fingerprints", {})
    actual_hashes = actual["source_fingerprints"]
    if not isinstance(expected_hashes, dict):
        return ["Declared source_fingerprints is invalid: expected an object."]
    for path in sorted(expected_hashes.keys() | actual_hashes.keys()):
        expected, current = expected_hashes.get(path), actual_hashes.get(path)
        if expected != current:
            lines += [
                "Reviewed source differs: " + path,
                "  expected SHA-256: " + str(expected or "<absent>"),
                "  actual SHA-256:   " + str(current or "<absent>"),
            ]

    def entries(report):
        rows = report.get("entries", [])
        if not isinstance(rows, list) or any(
            not isinstance(e, dict) or "id" not in e for e in rows
        ):
            return None
        return {e["id"]: e for e in rows}

    old_entries, new_entries = entries(declared), entries(actual)
    if old_entries is None:
        lines.append("Declared inventory entries are invalid.")
    else:
        for key in sorted(old_entries.keys() | new_entries.keys()):
            old, new = old_entries.get(key), new_entries.get(key)
            if old != new:
                fields = sorted(
                    k
                    for k in (old or {}).keys() | (new or {}).keys()
                    if (old or {}).get(k) != (new or {}).get(k)
                )
                lines.append(
                    "Reviewed entry differs: "
                    + key
                    + " (fields: "
                    + ", ".join(fields)
                    + ")"
                )
    for key in sorted(declared.keys() | actual.keys()):
        if key not in {"source_fingerprints", "entries"} and declared.get(
            key
        ) != actual.get(key):
            lines.append("Reviewed inventory metadata differs: " + key)
    if not lines:
        lines.append(
            "Rediscovered report data matches; serialization/documentation differs."
        )
    return lines


def _checked_inventory(collector, root, snapshot):
    try:
        return collector.check(root)
    except ValueError as exc:
        message = str(exc)
        if message.startswith("Inventory drift:"):
            message += "\n" + "\n".join(_drift_details(collector, root))
        raise InventorySnapshotError(snapshot, message) from exc


def check(root: Path = ROOT, target: str = "head") -> int:
    if target not in {"head", "index"}:
        raise ValueError("Unknown Git snapshot target")
    root = Path(root)
    work = _load_collector(root, "auth00_worktree")
    current = _checked_inventory(work, root, "WORKTREE")
    snapshot = _extract_snapshot(root, target)
    try:
        stored = _load_collector(snapshot, "auth00_" + target)
        expected = _checked_inventory(stored, snapshot, target.upper())
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
        if isinstance(exc, InventorySnapshotError) and exc.snapshot == "WORKTREE":
            print(
                "WORKTREE failed before the Git snapshot check; git add alone cannot repair WORKTREE drift. "
                "Review/restore the named sources and the matching delivered map. "
                "Do not regenerate the inventory merely to silence this failure. "
                "No files or index were changed.",
                file=sys.stderr,
            )
        elif args.target == "index":
            print(
                "INDEX may be stale or partially staged. Review the delivery manifests, explicitly git add all matching sources/maps, then retry. No automatic staging or commit was performed.",
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
