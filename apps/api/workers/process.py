"""Pure bounded subprocess: sanitized environment, stop/join proof, no DB publication."""

import os
import pickle
import signal
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass


@dataclass(frozen=True)
class StopProof:
    stopped: bool
    pid: int | None
    exit_code: int | None
    outcome: str


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
):
    if not 0 < float(timeout) <= 86400:
        raise ValueError("finite work timeout required")
    data = pickle.dumps(
        (target, args, kwargs or {}, admission, memory_mb, float(timeout), max_output),
        protocol=5,
    )
    with tempfile.TemporaryDirectory(prefix="cisstat-work-") as directory:
        input_path = os.path.join(directory, "input.bin")
        output_path = os.path.join(directory, "output.bin")
        with open(input_path, "wb") as stream:
            stream.write(data)
        proc = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "apps.api.workers.child",
                input_path,
                output_path,
                str(os.getpid()),
            ],
            env=child_environment(),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=os.name == "posix",
        )
        started = time.monotonic()
        failure = None
        try:
            while proc.poll() is None:
                if time.monotonic() - started >= timeout:
                    failure = "worker_timeout"
                    break
                if checkpoint is not None:
                    try:
                        checkpoint()
                    except Exception:
                        failure = "worker_authority_lost"
                        break
                if memory_mb and sys.platform == "linux":
                    try:
                        with open(f"/proc/{proc.pid}/statm") as f:
                            rss = (
                                int(f.read().split()[1])
                                * os.sysconf("SC_PAGE_SIZE")
                                / 1048576
                            )
                        if rss > memory_mb:
                            failure = "worker_memory_limit"
                            break
                    except (OSError, ValueError, IndexError):
                        pass
                try:
                    proc.wait(timeout=0.1)
                except subprocess.TimeoutExpired:
                    pass
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
            proof = StopProof(
                proc.poll() is not None,
                proc.pid,
                proc.returncode,
                failure or "completed",
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
                kind, value = pickle.load(stream)
            if kind == "domain_error":
                raise WorkFailed(value, proof)
            if kind != "ok":
                raise WorkStopped(value, proof)
            return value, proof
        finally:
            if proc.poll() is None:
                proc.kill()
                try:
                    proc.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    pass
