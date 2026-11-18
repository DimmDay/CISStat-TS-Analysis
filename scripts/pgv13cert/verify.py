"""Explicit PGV13 certification gate. Red/skip/no tests never means certified."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]


def main():
    if "--postgres" in sys.argv and not os.environ.get("CISSTAT_PGV13_CERT_DSN"):
        print("Set CISSTAT_PGV13_CERT_DSN to disposable PostgreSQL with CREATE DATABASE; no tests ran.")
        return 2
    build = subprocess.run(["npm", "run", "build", "--workspace=@cisstat/print-renderer"], cwd=ROOT, shell=os.name == "nt")
    if build.returncode:
        return build.returncode
    with tempfile.TemporaryDirectory(prefix="pgv13-cert-", dir=ROOT.parent) as temp:
        report = Path(temp) / "junit.xml"
        result = subprocess.run([sys.executable, "-m", "pytest", "scripts/pgv13cert", "-q", "--basetemp=" + str(Path(temp) / "pytest"), "--junitxml=" + str(report)], cwd=ROOT)
        if report.exists():
            cases = list(ET.parse(report).iter("testcase"))
            if not cases or any(case.find("skipped") is not None for case in cases):
                print("NOT CERTIFIED: skips/no tests")
                return 1
    print("NOT CERTIFIED" if result.returncode else "Contract probes passed; final-image/sandbox/VM acceptance remains required.")
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
