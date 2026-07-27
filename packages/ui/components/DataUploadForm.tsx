"use client";

// packages/ui/components/DataUploadForm.tsx
//
// Перенесено из постоянной боковой панели -- это ДЕЙСТВИЕ (выбор
// источника, загрузка файла), а не постоянный контекст, поэтому живёт
// только на странице "Загрузка", а не на каждой странице приложения.

import { useState } from "react";
import { useAppShell } from "../context/AppShellContext";
import { Button } from "./Button";

type Source = "file" | "db";

export function DataUploadForm() {
  const { setActiveDataset } = useAppShell();
  const [source, setSource] = useState<Source>("file");
  const [fileName, setFileName] = useState<string | null>(null);

  const handleMockUpload = () => {
    // ЗАМЕНИТЬ: реальная загрузка через apps/api (/v1/.../upload или прямой
    // POST на эндпоинт паспорта/валидации) -- сейчас просто моковые данные,
    // как и остальная часть прототипа.
    const mockName = fileName ?? "train.csv";
    setActiveDataset({ name: mockName, rows: 200, sizeLabel: "2.0 MB" });
  };

  return (
    <div className="max-w-md">
      <h2 className="font-semibold mb-3">Источник данных</h2>

      <div className="flex gap-4 mb-4 text-sm">
        <label className="flex items-center gap-2">
          <input type="radio" checked={source === "file"} onChange={() => setSource("file")} />
          Файл .xlsx, .xls, .csv, .json
        </label>
        <label className="flex items-center gap-2">
          <input type="radio" checked={source === "db"} onChange={() => setSource("db")} />
          База данных (SQL)
        </label>
      </div>

      {source === "file" ? (
        <div className="border-2 border-dashed border-neutral-300 rounded-lg p-6 text-center mb-4">
          <input
            type="file"
            id="file-upload"
            className="hidden"
            onChange={(e) => setFileName(e.target.files?.[0]?.name ?? null)}
          />
          <label htmlFor="file-upload" className="cursor-pointer text-sm text-neutral-600">
            {fileName ? `Выбран: ${fileName}` : "Перетащите файл сюда или нажмите для выбора"}
          </label>
        </div>
      ) : (
        <p className="text-sm text-neutral-500 mb-4">(форма подключения к БД -- заглушка)</p>
      )}

      <Button onClick={handleMockUpload}>Загрузить файл</Button>
    </div>
  );
}
