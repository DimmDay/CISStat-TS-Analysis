"use client";
import { useState } from "react";
import { demoRequest } from "../lib/demo";

export function DemoEntry() {
  const [login, setLogin] = useState(""),
    [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  async function enter(resume = false) {
    setBusy(true);
    setError("");
    try {
      if (resume) await demoRequest("auth/demo/resume", "POST");
      else {
        await demoRequest("auth/demo/prepare", "POST");
        await demoRequest("auth/demo/enter", "POST", {
          login,
          password,
          ...(code ? { admission_code: code } : {}),
        });
      }
      setPassword("");
      window.location.assign("/upload");
    } catch (e) {
      setError(
        e instanceof Error ? e.message : "Нет соединения. Повторите попытку.",
      );
    } finally {
      setBusy(false);
    }
  }
  async function leave() {
    setBusy(true);
    setError("");
    try {
      await demoRequest("auth/demo/leave", "POST");
      setPassword("");
      setLogin("");
      setError(
        "Демо-вход на устройстве завершён. Следующая выдача учитывается отдельно в лимите кампании.",
      );
    } catch (e) {
      setError(
        e instanceof Error ? e.message : "Нет соединения. Повторите попытку.",
      );
    } finally {
      setBusy(false);
    }
  }
  return (
    <section className="mx-auto max-w-lg space-y-4 rounded-xl border border-neutral-200 bg-white p-6 text-neutral-900">
      <h1 className="text-xl font-semibold">Демо-доступ с флаера</h1>
      <p className="text-sm text-neutral-600">
        Каждый участник работает в отдельном временном пространстве. Время и
        лимиты задаёт кампания. Повторный вход сохраняет прежний срок и расход.
        Постоянная история не включена.
      </p>
      <form
        className="space-y-3"
        onSubmit={(e) => {
          e.preventDefault();
          void enter();
        }}
      >
        <label className="block">
          Логин кампании
          <input
            className="block w-full rounded border p-2"
            value={login}
            onChange={(e) => setLogin(e.target.value)}
            autoComplete="username"
            required
            maxLength={128}
          />
        </label>
        <label className="block">
          Пароль с флаера
          <input
            className="block w-full rounded border p-2"
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete="current-password"
            required
            maxLength={1024}
          />
        </label>
        <label className="block">
          Код участника (если выдан)
          <input
            className="block w-full rounded border p-2"
            value={code}
            onChange={(e) => setCode(e.target.value)}
            maxLength={64}
            autoComplete="off"
          />
        </label>
        <button
          className="rounded bg-brand px-4 py-2 text-white"
          disabled={busy}
        >
          {busy ? "Проверяем доступ…" : "Войти в демо"}
        </button>
      </form>
      <button
        className="underline"
        disabled={busy}
        onClick={() => void enter(true)}
      >
        Продолжить свой демо-доступ
      </button>
      <button
        className="block underline"
        disabled={busy}
        onClick={() => void leave()}
      >
        Завершить демо на этом устройстве
      </button>
      {error && <p role="alert">{error}</p>}
      <p className="text-sm">
        <a href="/login" className="underline">
          Личный вход
        </a>{" "}
        ·{" "}
        <a href="/" className="underline">
          На главную
        </a>
      </p>
      <p className="text-xs text-neutral-500">
        Для общего компьютера завершите вход перед передачей следующему
        посетителю. Удаление cookie не устанавливает личность человека; общий
        срок и лимит кампании сохраняются.
      </p>
    </section>
  );
}
