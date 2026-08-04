"use client";

import { useState, useCallback } from "react";
import { useDropzone } from "react-dropzone";
import { toast } from "sonner";
import { useAppShell } from "../context/AppShellContext";
import { Button } from "./Button";

type PreviewData = {
  head: string[][];
  tail: string[][];
};

export function DataUploadForm() {
  const { setActiveDataset, addLogEntry } = useAppShell();
  const [previewData, setPreviewData] = useState<PreviewData | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [fileName, setFileName] = useState<string | null>(null);

  // Определяем URL API в зависимости от окружения
  const apiUrl = typeof window !== "undefined"
    ? (window.location.pathname.startsWith("/embedded")
        ? "/v1/internal/upload"
        : "/v1/public/upload")
    : "/v1/internal/upload";

  const onDrop = useCallback(
    async (acceptedFiles: File[]) => {
      if (acceptedFiles.length === 0) return;
      const file = acceptedFiles[0];
      setFileName(file.name);
      await handleUpload(file);
    },
    []
  );

  const { getRootProps, getInputProps, isDragActive, fileRejections } = useDropzone({
    accept: {
      "text/csv": [".csv"],
      "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": [".xlsx"],
      "application/vnd.ms-excel": [".xls"],
      "application/json": [".json"],
    },
    maxSize: 50 * 1024 * 1024, // 50MB
    onDrop,
    multiple: false,
  });

  const handleUpload = async (file: File) => {
    setIsLoading(true);
    setPreviewData(null);
    const formData = new FormData();
    formData.append("file", file);

    try {
      const response = await fetch(apiUrl, {
        method: "POST",
        body: formData,
      });

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({ detail: "Неизвестная ошибка" }));
        throw new Error(errorData.detail || "Ошибка загрузки файла");
      }

      const data = await response.json();
      // Обновляем контекст
      setActiveDataset({
        name: data.name,
        rows: data.rows,
        sizeLabel: `${(file.size / (1024 * 1024)).toFixed(2)} MB`,
      });
      addLogEntry("INFO", `Файл '${data.name}' загружен: ${data.rows} строк`);

      // Сохраняем предпросмотр
      setPreviewData({
        head: data.preview.head,
        tail: data.preview.tail,
      });
      toast.success("Файл загружен успешно!");
    } catch (error) {
      const message = error instanceof Error ? error.message : "Неизвестная ошибка";
      toast.error(`Ошибка: ${message}`);
      addLogEntry("ERROR", `Ошибка загрузки файла: ${message}`);
    } finally {
      setIsLoading(false);
    }
  };

  // Обработка отклонённых файлов (неверный формат/размер)
  const rejectedFiles = fileRejections.map(({ file, errors }) => ({
    file,
    errors: errors.map((e) => {
      if (e.code === "file-too-large") return "Файл слишком большой (макс. 50MB)";
      if (e.code === "file-invalid-type") return "Неподдерживаемый формат";
      return e.message;
    }),
  }));

  return (
    <div className="max-w-4xl w-full">
      <h2 className="font-semibold mb-4 text-lg">Загрузка данных</h2>

      {/* Зона Drag & Drop */}
      <div
        {...getRootProps()}
        className={`border-2 border-dashed rounded-lg p-8 text-center cursor-pointer transition-colors ${
          isDragActive ? "border-blue-500 bg-blue-50" : "border-neutral-300"
        }`}
      >
        <input {...getInputProps()} data-testid="dropzone-input" />
        <p className="text-neutral-600 mb-2">
          {isDragActive
            ? "Отпустите файл здесь"
            : "Перетащите файл сюда или кликните для выбора"}
        </p>
        <p className="text-sm text-neutral-500">
          Поддерживаемые форматы: .csv, .xlsx, .xls, .json (макс. 50MB)
        </p>
        {fileName && !isLoading && (
          <p className="mt-2 text-sm text-green-600">Выбран: {fileName}</p>
        )}
      </div>

      {/* Ошибки валидации */}
      {rejectedFiles.length > 0 && (
        <div className="mt-4 p-4 bg-red-50 border border-red-200 rounded-lg">
          <h3 className="font-medium text-red-700 mb-2">Ошибки:</h3>
          <ul className="list-disc list-inside text-sm text-red-600">
            {rejectedFiles.map(({ file, errors }) => (
              <li key={file.name}>
                {file.name}: {errors.join(", ")}
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Кнопка загрузки (альтернатива Drag & Drop) */}
      <div className="mt-4">
        <input
          type="file"
          id="file-upload"
          className="hidden"
          accept=".csv,.xlsx,.xls,.json"
          onChange={(e) => {
            const file = e.target.files?.[0];
            if (file) {
              setFileName(file.name);
              handleUpload(file);
            }
          }}
        />
        <Button
          onClick={() => document.getElementById("file-upload")?.click()}
          disabled={isLoading}
        >
          {isLoading ? "Загрузка..." : "Выбрать файл"}
        </Button>
      </div>

      {/* Предпросмотр данных */}
      {previewData && (
        <div className="mt-6">
          <h3 className="font-medium mb-3">Предпросмотр данных</h3>
          <div className="overflow-x-auto">
            <div className="mb-4">
              <h4 className="text-sm font-medium mb-2">Первые 5 строк:</h4>
              <table className="min-w-full border border-neutral-200 rounded-lg overflow-hidden">
                <thead className="bg-neutral-50">
                  <tr>
                    {previewData.head[0]?.map((header, i) => (
                      <th key={i} className="px-4 py-2 text-left text-sm border-b">
                        {header}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {previewData.head.slice(1).map((row, rowIndex) => (
                    <tr key={rowIndex} className="hover:bg-neutral-50">
                      {row.map((cell, cellIndex) => (
                        <td key={cellIndex} className="px-4 py-2 text-sm border-b">
                          {cell}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div>
              <h4 className="text-sm font-medium mb-2">Последние 5 строк:</h4>
              <table className="min-w-full border border-neutral-200 rounded-lg overflow-hidden">
                <thead className="bg-neutral-50">
                  <tr>
                    {previewData.tail[0]?.map((header, i) => (
                      <th key={i} className="px-4 py-2 text-left text-sm border-b">
                        {header}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {previewData.tail.slice(1).map((row, rowIndex) => (
                    <tr key={rowIndex} className="hover:bg-neutral-50">
                      {row.map((cell, cellIndex) => (
                        <td key={cellIndex} className="px-4 py-2 text-sm border-b">
                          {cell}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}