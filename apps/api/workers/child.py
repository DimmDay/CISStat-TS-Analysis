"""Trusted pure-work child entry point. Never accepts browser work orders/pickle."""

import math
import os
import pickle
import signal
import sys
import time
from contextlib import nullcontext


def main():
    if sys.platform == "linux":
        import ctypes

        ctypes.CDLL(None).prctl(1, signal.SIGKILL)
        if os.getppid() != int(sys.argv[3]):
            return 124
    with open(sys.argv[1], "rb") as stream:
        (
            target,
            args,
            kwargs,
            admission,
            memory_mb,
            timeout,
            max_output,
            work_key,
            work_limit,
        ) = pickle.load(stream)
    if os.name == "posix":
        import resource

        resource.setrlimit(
            resource.RLIMIT_CPU,
            (max(1, math.ceil(timeout)), max(2, math.ceil(timeout) + 1)),
        )
        if memory_mb:
            size = int(memory_mb * 1024 * 1024)
            resource.setrlimit(resource.RLIMIT_DATA, (size, size))
    from apps.api.billing.compute_meter import IN_CHILD, meter_scope

    IN_CHILD.set(True)
    started = time.process_time_ns()
    children_cpu = 0
    if os.name == "posix":
        usage = resource.getrusage(resource.RUSAGE_CHILDREN)
        children_cpu = usage.ru_utime + usage.ru_stime
    try:
        with (
            meter_scope(work_key, work_limit, path=sys.argv[4])
            if work_key
            else nullcontext()
        ):
            if admission is not None:
                from apps.api.scientific import execution_scope

                with execution_scope(admission):
                    value = target(*args, **kwargs)
            else:
                value = target(*args, **kwargs)
            result = ("ok", value)
    except BaseException as exc:
        from apps.api.backtesting import BacktestExecutionError
        from fastapi import HTTPException

        if isinstance(exc, HTTPException):
            result = (
                "http_error",
                {
                    "status_code": exc.status_code,
                    "detail": exc.detail,
                    "headers": exc.headers,
                },
            )
        elif isinstance(
            exc, (BacktestExecutionError, ValueError, ArithmeticError, RuntimeError)
        ):
            result = ("domain_error", exc)
        else:
            # Exception class only: messages may contain data, paths or credentials.
            result = ("error", "worker_computation_failed:" + type(exc).__name__)
    peak = None
    if os.name == "posix":
        import resource

        peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * (
            1 if sys.platform == "darwin" else 1024
        )
    cpu_ns = time.process_time_ns() - started
    if os.name == "posix":
        usage = resource.getrusage(resource.RUSAGE_CHILDREN)
        cpu_ns += int(max(0, usage.ru_utime + usage.ru_stime - children_cpu) * 1e9)
        peak += usage.ru_maxrss * (1 if sys.platform == "darwin" else 1024)
    metrics = {"cpu_ns": cpu_ns, "rss_peak_bytes": peak}
    result = (*result, metrics)
    data = pickle.dumps(result, protocol=5)
    if len(data) > max_output:
        data = pickle.dumps(("error", "worker_output_limit", metrics), protocol=5)
    with open(sys.argv[2], "wb") as stream:
        stream.write(data)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
