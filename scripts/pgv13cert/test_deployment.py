"""Acceptance of the shipped PGV13 procedure against actual image/topology.
These checks do not claim to observe or fix the operator's VM.
"""
import json
from pathlib import Path
import re
import subprocess

import yaml

ROOT = Path(__file__).resolve().parents[2]


def sources():
    doc = (ROOT / "docs/pgv13_passport_documents.md").read_text(encoding="utf-8-sig")
    commands = doc.split("VM-команды", 1)[1].split("```bash", 1)[1].split("```", 1)[0]
    renderer = yaml.safe_load((ROOT / "apps/print-renderer/build/deployment/docker-compose.yml").read_text(encoding="utf-8-sig"))["services"]["print-renderer"]
    stack = yaml.safe_load((ROOT / "deployment/cisstat-stack/docker-compose.yml").read_text(encoding="utf-8-sig"))["services"]
    return commands, renderer, stack


def test_documented_build_tag_is_the_image_compose_starts():
    commands, renderer, _ = sources()
    built = re.search(r"docker build[^\n]*-t\s+(\S+)", commands).group(1)
    assert built == renderer["image"], "F-C13-04a: runbook builds pgv13 but compose starts pgv08-fix"


def test_new_proxy_paths_require_web_build_in_primary_procedure():
    commands, _, _ = sources()
    old = json.loads(subprocess.check_output(["git", "show", "fc510f0:packages/ui/server/proxy-routes.generated.json"], cwd=ROOT))
    new = json.loads((ROOT / "packages/ui/server/proxy-routes.generated.json").read_text(encoding="utf-8-sig"))
    added = {r["path"] for r in new} - {r["path"] for r in old}
    assert any(p.endswith("/passport-documents") for p in added)
    assert re.search(r"docker compose build[^\n]*\bweb\b", commands), "F-C13-04b: changed compiled BFF allowlist requires web rebuild"


def test_shipped_topology_declares_a_usable_api_renderer_transport():
    _, renderer, stack = sources()
    env = stack["api"].get("environment", {})
    # The actual client is HTTP-only. With no shared net/IPC endpoint declared,
    # api loopback cannot refer to another network-namespace's loopback.
    url = env.get("CISSTAT_PNG_RENDERER_URL", "http://127.0.0.1:8907")
    assert renderer.get("network_mode") != "none" or bool(renderer.get("ports")) or bool(env.get("CISSTAT_PNG_RENDERER_IPC")), (
        "F-C13-04c: renderer network none, no published endpoint/IPC, API target=" + str(url))


def test_isolation_is_not_disabled_to_get_a_green_smoke():
    _, renderer, _ = sources()
    assert renderer["user"] == "10001:10001"
    assert renderer["read_only"] is True
    assert renderer["cap_drop"] == ["ALL"]
    assert "no-new-privileges:true" in renderer["security_opt"]
    worker = (ROOT / "apps/print-renderer/src/renderWorker.ts").read_text(encoding="utf-8-sig")
    assert "chromiumSandbox: true" in worker
    assert "--no-sandbox" not in worker
