"""Real host calibration. Produces raw evidence and a candidate; never enables billing."""

import argparse, json, sys, time, itertools
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from apps.api.billing.compute_profile import machine, kernel_digest
from apps.api.billing.compute_benchmark import measure, calibrate


def numbers(value):
    values = sorted(set(int(x) for x in value.split(",")))
    if not values or any(x < 1 for x in values):
        raise argparse.ArgumentTypeError("positive integer list required")
    return values


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--models", default="ets")
    p.add_argument("--rows", type=numbers, default=[120, 240, 480])
    p.add_argument("--folds", type=numbers, default=[2, 3])
    p.add_argument("--trials", type=numbers, default=[1, 2])
    p.add_argument("--horizon", type=int, default=4)
    p.add_argument("--concurrency", type=int, default=1)
    p.add_argument("--timeout", type=int, default=120)
    p.add_argument("--memory-mb", type=int, default=1024)
    p.add_argument("--reserve-memory-mb", type=int, default=1024)
    args = p.parse_args()
    if (
        len(args.rows) < 3
        or not 1 <= args.concurrency <= 8
        or not 1 <= args.timeout <= 600
        or not 128 <= args.memory_mb <= 4096
        or args.reserve_memory_mb < 0
        or not 1 <= args.horizon <= 120
    ):
        p.error("finite benchmark bounds required; at least three row sizes")
    if max(args.rows) > 100000 or max(args.folds) > 20 or max(args.trials) > 64:
        p.error("benchmark matrix exceeds safety bound")
    keys = ["pelt"] + [
        "tuning:" + m.strip() for m in args.models.split(",") if m.strip()
    ]
    cases = []
    for key in keys:
        shapes = (
            [(1, 1)]
            if key == "pelt"
            else list(itertools.product(args.folds, args.trials))
        )
        for n, (folds, trials), seed in itertools.product(
            args.rows, shapes, [17, 29, 101]
        ):
            for scenario in ["smooth", "breaks"] if key == "pelt" else ["smooth"]:
                cases.append(
                    dict(
                        key=key,
                        rows=n,
                        folds=folds,
                        trials=trials,
                        horizon=args.horizon,
                        seed=seed,
                        holdout=seed == 101,
                        scenario=scenario,
                    )
                )
    if len(cases) > 1000:
        p.error("at most 1000 measured samples per report")
    args.output.mkdir(parents=True, exist_ok=True)
    for name in ("candidate.json", "validation.json"):
        (args.output / name).unlink(missing_ok=True)
    report = {
        "schema_version": "auth14.benchmark/1",
        "environment": machine(),
        "kernels": kernel_digest(),
        "requested_keys": keys,
        "timeout_seconds": args.timeout,
        "memory_mb": args.memory_mb,
        "reserve_memory_mb": args.reserve_memory_mb,
        "samples": [],
    }

    def save():
        (args.output / "report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n"
        )

    for index, case in enumerate(cases, 1):
        result = measure(case, timeout=args.timeout, memory_mb=args.memory_mb)
        report["samples"].append(result)
        save()
        print(
            f"{index}/{len(cases)} {case['key']} n={case['rows']} seed={case['seed']}: {result['status']}",
            flush=True,
        )
    hardest = max(
        (s for s in report["samples"] if s["status"] == "ok"),
        key=lambda s: s["metrics"]["parent_wall_ns"],
        default=None,
    )
    if hardest is None:
        print("No successful samples; profile unavailable")
        return 1
    started = time.monotonic_ns()
    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        samples = list(
            pool.map(
                lambda _: measure(
                    hardest["case"], timeout=args.timeout, memory_mb=args.memory_mb
                ),
                range(args.concurrency),
            )
        )
    report["load_test"] = {
        "concurrency": args.concurrency,
        "wall_ns": time.monotonic_ns() - started,
        "samples": samples,
    }
    save()
    try:
        profile, checks = calibrate(report)
        (args.output / "candidate.json").write_text(
            profile.model_dump_json(indent=2) + "\n"
        )
        (args.output / "validation.json").write_text(
            json.dumps(
                {"ok": True, "profile_sha256": profile.digest, "checks": checks},
                indent=2,
            )
            + "\n"
        )
        print(
            json.dumps(
                {
                    "ok": True,
                    "profile_sha256": profile.digest,
                    "candidate": str(args.output / "candidate.json"),
                }
            )
        )
        return 0
    except Exception as exc:
        (args.output / "validation.json").write_text(
            json.dumps({"ok": False, "code": str(exc)}) + "\n"
        )
        print("Calibration rejected; inspect validation.json. No profile enabled.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
