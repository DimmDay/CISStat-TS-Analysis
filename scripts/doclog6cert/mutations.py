#!/usr/bin/env python3
"""DOCLOG-6-CERT: мутационная кампания («мутанты на своих мутантах»).

Двухканальная схема:
  REPO    -- tests/api/test_doclog{2,3,4,5,6}_*.py (каталоги-пины +
             смежные поверхности согласования/выдачи, 326 тестов);
  ORACLE  -- scripts/doclog6cert (собственный корпус сертификатора, 79).

Классификация: DUAL-KILLED / REPO-ONLY / ORACLE-ONLY / SURVIVED.
Контрольные (no-op) мутанты обязаны остаться ALIVE в обоих каналах.

Мета-валидация:
  MV1 patch-applies: каждый мутант применяется ровно один раз по
      уникальному якорю (счётчик обязан быть = 1);
  MV2 classifier self-test: сверка с синтетикой;
  MV3 RESTORE: после каждого мутанта файл восстановлен байт-в-байт
      (md5-сверка; счётчик RESTORE-FAIL обязан быть 0);
  MV4 controls: 3 no-op контроля ALIVE (каналы не «косят» всё).

Resume: существующие protocols/mut_<name>.json не пересчитываются.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path

REPO = Path("/home/z/my-project/CISStat-TS-Analysis")
CERT_DIR = REPO / "scripts" / "doclog6cert"
PROTOCOLS = CERT_DIR / "protocols"

LIFECYCLE = REPO / "apps" / "api" / "document_lifecycle.py"
ROUTER = REPO / "apps" / "api" / "routers" / "documentation.py"
JOBS = REPO / "apps" / "api" / "document_jobs.py"
SECURITY = REPO / "apps" / "api" / "security_audit.py"

REPO_CMD = [
    sys.executable, "-m", "pytest",
    "tests/api/test_doclog6_approvals_archive.py",
    "tests/api/test_doclog4_document_delivery.py",
    "tests/api/test_doclog5_formats_worker.py",
    "tests/api/test_doclog2_snapshots.py",
    "tests/api/test_doclog3_telemetry_audit.py",
    "-q", "--tb=no", "-p", "no:cacheprovider",
]
ORACLE_CMD = [
    sys.executable, "-m", "pytest",
    "scripts/doclog6cert/test_d6cert_oracle_unit.py",
    "scripts/doclog6cert/test_d6cert_oracle_api.py",
    "scripts/doclog6cert/test_d6cert_oracle_static.py",
    "-q", "--tb=no", "-p", "no:cacheprovider",
]

# ── Мутанты: (имя, файл, старое, новое, класс) ────────────────────────

BATTLE: list[tuple[str, Path, str, str]] = [
    # 1. Вычислимое состояние (§11)
    ("M01_state_approved_branch_off", LIFECYCLE,
     '''            elif record.event == EVENT_APPROVED:
                state = STATE_APPROVED''',
     '''            elif False:
                state = STATE_APPROVED'''),
    ("M02_state_published_branch_off", LIFECYCLE,
     '''            elif record.event == EVENT_PUBLISHED:
                state = STATE_PUBLISHED''',
     '''            elif False:
                state = STATE_PUBLISHED'''),
    ("M03_request_gate_inverted", LIFECYCLE,
     '''        state = self.revision_state(revision_id)
        if state != STATE_DRAFT:
            raise InvalidTransitionError(
                f"Запрос согласования возможен только из draft''',
     '''        state = self.revision_state(revision_id)
        if state == STATE_DRAFT:
            raise InvalidTransitionError(
                f"Запрос согласования возможен только из draft'''),
    ("M04_decision_validation_off", LIFECYCLE,
     '''        if decision not in ("approve", "reject"):
            raise InvalidTransitionError(
                "decision обязан быть approve | reject"
            )''',
     '''        if False:
            raise InvalidTransitionError(
                "decision обязан быть approve | reject"
            )'''),
    ("M05_expected_hash_inverted", LIFECYCLE,
     '''        if expected_snapshot_sha256 is not None and (
            expected_snapshot_sha256 != current_hash
        ):''',
     '''        if expected_snapshot_sha256 is not None and (
            expected_snapshot_sha256 == current_hash
        ):'''),
    ("M06_manifest_includes_not_ready", LIFECYCLE,
     '''            for rendition in self.delivery.registry.list_renditions(
                revision.snapshot_id
            )
            if rendition.state == "ready"
        ]''',
     '''            for rendition in self.delivery.registry.list_renditions(
                revision.snapshot_id
            )
            if True
        ]'''),
    # 2. Publish bound-hash (AC07)
    ("M07_publish_snapshot_hash_check_off", LIFECYCLE,
     '''        if current_hash != approval.snapshot_payload_sha256:
            raise ApprovalNotApplicableError(''',
     '''        if False:
            raise ApprovalNotApplicableError('''),
    ("M08_publish_rendition_check_off", LIFECYCLE,
     '''            if (
                rendition is None
                or str(rendition.content_sha256)
                != str(bound.get("content_sha256"))
            ):''',
     '''            if False:'''),
    # 3. Publish policy (§11)
    ("M09_d11_gate_inverted", LIFECYCLE,
     '''        if kind_code == "D11" and completeness_status != "complete":''',
     '''        if kind_code == "D11" and completeness_status == "complete":'''),
    ("M10_d11_kind_never_blocks", LIFECYCLE,
     '''        if kind_code == "D11" and completeness_status != "complete":''',
     '''        if False and completeness_status != "complete":'''),
    ("M11_empty_sections_check_off", LIFECYCLE,
     '''        sections = getattr(snapshot, "sections", []) or []
        if not sections:''',
     '''        sections = getattr(snapshot, "sections", []) or []
        if False:'''),
    ("M12_superseded_record_off", LIFECYCLE,
     '''        if supersedes is not None:
            self.registry.append_lifecycle(''',
     '''        if False:
            self.registry.append_lifecycle('''),
    # 4. Retract (§11)
    ("M13_retract_state_gate_off", LIFECYCLE,
     '''        state = self.revision_state(revision_id)
        if state != STATE_PUBLISHED:
            raise InvalidTransitionError(
                f"Отзыв возможен только из published''',
     '''        state = self.revision_state(revision_id)
        if False:
            raise InvalidTransitionError(
                f"Отзыв возможен только из published'''),
    ("M14_retract_event_wrong", LIFECYCLE,
     '''                run_id=revision.run_id,
                event=EVENT_RETRACTED,''',
     '''                run_id=revision.run_id,
                event=EVENT_SUPERSEDED,'''),
    # 5. Mandatory audit (§14.1/AC11)
    ("M15_mandatory_audit_downgraded", LIFECYCLE,
     '''        record_mandatory(
            action,
            decision,''',
     '''        record_standard(
            action,
            decision,'''),
    # 6. Pin и purge (§16)
    ("M16_pin_reason_generic", LIFECYCLE,
     '''                reason=(
                    f"document:{document.document_id}:published:"
                    f"{revision.version_no}"
                ),''',
     '''                reason="document:published",'''),
    ("M17_purge_state_kept_ready", LIFECYCLE,
     '''        updated = replace_record(rendition, state=RENDITION_PURGED, content_bytes=None)''',
     '''        updated = replace_record(rendition, state="ready", content_bytes=None)'''),
    ("M18_purge_no_unlink", LIFECYCLE,
     '''                path.unlink(missing_ok=True)''',
     '''                pass  # unlink выключен мутантом'''),
    # 7. Retention sweep (§16.1)
    ("M19_hold_ignored", LIFECYCLE,
     '''            if retention is not None and retention.hold:''',
     '''            if False:'''),
    ("M20_protected_states_ignored", LIFECYCLE,
     '''            if states & _PROTECTED_STATES:''',
     '''            if False:'''),
    ("M21_cutoff_inverted", LIFECYCLE,
     '''                    if created is None or created > cutoff:''',
     '''                    if created is None or created < cutoff:'''),
    ("M22_report_counter_off", LIFECYCLE,
     '''                    self._purge_rendition(registry, rendition)
                    report["purged_renditions"] += 1''',
     '''                    self._purge_rendition(registry, rendition)'''),
    # 8. Restore drill (AC18)
    ("M23_verify_ok_always", LIFECYCLE,
     '''        ok = not missing and not mismatched and not ref_errors''',
     '''        ok = True'''),
    ("M24_verify_digest_check_off", LIFECYCLE,
     '''                if digest != str(member.get("sha256")):
                    mismatched.append(path)''',
     '''                if False:
                    mismatched.append(path)'''),
    ("M25_approval_hash_ref_error_off", LIFECYCLE,
     '''                if bound and actual and bound != actual:''',
     '''                if False:'''),
    ("M26_member_sha256_of_empty", LIFECYCLE,
     '''def _member(bundle_dir: Path, relative: str) -> dict[str, Any]:
    data = (bundle_dir / relative).read_bytes()''',
     '''def _member(bundle_dir: Path, relative: str) -> dict[str, Any]:
    return {"path": relative, "sha256": "0" * 64, "size_bytes": 0}
    data = (bundle_dir / relative).read_bytes()'''),
    ("M27_manifest_self_hash", LIFECYCLE,
     '''        manifest_payload = {
            "bundle_id": bundle_id,''',
     '''        members.append({"path": "manifest.json", "sha256": "0" * 64, "bytes": 0})
        manifest_payload = {
            "bundle_id": bundle_id,'''),
    # 9. Diff (§17)
    ("M28_diff_cross_doc_off", LIFECYCLE,
     '''        if document.document_id != document_b.document_id:''',
     '''        if False:'''),
    ("M29_recalculated_true", LIFECYCLE,
     '''            "recalculated": False,''',
     '''            "recalculated": True,'''),
    ("M30_validity_changed_off", LIFECYCLE,
     '''            if text in b_claims and claim["validity"] != b_claims[text]["validity"]''',
     '''            if False'''),
    # 10. Права и policy (§15/D5/D6)
    ("M31_admin_catalog_basis_lost", LIFECYCLE,
     '''    if role == "admin":
        return LifecycleRights(True, True, True, True, "admin_full_catalog")''',
     '''    if False:
        return LifecycleRights(True, True, True, True, "admin_full_catalog")'''),
    ("M32_scoped_surrogate_pilot_leak", LIFECYCLE,
     '''    if via == "session_surrogate" and _identity_mode() in _PILOT_MODES:''',
     '''    if via == "session_surrogate":'''),
    ("M33_policy_unknown_to_two_person", LIFECYCLE,
     '''            APPROVAL_POLICY_ENV, raw, POLICY_SINGLE,
        )
        return POLICY_SINGLE''',
     '''            APPROVAL_POLICY_ENV, raw, POLICY_SINGLE,
        )
        return POLICY_TWO_PERSON'''),
    # 11. HTTP-слой (роутер/document_jobs)
    ("M34_lifecycle_state_always_draft", ROUTER,
     '''    try:
        payload["lifecycle_state"] = _lifecycle_service().revision_state(
            revision.revision_id
        )
    except Exception:''',
     '''    try:
        payload["lifecycle_state"] = "draft"
    except Exception:'''),
    ("M35_purged_410_to_500", ROUTER,
     '''        return HTTPException(
            status_code=410,
            detail={
                "code": "purged_artifact",''',
     '''        return HTTPException(
            status_code=500,
            detail={
                "code": "purged_artifact",'''),
    ("M36_scope_403_to_404", ROUTER,
     '''    if isinstance(exc, InsufficientScopeError):
        # §15/D5: субъект владеет ресурсом, права на действие нет.
        return HTTPException(
            status_code=403,''',
     '''    if isinstance(exc, InsufficientScopeError):
        # §15/D5: субъект владеет ресурсом, права на действие нет.
        return HTTPException(
            status_code=404,'''),
    ("M37_purged_reader_error_off", JOBS,
     '''        if rendition.state == RENDITION_PURGED:
            raise RenditionPurgedError(''',
     '''        if False:
            raise RenditionPurgedError('''),
    ("M38_archive_action_unregistered", SECURITY,
     '''    ACTION_ARCHIVE_BUNDLE_CREATED,
})''',
     '''})'''),
]

CONTROLS: list[tuple[str, Path, str, str]] = [
    ("C1_docstring_only", LIFECYCLE,
     "согласование и архив -- ось СОДЕРЖАНИЯ жизненного цикла документов.",
     "согласование и архив -- ось СОДЕРЖАНИЯ жизненного цикла документов. [контроль C1]"),
    ("C2_comment_only", ROUTER,
     "# ── DOCLOG-6: согласование и архив (§11, §16, §17) ───────────────────",
     "# ── DOCLOG-6: согласование и архив (§11, §16, §17) [контроль C2] ─────"),
    ("C3_docstring_only", LIFECYCLE,
     '"""§16.1: purge невостребованных draft renditions; hold\n        приоритетен; published/approved/retracted/superseded не\n        очищаются; научный слой и pinned-зависимости не трогаются."""',
     '"""§16.1: purge невостребованных draft renditions; hold\n        приоритетен; published/approved/retracted/superseded не\n        очищаются; научный слой и pinned-зависимости не трогаются.\n\n        [контроль C3 -- no-op]."""'),
]


def classify(repo_ok: bool, oracle_ok: bool) -> str:
    """MV2-классификатор (сверен с синтетикой в self_test)."""
    if repo_ok and oracle_ok:
        return "SURVIVED"
    if not repo_ok and not oracle_ok:
        return "DUAL-KILLED"
    if not repo_ok and oracle_ok:
        return "REPO-ONLY"
    return "ORACLE-ONLY"


def self_test_classifier() -> bool:
    return (
        classify(True, True) == "SURVIVED"
        and classify(False, False) == "DUAL-KILLED"
        and classify(False, True) == "REPO-ONLY"
        and classify(True, False) == "ORACLE-ONLY"
    )


def md5_of(path: Path) -> str:
    return hashlib.md5(path.read_bytes()).hexdigest()


def run_channel(cmd: list[str], cwd: Path, timeout: int = 420) -> tuple[bool, str]:
    result = subprocess.run(
        cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout
    )
    tail = "\n".join(result.stdout.strip().splitlines()[-6:])
    return result.returncode == 0, tail


def apply_mutant(path: Path, old: str, new: str) -> bool:
    """MV1: якорь обязан встречаться ровно один раз."""
    content = path.read_text(encoding="utf-8")
    if content.count(old) != 1:
        return False
    path.write_text(content.replace(old, new, 1), encoding="utf-8")
    return True


def restore(path: Path, md5_original: str, original: str) -> bool:
    path.write_text(original, encoding="utf-8")
    return md5_of(path) == md5_original


def run_one(name: str, path: Path, old: str, new: str, kind: str) -> dict:
    protocol_file = PROTOCOLS / f"mut_{name}.json"
    if protocol_file.exists():
        return json.loads(protocol_file.read_text(encoding="utf-8"))
    original = path.read_text(encoding="utf-8")
    md5_before = md5_of(path)
    entry: dict = {
        "name": name, "kind": kind, "file": path.name,
        "patch_applies": apply_mutant(path, old, new),  # MV1
    }
    if entry["patch_applies"]:
        time.sleep(0.2)
        repo_ok, repo_tail = run_channel(REPO_CMD, REPO)
        oracle_ok, oracle_tail = run_channel(ORACLE_CMD, REPO)
        entry.update({
            "repo_pass": repo_ok,
            "oracle_pass": oracle_ok,
            "classification": classify(repo_ok, oracle_ok),
            "repo_tail": repo_tail,
            "oracle_tail": oracle_tail,
            "restored": restore(path, md5_before, original),  # MV3 md5
        })
        if not entry["restored"]:
            entry["classification"] = "RESTORE-FAIL"
    else:
        entry.update({
            "repo_pass": None, "oracle_pass": None,
            "classification": "PATCH-FAIL", "restored": True,
        })
    protocol_file.write_text(
        json.dumps(entry, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    return entry


def main() -> int:
    PROTOCOLS.mkdir(parents=True, exist_ok=True)
    start = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    end = int(sys.argv[2]) if len(sys.argv) > 2 else 10**9
    universe = [
        (name, path, old, new, "battle")
        for name, path, old, new in BATTLE
    ] + [
        (name, path, old, new, "control")
        for name, path, old, new in CONTROLS
    ]
    if not self_test_classifier():
        print("MV2 classifier self-test FAILED")
        return 2
    print("MV2 classifier self-test OK")
    restore_failures = 0
    patch_failures = 0
    for index, (name, path, old, new, kind) in enumerate(universe):
        if not (start <= index < end):
            continue
        entry = run_one(name, path, old, new, kind)
        if entry["classification"] == "RESTORE-FAIL":
            restore_failures += 1
        if entry["classification"] == "PATCH-FAIL":
            patch_failures += 1
        print(
            f"[{index:02d}] {name:38s} {entry['classification']}",
            flush=True,
        )
    print(f"restore_failures={restore_failures} patch_failures={patch_failures}")
    # сводка
    entries = []
    for name, path, old, new, kind in universe:
        f = PROTOCOLS / f"mut_{name}.json"
        if f.exists():
            entries.append(json.loads(f.read_text(encoding="utf-8")))
    summary = {
        "total": len(entries),
        "battle": sum(e.get("kind") == "battle" for e in entries),
        "controls": sum(e.get("kind") == "control" for e in entries),
        "DUAL-KILLED": sum(e["classification"] == "DUAL-KILLED" for e in entries),
        "REPO-ONLY": sum(e["classification"] == "REPO-ONLY" for e in entries),
        "ORACLE-ONLY": sum(e["classification"] == "ORACLE-ONLY" for e in entries),
        "SURVIVED": sum(e["classification"] == "SURVIVED" for e in entries),
        "PATCH-FAIL": sum(e["classification"] == "PATCH-FAIL" for e in entries),
        "RESTORE-FAIL": sum(e["classification"] == "RESTORE-FAIL" for e in entries),
        "controls_alive": sum(
            e["classification"] == "SURVIVED"
            for e in entries if e.get("kind") == "control"
        ),
    }
    (PROTOCOLS / "mutations_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
