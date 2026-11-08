"""Trusted pure-work child entry point. Never accepts browser work orders/pickle."""

import math
import os
import pickle
import signal
import sys


def main():
    if sys.platform == "linux":
        import ctypes

        ctypes.CDLL(None).prctl(1, signal.SIGKILL)
        if os.getppid() != int(sys.argv[3]):
            return 124
    with open(sys.argv[1], "rb") as stream:
        target, args, kwargs, admission, memory_mb, timeout, max_output = pickle.load(
            stream
        )
    if os.name == "posix":
        import resource

        resource.setrlimit(
            resource.RLIMIT_CPU,
            (max(1, math.ceil(timeout)), max(2, math.ceil(timeout) + 1)),
        )
        if memory_mb:
            size = int(memory_mb * 1024 * 1024)
            resource.setrlimit(resource.RLIMIT_DATA, (size, size))
    try:
        if admission is not None:
            from apps.api.scientific import execution_scope

            with execution_scope(admission):
                value = target(*args, **kwargs)
        else:
            value = target(*args, **kwargs)
        result = ("ok", value)
    except BaseException as exc:
        from apps.api.backtesting import BacktestExecutionError

        if isinstance(
            exc, (BacktestExecutionError, ValueError, ArithmeticError, RuntimeError)
        ):
            result = ("domain_error", exc)
        else:
            # Exception class only: messages may contain data, paths or credentials.
            result = ("error", "worker_computation_failed:" + type(exc).__name__)
    data = pickle.dumps(result, protocol=5)
    if len(data) > max_output:
        data = pickle.dumps(("error", "worker_output_limit"), protocol=5)
    with open(sys.argv[2], "wb") as stream:
        stream.write(data)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
