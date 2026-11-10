"use client";
import { useEffect, useRef, useState, FormEvent } from "react";
import { useAuth } from "../context/AuthContext";
import {
  authCommand,
  AuthFailure,
  Challenge,
  LoginResult,
  safeReturnTo,
} from "../lib/authClient";
import { authEntryFlags } from "../lib/browserTransport";
type Enrollment = Challenge & { secret: string };
export function LoginScreen({
  returnTo,
  onNavigate,
  onExternalNavigate,
}: {
  returnTo?: unknown;
  onNavigate?: (path: string) => void;
  // AUTH-19: top-level cross-origin hop (corporate IdP); injectable for tests.
  onExternalNavigate?: (url: string) => void;
}) {
  const auth = useAuth(),
    [framed, setFramed] = useState<boolean | null>(null),
    [login, setLogin] = useState(""),
    [password, setPassword] = useState(""),
    [code, setCode] = useState("");
  const [challenge, setChallenge] = useState<Challenge | null>(null),
    [seed, setSeed] = useState(""),
    [codes, setCodes] = useState<string[]>([]),
    [accounts, setAccounts] = useState<{ account_id: string; label: string }[]>(
      [],
    ),
    [account, setAccount] = useState("");
  // AUTH-19: entry availability flags, external selection and the magic-link
  // token. The secret lives only in memory; the URL parameter is cleaned.
  const [flags, setFlags] = useState<{ oidc: boolean; email_trial: boolean } | null>(
    null,
  ),
    [email, setEmail] = useState(""),
    [emailSent, setEmailSent] = useState(false),
    [linkToken, setLinkToken] = useState<string | null>(null),
    [selection, setSelection] = useState<{ token: string; source: "oidc" | "email" } | null>(
      null,
    );
  const [recovery, setRecovery] = useState(false),
    [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [status, setStatus] = useState(""),
    lock = useRef(false),
    mounted = useRef(true);
  const navigate =
    onNavigate ?? ((path: string) => window.location.assign(path));
  const externalNavigate =
    onExternalNavigate ?? ((url: string) => window.location.assign(url));
  useEffect(() => {
    mounted.current = true;
    setFramed(window.top !== window.self);
    return () => {
      mounted.current = false;
    };
  }, []);
  useEffect(() => {
    if (framed) return;
    // OIDC callback and the magic link arrive as query parameters on this
    // page. Reading is read-only; nothing is consumed by a GET — the
    // consumption stays an explicit POST behind the confirm button.
    const params = new URLSearchParams(window.location.search);
    const link = params.get("email_challenge");
    const oidcCode = params.get("code");
    const oidcState = params.get("state");
    if (link || (oidcCode && oidcState)) {
      params.delete("email_challenge");
      params.delete("code");
      params.delete("state");
      const rest = params.toString();
      window.history.replaceState(
        null,
        "",
        window.location.pathname + (rest ? "?" + rest : ""),
      );
    }
    if (link) setLinkToken(link);
    else if (oidcCode && oidcState) {
      setBusy(true);
      authCommand("oidc/callback", { code: oidcCode, state: oidcState })
        .then((value) => {
          if (mounted.current) void handleExternal(value, "oidc");
        })
        .catch((caught) => {
          if (mounted.current)
            setError(
              caught instanceof AuthFailure
                ? caught.message
                : "Не удалось завершить вход. Повторите попытку.",
            );
        })
        .finally(() => {
          if (mounted.current) setBusy(false);
        });
    }
    authEntryFlags()
      .then((value) => {
        if (mounted.current) setFlags(value);
      })
      .catch(() => {
        if (mounted.current) setFlags({ oidc: false, email_trial: false });
      });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [framed]);
  useEffect(() => {
    if (!challenge) return;
    const tick = () => {
      if (Date.now() >= Date.parse(challenge.expires_at)) {
        setChallenge(null);
        setSeed("");
        setCode("");
        setRecovery(false);
        setError("Время подтверждения истекло. Войдите заново.");
      }
    };
    tick();
    const timer = setInterval(tick, 1000);
    return () => clearInterval(timer);
  }, [challenge]);
  async function action(work: () => Promise<void>) {
    if (lock.current) return;
    lock.current = true;
    setBusy(true);
    setError("");
    setStatus("");
    try {
      await work();
    } catch (caught) {
      if (mounted.current)
        setError(
          caught instanceof AuthFailure
            ? caught.message
            : "Не удалось завершить вход. Повторите попытку.",
        );
    } finally {
      lock.current = false;
      if (mounted.current) setBusy(false);
    }
  }
  async function finish() {
    const session = await auth.refresh();
    if (!session) throw new Error("Session unconfirmed");
    navigate(safeReturnTo(returnTo));
  }
  async function result(value: LoginResult) {
    if (!mounted.current) return;
    if (value.status === "challenge_required") {
      setChallenge(value);
      setSeed("");
      setCode("");
      setRecovery(value.purpose === "recovery");
      return;
    }
    if (value.status === "account_required") {
      setAccounts(value.accounts);
      setAccount(value.accounts[0]?.account_id ?? "");
      return;
    }
    setChallenge(null);
    setSeed("");
    setCode("");
    if ("recovery_codes" in value && value.recovery_codes?.length) {
      setCodes(value.recovery_codes);
      await auth.refresh();
    } else await finish();
  }
  async function externalResult(
    value: LoginResult,
    source: "oidc" | "email",
  ) {
    if (!mounted.current) return;
    if (value.status === "account_required") {
      setAccounts(value.accounts);
      setAccount(value.accounts[0]?.account_id ?? "");
      if (value.selection_token)
        setSelection({ token: value.selection_token, source });
      return;
    }
    if (value.status === "challenge_required") {
      // Local MFA for an external identity is not issued in AUTH-19 v1;
      // a challenge here would be unexpected, show a safe status.
      setError("Подтверждение входа недоступно для этого способа.");
      return;
    }
    if (value.status === "linked" || value.status === "email_bound") {
      setEmailSent(false);
      setLinkToken(null);
      setSelection(null);
      setError("");
      setStatus("Готово: изменения учётной записи сохранены.");
      return;
    }
    await result(value);
  }
  function handleExternal(value: LoginResult, source: "oidc" | "email") {
    return externalResult(value, source);
  }
  function startOidc(event: FormEvent) {
    event.preventDefault();
    void action(async () => {
      const value = await authCommand<{ authorize_url: string }>("oidc/start", {
        purpose: "login",
      });
      // Top-level redirect to the corporate IdP; the first-party proxy is
      // not involved in the cross-origin hop.
      externalNavigate(value.authorize_url);
    });
  }
  function startEmail(event: FormEvent) {
    event.preventDefault();
    void action(async () => {
      await authCommand("email/start", { email, purpose: "trial_login" });
      if (mounted.current) {
        setEmailSent(true);
        setEmail("");
      }
    });
  }
  function confirmLink(event: FormEvent) {
    event.preventDefault();
    if (!linkToken) return;
    void action(async () => {
      await handleExternal(
        await authCommand("email/consume", { token: linkToken }),
        "email",
      );
      if (mounted.current) setLinkToken(null);
    });
  }
  function chooseExternal(event: FormEvent) {
    event.preventDefault();
    if (!selection) return;
    void action(async () => {
      await handleExternal(
        await authCommand(
          selection.source === "oidc" ? "oidc/callback" : "email/consume",
          { selection: selection.token, account_id: account },
        ),
        selection.source,
      );
      if (mounted.current) setSelection(null);
    });
  }
  function signIn(event: FormEvent) {
    event.preventDefault();
    const secret = password;
    setPassword("");
    void action(async () => {
      await result(
        await authCommand("login", {
          login,
          password: secret,
          ...(account ? { account_id: account } : {}),
        }),
      );
    });
  }
  function verify(event: FormEvent) {
    event.preventDefault();
    if (!challenge) return;
    const token = challenge.challenge_token,
      entered = code;
    setCode("");
    void action(async () => {
      await result(
        await authCommand(recovery ? "recovery" : "mfa/verify", {
          challenge_token: token,
          code: entered,
        }),
      );
    });
  }
  function reset() {
    setChallenge(null);
    setSeed("");
    setCode("");
    setPassword("");
    setCodes([]);
    setRecovery(false);
    setError("");
    setStatus("");
    setEmailSent(false);
    setLinkToken(null);
    setSelection(null);
  }
  const input =
      "w-full rounded-lg border border-neutral-300 bg-white px-3 py-2 text-neutral-900 focus:outline-none focus:ring-2 focus:ring-brand",
    button = "rounded-lg bg-brand px-4 py-2 text-white disabled:opacity-50";
  if (framed === null) return <p role="status">Подготовка входа…</p>;
  if (framed)
    return (
      <section className="mx-auto max-w-lg space-y-4 rounded-2xl border border-neutral-200 p-6">
        <h1 className="text-2xl font-semibold">Вход в отдельном окне</h1>
        <p>
          Откройте платформу на верхнем уровне браузера для безопасного личного
          входа.
        </p>
        <a
          className="text-brand underline"
          href={
            "/login?return_to=" + encodeURIComponent(safeReturnTo(returnTo))
          }
          target="_top"
        >
          Открыть страницу входа
        </a>
      </section>
    );
  return (
    <section
      className="mx-auto max-w-lg space-y-5 rounded-2xl border border-neutral-200 bg-white p-6 shadow-sm"
      aria-busy={busy}
    >
      <div>
        <h1 className="text-2xl font-semibold text-neutral-900">
          Вход в CISStat DataTime Lab
        </h1>
        <p className="mt-2 text-sm text-neutral-600">
          Личная учётная запись для работы с платформой
        </p>
      </div>
      {error && (
        <p role="alert" className="text-sm text-red-700">
          {error}
        </p>
      )}
      {status && !error && (
        <p role="status" className="text-sm text-neutral-700">
          {status}
        </p>
      )}
      {auth.status === "unavailable" && (
        <p role="status">
          Проверка сессии недоступна. Повторите попытку позднее.
        </p>
      )}
      {codes.length > 0 ? (
        <div className="space-y-4">
          <h2 className="font-semibold">Сохраните резервные коды</h2>
          <p className="text-sm">
            Каждый код можно использовать один раз для восстановления MFA.
            Сохраните их в защищённом месте: повторно посмотреть этот набор
            нельзя.
          </p>
          <ul className="space-y-1 break-all font-mono text-sm">
            {codes.map((value) => (
              <li key={value}>{value}</li>
            ))}
          </ul>
          <button
            className={button}
            disabled={busy}
            onClick={() => {
              setCodes([]);
              void action(finish);
            }}
          >
            Коды сохранены — продолжить
          </button>
        </div>
      ) : challenge ? (
        <div className="space-y-4">
          {challenge.purpose === "enroll_start" ? (
            <>
              <h2 className="font-semibold">Настройка MFA</h2>
              <p>Подключите приложение-аутентификатор, чтобы завершить вход.</p>
              <button
                className={button}
                disabled={busy}
                onClick={() =>
                  void action(async () => {
                    const value = await authCommand<Enrollment>("mfa/enroll", {
                      challenge_token: challenge.challenge_token,
                    });
                    if (mounted.current) {
                      setChallenge(value);
                      setSeed(value.secret);
                    }
                  })
                }
              >
                Получить ключ настройки
              </button>
            </>
          ) : (
            <>
              <h2 className="font-semibold">
                {recovery ? "Восстановление MFA" : "Подтверждение входа"}
              </h2>
              {seed && (
                <label className="block space-y-2 text-sm">
                  Ключ для приложения
                  <input
                    className={input + " font-mono"}
                    value={seed}
                    readOnly
                    autoComplete="off"
                  />
                  <span className="block text-neutral-600">
                    Добавьте ключ в приложение-аутентификатор и введите его
                    шестизначный код.
                  </span>
                </label>
              )}
              <form onSubmit={verify} className="space-y-4">
                <label className="block space-y-2">
                  {recovery ? "Резервный код" : "Код из приложения"}
                  <input
                    className={input}
                    value={code}
                    onChange={(e) => setCode(e.target.value)}
                    autoComplete={recovery ? "off" : "one-time-code"}
                    type={recovery ? "password" : "text"}
                    inputMode={recovery ? "text" : "numeric"}
                    maxLength={recovery ? 64 : 6}
                    pattern={recovery ? undefined : "[0-9]{6}"}
                    required
                    disabled={busy}
                  />
                </label>
                <button className={button} disabled={busy}>
                  {recovery ? "Восстановить MFA" : "Подтвердить вход"}
                </button>
              </form>
              {challenge.purpose === "login" && !recovery && (
                <button
                  className="text-sm text-brand underline"
                  disabled={busy}
                  onClick={() => {
                    setRecovery(true);
                    setCode("");
                  }}
                >
                  Использовать резервный код
                </button>
              )}
            </>
          )}
          <button
            className="block text-sm text-neutral-600 underline"
            disabled={busy}
            onClick={reset}
          >
            Начать заново
          </button>
        </div>
      ) : auth.status === "authenticated" ? (
        <div className="space-y-4">
          <p role="status">Вы вошли в личную учётную запись.</p>
          <a className="block text-brand underline" href="/account">Аккаунт и команда</a>
          <button
            className={button}
            disabled={busy}
            onClick={() => void action(finish)}
          >
            Продолжить
          </button>
          <button
            className="ml-4 text-brand underline"
            disabled={busy}
            onClick={() =>
              void action(async () => {
                await auth.logout();
                reset();
                navigate("/login");
              })
            }
          >
            Выйти
          </button>
        </div>
      ) : selection ? (
        <form onSubmit={chooseExternal} className="space-y-4">
          <h2 className="font-semibold">Выбор аккаунта</h2>
          <label className="block space-y-2">
            Аккаунт
            <select
              className={input}
              value={account}
              onChange={(e) => setAccount(e.target.value)}
            >
              {accounts.map((value) => (
                <option key={value.account_id} value={value.account_id}>
                  {value.label}
                </option>
              ))}
            </select>
            <span className="block text-sm text-neutral-600">
              Вход уже подтверждён; выберите аккаунт для продолжения.
            </span>
          </label>
          <button className={button} disabled={busy}>
            Продолжить
          </button>
        </form>
      ) : linkToken ? (
        <form onSubmit={confirmLink} className="space-y-4">
          <h2 className="font-semibold">Подтверждение входа по ссылке</h2>
          <p className="text-sm text-neutral-600">
            Нажмите кнопку, чтобы подтвердить вход. Само открытие ссылки ничего
            не подтверждает.
          </p>
          <button className={button} disabled={busy}>
            Подтвердить вход
          </button>
        </form>
      ) : emailSent ? (
        <div className="space-y-4">
          <h2 className="font-semibold">Проверьте почту</h2>
          <p className="text-sm text-neutral-600">
            Если адрес зарегистрирован, письмо со ссылкой и кодом отправлено.
            Ссылка и код работают один раз и действительны 15 минут.
          </p>
        </div>
      ) : (
        <>
          <form onSubmit={signIn} className="space-y-4">
            <label className="block space-y-2">
              Логин
              <input
                name="username"
                autoComplete="username"
                className={input}
                value={login}
                onChange={(e) => setLogin(e.target.value)}
                maxLength={128}
                required
                disabled={busy}
              />
            </label>
            <label className="block space-y-2">
              Пароль
              <input
                name="password"
                type="password"
                autoComplete="current-password"
                className={input}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                maxLength={1024}
                required
                disabled={busy}
              />
            </label>
            {accounts.length > 0 && (
              <label className="block space-y-2">
                Аккаунт
                <select
                  className={input}
                  value={account}
                  onChange={(e) => setAccount(e.target.value)}
                >
                  {accounts.map((value) => (
                    <option key={value.account_id} value={value.account_id}>
                      {value.label}
                    </option>
                  ))}
                </select>
                <span className="block text-sm">
                  Выберите аккаунт и повторно введите пароль.
                </span>
              </label>
            )}
            <button
              className={button}
              disabled={busy || auth.status === "loading"}
            >
              Войти
            </button>
          </form>
          {flags?.oidc && (
            <form onSubmit={startOidc} className="space-y-2">
              <button
                type="submit"
                className="w-full rounded-lg border border-neutral-300 bg-white px-4 py-2 text-neutral-900 disabled:opacity-50"
                disabled={busy}
              >
                Войти через корпоративный SSO
              </button>
            </form>
          )}
          {flags?.email_trial && (
            <form onSubmit={startEmail} className="space-y-2">
              <label className="block space-y-2 text-sm">
                Вход по email
                <input
                  type="email"
                  name="email"
                  autoComplete="email"
                  className={input}
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  maxLength={320}
                  required
                  disabled={busy}
                />
              </label>
              <button
                type="submit"
                className="w-full rounded-lg border border-neutral-300 bg-white px-4 py-2 text-neutral-900 disabled:opacity-50"
                disabled={busy}
              >
                Отправить письмо для входа
              </button>
            </form>
          )}
        </>
      )}
    </section>
  );
}
