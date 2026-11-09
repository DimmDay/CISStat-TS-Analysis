"use client";
import { useEffect, useState } from "react";
import { Campaign, CampaignPolicy, demoRequest } from "../lib/demo";
const initial: Record<string, string> = {
  alias: "",
  starts_at: "",
  ends_at: "",
  grant_minutes: "",
  max_grants: "",
  campaign_cu: "",
  participant_cu: "",
  campaign_concurrency: "",
  participant_concurrency: "",
  campaign_analyses: "",
  participant_analyses: "",
  max_rows: "",
  allowed_origins: "",
  participant_requests: "600",
  campaign_requests: "60000",
  max_upload_bytes: "4194304",
  retention_hours: "24",
};
const labels: Record<string, string> = {
  participant_requests: "Научных запросов участника",
  campaign_requests: "Научных запросов кампании",
  max_upload_bytes: "Размер файла, байт (до 4194304)",
  retention_hours: "Хранение после окончания, часов (1–720)",
  alias: "Логин с флаера",
  starts_at: "Начало (UTC)",
  ends_at: "Окончание (UTC)",
  grant_minutes: "Доступ участника, минут",
  max_grants: "Всего выдач",
  campaign_cu: "Бюджет кампании, micro-CU",
  participant_cu: "Бюджет участника, micro-CU",
  campaign_concurrency: "Одновременных операций кампании",
  participant_concurrency: "Одновременных операций участника",
  campaign_analyses: "Исследований кампании",
  participant_analyses: "Исследований участника (до 10)",
  max_rows: "Строк в датасете (до 5000)",
  allowed_origins: "Адреса оболочек HTTPS (через запятую)",
};
export function DemoCampaignAdmin() {
  const [loaded, setLoaded] = useState(false);
  const [admission, setAdmission] = useState(false),
    [codeCount, setCodeCount] = useState(1),
    [codes, setCodes] = useState<string[]>([]);
  const [items, setItems] = useState<Campaign[]>([]),
    [form, setForm] = useState(initial),
    [upload, setUpload] = useState(false);
  const [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [reason, setReason] = useState("");
  const [secret, setSecret] = useState(""),
    [editing, setEditing] = useState<Campaign | null>(null),
    [usage, setUsage] = useState<
      { metric: string; limit_units: number; spent: number; reserved: number }[]
    >([]);
  async function reload() {
    const r = await demoRequest("admin/demo-campaigns");
    setItems(r.campaigns);
    setLoaded(true);
  }
  useEffect(() => {
    reload().catch((e) => setError(e.message));
  }, []);
  async function run(action: () => Promise<void>) {
    setBusy(true);
    setError("");
    setSecret("");
    setCodes([]);
    try {
      await action();
      await reload();
    } catch (e) {
      setError(
        e instanceof Error ? e.message : "Нет соединения. Повторите попытку.",
      );
    } finally {
      setBusy(false);
    }
  }
  function policy(): CampaignPolicy {
    const p: Record<string, unknown> = {};
    for (const key of Object.keys(initial)) {
      if (key === "alias") continue;
      p[key] =
        key === "allowed_origins"
          ? form[key].split(",").map((x) => x.trim())
          : key.endsWith("_at")
            ? new Date(form[key] + "Z").toISOString()
            : Number(form[key]);
    }
    return {
      ...p,
      allow_upload: upload,
      require_admission: admission,
    } as CampaignPolicy;
  }
  function edit(c: Campaign) {
    const v: Record<string, string> = { ...initial, alias: c.alias };
    for (const [k, value] of Object.entries(c.policy)) {
      if (k in v)
        v[k] = Array.isArray(value)
          ? value.join(", ")
          : k.endsWith("_at")
            ? String(value).slice(0, 16)
            : String(value);
    }
    setForm(v);
    setUpload(c.policy.allow_upload);
    setAdmission(c.policy.require_admission ?? false);
    setEditing(c);
    setSecret("");
  }
  return (
    <section className="mx-auto max-w-5xl space-y-5 p-6 text-neutral-900">
      <h1 className="text-xl font-semibold">Демо-кампании</h1>
      <p className="text-sm text-neutral-600">
        Общая пара выдаёт отдельное пространство каждому посетителю. Все лимиты
        конечны; 1 CU = 1 000 000 micro-CU. Политика сужает возможности Demo.
        Изменение срока после создания не поддерживается; создайте новую
        кампанию. Для изменения требуется личное MFA не старше пяти минут.
      </p>
      <a
        className="underline"
        href="/login?return_to=%2Fadmin%2Fdemo-campaigns"
      >
        Повторить личный вход и MFA
      </a>
      <label className="block">
        Причина действия
        <input
          className="block w-full rounded border p-2"
          required
          maxLength={256}
          value={reason}
          onChange={(e) => setReason(e.target.value)}
        />
      </label>
      <form
        className="grid gap-3 md:grid-cols-2"
        onSubmit={(e) => {
          e.preventDefault();
          void run(async () => {
            const result = await demoRequest(
              editing
                ? "admin/demo-campaigns/" + editing.campaign_id
                : "admin/demo-campaigns",
              editing ? "PATCH" : "POST",
              editing
                ? {
                    policy: policy(),
                    expected_version: editing.policy_version,
                    reason,
                  }
                : { alias: form.alias, policy: policy(), reason },
            );
            setSecret(result.secret ?? "");
            setEditing(null);
            setForm(initial);
          });
        }}
      >
        {Object.keys(initial).map((key) => (
          <label key={key}>
            {labels[key]}
            <input
              className="block w-full rounded border p-2"
              required
              disabled={
                !!editing && ["alias", "starts_at", "ends_at"].includes(key)
              }
              type={
                key.endsWith("_at")
                  ? "datetime-local"
                  : ["alias", "allowed_origins"].includes(key)
                    ? "text"
                    : "number"
              }
              max={
                ["alias", "allowed_origins"].includes(key) ||
                key.endsWith("_at")
                  ? undefined
                  : Number.MAX_SAFE_INTEGER
              }
              step={key.endsWith("_at") ? 60 : 1}
              min="0"
              value={form[key]}
              onChange={(e) => setForm({ ...form, [key]: e.target.value })}
            />
          </label>
        ))}
        <label>
          <input
            type="checkbox"
            checked={upload}
            onChange={(e) => setUpload(e.target.checked)}
          />{" "}
          Разрешить собственные данные
        </label>
        <label>
          <input
            type="checkbox"
            checked={admission}
            onChange={(e) => setAdmission(e.target.checked)}
          />{" "}
          Требовать одноразовый код участника
        </label>
        <button
          className="rounded bg-brand p-2 text-white"
          disabled={busy || !reason.trim()}
        >
          {editing ? "Сохранить политику" : "Создать черновик"}
        </button>
        {editing && (
          <button
            type="button"
            onClick={() => {
              setEditing(null);
              setForm(initial);
            }}
          >
            Отменить редактирование
          </button>
        )}
      </form>
      {secret && (
        <div role="status" className="rounded border p-3">
          <p>
            Пароль показан один раз. Сохраните его для флаера:{" "}
            <code>{secret}</code>
          </p>
          <button onClick={() => setSecret("")}>Скрыть пароль</button>
        </div>
      )}
      {codes.length > 0 && (
        <div role="status">
          <p>
            Коды показаны один раз. Передайте каждому участнику отдельный код.
          </p>
          <textarea
            aria-label="Выданные коды"
            readOnly
            className="w-full border p-2"
            value={codes.join("\n")}
          />
          <button onClick={() => setCodes([])}>Скрыть коды</button>
        </div>
      )}
      <label className="block">
        Кодов в партии (1–200)
        <input
          type="number"
          min={1}
          max={200}
          value={codeCount}
          onChange={(e) => setCodeCount(Number(e.target.value))}
        />
      </label>
      {error && <p role="alert">{error}</p>}
      <button
        disabled={busy}
        className="underline"
        onClick={() => void run(reload)}
      >
        Обновить список
      </button>
      {!loaded && !error && <p role="status">Загружаем кампании…</p>}
      {loaded && !items.length && <p>Кампаний пока нет.</p>}
      <ul className="space-y-3">
        {items.map((c) => (
          <li
            className="rounded border border-neutral-200 bg-white p-4"
            key={c.campaign_id}
          >
            <h2 className="font-semibold">
              {c.alias} ·{" "}
              {(
                {
                  draft: "Черновик",
                  scheduled: "Запланирована",
                  active: "Активна",
                  paused: "Приостановлена",
                  expired: "Завершена",
                  revoked: "Отозвана",
                } as Record<string, string>
              )[c.status] ?? c.status}{" "}
              · версия {c.policy_version}
            </h2>
            <p>
              Выдано {c.issued_grants} из {c.policy.max_grants}. Окончание:{" "}
              {c.policy.ends_at}. Доступ: {c.policy.grant_minutes} мин.
            </p>
            <p className="text-sm">
              Приостановка и отзыв закрывают доступ для {c.issued_grants}{" "}
              участников. После смены общего пароля потребуется повторный вход;
              сроки и расход участников сохранятся.
            </p>
            <div className="mt-2 flex flex-wrap gap-3">
              {!["revoked", "expired"].includes(c.status) && (
                <button
                  disabled={
                    busy || !reason.trim() || codeCount < 1 || codeCount > 200
                  }
                  onClick={() =>
                    void run(async () => {
                      const result = await demoRequest(
                        "admin/demo-campaigns/" + c.campaign_id + "/admissions",
                        "POST",
                        {
                          expected_version: c.policy_version,
                          reason,
                          count: codeCount,
                          expires_at: c.policy.ends_at,
                        },
                      );
                      setCodes(result.codes);
                    })
                  }
                >
                  Выдать коды до конца кампании
                </button>
              )}
              <button disabled={busy} onClick={() => edit(c)}>
                Редактировать
              </button>
              {["activate", "pause", "resume", "revoke", "rotate-credential"]
                .filter((a) =>
                  a === "activate"
                    ? c.status === "draft"
                    : a === "resume"
                      ? c.status === "paused"
                      : a === "pause"
                        ? ["active", "scheduled"].includes(c.status)
                        : !["revoked", "expired"].includes(c.status),
                )
                .map((a) => (
                  <button
                    key={a}
                    disabled={busy || !reason.trim()}
                    onClick={() =>
                      void run(async () => {
                        const r = await demoRequest(
                          "admin/demo-campaigns/" + c.campaign_id + "/" + a,
                          "POST",
                          { expected_version: c.policy_version, reason },
                        );
                        setSecret(r.secret ?? "");
                      })
                    }
                  >
                    {
                      {
                        activate: "Активировать",
                        pause: "Приостановить",
                        resume: "Возобновить",
                        revoke: "Отозвать",
                        "rotate-credential": "Сменить общий пароль",
                      }[a]
                    }
                  </button>
                ))}
              <button
                disabled={busy}
                onClick={() =>
                  void run(async () => {
                    const r = await demoRequest(
                      "admin/demo-campaigns/" + c.campaign_id + "/usage",
                    );
                    setUsage(r.budgets);
                  })
                }
              >
                Расход и резервы
              </button>
            </div>
          </li>
        ))}
      </ul>
      {usage.length > 0 && (
        <table className="w-full text-sm">
          <caption>Расход и резервы выбранной кампании</caption>
          <thead>
            <tr>
              <th>Ресурс</th>
              <th>Лимит</th>
              <th>Расход</th>
              <th>Резерв</th>
              <th>Остаток</th>
            </tr>
          </thead>
          <tbody>
            {usage.map((b) => (
              <tr key={b.metric}>
                <th>
                  {(
                    {
                      cu: "micro-CU",
                      analysis: "Исследования",
                      concurrency: "Одновременные операции",
                      api: "Программный API",
                    } as Record<string, string>
                  )[b.metric] ?? b.metric}
                </th>
                <td>{b.limit_units}</td>
                <td>{b.spent}</td>
                <td>{b.reserved}</td>
                <td>{b.limit_units - b.spent - b.reserved}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}
