import { NavigatorHero } from "./NavigatorHero";
import { TsAnalysisNavigator } from "./TsAnalysisNavigator";

/** Общая композиция /navigator для standalone и embedded приложений. */
export function PlatformIntroduction() {
  return (
    <>
      <NavigatorHero />
      <section
        id="platform-navigation"
        aria-labelledby="platform-navigation-title"
        className="scroll-mt-24 mt-12"
      >
        <h2
          id="platform-navigation-title"
          className="font-sans text-2xl font-normal tracking-tight text-[#1e3a8a] text-center mb-4"
        >
          Подробная навигация по платформе
        </h2>
        <TsAnalysisNavigator />
      </section>
      <div
        data-testid="page-bottom-separator"
        className="mt-12 h-px w-full bg-neutral-200"
        aria-hidden="true"
      />
    </>
  );
}
