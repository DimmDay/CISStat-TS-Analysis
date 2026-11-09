"use client";
import { useEffect, useRef, useState } from "react";
import { demoRequest } from "../lib/demo";
export function DemoLimits() {
  const [limits, setLimits] = useState<{
      expires_at: string;
      requests_remaining: number;
      analyses_remaining: number;
    } | null>(null),
    [error, setError] = useState("");
  const known = useRef(false);
  useEffect(() => {
    let live = true;
    const read = () =>
      demoRequest("auth/demo/me")
        .then(() => {
          known.current = true;
          return demoRequest("auth/demo/limits");
        })
        .then((r) => {
          if (live) {
            setLimits(r);
            setError("");
          }
        })
        .catch((e) => {
          if (live) {
            setLimits(null);
            if (known.current) setError(e.message);
          }
        });
    void read();
    const timer = setInterval(read, 30000);
    return () => {
      live = false;
      clearInterval(timer);
    };
  }, []);
  if (!known.current && !limits && !error) return null;
  return (
    <aside className="border-b p-2 text-sm" aria-label="Лимиты демо">
      {error ||
        (limits
          ? `Демо до ${new Date(limits.expires_at).toLocaleString("ru-RU")}. Осталось исследований: ${limits.analyses_remaining}; научных запросов: ${limits.requests_remaining}.`
          : "Проверяем лимиты демо…")}{" "}
      <a className="underline" href="/demo">
        Демо-доступ
      </a>
    </aside>
  );
}
