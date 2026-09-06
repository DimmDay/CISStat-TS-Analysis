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

  it("фиксирует 44 прокручиваемых и 121 непрокручиваемое состояние", () => {
    const classes = WORKSPACE_COMPONENTS.flatMap((fileName) => {
      const source = readFileSync(join(__dirname, fileName), "utf8");
      // \{? после "=" (Task 97.2): условные состояния Обзоров пишутся
      // шаблонным className={`... ${cond ? "a" : "b"}`} — без \{? фигурная
      // скобка делает такие строки невидимыми для теста (у Обзоров пилота
      // Этапа 2 корень стал шаблонным: relative + условная пара overflow).
      return Array.from(source.matchAll(/className=\{?(?:"([^"]*)"|`([^`]*)`)/gs), (match) => (
        match[1] ?? match[2] ?? ""
      ));
    });
    const heightStates = classes.flatMap((className) => (
      Array.from(className.matchAll(/h-\[468px\]/g), () => className)
    ));
    const scrolling = heightStates.filter((className) => /overflow-(?:y-)?auto/.test(className));

    expect(heightStates).toHaveLength(165);
    expect(scrolling).toHaveLength(44);
    expect(heightStates.length - scrolling.length).toBe(121);
  });
});
