"use client";
import { useState } from "react";
import { demoRequest, publicDemoCredentials } from "../lib/demo";

// packages/ui/components/DemoEntry.tsx
//
// Виджет входа в демо-режим (AUTH-KABINET-DEMO). Три сценария на тех же
// endpoints, что и раньше (контракт AUTH-16 не менялся):
//   1. Самообслуживание — кнопка «Запустить демо-режим»: prepare + enter
//      с публичной парой из env (см. publicDemoCredentials). Пар форма не
//      требует: пара ходит только в теле POST (AC22), в URL не появляется.
//   2. Кампании организатора — форма «Вход в кампанию»: логин/пароль и
//      (при выдаче) одноразовый код участника; усиленный режим AUTH-16.
//   3. Продолжение — «Продолжить свой демо-доступ»: resume по device-куке,
//      без пары (POST /v1/auth/demo/resume).
// h1 страницы живёт в DemoLanding — здесь один виджет входа на страницу.
// Успех любого сценария → /upload (как раньше). leave — завершение демо
// на устройстве.

export function DemoEntry({ campaignOnly = false }: { campaignOnly?: boolean }) {
  const [login, setLogin] = useState(""),
    [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  const publicPair = publicDemoCredentials();
  async function enter(source: "public" | "form" | "resume") {
    setBusy(true);
    setError("");
    try {
      if (source === "resume") {
        await demoRequest("auth/demo/resume", "POST");
      } else {
        const creds =
          source === "public"
            ? publicDemoCredentials()
            : { login, password };
        if (!creds) throw new Error("Публичный демо-доступ временно недоступен.");
        await demoRequest("auth/demo/prepare", "POST");
        await demoRequest("auth/demo/enter", "POST", {
          login: creds.login,
          password: creds.password,
          ...(source === "form" && code ? { admission_code: code } : {}),
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
    <section
      aria-label="Вход в демо-режим"
      className="mx-auto max-w-lg space-y-4 rounded-xl border border-neutral-200 bg-white p-6 text-neutral-900"
    >
      <p className="text-sm text-neutral-600">
        Каждый участник работает в отдельном временном пространстве. Время и
        лимиты задаёт кампания. Повторный вход сохраняет прежний срок и расход.
        Постоянная история не включена.
      </p>
      {(!campaignOnly || publicPair) && (
      <button
        className="w-full rounded bg-brand px-4 py-2 text-white disabled:opacity-50"
        disabled={busy || !publicPair}
        onClick={() => void enter("public")}
      >
        {busy ? "Проверяем доступ…" : campaignOnly ? "Запустить публичную кампанию" : "Запустить демо-режим"}
      </button>
      )}
      {!publicPair && !campaignOnly && (
        <p className="text-xs text-neutral-500">
          Публичный демо-доступ временно недоступен. Можно войти в кампанию
          организатора ниже.
        </p>
      )}
      <form
        aria-label="Вход в кампанию организатора"
        className="space-y-3 border-t border-neutral-200 pt-4"
        onSubmit={(e) => {
          e.preventDefault();
          void enter("form");
        }}
      >
        <p className="text-sm font-medium text-neutral-700">
          Вход в кампанию организатора
        </p>
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
          Пароль кампании
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
          {busy ? "Проверяем доступ…" : "Войти в кампанию"}
        </button>
      </form>
      <button
        className="underline"
        disabled={busy}
        onClick={() => void enter("resume")}
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
