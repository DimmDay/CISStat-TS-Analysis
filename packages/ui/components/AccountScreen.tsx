"use client";
import { useEffect, useRef, useState } from "react";
import { useAuth } from "../context/AuthContext";
import { commandKey, teamRequest, TeamAccount } from "../lib/team";
export function AccountScreen() {
  const auth = useAuth();
  const [account, setAccount] = useState<TeamAccount | null>(null),
    [choices, setChoices] = useState<
      { account_id: string; account_type: string; plan: string }[]
    >([]),
    [error, setError] = useState(""),
    [message, setMessage] = useState(""),
    [busy, setBusy] = useState(false);
  const [reason, setReason] = useState(""),
    [inviteTarget, setInviteTarget] = useState(""),
    [targetKind, setTargetKind] = useState("email"),
    [token, setToken] = useState(""),
    [issued, setIssued] = useState(""),
    [shared, setShared] = useState(false),
    [seats, setSeats] = useState(2);
  const generation = useRef(0),
    lock = useRef(false);
  async function reload() {
    const seq = ++generation.current;
    const list = await teamRequest();
    const detail = await teamRequest("/" + list.current_account_id);
    if (seq === generation.current) {
      setChoices(list.accounts);
      setAccount(detail);
    }
  }
  useEffect(() => {
    if (auth.status === "authenticated") {
      void reload().catch((e) => setError(e.message));
    }
    return () => {
      generation.current++;
    };
  }, [auth.status, auth.session?.account_id]);
  async function run(action: () => Promise<void>) {
    if (lock.current) return;
    lock.current = true;
    setBusy(true);
    setError("");
    setMessage("");
    setIssued("");
    try {
      await action();
      await reload();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Сервис временно недоступен.");
    } finally {
      lock.current = false;
      setBusy(false);
    }
  }
  function common() {
    if (!account) throw new Error("Обновите состояние аккаунта.");
    return {
      expected_version: account.entitlement_version,
      reason: reason.trim(),
      idempotency_key: commandKey(),
    };
  }
  async function mutate(path: string, extra: Record<string, unknown> = {}) {
    if (!reason.trim()) throw new Error("Укажите причину действия.");
    const result = await teamRequest("/" + account!.account_id + path, {
      ...common(),
      ...extra,
    });
    if (result.session_invalidated) {
      window.location.assign("/login?return_to=%2Faccount");
    }
    return result;
  }
  if (auth.status === "loading")
    return <p role="status">Проверяем личный вход…</p>;
  if (auth.status !== "authenticated")
    return (
      <section className="p-6">
        <h1>Аккаунт и команда</h1>
        <p>Для управления и принятия приглашения нужен личный вход.</p>
        <a className="underline" href="/login?return_to=%2Faccount">
          Войти
        </a>
      </section>
    );
  return (
    <section className="mx-auto max-w-4xl space-y-5 p-6 text-neutral-900">
      <h1 className="text-xl font-semibold">Аккаунт и команда</h1>
      <p className="text-sm">
        Ваш ID для приглашения: <code>{auth.session?.subject_id}</code>.
        Подтверждённый email также можно использовать для приглашения.
        Исследования принадлежат выбранному аккаунту.
      </p>
      {error && <p role="alert">{error}</p>}
      {message && <p role="status">{message}</p>}
      <button
        className="underline"
        disabled={busy}
        onClick={() => void run(reload)}
      >
        Обновить
      </button>
      <div className="space-y-2">
        <h2>Ваши аккаунты</h2>
        {choices.map((c) => (
          <button
            className="mr-3 rounded border p-2"
            key={c.account_id}
            disabled={busy || c.account_id === account?.account_id}
            onClick={() =>
              void run(async () => {
                await teamRequest("/" + c.account_id + "/select", {});
                window.location.assign("/upload");
              })
            }
          >
            {c.account_type === "mono" ? "Личный" : "Командный"} · {c.plan}
            {c.account_id === account?.account_id ? " · выбран" : " · выбрать"}
          </button>
        ))}
      </div>
      <form
        className="space-y-2 rounded border p-3"
        onSubmit={(e) => {
          e.preventDefault();
          void run(async () => {
            const value = token;
            await teamRequest("/invitations/accept", {
              invitation_token: value,
              idempotency_key: commandKey(),
              reason: "Принять приглашение",
            });
            setToken("");
            setMessage("Приглашение принято. Выберите аккаунт для работы.");
          });
        }}
      >
        <h2>Принять приглашение</h2>
        <label className="block">
          Код приглашения
          <input
            type="password"
            autoComplete="off"
            required
            value={token}
            onChange={(e) => setToken(e.target.value)}
            className="ml-2 rounded border p-2"
          />
        </label>
        <button className="rounded bg-brand p-2 text-white" disabled={busy}>
          Принять
        </button>
        <p className="text-sm">
          Email-приглашение требует подтверждённого адреса вашей личной учётной
          записи. При его отсутствии используйте приглашение по ID пользователя.
        </p>
      </form>
      {account && (
        <>
          <p>
            Тип: {account.account_type === "mono" ? "личный" : "командный"}.
            Подтверждённых мест: {account.seats}; занято: {account.occupied};
            свободно: {account.free_seats}.
          </p>
          {account.can_manage && (
            <>
              <label className="block">
                Причина действия
                <input
                  required
                  maxLength={256}
                  className="ml-2 w-full rounded border p-2"
                  value={reason}
                  onChange={(e) => setReason(e.target.value)}
                />
              </label>
              {account.account_type === "mono" ? (
                <div className="space-y-2">
                  <label>
                    <input
                      type="checkbox"
                      checked={shared}
                      onChange={(e) => setShared(e.target.checked)}
                    />{" "}
                    Разрешить участникам команды доступ к исследованиям этого
                    аккаунта
                  </label>
                  <button
                    className="block rounded border p-2"
                    disabled={busy || !shared || !reason.trim()}
                    onClick={() =>
                      void run(() =>
                        mutate("/type", {
                          account_type: "multi",
                          acknowledge_shared_access: true,
                        }).then(() => {
                          setShared(false);
                        }),
                      )
                    }
                  >
                    Включить командный доступ
                  </button>
                </div>
              ) : (
                <>
                  <form
                    className="space-y-2 rounded border p-3"
                    onSubmit={(e) => {
                      e.preventDefault();
                      void run(async () => {
                        const r = await mutate("/invitations", {
                          [targetKind === "email"
                            ? "email"
                            : "target_subject_id"]: inviteTarget,
                          ttl_hours: 24,
                        });
                        setIssued(r.invitation_token ?? "");
                        if (!r.invitation_token)
                          setMessage(
                            "Запрос уже выполнен. Старый код повторно не раскрывается.",
                          );
                      });
                    }}
                  >
                    <h2>Пригласить участника на свободное место</h2>
                    <label>
                      Способ приглашения
                      <select
                        aria-label="Способ приглашения"
                        value={targetKind}
                        onChange={(e) => {
                          setTargetKind(e.target.value);
                          setInviteTarget("");
                        }}
                      >
                        <option value="email">Подтверждённый email</option>
                        <option value="id">ID пользователя</option>
                      </select>
                    </label>
                    <label className="block">
                      Получатель
                      <input
                        required
                        type={targetKind === "email" ? "email" : "text"}
                        className="ml-2 rounded border p-2"
                        value={inviteTarget}
                        onChange={(e) => setInviteTarget(e.target.value)}
                      />
                    </label>
                    <button disabled={busy || !reason.trim()}>
                      Создать приглашение на 24 часа
                    </button>
                    <p className="text-sm">
                      Приглашение не резервирует место. Код передайте получателю
                      отдельно; одно приглашение не создаёт новую учётную
                      запись.
                    </p>
                  </form>
                  {issued && (
                    <div role="status">
                      <p>Код показан один раз:</p>
                      <input
                        aria-label="Выданный код приглашения"
                        readOnly
                        value={issued}
                        className="w-full rounded border p-2"
                      />
                      <button onClick={() => setIssued("")}>Скрыть код</button>
                    </div>
                  )}
                  <div>
                    <h2>Изменить подтверждённую ёмкость</h2>
                    <p className="text-sm">
                      ID аккаунта для заявки: <code>{account.account_id}</code>
                    </p>
                    <label>
                      Количество мест
                      <input
                        type="number"
                        min={1}
                        max={1000}
                        value={seats}
                        onChange={(e) => setSeats(Number(e.target.value))}
                      />
                    </label>
                    <button
                      disabled={
                        busy || !reason.trim() || seats < 1 || seats > 1000
                      }
                      onClick={() =>
                        void run(async () => {
                          await mutate("/seat-requests", { seats });
                          setMessage(
                            "Заявка создана. До подтверждения места и квоты не изменяются.",
                          );
                        })
                      }
                    >
                      Подать заявку
                    </button>
                    <p className="text-sm">
                      Изменение требует подтверждения прав на места. Принятие
                      приглашений и смена состава не обнуляют расход и не
                      начисляют CU.
                    </p>
                  </div>
                  <ul>
                    {account.seat_requests.map((r) => (
                      <li key={r.request_id}>
                        Заявка <code>{r.request_id}</code> · Мест: {r.seats} ·{" "}
                        {(
                          {
                            pending: "Ожидает подтверждения",
                            applied: "Применена",
                            rejected: "Закрыта",
                          } as Record<string, string>
                        )[r.state] ?? r.state}
                        {r.state === "pending" && (
                          <button
                            disabled={busy || !reason.trim()}
                            onClick={() =>
                              void run(() =>
                                mutate(
                                  "/seat-requests/" + r.request_id + "/cancel",
                                ).then(() => {}),
                              )
                            }
                          >
                            Отменить заявку
                          </button>
                        )}
                      </li>
                    ))}
                  </ul>
                  <button
                    disabled={busy || !reason.trim()}
                    onClick={() =>
                      void run(() =>
                        mutate("/type", { account_type: "mono" }).then(
                          () => {},
                        ),
                      )
                    }
                  >
                    Вернуться к личному доступу
                  </button>
                  <p className="text-sm">
                    Возврат требует одного места, одного участника и отсутствия
                    незавершённых операций.
                  </p>
                  <ul>
                    {account.invitations.map((i) => (
                      <li key={i.invitation_id}>
                        {i.email ?? i.target_subject_id} · до{" "}
                        {new Date(i.expires_at).toLocaleString("ru-RU")} ·{" "}
                        {i.consumed_at
                          ? "Принято"
                          : i.revoked_at
                            ? "Отозвано"
                            : "Ожидает принятия"}
                        {!i.consumed_at && !i.revoked_at && (
                          <button
                            disabled={busy || !reason.trim()}
                            onClick={() =>
                              void run(() =>
                                mutate(
                                  "/invitations/" + i.invitation_id + "/revoke",
                                ).then(() => {}),
                              )
                            }
                          >
                            Отозвать
                          </button>
                        )}
                      </li>
                    ))}
                  </ul>
                </>
              )}
              <button
                className="underline"
                disabled={busy}
                onClick={() =>
                  void run(async () => {
                    await auth.logout();
                    window.location.assign("/login?return_to=%2Faccount");
                  })
                }
              >
                Повторить личный вход для передачи владения
              </button>
            </>
          )}
          <h2>Участники</h2>
          <ul>
            {account.members.map((m) => (
              <li
                key={m.subject_id}
                className="flex flex-wrap gap-3 border-b p-2"
              >
                {m.label} ·{" "}
                {m.account_role === "owner" ? "Владелец" : "Участник"} ·{" "}
                {m.status === "active" ? "Активен" : "Доступ отозван"}
                {account.can_manage &&
                  m.status === "active" &&
                  m.subject_id !== auth.session?.subject_id && (
                    <>
                      <button
                        disabled={busy || !reason.trim()}
                        onClick={() =>
                          void run(() =>
                            mutate("/members/" + m.subject_id + "/remove").then(
                              () => {},
                            ),
                          )
                        }
                      >
                        Удалить участника
                      </button>
                      {m.account_role !== "owner" && (
                        <button
                          disabled={busy || !reason.trim()}
                          onClick={() =>
                            void run(() =>
                              mutate("/ownership-transfer", {
                                target_subject_id: m.subject_id,
                              }).then(() => {}),
                            )
                          }
                        >
                          Передать владение
                        </button>
                      )}
                    </>
                  )}
              </li>
            ))}
          </ul>
          {account.members.some(
            (m) =>
              m.subject_id === auth.session?.subject_id &&
              m.account_role === "member" &&
              m.status === "active",
          ) && (
            <button
              disabled={busy}
              onClick={() =>
                void run(async () => {
                  const result = await teamRequest(
                    "/" +
                      account.account_id +
                      "/members/" +
                      auth.session!.subject_id +
                      "/remove",
                    { ...common(), reason: "Покинуть команду" },
                  );
                  if (result.session_invalidated)
                    window.location.assign("/login?return_to=%2Faccount");
                })
              }
            >
              Покинуть команду
            </button>
          )}
        </>
      )}
    </section>
  );
}
