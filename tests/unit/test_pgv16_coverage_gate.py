# tests/unit/test_pgv16_coverage_gate.py
"""TDD-корпус COV-1 (spec_passport_graphics_visual.md §5/§13, строка
PGV-16, точка изменения «registry»): scripts/pgv16/coverage_gate.py --
fail-closed CERT-гейт покрытия реестра render-sites.

«Unknown/unmapped scientific site блокирует CERT и остаётся в
denominator coverage» (§5): Python-гейт -- структура/ссылки/паритет
print-схемы (jest-оракул visualExportRegistry.coverage.test.ts
остаётся AST-сканером исходников -- разделение труда честно
задокументировано в docs/pgv16_security_retention_ops_coverage.md §2
COV-1). Тампер-оракулы: любой ослабляющий мутант гейта убивается."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.pgv16 import coverage_gate as gate

REPO_ROOT = Path(__file__).resolve().parents[2]


def _write_registry(payload: dict, tmp: Path) -> Path:
    path = tmp / "visual_registry.json"
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return path


class CoverageGatePristineTests(unittest.TestCase):
    def test_pristine_repository_passes(self):
        """Честный репозиторий: гейт зелёный (не «всегда красный» --
        гейт обслуживает CERT, а не создаёт постоянный шум)."""
        violations = gate.run_gate()
        self.assertEqual(violations, [], "\n".join(map(str, violations)))


class CoverageGateTamperTests(unittest.TestCase):
    """Мутанты гейта убиваются: каждый tamper-кейс -- violations."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.tmp_path = Path(self.tmp.name)
        pristine = json.loads(
            (REPO_ROOT / "config" / "visual_registry.json").read_text(
                encoding="utf-8"
            )
        )
        self.pristine = pristine

    def check(self, payload: dict) -> list[str]:
        path = _write_registry(payload, self.tmp_path)
        return gate.run_gate(registry_path=path)

    def test_registry_version_mismatch_rejected(self):
        payload = dict(self.pristine)
        payload["registry_version"] = "pgv16-deadbeefdead"
        violations = self.check(payload)
        self.assertTrue(
            any("registry_version" in v for v in violations), violations
        )

    def test_missing_registry_version_rejected(self):
        payload = {k: v for k, v in self.pristine.items() if k != "registry_version"}
        violations = self.check(payload)
        self.assertTrue(
            any("registry_version" in v for v in violations), violations
        )

    def test_duplicate_view_id_rejected(self):
        payload = json.loads(json.dumps(self.pristine))
        payload["sites"].append(dict(payload["sites"][0]))
        payload["total_sites"] = len(payload["sites"])
        violations = self.check(payload)
        self.assertTrue(any("view_id" in v for v in violations), violations)

    def test_unknown_reason_class_rejected(self):
        payload = json.loads(json.dumps(self.pristine))
        payload["exclusions"][0]["reason_class"] = "just_because"
        violations = self.check(payload)
        self.assertTrue(
            any("reason_class" in v for v in violations), violations
        )

    def test_missing_site_file_rejected(self):
        payload = json.loads(json.dumps(self.pristine))
        payload["sites"][0]["render_site"] = (
            "packages/ui/components/NotAFile.tsx#series"
        )
        violations = self.check(payload)
        self.assertTrue(
            any("render_site" in v for v in violations), violations
        )

    def test_missing_exclusion_target_rejected(self):
        payload = json.loads(json.dumps(self.pristine))
        payload["exclusions"][0]["targets"] = [
            "packages/ui/components/NotAFile.tsx"
        ]
        violations = self.check(payload)
        self.assertTrue(any("target" in v for v in violations), violations)

    def test_empty_module_rejected(self):
        payload = json.loads(json.dumps(self.pristine))
        payload["modules"] = {k: (0 if k == "tasks" else v)
                              for k, v in payload["modules"].items()}
        violations = self.check(payload)
        self.assertTrue(any("модуль" in v or "module" in v for v in violations),
                        violations)

    def test_total_sites_mismatch_rejected(self):
        payload = json.loads(json.dumps(self.pristine))
        payload["total_sites"] = payload["total_sites"] + 1
        violations = self.check(payload)
        self.assertTrue(
            any("total_sites" in v for v in violations), violations
        )

    def test_unknown_export_status_rejected(self):
        payload = json.loads(json.dumps(self.pristine))
        payload["sites"][0]["export_status"] = "shipped_somewhere"
        violations = self.check(payload)
        self.assertTrue(
            any("export_status" in v for v in violations), violations
        )

    def test_print_schema_missing_basis_kind_rejected(self):
        """Паритет print-схемы: каталог basis-kinds без P02 -- гейт
        красный (V01/P01/P02 -- печатные семейства PGV-15)."""
        schema = json.loads(
            (REPO_ROOT / "config" / "print_schema.json").read_text(
                encoding="utf-8"
            )
        )
        # Честный тампер -- в tmp-файл со структурой схем; если каталог
        # basis-kinds живёт в коде (PRINT_RENDER_BASIS_KINDS), гейт
        # проверяет код-источник и тампер-файл не влияет.
        schema_path = self.tmp_path / "print_schema.json"
        schema_path.write_text(
            json.dumps(schema, ensure_ascii=False), encoding="utf-8"
        )
        violations = gate.run_gate()
        self.assertEqual(violations, [], "\n".join(map(str, violations)))
        # Инвариант каталога -- прямой оракул код-источника.
        from apps.api.document_jobs import PRINT_RENDER_BASIS_KINDS
        from apps.api.report_snapshot import PRINT_DOCUMENT_KIND_CODES

        self.assertTrue(
            {"visual_print_snapshot", "passport_print_snapshot",
             "passport_comparison_snapshot"} <= set(PRINT_RENDER_BASIS_KINDS)
        )
        self.assertTrue({"V01", "P01", "P02"} <= set(PRINT_DOCUMENT_KIND_CODES))

    def test_print_limits_parity_honest(self):
        """Лимиты §7 гейта совпадают со штатным print_limits()."""
        from apps.api.print_schema import print_limits

        self.assertEqual(gate.EXPECTED_PRINT_LIMITS, print_limits())


class CoverageGateEntryTests(unittest.TestCase):
    def test_main_exits_nonzero_on_violations(self):
        with tempfile.TemporaryDirectory() as tmp:
            payload = json.loads(
                (REPO_ROOT / "config" / "visual_registry.json").read_text(
                    encoding="utf-8"
                )
            )
            payload["total_sites"] = payload["total_sites"] + 5
            path = _write_registry(payload, Path(tmp))
            with self.assertRaises(SystemExit) as ctx:
                gate.main([str(path)])
            self.assertNotEqual(ctx.exception.code, 0)

    def test_main_exits_zero_on_pristine(self):
        with self.assertRaises(SystemExit) as ctx:
            gate.main([])
        self.assertEqual(ctx.exception.code, 0)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
