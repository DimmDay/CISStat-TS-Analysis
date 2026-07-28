import Link from "next/link";

export default function Home() {
  return (
    <div>
      <h1 className="text-2xl font-semibold mb-2">CISStat TS Analysis</h1>
      <p className="text-neutral-600 mb-4 max-w-xl">
        Платформа анализа временных рядов — доступна как веб-приложение и через API
        для интеграции в сторонние ИТ-системы.
      </p>
      <div className="flex gap-3">
        <Link href="/preprocessing" className="bg-brand text-white rounded px-4 py-2 text-sm">
          Открыть в браузере →
        </Link>
        <Link href="/docs" className="border border-neutral-300 rounded px-4 py-2 text-sm">
          Документация API
        </Link>
      </div>
    </div>
  );
}
