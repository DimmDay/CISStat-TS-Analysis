"use client";

import { useEffect, useState } from "react";
import { demoRequest } from "../lib/demo";

type Policy = {
  available: boolean;
  limits: { days: number; micro_cu: number; analyses: number; concurrency: number; max_rows: number };
};

export function PersonalDemoEntry() {
  const [policy, setPolicy] = useState<Policy | null>(null);
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    let live = true;
    Promise.resolve(demoRequest("auth/personal-demo"))
      .then((value) => { if (live) setPolicy(value || null); })
      .catch(() => { if (live) setPolicy(null); })
      .finally(() => { if (live) setLoading(false); });
    return () => { live = false; };
  }, []);
  const limits = policy?.limits;
  return (
    <section aria-label="Самостоятельный MONO-доступ" className="space-y-4">
      <p>Подтвердите свой email. Вы получите личный аккаунт с собственными данными и стартовым вычислительным бюджетом.</p>
      {limits && (
        <ul className="list-disc space-y-2 pl-5">
          <li>Срок пробного доступа: до {limits.days} дней с выдачи стартового бюджета.</li>
          <li>До {limits.analyses} исследований и {limits.micro_cu / 1000000} CU; {limits.concurrency} одновременное вычисление.</li>
          <li>До {limits.max_rows.toLocaleString("ru-RU")} строк в датасете; базовые модели, без настройки и обучения собственных моделей.</li>
        </ul>
      )}
      <p>Повторный вход сохраняет срок и расход. Пробный бюджет выдаётся один раз. После окончания срока доступ закрывается; переход на дальнейшие условия не восстанавливает израсходованные кредиты.</p>
      {loading ? (
        <p role="status">Проверяем доступность личного демо…</p>
      ) : policy?.available ? (
        <a className="inline-block rounded bg-brand px-4 py-2 text-white" href="/login?return_to=/upload">Получить личный демо-доступ</a>
      ) : (
        <p role="status">Личная регистрация сейчас недоступна. Попробуйте позже.</p>
      )}
      <p><a className="underline" href="/login?return_to=/upload">Войти в существующий личный аккаунт</a></p>
      <p className="text-sm">После подтверждения письма вы перейдёте к загрузке данных. Кошелёк и ограничения настраиваются автоматически.</p>
    </section>
  );
}
