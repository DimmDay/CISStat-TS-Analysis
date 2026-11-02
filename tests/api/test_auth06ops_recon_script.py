"""AUTH-06-OPS-RECON: static guards for the Windows recon deliverable.

The task delivers a read-only PowerShell recon script
(scripts/auth06ops/recon_windows.ps1) and the migration plan
(docs/auth06/own-server-recon-plan.md). The development sandbox has no
Windows, so the executable proof lives in the operator's run on the real
machine. What CAN be enforced automatically here is the class of defects
that silently break Windows PowerShell 5.1:

1. encoding: PS 5.1 reads BOM-less files as ANSI, so any non-ASCII byte
   (Cyrillic, typographic dashes) turns comments/messages into mojibake;
   the script therefore must be pure ASCII;
2. PS7-only syntax (ternary '?:', coalesce '??', pipeline chains '&&'/'||',
   'ForEach-Object -Parallel', 'Join-String', 'utf8NoBOM') parses in pwsh 7
   but fails on the shipping Windows PowerShell 5.1;
3. structural integrity (balanced braces) and the presence of the
   documented report artefacts and three-level verdict vocabulary;
4. the plan document must carry the contract keys the rollout depends on
   (API_URL, CISSTAT_AUTH_*, migration/bootstrap entry points, CGNAT).

The optional live parse gate runs only when CISSTAT_PWSH points to a
pwsh executable; it is skipped in every other environment.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
PS1 = REPO / "scripts" / "auth06ops" / "recon_windows.ps1"
PLAN = REPO / "docs" / "auth06" / "own-server-recon-plan.md"

PS7_ONLY_TOKENS = (
    "??",                       # null-coalescing operator (PS7)
    " && ",                     # pipeline chain operator (PS7)
    " || ",                     # pipeline chain operator (PS7)
    "ForEach-Object -Parallel", # PS7-only switch
    "Join-String",              # PS7-only cmdlet
    "utf8NoBOM",                # PS7-only encoding value
    "-AsHashtable",             # PS7-only ConvertFrom-Json/ConvertTo-Json switch
)


def _read_ps1() -> bytes:
    assert PS1.exists(), f"missing deliverable: {PS1}"
    return PS1.read_bytes()


def test_recon_script_is_pure_ascii_for_powershell_51() -> None:
    """PS 5.1 treats BOM-less files as ANSI; only ASCII bytes are safe."""

    raw = _read_ps1()
    assert not raw.startswith(b"\xef\xbb\xbf"), (
        "BOM is acceptable but the contract here is stricter: pure ASCII "
        "so the file survives any editor/tooling round-trip"
    )
    try:
        raw.decode("ascii")
    except UnicodeDecodeError as exc:  # pragma: no cover - message detail
        offending = next(
            (i for i, b in enumerate(raw) if b > 0x7F), -1
        )
        raise AssertionError(
            f"non-ASCII byte 0x{offending:02x} at offset {offending}: {exc}"
        ) from exc


def test_recon_script_has_no_powershell_7_only_syntax() -> None:
    text = _read_ps1().decode("ascii")
    lowered = text.lower()
    for token in PS7_ONLY_TOKENS:
        assert token.lower() not in lowered, (
            f"PS7-only construct found: {token!r} breaks Windows PowerShell 5.1"
        )


def test_recon_script_balanced_braces() -> None:
    """Brace bookkeeping: the script must not use literal braces in strings

    (enforced by review), so a plain count balance is a faithful guard
    against truncated edits. Parentheses appear in prose strings and are
    intentionally not counted.
    """

    text = _read_ps1().decode("ascii")
    assert text.count("{") == text.count("}"), (
        f"unbalanced braces: {text.count('{')} opening vs {text.count('}')} closing"
    )


def test_recon_script_contract_surface() -> None:
    text = _read_ps1().decode("ascii")
    # parameter surface documented in the plan
    assert "[CmdletBinding()]" in text
    assert "$Domain" in text and "$OutDir" in text
    # report artefacts the team lead sends back
    assert "cisstat_recon_" in text
    assert ".json" in text and ".txt" in text
    # three-level verdict vocabulary (TASK-144 house style)
    for verdict in ("PASS", "ATTENTION", "FAIL"):
        assert verdict in text, f"verdict level missing: {verdict}"
    # hardware/network probes grounded in the deployment requirements
    for probe in (
        "Win32_Processor",
        "Win32_OperatingSystem",
        "Win32_LogicalDisk",
        "Get-NetTCPConnection",
        "Resolve-DnsName",
        "WSL_UTF8",
        "docker",
        "wsl.exe",
    ):
        assert probe in text, f"expected probe missing: {probe}"
    # NAT/CGNAT classification must exist (deployment blocker class)
    assert "100.64" in text, "CGNAT range check (100.64.0.0/10) missing"
    # read-only promise: no mutating cmdlets
    for banned in ("Set-ItemProperty", "New-NetFirewallRule", "Remove-Item", "Stop-Service",
                   "Start-Service", "Restart-Computer", "Set-ExecutionPolicy", "New-Item"):
        assert banned not in text, f"mutating cmdlet found in read-only script: {banned}"


def test_plan_document_carries_rollout_contract() -> None:
    assert PLAN.exists(), f"missing deliverable: {PLAN}"
    text = PLAN.read_text(encoding="utf-8")
    required = (
        "API_URL",                      # Vercel server-only switch
        "ALLOWED_ORIGINS",              # API-side exact origins
        "CISSTAT_AUTH_CSRF_KEY",        # >=32 bytes, no default
        "CISSTAT_AUTH_MFA_KEYS",        # MFA keyring
        "CISSTAT_STORAGE_MODE",         # fail-closed durable mode
        "CISSTAT_AUTH_DATABASE_URL",    # auth store DSN (or DATABASE_URL)
        "scripts/auth05/migrate.py",
        "scripts/auth05/bootstrap.py",
        "docs/auth06/first-admin.md",
        "docker compose",
        "Ubuntu",                       # recommended production OS
        "100.64",                       # CGNAT trap
        "22/80/443",                    # firewall surface
        "SSH",                          # operator tunnel
        "render.com",                   # what we retire after cutover
        "ts-standalone.vercel.app",
        "PostgreSQL 16",
        "0021",                         # AUTH-05 additive migration
        "/health/ops",
    )
    for token in required:
        assert token in text, f"plan document misses contract token: {token}"


def test_optional_live_pwsh_parse_gate() -> None:
    """Full syntax gate via the real PowerShell parser when available."""

    pwsh = os.environ.get("CISSTAT_PWSH") or shutil.which("pwsh")
    if not pwsh or not Path(pwsh).exists():
        raise AssertionError(
            "pwsh not configured (CISSTAT_PWSH/PATH): the environment that "
            "produced the deliverable must run the parser gate"
        )
    script = (
        "$t=$null;$e=$null;"
        f"[System.Management.Automation.Language.Parser]::ParseFile("
        f"'{PS1.as_posix()}',[ref]$t,[ref]$e)|Out-Null;"
        "if($e -and $e.Count -gt 0){$e|ForEach-Object{$_.Message};exit 1}"
        "'PARSE_OK'"
    )
    proc = subprocess.run(
        [pwsh, "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 0 and "PARSE_OK" in proc.stdout, (
        f"PowerShell parser rejected the script: {proc.stdout.strip()!r} "
        f"/ {proc.stderr.strip()!r}"
    )
