#!/usr/bin/env python3
"""PGV-10-CERT: мутационная кампания сертификатора (свои мутанты).

Мишени -- файлы поставки PGV-10. Каждый мутант -- минимальная правка
конкретной строки; исходы предрегистрируются (expected_killer -- класс
моих оракулов, который ОБЯЗАН убить мутанта). Восстановление -- побайтовое
из сохранённой копии с cmp-контролем (урок PROGR-19).

Запуск: python scripts/p10cert/mutations.py [--only M1,M2]
Протоколы: scripts/p10cert/protocols/mutation_campaign.{json,txt}
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

REPO = Path("/home/z/my-project/CISStat-TS-Analysis")
PROT = REPO / "scripts" / "p10cert" / "protocols"
BACKUP = Path("/tmp/p10cert_backup")

# ── Мутанты (свои; строковые правки -- точка и семантика) ────────────

MUTANTS = [
    {
        "id": "M1",
        "title": "Объектный гейт экспорта снят (чужой run получает экспорт)",
        "file": "apps/api/visual_exports.py",
        "find": '    except (PromotionDenied, ArtifactAccessDenied) as exc:\n        raise VisualExportAccessDenied("экспорт недоступен") from exc\n\n    if resolve_print_profile(profile_id) is None:',
        "replace": "    except (PromotionDenied, ArtifactAccessDenied):\n        pass\n\n    if resolve_print_profile(profile_id) is None:",
        "expected": "KILLED",
        "killer_suite": "tests/api/test_p10cert_oracles.py::TestCertCasAndAccess",
    },
    {
        "id": "M2",
        "title": "svg-член identity снапшота снят (иной SVG -- тот же снапшот)",
        "file": "apps/api/visual_artifacts.py",
        "find": "    svg_digest = _str(result.get(\"screen_svg_sha256\"))\n    if svg_digest:\n        return f\"pgv.print_snapshot:{view_id}:{identity}:{svg_digest[:16]}\"\n    return f\"pgv.print_snapshot:{view_id}:{identity}\"",
        "replace": "    return f\"pgv.print_snapshot:{view_id}:{identity}\"",
        "expected": "KILLED",
        "killer_suite": "tests/api/test_p10cert_oracles.py::TestCertDurableExport::test_o7_different_screen_svg_is_different_snapshot",
    },
    {
        "id": "M3",
        "title": "Идемпотентность сломана: frozen input всегда строится заново",
        "file": "apps/api/visual_exports.py",
        "find": "    promotion = PromotionService.create_default()\n    existing_snapshot = promotion.find_by_producer(run_id, producer_key)\n    if existing_snapshot is not None:\n        snapshot_artifact = existing_snapshot",
        "replace": "    promotion = PromotionService.create_default()\n    existing_snapshot = None\n    if existing_snapshot is not None:\n        snapshot_artifact = existing_snapshot",
        "expected": "KILLED",
        "killer_suite": "tests/api/test_p10cert_oracles.py::TestCertDurableExport::test_o5_idempotent_repeat_same_snapshot_revision_job",
    },
    {
        "id": "M4",
        "title": "CAS-сверка снята: expected_* клиента не доходят до freeze",
        "file": "apps/api/visual_exports.py",
        "find": "            expected_context_id=expected_context_id,\n            expected_data_revision=expected_data_revision,\n            date_column=date_column,\n            render_requested_at=render_requested_at,\n        )",
        "replace": "            expected_context_id=None,\n            expected_data_revision=None,\n            date_column=date_column,\n            render_requested_at=render_requested_at,\n        )",
        "expected": "KILLED",
        "killer_suite": "tests/api/test_p10cert_oracles.py::TestCertCasAndAccess::test_o8_cas_revision_conflict_409_nothing_registered",
    },
    {
        "id": "M5",
        "title": "screen_svg_required снят: chart-снапшот без геометрии строится",
        "file": "apps/api/visual_exports.py",
        "find": "        kind = section[\"renderer_kind\"]\n        if kind == \"recharts_svg\":\n            if not screen_svg:\n                raise PrintScreenSvgRequired(",
        "replace": "        kind = section[\"renderer_kind\"]\n        if kind == \"recharts_svg\":\n            if not screen_svg and False:\n                raise PrintScreenSvgRequired(",
        "expected": "KILLED",
        "killer_suite": "tests/api/test_p10cert_oracles.py::TestCertPreflight::test_o10_chart_without_svg_refused_before_job",
    },
    {
        "id": "M6",
        "title": "on*-санитайзер preflight снят (AC19 в глубину)",
        "file": "apps/api/visual_exports.py",
        "find": "    import re\n\n    if re.search(r\"\\son[a-z]+\\s*=\", lowered):\n        raise InvalidScreenSvg(\"screen_svg содержит on*-обработчики (AC19)\")",
        "replace": "    import re  # on*-проверка снята (мутант M6)",
        "expected": "KILLED",
        "killer_suite": "tests/api/test_p10cert_oracles.py::TestCertPreflight::test_o10b_invalid_svg_variants_refused",
    },
    {
        "id": "M7",
        "title": "foreignObject-санитайзер preflight снят (AC19 в глубину)",
        "file": "apps/api/visual_exports.py",
        "find": "    if \"<script\" in lowered or \"foreignobject\" in lowered:\n        raise InvalidScreenSvg(\n            \"screen_svg содержит запрещённое содержимое (<script>/\"\n            \"foreignObject) -- AC19\"\n        )",
        "replace": "    if \"<script\" in lowered:\n        raise InvalidScreenSvg(\n            \"screen_svg содержит запрещённое содержимое (<script>/\"\n            \"foreignObject) -- AC19\"\n        )",
        "expected": "KILLED",
        "killer_suite": "tests/api/test_p10cert_oracles.py::TestCertPreflight::test_o10b_invalid_svg_variants_refused",
    },
    {
        "id": "M8",
        "title": "Домен теплокарты захардкожен [0,1] (не из frozen данных)",
        "file": "apps/api/visual_exports.py",
        "find": "    if not values:\n        return [0.0, 1.0]\n    return [min(values), max(values)]",
        "replace": "    if not values:\n        return [0.0, 1.0]\n    return [0.0, 1.0]",
        "expected": "KILLED",
        "killer_suite": "tests/api/test_p10cert_oracles.py::TestCertSnapshotContent::test_o12_heatmap_domain_from_frozen_cells",
    },
    {
        "id": "M9",
        "title": "detail_level всегда expanded (sampling-честность снята)",
        "file": "apps/api/visual_exports.py",
        "find": "    detail_level = (\n        \"sampling\"\n        if sampling_mode in (\"downsampled\", \"windowed\", \"truncated\", \"aggregated\")\n        else \"expanded\"\n    )",
        "replace": "    detail_level = \"expanded\"",
        "expected": "KILLED",
        "killer_suite": "tests/api/test_p10cert_oracles.py::TestCertSnapshotContent::test_o13_sampling_honesty_detail_level",
    },
    {
        "id": "M10",
        "title": "Refs фабрикуются: отсутствующий target_column подменяется 'unknown'",
        "file": "apps/api/visual_exports.py",
        "find": "    for key, value in (\n        (\"context_id\", run.context_id),\n        (\"data_revision\", run.data_revision),\n        (\"target_column\", run.target_column),\n    ):\n        if value is None or str(value) == \"\":\n            return {}, key",
        "replace": "    for key, value in (\n        (\"context_id\", run.context_id),\n        (\"data_revision\", run.data_revision),\n        (\"target_column\", run.target_column),\n    ):\n        if value is None or str(value) == \"\":\n            if key == \"target_column\":\n                continue  # мутант M10: fabricate-подмена отказа\n            return {}, key\n    if refs.get(\"target_column\") == \"\":\n        refs[\"target_column\"] = \"unknown\"",
        "expected": "KILLED",
        "killer_suite": "tests/api/test_p10cert_oracles.py::TestCertSnapshotContent::test_o14_refs_honest_no_fabrication",
    },
    {
        "id": "M11",
        "title": "Мост: отсутствующие строки таблицы подменяются пустыми (не отказ)",
        "file": "apps/api/print_render_payload.py",
        "find": "        if kind == \"html_table\":\n            if \"rows\" not in content:\n                raise PrintRenderPayloadIncomplete(\n                    f\"missing_section_content: таблица {section_id!r} без \"\n                    \"frozen rows\"\n                )",
        "replace": "        if kind == \"html_table\":\n            if \"rows\" not in content:\n                content = dict(content)\n                content[\"rows\"] = []  # мутант M11: пустая таблица вместо отказа",
        "expected": "KILLED",
        "killer_suite": "tests/api/test_p10cert_oracles.py::TestCertBridge::test_o16b_missing_form_is_honest_incomplete",
    },
    {
        "id": "M12",
        "title": "«Не первый SVG» снят в сериализаторе (document-скан)",
        "file": "packages/ui/lib/serializeChartSvg.ts",
        "find": '  const svg = container.querySelector("svg");',
        "replace": '  const svg = document.querySelector("svg");',
        "expected": "KILLED",
        "killer_suite": "packages/ui/lib/serializeChartSvg.p10cert.test.ts (U1/U5)",
        "runner": "jest",
    },
    {
        "id": "M13",
        "title": "Локальный отказ кнопки без геометрии снят (POST без screen_svg)",
        "file": "packages/ui/components/VisualExportButton.tsx",
        "find": "    const screenSvg = getScreenSvg ? getScreenSvg() : null;\n    if (getScreenSvg && !screenSvg) {\n      setPhase({\n        kind: \"error\",\n        message:\n          \"Печатная геометрия графика не приложена — разверните график и повторите.\",\n      });\n      return;\n    }",
        "replace": "    const screenSvg = getScreenSvg ? getScreenSvg() : null;\n    if (false) {\n      setPhase({ kind: \"error\", message: \"unused\" });\n      return;\n    }",
        "expected": "KILLED",
        "killer_suite": "packages/ui/components/VisualExportButton.p10cert.test.tsx (U7)",
        "runner": "jest",
    },
    {
        "id": "M14",
        "title": "Sampling frozen результата не переносится в снапшот",
        "file": "apps/api/visual_exports.py",
        "find": '        "sampling": dict(sampling),\n        "dimensions": {',
        "replace": '        "sampling": {},\n        "dimensions": {',
        "expected": "KILLED",
        "killer_suite": "tests/api/test_p10cert_oracles.py::TestCertSnapshotContent::test_o13_sampling_honesty_detail_level",
    },
    {
        "id": "M15",
        "title": "sha256 screen_svg не пишется ни в секцию, ни в identity",
        "file": "apps/api/visual_exports.py",
        "find": '            section["screen_svg"] = screen_svg\n            section["screen_svg_sha256"] = _screen_svg_digest(screen_svg)',
        "replace": "            section[\"screen_svg\"] = screen_svg",
        "expected": "KILLED",
        "killer_suite": "tests/api/test_p10cert_oracles.py::TestCertSnapshotContent::test_o11_mixed_sections_from_one_frozen_data",
    },
]

# ── Инфраструктура восстановления (побайтовая, с cmp) ─────────────────


def restore(path: Path) -> bool:
    backup = BACKUP / path.name
    if not backup.exists():
        return False
    shutil.copyfile(backup, path)
    return backup.read_bytes() == path.read_bytes()


def run_pytest(target: str) -> tuple[bool, str]:
    cmd = [
        sys.executable, "-m", "pytest", target, "-q", "--tb=no",
        "-p", "no:cacheprovider",
    ]
    proc = subprocess.run(cmd, cwd=REPO, capture_output=True, text=True, timeout=420)
    tail = (proc.stdout + proc.stderr).strip().splitlines()[-1:] or [""]
    return proc.returncode == 0, tail[0]


def run_jest() -> tuple[bool, str]:
    cmd = [
        "node", "/tmp/jestmini/node_modules/jest/bin/jest.js", "--ci",
        "--runInBand", "--cache=false",
        "--config", "/home/z/my-project/scripts/p10cert/jest.p10cert.config.js",
    ]
    env = {"PATH": "/usr/bin:/bin", "NODE_OPTIONS": "--max-old-space-size=768"}
    proc = subprocess.run(cmd, cwd="/tmp/jestmini", capture_output=True, text=True,
                          timeout=420, env=env)
    return proc.returncode == 0, "jest exit=" + str(proc.returncode)


def main() -> int:
    PROT.mkdir(parents=True, exist_ok=True)
    only = None
    if "--only" in sys.argv:
        only = set(sys.argv[sys.argv.index("--only") + 1].split(","))
    BACKUP.mkdir(exist_ok=True)
    results = []
    for m in MUTANTS:
        if only and m["id"] not in only:
            continue
        path = REPO / m["file"]
        backup = BACKUP / path.name
        if not backup.exists():
            shutil.copyfile(path, backup)
        original = path.read_text(encoding="utf-8")
        if m["find"] not in original:
            results.append({**m, "applied": False,
                            "result": "NOT_APPLIED (find-строка не найдена)"})
            continue
        mutated = original.replace(m["find"], m["replace"], 1)
        path.write_text(mutated, encoding="utf-8")
        t0 = time.time()
        try:
            if m.get("runner") == "jest":
                ok, tail = run_jest()
            else:
                ok, tail = run_pytest(m["killer_suite"])
        except subprocess.TimeoutExpired:
            ok, tail = False, "TIMEOUT"
        finally:
            restored = restore(path)
        killed = not ok
        results.append({
            **m,
            "applied": True,
            "result": "KILLED" if killed else "SURVIVED",
            "killer_tail": tail,
            "restored_bytes_equal": restored,
            "seconds": round(time.time() - t0, 1),
        })
        print(f"[{m['id']}] {results[-1]['result']:8s} {m['title'][:70]} ({tail[:60]})")
    (PROT / "mutation_campaign.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    lines = [
        f"{r['id']}\t{r['result']}\t{r['title']}\tkiller={r['killer_suite']}"
        for r in results
    ]
    (PROT / "mutation_campaign.txt").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )
    killed_n = sum(1 for r in results if r.get("result") == "KILLED")
    print(f"\nИтог: {killed_n}/{len(results)} KILLED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
