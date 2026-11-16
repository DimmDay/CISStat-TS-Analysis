import { DemoEntry } from "./DemoEntry";
import { PersonalDemoEntry } from "./PersonalDemoEntry";

export function DemoLanding() {
  return (
    <div className="mx-auto max-w-6xl space-y-8 px-4 py-8 text-neutral-900">
      <header className="space-y-3">
        <h1 className="text-2xl font-semibold">Демо-режим платформы</h1>
        <p>
          Выберите доступ через организатора или самостоятельный личный вход.
          В обоих случаях данные и вычисления ограничены условиями выбранного режима.
        </p>
      </header>
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <section aria-labelledby="campaign-demo-title" className="min-w-0 space-y-4 rounded-xl border border-neutral-200 bg-white p-5">
          <h2 id="campaign-demo-title" className="text-xl font-semibold">
            Мульти-доступ через кампанию организатора
          </h2>
          <p>Для участников мероприятия или программы организатора. Введите выданные логин, пароль кампании и код участника, если он требуется.</p>
          <ul className="list-disc space-y-2 pl-5">
            <li>Каждому участнику выдаётся отдельное временное пространство; исследования других участников недоступны.</li>
            <li>Время, вычислительный бюджет, число исследований, размер загрузки и срок хранения задаёт организатор.</li>
            <li>Продолжение на том же устройстве сохраняет прежний срок и расход. Постоянная история не включена.</li>
            <li>После окончания демо доступ закрывается; результаты удаляются по сроку хранения кампании.</li>
          </ul>
          <DemoEntry campaignOnly />
        </section>
        <section aria-labelledby="personal-demo-title" className="min-w-0 space-y-4 rounded-xl border border-neutral-200 bg-white p-5">
          <h2 id="personal-demo-title" className="text-xl font-semibold">
            Самостоятельный MONO-доступ
          </h2>
          <PersonalDemoEntry />
        </section>
      </div>
    </div>
  );
}
