// @ts-nocheck

import { readFileSync } from "fs";
import { join } from "path";

const OVERVIEWS = [
  "EdaDistributionOverview.tsx",
  "EdaFeatureSelectionOverview.tsx",
  "EdaModelMatrixOverview.tsx",
  "EdaSeasonalityOverview.tsx",
  "EdaStationarityOverview.tsx",
  "EdaStructuralBreaksOverview.tsx",
  "EdaValidationStrategyOverview.tsx",
  "PreprocessingDecompositionOverview.tsx",
  "PreprocessingFeatureEngineeringOverview.tsx",
  "PreprocessingScalingOverview.tsx",
  "PreprocessingSmoothingOverview.tsx",
  "PreprocessingSpectralOverview.tsx",
  "PreprocessingStationarityOverview.tsx",
  "PreprocessingVarianceOverview.tsx",
  "ValidationUniquenessOverview.tsx",
] as const;

const DELEGATING_OVERVIEWS = [
  "PreprocessingMissingOverview.tsx",
  "PreprocessingOutliersOverview.tsx",
  "PreprocessingRegularityOverview.tsx",
] as const;

const NESTED_VISUALIZATIONS = [
  "PreprocessingMissingVisualizations.tsx",
  "PreprocessingOutliersVisualizations.tsx",
  "PreprocessingRegularityVisualizations.tsx",
] as const;

const LEGACY_FIXED_HEIGHTS = [
  "h-[185px]",
  "h-[205px]",
  "h-[235px]",
  "h-[238px]",
  "h-[245px]",
  "h-[255px]",
  "h-[260px]",
  "h-[265px]",
  "h-[270px]",
  "h-[275px]",
  "h-[300px]",
  "h-[310px]",
  "h-[340px]",
] as const;

describe("адаптивная высота вложенных визуализаций рабочего окна", () => {
  it.each(OVERVIEWS)("растягивает runtime-состояния %s на остаток 468px", (fileName) => {
    const source = readFileSync(join(__dirname, fileName), "utf8");

    expect(source).toContain("flex h-[468px] min-h-0 flex-col");
    expect(source).toContain("min-h-0 flex-1");
    for (const legacyHeight of LEGACY_FIXED_HEIGHTS) {
      expect(source).not.toContain(legacyHeight);
    }
  });

  it.each(NESTED_VISUALIZATIONS)("не ограничивает фиксированной высотой %s", (fileName) => {
    const source = readFileSync(join(__dirname, fileName), "utf8");

    expect(source).toContain("min-h-0 flex-1");
    for (const legacyHeight of LEGACY_FIXED_HEIGHTS) {
      expect(source).not.toContain(legacyHeight);
    }
  });

  it.each(DELEGATING_OVERVIEWS)("отдаёт остаток высоты вложенному компоненту %s", (fileName) => {
    const source = readFileSync(join(__dirname, fileName), "utf8");

    expect(source).toContain("flex h-[468px] min-h-0 flex-col");
    for (const legacyHeight of LEGACY_FIXED_HEIGHTS) {
      expect(source).not.toContain(legacyHeight);
    }
  });
});
