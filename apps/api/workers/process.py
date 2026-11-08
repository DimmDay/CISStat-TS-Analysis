"""Pure bounded subprocess: sanitized environment, stop/join proof, no DB publication."""

import os
import pickle
import signal
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass


@dataclass(frozen=True)
class StopProof:
    stopped: bool
    pid: int | None
    exit_code: int | None
    outcome: str
    usage: dict | None = None
    metrics: dict | None = None


class WorkStopped(RuntimeError):
    def __init__(self, code, proof):
        self.code = code
        self.proof = proof
        super().__init__(code)


class WorkFailed(RuntimeError):
    """A joined trial returned a known domain error, not an unknown execution."""

    def __init__(self, error, proof):
        self.error = error
        self.proof = proof
        super().__init__("worker_trial_failed")


def _linux_group(group):
    """Aggregate live process-group RSS, including native model subprocesses."""
    from pathlib import Path

    rss = 0
    pids = []
    for path in Path("/proc").glob("[0-9]*/stat"):
        try:
            fields = path.read_text().rsplit(")", 1)[1].split()
            if int(fields[2]) == group and fields[0] != "Z":
                pids.append(int(path.parent.name))
                rss += max(0, int(fields[21])) * os.sysconf("SC_PAGE_SIZE")
        except (OSError, ValueError, IndexError):
            continue
    return rss, pids


def child_environment():
    keep = {
        "PATH",
        "SYSTEMROOT",
        "WINDIR",
        "TEMP",
        "TMP",
        "TMPDIR",
        "LANG",
        "LC_ALL",
        "TZ",
        "LD_LIBRARY_PATH",
        "CUDA_VISIBLE_DEVICES",
    }
    result = {k: v for k, v in os.environ.items() if k.upper() in keep}
    result["PYTHONPATH"] = os.pathsep.join(str(x) for x in sys.path if x)
    for key in (
        "OMP_NUM_THREADS",
        "MKL_NUM_THREADS",
        "OPENBLAS_NUM_THREADS",
        "NUMEXPR_NUM_THREADS",
    ):
        result[key] = "1"
    result["PYTHONUNBUFFERED"] = "1"
    return result


def run_bounded(
    target,
    args=(),
    kwargs=None,
    *,
    timeout,
    checkpoint=None,
    memory_mb=None,
    admission=None,
    max_output=64 * 1024 * 1024,
    work_key=None,
    work_limit=None,
):
    if not 0 < float(timeout) <= 86400:
        raise ValueError("finite work timeout required")
    data = pickle.dumps(
        (
            target,
            args,
            kwargs or {},
            admission,
            memory_mb,
            float(timeout),
            max_output,
            work_key,
            work_limit,
        ),
        protocol=5,
    )
    with tempfile.TemporaryDirectory(prefix="cisstat-work-") as directory:
        input_path = os.path.join(directory, "input.bin")
        output_path = os.path.join(directory, "output.bin")
        progress_path = os.path.join(directory, "progress.json")
        with open(input_path, "wb") as stream:
            stream.write(data)
        if work_key is not None:
            from apps.api.billing.compute_meter import Meter

            Meter(work_key, work_limit, progress_path).save()
        proc = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "apps.api.workers.child",
                input_path,
                output_path,
                str(os.getpid()),
                progress_path,
            ],
            env=child_environment(),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=os.name == "posix",
        )
        started = time.monotonic()
        failure = None
        rss_peak = 0
        monitor_done = threading.Event()
        monitor_lock = threading.Lock()

        def supervise():
            # Physical limits must not wait for database/authority I/O in checkpoint.
            nonlocal failure, rss_peak
            while not monitor_done.is_set():
                with monitor_lock:
                    if monitor_done.is_set():
                        return
                    alive = proc.poll() is None
                    if sys.platform == "linux":
                        rss, descendants = _linux_group(proc.pid)
                        alive = alive or bool(descendants)
                        rss_peak = max(rss_peak, rss / 1048576)
                    if not alive:
                        return
                    if time.monotonic() - started >= timeout:
                        failure = "worker_timeout"
                    elif memory_mb and rss_peak > memory_mb:
                        failure = "worker_memory_limit"
                    if failure:
                        if os.name == "posix":
                            try:
                                os.killpg(proc.pid, signal.SIGKILL)
                            except ProcessLookupError:
                                pass
                        elif proc.poll() is None:
                            proc.kill()
                        return
                monitor_done.wait(
                    min(0.05, max(0.001, timeout - (time.monotonic() - started)))
                )

        monitor = threading.Thread(
            target=supervise, name="cisstat-work-limits", daemon=True
        )
        monitor.start()
        try:
            while proc.poll() is None:
                if failure:
                    break
                if checkpoint is not None:
                    try:
                        checkpoint()
                    except Exception:
                        failure = failure or "worker_authority_lost"
                        break
                try:
                    proc.wait(timeout=0.1)
                except subprocess.TimeoutExpired:
                    pass
            # End observation before reusing/releasing the subprocess identity.
            with monitor_lock:
                monitor_done.set()
            monitor.join()
            if failure and proc.poll() is None:
                if os.name == "posix":
                    try:
                        os.killpg(proc.pid, signal.SIGTERM)
                    except ProcessLookupError:
                        pass
                proc.terminate()
                try:
                    proc.wait(timeout=0.5)
                except subprocess.TimeoutExpired:
                    if os.name == "posix":
                        try:
                            os.killpg(proc.pid, signal.SIGKILL)
                        except ProcessLookupError:
                            pass
                    proc.kill()
                    try:
                        proc.wait(timeout=1)
                    except subprocess.TimeoutExpired:
                        pass
            group_stopped = True
            if sys.platform == "linux":
                _, alive = _linux_group(proc.pid)
                if alive:
                    # A joined Python parent is not proof that native descendants stopped.
                    try:
                        os.killpg(proc.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    until = time.monotonic() + 1
                    while alive and time.monotonic() < until:
                        time.sleep(0.02)
                        _, alive = _linux_group(proc.pid)
                    group_stopped = not alive
            usage = None
            if work_key is not None:
                import json

                try:
                    with open(progress_path, encoding="utf-8") as stream:
                        usage = json.load(stream)
                    if (
                        usage["key"] != work_key
                        or type(usage["units"]) is not int
                        or not 0 <= usage["units"] <= work_limit
                    ):
                        usage = None
                except (OSError, ValueError, KeyError, TypeError):
                    usage = None
            proof = StopProof(
                proc.poll() is not None and group_stopped,
                proc.pid,
                proc.returncode,
                failure or "completed",
                usage,
                {
                    "wall_ns": int((time.monotonic() - started) * 1e9),
                    "rss_peak_bytes": int(rss_peak * 1048576),
                },
            )
            if not proof.stopped:
                raise WorkStopped("worker_stop_unknown", proof)
            if failure:
                raise WorkStopped(failure, proof)
            if proc.returncode != 0:
                raise WorkStopped("worker_process_crash", proof)
            if not os.path.isfile(output_path):
                raise WorkStopped("worker_process_crash", proof)
            if os.path.getsize(output_path) > max_output:
                raise WorkStopped("worker_output_limit", proof)
            with open(output_path, "rb") as stream:
                kind, value, child_metrics = pickle.load(stream)
            from dataclasses import replace

            proof = replace(
                proof,
                metrics={
                    **proof.metrics,
                    **child_metrics,
                    "rss_peak_bytes": max(
                        proof.metrics.get("rss_peak_bytes") or 0,
                        child_metrics.get("rss_peak_bytes") or 0,
                    ),
                },
            )
            if kind == "http_error":
                from fastapi import HTTPException

                raise WorkFailed(HTTPException(**value), proof)
            if kind == "domain_error":
                raise WorkFailed(value, proof)
            if kind != "ok":
                raise WorkStopped(value, proof)
            return value, proof
        finally:
            with monitor_lock:
                monitor_done.set()
            monitor.join()
            if proc.poll() is None:
                proc.kill()
                try:
                    proc.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    pass
