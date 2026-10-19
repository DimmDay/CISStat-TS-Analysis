"use client";

import { useEffect, useId, useRef, useState } from "react";
import { Database, Loader2, PlugZap } from "lucide-react";
import { apiUrl } from "../lib/apiClient";
import { DB_SOURCES, type DbKind, type UploadApiResponse } from "../lib/upload";
import { Button } from "./Button";

interface Props {
  onLoaded: (data: UploadApiResponse) => void | Promise<void>;
  onBusyChange?: (busy: boolean) => void;
  disabled?: boolean;
}
interface Probe { version?: string; latency?: number; }
const inputClass = "w-full rounded-md border border-neutral-300 bg-white px-3 py-2 text-sm text-neutral-900 focus:outline-none focus:ring-2 focus:ring-brand disabled:opacity-60";
const initialSql = (kind: DbKind) => kind === "mssql" ? "SELECT TOP (1000) * FROM your_table" : "SELECT * FROM your_table LIMIT 1000";
const fileSql = (path: string) => `SELECT * FROM '${path.replace(/'/g, "''")}' LIMIT 1000`;

/** Credentials live only in this mounted form, never localStorage/URLs/logs. */
export function DbConnectionForm({ onLoaded, onBusyChange, disabled = false }: Props) {
  const id = useId();
  const [kind, setKind] = useState<DbKind>("postgresql");
  const [host, setHost] = useState("");
  const [port, setPort] = useState("5432");
  const [database, setDatabase] = useState("");
  const [user, setUser] = useState("");
  const [password, setPassword] = useState("");
  const [ssl, setSsl] = useState(false);
  const [path, setPath] = useState("");
  const [sql, setSql] = useState(initialSql("postgresql"));
  const [limit, setLimit] = useState("1000000");
  const [busy, setBusy] = useState<"test" | "load" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [probe, setProbe] = useState<Probe | null>(null);
  const requestRef = useRef<AbortController | null>(null);
  const liveRef = useRef(true);
  const inFlight = useRef(false);
  const customSql = useRef(false);
  const embedded = kind === "duckdb" || kind === "sqlite";

  useEffect(() => {
    liveRef.current = true;
    return () => { liveRef.current = false; requestRef.current?.abort(); onBusyChange?.(false); };
    // onBusyChange is the parent state setter; teardown must run only on unmount.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  function edited() { setProbe(null); setError(null); }
  function selectKind(value: DbKind) {
    edited(); setKind(value); setHost(""); setDatabase(""); setUser(""); setPassword("");
    setPath(""); setSsl(false); setPort(String(DB_SOURCES.find(s => s.id === value)?.port ?? ""));
    customSql.current = false; setSql(initialSql(value));
  }
  function changePath(value: string) {
    edited(); setPath(value);
    if (!customSql.current) setSql(kind === "duckdb" && /\.(csv|parquet)$/i.test(value.trim()) ? fileSql(value.trim()) : initialSql(kind));
  }
  function safeMessage(value: string) {
    return password ? value.split(password).join("****") : value;
  }
  async function submit(operation: "test" | "load") {
    if (inFlight.current || disabled) return;
    setError(null); setProbe(null);
    if (embedded ? !path.trim() : !host.trim() || !database.trim() || !user.trim()) {
      setError(embedded ? "Укажите путь к файлу на сервере API." : "Укажите хост, базу данных и пользователя."); return;
    }
    if (!embedded && (!Number.isInteger(Number(port)) || Number(port) < 1 || Number(port) > 65535)) {
      setError("Порт должен быть целым числом от 1 до 65535."); return;
    }
    if (operation === "load" && (!sql.trim() || !Number.isInteger(Number(limit)) || Number(limit) < 1)) {
      setError("Введите SQL-запрос и положительный целый лимит строк."); return;
    }
    const connection = embedded ? { db_type: kind, path: path.trim() } : {
      db_type: kind, host: host.trim(), port: Number(port), database: database.trim(), user: user.trim(), password, ssl,
    };
    const controller = new AbortController(); requestRef.current = controller;
    inFlight.current = true; setBusy(operation); onBusyChange?.(true);
    try {
      const response = await fetch(apiUrl(`/upload/db/${operation}`), {
        method: "POST", credentials: "include", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(operation === "test" ? { connection } : { connection, sql: sql.trim(), row_limit: Number(limit) }),
        signal: controller.signal,
      });
      if (!liveRef.current || controller.signal.aborted) return;
      const data = await response.json();
      if (!liveRef.current || controller.signal.aborted) return;
      if (!response.ok || operation === "test" && data?.ok !== true) {
        const detail = Array.isArray(data?.detail) ? data.detail.map((d: { msg?: string }) => d.msg ?? "Ошибка параметров").join("; ") : data?.detail;
        throw new Error(safeMessage(typeof detail === "string" ? detail : data?.error ?? `Ошибка API (HTTP ${response.status})`));
      }
      if (operation === "test") {
        setProbe({ version: typeof data.server_version === "string" ? safeMessage(data.server_version) : undefined,
          latency: typeof data.latency_ms === "number" ? data.latency_ms : undefined });
      } else {
        if (!data?.dataset_id || !data.preview || !Array.isArray(data.parse_warnings)) throw new Error("API не вернул загруженный датасет.");
        setPassword("");
        await onLoaded(data as UploadApiResponse);
      }
    } catch (e) {
      if (liveRef.current && !controller.signal.aborted) {
        setError(e instanceof TypeError || e instanceof Error && e.message === "network"
          ? "Не удалось связаться с API — проверьте соединение с сетью."
          : safeMessage(e instanceof Error ? e.message : "Не удалось выполнить запрос к API."));
      }
    } finally {
      inFlight.current = false;
      if (liveRef.current) { setBusy(null); onBusyChange?.(false); }
    }
  }
  const field = (label: string, name: string, value: string, change: (v: string) => void, type = "text") => (
    <label htmlFor={`${id}-${name}`} className="block space-y-1 text-sm text-neutral-700">
      <span>{label}</span>
      <input id={`${id}-${name}`} type={type} value={value} onChange={e => { edited(); change(e.target.value); }}
        className={inputClass} autoComplete={name === "password" ? "new-password" : "off"}
        {...(name === "port" ? { min: 1, max: 65535, step: 1 } : {})}
        {...(name === "limit" ? { min: 1, step: 1 } : {})} />
    </label>
  );
  return (
    <form aria-label="Подключение к базе данных" noValidate onSubmit={e => { e.preventDefault(); submit("load"); }} className="mt-4 space-y-4 rounded-lg border border-neutral-200 bg-neutral-50 p-4">
      <fieldset disabled={disabled || busy !== null} className="space-y-4">
        <label htmlFor={`${id}-kind`} className="block space-y-1 text-sm text-neutral-700">
          <span>Тип БД</span>
          <select id={`${id}-kind`} value={kind} onChange={e => selectKind(e.target.value as DbKind)} className={inputClass}>
            {DB_SOURCES.map(s => <option key={s.id} value={s.id}>{s.label}</option>)}
          </select>
        </label>
        {embedded ? <>
          {field("Путь к файлу", "path", path, changePath)}
          <p className="text-xs text-neutral-500">Файл должен находиться на сервере API. {kind === "duckdb" ? "Форматы: .db, .duckdb, .csv, .parquet." : "Форматы: .db, .sqlite."}</p>
        </> : <>
          <div className="grid gap-3 sm:grid-cols-[2fr_1fr]">{field("Хост", "host", host, setHost)}{field("Порт", "port", port, setPort, "number")}</div>
          <div className="grid gap-3 sm:grid-cols-2">{field("База данных", "database", database, setDatabase)}{field("Пользователь", "user", user, setUser)}</div>
          {field("Пароль", "password", password, setPassword, "password")}
          <label className="flex items-center gap-2 text-sm text-neutral-700"><input type="checkbox" checked={ssl} onChange={e => { edited(); setSsl(e.target.checked); }} className="accent-brand" />TLS (шифрование соединения)</label>
          {kind === "clickhouse" && ssl && <p className="text-xs text-neutral-500">Укажите HTTPS-порт своего ClickHouse-сервера.</p>}
        </>}
        <label htmlFor={`${id}-sql`} className="block space-y-1 text-sm text-neutral-700">
          <span>SQL-запрос</span>
          <textarea id={`${id}-sql`} value={sql} rows={3} spellCheck={false} className={`${inputClass} font-mono`}
            onChange={e => { edited(); customSql.current = true; setSql(e.target.value); }} />
        </label>
        <p className="text-xs text-neutral-500">Только SELECT / WITH. Для небольшой пробы используйте {kind === "mssql" ? "TOP (1000)" : "LIMIT 1000"}. Права пользователя БД должны разрешать только чтение.</p>
        {field("Лимит строк", "limit", limit, setLimit, "number")}
        <div className="flex flex-wrap gap-3">
          <Button type="button" variant="secondary" disabled={disabled || busy !== null} onClick={() => submit("test")}>
            <span className="inline-flex items-center gap-2">{busy === "test" ? <Loader2 size={15} className="animate-spin" aria-hidden="true" /> : <PlugZap size={15} aria-hidden="true" />}Тест подключения</span>
          </Button>
          <Button type="submit" disabled={disabled || busy !== null}>
            <span className="inline-flex items-center gap-2">{busy === "load" ? <Loader2 size={15} className="animate-spin" aria-hidden="true" /> : <Database size={15} aria-hidden="true" />}Загрузить из БД</span>
          </Button>
        </div>
      </fieldset>
      {probe && <p role="status" className="text-sm text-green-700">Подключение успешно{probe.latency != null ? ` (${probe.latency} мс)` : ""}.{probe.version ? ` ${probe.version}` : ""}</p>}
      {error && <p role="alert" className="break-words text-sm text-red-600">{error}</p>}
    </form>
  );
}
