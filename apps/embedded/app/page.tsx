import Link from "next/link";

export default function Home() {
  return (
    <div>
      <h1 className="text-xl font-semibold mb-2">CISStat TS Analysis</h1>
      <p className="text-neutral-600 mb-4">Раздел портала: анализ временных рядов.</p>
      <Link href="/preprocessing" className="inline-block bg-brand text-white rounded px-4 py-2">
        Перейти к анализу →
      </Link>
    </div>
  );
}
