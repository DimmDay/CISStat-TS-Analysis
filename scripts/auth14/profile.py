"""Verify raw benchmark evidence before an explicit atomic profile installation."""

import argparse, json, os, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--report", type=Path, required=True)
    p.add_argument("--candidate", type=Path, required=True)
    p.add_argument("--install", type=Path)
    args = p.parse_args()
    try:
        from apps.api.billing.compute_benchmark import calibrate
        from apps.api.billing.compute_profile import Profile

        report = json.loads(args.report.read_text())
        measured, _ = calibrate(report)
        candidate = Profile.model_validate_json(args.candidate.read_bytes())
        if candidate.digest != measured.digest:
            raise ValueError("candidate differs from raw evidence")
        candidate.check_environment()
        if args.install:
            args.install.parent.mkdir(parents=True, exist_ok=True)
            temp = args.install.with_suffix(".tmp")
            fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w") as stream:
                stream.write(candidate.model_dump_json(indent=2) + "\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp, args.install)
        print(
            json.dumps(
                {
                    "ok": True,
                    "profile_sha256": candidate.digest,
                    "keys": [c.key for c in candidate.coefficients],
                    "max_concurrency": candidate.max_concurrency,
                    "installed": str(args.install) if args.install else None,
                }
            )
        )
        return 0
    except Exception:
        print(json.dumps({"ok": False, "code": "compute_profile_invalid"}))
        return 1


if __name__ == "__main__":
    sys.exit(main())
