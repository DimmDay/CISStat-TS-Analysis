"""Package only this hotfix against the exact previously delivered AUTH-16 ZIP."""

import argparse
import hashlib
import shutil
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED

ROOT = Path(__file__).resolve().parents[3]
ORIGINAL_SHA256 = "fc46872d0dc04395ab899879824666dde63a14ae4d84661843de7fa91c01785c"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--original-zip", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=ROOT.parent / "download")
    args = parser.parse_args()
    if hashlib.sha256(args.original_zip.read_bytes()).hexdigest() != ORIGINAL_SHA256:
        raise ValueError("Exact reviewed original AUTH-16 archive required")
    with ZipFile(args.original_zip) as original:
        if original.testzip() is not None:
            raise ValueError("Original CRC mismatch")
        old = {name: original.read(name) for name in original.namelist()}
    additions = {
        p.relative_to(ROOT).as_posix()
        for p in (ROOT / "scripts/auth16/hotfix01").rglob("*")
        if p.is_file() and "__pycache__" not in p.parts
    } | {
        "docs/auth16/hotfix01.md",
        "scripts/auth16/hotfix01/files.txt",
        "scripts/auth00/inventory.py",
        "tests/unit/test_auth00_inventory.py",
        "tests/unit/test_auth00_precommit.py",
    }
    all_paths = sorted(set(old) | additions)
    (ROOT / "scripts/auth16/files.txt").write_text(
        "\n".join(all_paths) + "\n", encoding="utf-8", newline="\n"
    )
    changed = sorted(
        additions
        | {name for name, data in old.items() if (ROOT / name).read_bytes() != data}
    )
    (ROOT / "scripts/auth16/hotfix01/files.txt").write_text(
        "\n".join(changed) + "\n", encoding="utf-8", newline="\n"
    )
    if any(
        not (ROOT / name).is_file()
        or (ROOT / name).is_symlink()
        or Path(name).is_absolute()
        or ".." in Path(name).parts
        for name in changed
    ):
        raise ValueError("Only repository-relative regular files supported")
    args.output.mkdir(parents=True, exist_ok=True)
    archive = args.output / "cisstat-auth16-hotfix01.zip"
    with ZipFile(archive, "w", ZIP_DEFLATED, compresslevel=9) as out:
        for name in changed:
            out.write(ROOT / name, name)
    with ZipFile(archive) as out:
        if out.testzip() is not None or out.namelist() != changed:
            raise ValueError("Hotfix CRC/manifest mismatch")
        for name in changed:
            if out.read(name) != (ROOT / name).read_bytes():
                raise ValueError("Hotfix payload byte mismatch")
    (args.output / (archive.name + ".sha256")).write_text(
        hashlib.sha256(archive.read_bytes()).hexdigest() + "  " + archive.name + "\n",
        encoding="utf-8",
        newline="\n",
    )
    shutil.copyfile(
        ROOT / "scripts/auth16/hotfix01/files.txt",
        args.output / "auth16-hotfix01-files.txt",
    )
    shutil.copyfile(
        ROOT / "worklog/worklog12.md", args.output / "worklog12-auth16-hotfix01.md"
    )
    shutil.copyfile(
        ROOT / "docs/auth16/hotfix01.md",
        args.output / "auth16-hotfix01-instructions.md",
    )
    print(f"{archive}: {len(changed)} patch files; CRC and all bytes verified")


if __name__ == "__main__":
    main()
