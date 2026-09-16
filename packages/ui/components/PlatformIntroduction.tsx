import { NavigatorHero } from "./NavigatorHero";
import { TsAnalysisNavigator } from "./TsAnalysisNavigator";

/** Общая композиция /navigator для standalone и embedded приложений.
 *
 *  Task NAVIG-1: черта над заголовком «Подробная навигация по платформе» —
 *  фирменный индиго (border-brand, паттерн главной страницы); нижняя
 *  серая черта (page-bottom-separator) удалена — как на главной.
 */
export function PlatformIntroduction() {
  return (
    <>
      <NavigatorHero />
      <section
        id="platform-navigation"
        aria-labelledby="platform-navigation-title"
        className="scroll-mt-24 mt-12"
      >
        <div className="w-full border-t border-brand pt-4">
          <h2
            id="platform-navigation-title"
            className="font-sans text-2xl font-normal tracking-tight text-[#1e3a8a] text-center mb-4"
          >
            Подробная навигация по платформе
          </h2>
        </div>
        <TsAnalysisNavigator />
      </section>
    </>
  );
}
