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
    uds = yaml.safe_load((ROOT / "apps/print-renderer/build/deployment/docker-compose.uds.yml").read_text())["services"]["print-renderer"]
    api_uds = yaml.safe_load((ROOT / "deployment/cisstat-stack/docker-compose.renderer-uds.yml").read_text())["services"]["api"]
    renderer = {**renderer, **uds, "security_opt": renderer["security_opt"] + uds["security_opt"]}
    stack["api"] = {**stack["api"], **api_uds, "environment": {**stack["api"]["environment"], **api_uds["environment"]}}
    return commands.replace("\\\n", " "), renderer, stack


def test_documented_build_tag_is_the_image_compose_starts():
    commands, renderer, _ = sources()
    built = re.search(r"docker build[^\n]*-t\s+(\S+)", commands).group(1)
    assert renderer["image"] == "${CISSTAT_UDS_RENDERER_IMAGE:?Pin the new UDS image ID}"
    assert "docker image inspect --format '{{.Id}}' " + built in commands
    assert renderer["pull_policy"] == "never"
    assert "docker-compose.uds.yml" in (ROOT / "docs/pgv13_passport_documents.md").read_text()


def test_new_proxy_paths_require_web_build_in_primary_procedure():
    commands, _, _ = sources()
    old = json.loads(subprocess.check_output(["git", "show", "fc510f0:packages/ui/server/proxy-routes.generated.json"], cwd=ROOT))
    new = json.loads((ROOT / "packages/ui/server/proxy-routes.generated.json").read_text(encoding="utf-8-sig"))
    added = {r["path"] for r in new} - {r["path"] for r in old}
    assert any(p.endswith("/passport-documents") for p in added)
    assert re.search(r"docker compose[^\n]* build[^\n]*\bweb\b", commands), "F-C13-04b: changed compiled BFF allowlist requires web rebuild"


def test_shipped_topology_declares_a_usable_api_renderer_transport():
    _, renderer, stack = sources()
    env = stack["api"].get("environment", {})
    assert env["CISSTAT_PNG_RENDERER_IPC"] == renderer["environment"]["CISSTAT_PRINT_RENDERER_SOCKET"]
    assert renderer["network_mode"] == "none" and not renderer.get("ports")
    api_mount=stack["api"]["volumes"][0];render_mount=renderer["volumes"][0]
    assert api_mount["target"]==render_mount["target"]=="/run/cisstat-renderer"
    assert api_mount["source"]==render_mount["source"]=="renderer_ipc"
    assert api_mount["read_only"] is True and api_mount["volume"]["nocopy"] is True
    assert not render_mount.get("read_only",False)
    assert stack["api"]["group_add"]==["10001"]
    for file in ("apps/print-renderer/build/deployment/docker-compose.uds.yml","deployment/cisstat-stack/docker-compose.renderer-uds.yml"):
        volume=yaml.safe_load((ROOT/file).read_text())["volumes"]["renderer_ipc"]
        assert volume=={"external":True,"name":"${CISSTAT_RENDERER_IPC_VOLUME:-cisstat_renderer_ipc_v1}"}



def test_isolation_is_not_disabled_to_get_a_green_smoke():
    _, renderer, _ = sources()
    assert renderer["user"] == "10001:10001"
    assert renderer["read_only"] is True
    assert renderer["cap_drop"] == ["ALL"]
    assert "no-new-privileges:true" in renderer["security_opt"]
    worker = (ROOT / "apps/print-renderer/src/renderWorker.ts").read_text(encoding="utf-8-sig")
    assert "chromiumSandbox: true" in worker
    assert "--no-sandbox" not in worker
