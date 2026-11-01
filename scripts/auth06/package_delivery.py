#!/usr/bin/env python3
"""Package exactly AUTH-06 restored changes; verify inventory, CRC and every byte."""

import shutil
import subprocess
import sys
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT.parent / "upload"
FILES = {
    ".github/workflows/auth06.yml",
    "apps/api/access_registry.py",
    "apps/api/authentication/csrf.py",
    "apps/api/authentication/http_contract.py",
    "apps/api/authentication/sessions.py",
    "apps/api/main.py",
    "apps/api/routers/authentication.py",
    "apps/embedded/app/api/v1/[...path]/route.ts",
    "apps/embedded/app/layout.tsx",
    "apps/embedded/app/login/page.tsx",
    "apps/embedded/next.config.mjs",
    "apps/standalone/app/api/v1/[...path]/route.ts",
    "apps/standalone/app/layout.tsx",
    "apps/standalone/app/login/page.tsx",
    "apps/standalone/components/ProductHeader.tsx",
    "apps/standalone/components/ProductHeaderThemeToggle.test.tsx",
    "apps/standalone/components/product-header-nav-slogan.test.tsx",
    "apps/standalone/next.config.mjs",
    "docs/auth00/inventory.json",
    "docs/auth00/inventory.md",
    "docs/auth00/operation_variants.md",
    "docs/auth00/policy_review.json",
    "docs/auth01/openapi.json",
    "docs/auth06/design.md",
    "jest.setup.js",
    "packages/ui/components/DatasetPassportPanel.tsx",
    "packages/ui/components/DatasetViewEditor.tsx",
    "packages/ui/components/DbConnectionForm.tsx",
    "packages/ui/components/EdaDescriptiveOverview.test.tsx",
    "packages/ui/components/EdaDescriptiveOverview.tsx",
    "packages/ui/components/EmbeddedHome.tsx",
    "packages/ui/components/LoginScreen.test.tsx",
    "packages/ui/components/LoginScreen.tsx",
    "packages/ui/components/ModelingWorkflowOverview.tsx",
    "packages/ui/components/PortalNavBar.tsx",
    "packages/ui/components/PreprocessingDecompositionPipeline.tsx",
    "packages/ui/components/PreprocessingFeatureEngineeringPipeline.tsx",
    "packages/ui/components/PreprocessingMissingManualEditor.tsx",
    "packages/ui/components/PreprocessingMissingOverview.tsx",
    "packages/ui/components/PreprocessingMissingPipeline.tsx",
    "packages/ui/components/PreprocessingMissingVisualizations.tsx",
    "packages/ui/components/PreprocessingOutliersManualEditor.tsx",
    "packages/ui/components/PreprocessingOutliersOverview.tsx",
    "packages/ui/components/PreprocessingOutliersPipeline.tsx",
    "packages/ui/components/PreprocessingOutliersVisualizations.tsx",
    "packages/ui/components/PreprocessingRegularityOverview.tsx",
    "packages/ui/components/PreprocessingRegularityPipeline.tsx",
    "packages/ui/components/PreprocessingRegularityVisualizations.tsx",
    "packages/ui/components/PreprocessingScalingPipeline.tsx",
    "packages/ui/components/PreprocessingSmoothingPipeline.tsx",
    "packages/ui/components/PreprocessingSpectralPipeline.tsx",
    "packages/ui/components/PreprocessingStationarityPipeline.tsx",
    "packages/ui/components/PreprocessingVariancePipeline.tsx",
    "packages/ui/components/ProgressCheckpointBar.tsx",
    "packages/ui/components/ProgressDrawer.tsx",
    "packages/ui/components/ResidualDiagnosticsPanel.tsx",
    "packages/ui/components/RulesManagementPanel.tsx",
    "packages/ui/components/TsAnalysisEDA.test.tsx",
    "packages/ui/components/TsAnalysisEDA.tsx",
    "packages/ui/components/TsAnalysisForecasting.tsx",
    "packages/ui/components/TsAnalysisModeling.tsx",
    "packages/ui/components/TsAnalysisPreprocessing.test.tsx",
    "packages/ui/components/TsAnalysisPreprocessing.tsx",
    "packages/ui/components/TsAnalysisUpload.tsx",
    "packages/ui/components/TsAnalysisValidation.test.tsx",
    "packages/ui/components/TsAnalysisValidation.tsx",
    "packages/ui/components/ValidationConsistencyOverview.tsx",
    "packages/ui/components/ValidationConsistencyPipeline.tsx",
    "packages/ui/components/ValidationFormatPipeline.tsx",
    "packages/ui/components/ValidationInclusionOverview.tsx",
    "packages/ui/components/ValidationInclusionPipeline.tsx",
    "packages/ui/components/ValidationRangeOverview.tsx",
    "packages/ui/components/ValidationRangePipeline.tsx",
    "packages/ui/components/ValidationReferentialOverview.tsx",
    "packages/ui/components/ValidationReferentialPipeline.tsx",
    "packages/ui/components/ValidationRegularityOverview.tsx",
    "packages/ui/components/ValidationRegularityPipeline.tsx",
    "packages/ui/components/ValidationSufficiencyOverview.tsx",
    "packages/ui/components/ValidationSufficiencyPipeline.tsx",
    "packages/ui/components/ValidationTextQualityOverview.tsx",
    "packages/ui/components/ValidationTextQualityPipeline.tsx",
    "packages/ui/components/ValidationTypePipeline.tsx",
    "packages/ui/components/ValidationUniquenessOverview.tsx",
    "packages/ui/components/ValidationUniquenessPipeline.tsx",
    "packages/ui/components/edarecalccert_EDA-RECALC-COMPENSATION.test.tsx",
    "packages/ui/components/upload-panel-transforms.test.tsx",
    "packages/ui/context/AppShellContext.tsx",
    "packages/ui/context/AuthContext.test.tsx",
    "packages/ui/context/AuthContext.tsx",
    "packages/ui/hooks/useProgressMapDelivery.ts",
    "packages/ui/hooks/useTargetColumn.ts",
    "packages/ui/lib/access-contract.generated.ts",
    "packages/ui/lib/admin.ts",
    "packages/ui/lib/adminLogs.ts",
    "packages/ui/lib/apiClient.ts",
    "packages/ui/lib/auth06SourceBoundary.test.ts",
    "packages/ui/lib/authClient.test.ts",
    "packages/ui/lib/authClient.ts",
    "packages/ui/lib/browserTransport.test.ts",
    "packages/ui/lib/browserTransport.ts",
    "packages/ui/lib/documentation.ts",
    "packages/ui/lib/forecasting.ts",
    "packages/ui/lib/mentor.ts",
    "packages/ui/lib/monitoring.ts",
    "packages/ui/lib/tasks.ts",
    "packages/ui/lib/visualExports.ts",
    "packages/ui/server/firstPartyProxy.test.ts",
    "packages/ui/server/firstPartyProxy.ts",
    "packages/ui/server/proxy-routes.generated.json",
    "scripts/auth00/inventory.py",
    "scripts/local_gates.py",
    "tests/integration/test_auth06_transport.py",
    "tests/unit/test_auth00_inventory.py",
    "tests/unit/test_auth06_csrf.py",
    "worklog/worklog11.md",
}


def main():
    assert (
        subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT).decode().strip()
        == "8e8f747b376c9b09ec7406996dec2374dc1fdf54"
    )
    for script in (
        "scripts/auth01/generate.py",
        "scripts/auth00/inventory.py",
        "scripts/auth06/generate_proxy_routes.py",
    ):
        subprocess.run([sys.executable, script, "--check"], cwd=ROOT, check=True)
    files = FILES | {
        p.relative_to(ROOT).as_posix()
        for p in (ROOT / "scripts/auth06").rglob("*")
        if p.is_file() and "__pycache__" not in p.parts
    }
    files.add("scripts/auth06/files.txt")
    names = "\n".join(sorted(files)) + "\n"
    (ROOT / "scripts/auth06/files.txt").write_text(
        names, encoding="utf-8", newline="\n"
    )
    changed = set()
    for command in (
        ["git", "diff", "--name-only", "-z"],
        ["git", "ls-files", "--others", "--exclude-standard", "-z"],
    ):
        changed.update(
            subprocess.check_output(command, cwd=ROOT)
            .decode("utf-8")
            .strip("\0")
            .split("\0")
        )
    changed.discard("")
    if changed != files:
        raise ValueError(
            "Delivery differs from git changes: " + repr(sorted(changed ^ files))
        )
    OUTPUT.mkdir(exist_ok=True)
    target = OUTPUT / "cisstat-auth06-8e8f747-restored.zip"
    with ZipFile(target, "w", compression=ZIP_DEFLATED) as archive:
        for name in sorted(files):
            archive.write(ROOT / name, name)
    with ZipFile(target) as archive:
        assert archive.testzip() is None
        assert set(archive.namelist()) == files
        for name in files:
            assert archive.read(name) == (ROOT / name).read_bytes(), name
    shutil.copyfile(
        ROOT / "worklog/worklog11.md", OUTPUT / "worklog11-auth06-restored.md"
    )
    (OUTPUT / "auth06-restored-files.txt").write_text(
        names, encoding="utf-8", newline="\n"
    )
    print(f"ZIP verified: {target}; {len(files)} files; {target.stat().st_size} bytes")


if __name__ == "__main__":
    main()
