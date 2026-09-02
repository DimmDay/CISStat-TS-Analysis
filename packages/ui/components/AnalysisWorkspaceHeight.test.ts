// @ts-nocheck

import { readFileSync } from "fs";
import { join } from "path";

const WORKSPACE_COMPONENTS = [
  "EdaCorrelationOverview.tsx",
  "EdaDescriptiveOverview.tsx",
  "EdaDistributionOverview.tsx",
  "EdaFeatureSelectionOverview.tsx",
  "EdaIhOverview.tsx",
  "EdaModelMatrixOverview.tsx",
  "EdaSeasonalityOverview.tsx",
  "EdaStationarityOverview.tsx",
  "EdaStructuralBreaksOverview.tsx",
  "EdaValidationStrategyOverview.tsx",
  "PreprocessingDecompositionOverview.tsx",
  "PreprocessingDecompositionPipeline.tsx",
  "PreprocessingFeatureEngineeringOverview.tsx",
  "PreprocessingFeatureEngineeringPipeline.tsx",
  "PreprocessingMissingOverview.tsx",
  "PreprocessingMissingPipeline.tsx",
  "PreprocessingOutliersOverview.tsx",
  "PreprocessingOutliersPipeline.tsx",
  "PreprocessingRegularityOverview.tsx",
  "PreprocessingRegularityPipeline.tsx",
  "PreprocessingScalingOverview.tsx",
  "PreprocessingScalingPipeline.tsx",
  "PreprocessingSmoothingOverview.tsx",
  "PreprocessingSmoothingPipeline.tsx",
  "PreprocessingSpectralOverview.tsx",
  "PreprocessingSpectralPipeline.tsx",
  "PreprocessingStationarityOverview.tsx",
  "PreprocessingStationarityPipeline.tsx",
  "PreprocessingVarianceOverview.tsx",
  "PreprocessingVariancePipeline.tsx",
  "TsAnalysisEDA.tsx",
  "TsAnalysisPreprocessing.tsx",
  "TsAnalysisValidation.tsx",
  "ValidationCheckChart.tsx",
  "ValidationConsistencyOverview.tsx",
  "ValidationConsistencyPipeline.tsx",
  "ValidationFormatPipeline.tsx",
  "ValidationInclusionPipeline.tsx",
  "ValidationRangeOverview.tsx",
  "ValidationRangePipeline.tsx",
  "ValidationReferentialPipeline.tsx",
  "ValidationRegularityPipeline.tsx",
  "ValidationSufficiencyPipeline.tsx",
  "ValidationTextQualityPipeline.tsx",
  "ValidationTypeMatrix.tsx",
  "ValidationTypePipeline.tsx",
  "ValidationUniquenessOverview.tsx",
  "ValidationUniquenessPipeline.tsx",
] as const;

describe("единая высота окна «Обзор»/«Мастер»", () => {
  it.each(WORKSPACE_COMPONENTS)("использует 468px во всех состояниях %s", (fileName) => {
    const source = readFileSync(join(__dirname, fileName), "utf8");

    expect(source).toContain("h-[468px]");
    expect(source).not.toContain("h-[420px]");
  });

  it("покрывает все 165 состояний рабочего окна", () => {
    const count = WORKSPACE_COMPONENTS.reduce((total, fileName) => {
      const source = readFileSync(join(__dirname, fileName), "utf8");
      return total + (source.match(/h-\[468px\]/g) ?? []).length;
    }, 0);

    expect(count).toBe(165);
  });
});
