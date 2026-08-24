"use client";

// packages/ui/components/RulesManagementPanel.tsx
//
// Панель «Управление правилами» — полноценная замена
// Streamlit-секции "Управление правилами" (app.py строки 640–744).
// Рендерится в центральном текстовом окне вкладки «Валидация»
// при нажатии кнопки «Управление правилами» внизу степпера.
//
// Содержит:
//   • Селектор шаблона (Custom / Default / FAO Prices / Macro)
//   • Редактор диапазонов (min/max для каждого правила)
//   • Кнопки «Применить правила» / «Сбросить к исходным»
//   • Статус загрузки / ошибки

import { useState, useEffect, useCallback } from "react";
import { Settings, Check, RotateCcw, AlertCircle, Loader2 } from "lucide-react";

// ── API-базовый URL ──
// В проде -- ОТНОСИТЕЛЬНЫЙ путь "/api" (Next.js rewrite проксирует на
// бэкенд, см. apps/standalone/next.config.mjs). НЕ дёргаем NEXT_PUBLIC_API_URL
// напрямую -- иначе обойдём прокси и потеряем first-party cookie
// (см. packages/ui/lib/apiClient.ts::getApiBase для контекста).
import { getApiBase } from "../lib/apiClient";
const API_BASE = getApiBase();

// ── Типы ──────────────────────────────────────────────────────

interface Template {
  id: string;
  label: string;
  description?: string;
}

interface RangeRule {
  name?: string;
  keywords: string[];
  min: number | null;
  max: number | null;
  description?: string;
}

interface RulesContent {
  ranges: RangeRule[];
  inclusion?: Record<string, unknown>;
  consistency?: unknown[];
  formats?: Record<string, unknown>;
  referential?: unknown[];
  outliers?: Record<string, unknown>;
  sufficiency?: Record<string, unknown>;
}

// ── Компонент ─────────────────────────────────────────────────

export function RulesManagementPanel({ onRulesApplied = () => undefined }: { onRulesApplied?: () => void }) {
  // ── Состояние ──
  const [templates, setTemplates] = useState<Template[]>([]);
  const [selectedTemplate, setSelectedTemplate] = useState<string>("");
  const [rules, setRules] = useState<RulesContent | null>(null);
  const [originalRules, setOriginalRules] = useState<RulesContent | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [applied, setApplied] = useState(false);

  // ── Загрузка списка шаблонов и текущего выбора сессии при маунте ──
  useEffect(() => {
    let cancelled = false;
    const hydrate = async () => {
      try {
        const [templatesResponse, sessionResponse] = await Promise.all([
          fetch(`${API_BASE}/v1/internal/rules/templates`),
          fetch(`${API_BASE}/v1/session/dataset/validation-rules`, { credentials: "include" }),
        ]);
        if (!templatesResponse.ok) throw new Error("templates");
        const templatesData = await templatesResponse.json();
        const sessionData = sessionResponse.ok ? await sessionResponse.json() : { template_id: "system" };
        if (cancelled) return;
        const nextTemplates: Template[] = templatesData.templates || [];
        setTemplates(nextTemplates);
        const storedTemplate = sessionData.template_id === "system" ? "custom" : sessionData.template_id;
        setSelectedTemplate(
          nextTemplates.some((template) => template.id === storedTemplate)
            ? storedTemplate
            : nextTemplates[0]?.id || "custom"
        );
      } catch {
        if (cancelled) return;
        setTemplates([
          { id: "custom", label: "Custom (автогенерация)" },
          { id: "default", label: "Default (общий)" },
          { id: "fao_prices", label: "FAO Prices (CIS)" },
          { id: "macro", label: "Macro indicators" },
        ]);
        setSelectedTemplate("custom");
      }
    };
    void hydrate();
    return () => { cancelled = true; };
  }, []);

  // ── Загрузка правил по шаблону ──
  const loadTemplate = useCallback(async (templateId: string) => {
    setLoading(true);
    setError(null);
    setApplied(false);
    try {
      const resp = await fetch(`${API_BASE}/v1/internal/rules/load/${templateId}`);
      if (!resp.ok) {
        const err = await resp.json().catch(() => ({}));
        setError(err.detail || `Ошибка загрузки шаблона "${templateId}"`);
        setRules(null);
        setOriginalRules(null);
        return;
      }
      const data = await resp.json();
      const content: RulesContent = data.rules || { ranges: [] };
      setRules(content);
      setOriginalRules(JSON.parse(JSON.stringify(content))); // deep copy
    } catch (e) {
      setError("Сервер недоступен. Проверьте подключение к API.");
      setRules(null);
      setOriginalRules(null);
    } finally {
      setLoading(false);
    }
  }, []);

  // Автозагрузка при смене шаблона
  useEffect(() => {
    if (selectedTemplate && selectedTemplate !== "custom") {
      loadTemplate(selectedTemplate);
    } else if (selectedTemplate === "custom") {
      // Custom — нужна автогенерация по датасету; пока показываем плейсхолдер
      setRules({ ranges: [] });
      setOriginalRules({ ranges: [] });
      setError(null);
    }
  }, [selectedTemplate, loadTemplate]);

  // ── Обработчики редактора ──

  const updateRangeMin = (index: number, value: number) => {
    if (!rules) return;
    const newRanges = [...rules.ranges];
    newRanges[index] = { ...newRanges[index], min: value };
    setRules({ ...rules, ranges: newRanges });
  };

  const updateRangeMax = (index: number, value: number) => {
    if (!rules) return;
    const newRanges = [...rules.ranges];
    newRanges[index] = { ...newRanges[index], max: value };
    setRules({ ...rules, ranges: newRanges });
  };

  const [applyLoading, setApplyLoading] = useState(false);

  const handleApply = async () => {
    if (!rules || !selectedTemplate) return;
    setApplyLoading(true);
    setError(null);
    try {
      const resp = await fetch(`${API_BASE}/v1/session/dataset/validation-rules`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({
          template_id: selectedTemplate === "custom" ? "system" : selectedTemplate,
          overrides: JSON.stringify(rules.ranges) === JSON.stringify(originalRules?.ranges ?? [])
            ? {}
            : { ranges: rules.ranges },
        }),
      });
      if (!resp.ok) {
        const err = await resp.json().catch(() => ({}));
        setError(err.detail || "Ошибка обновления правил");
        return;
      }
      setApplied(true);
      onRulesApplied();
      setTimeout(() => setApplied(false), 3000);
    } catch {
      setError("Сервер недоступен. Не удалось применить правила.");
    } finally {
      setApplyLoading(false);
    }
  };

  const handleReset = () => {
    if (originalRules) {
      setRules(JSON.parse(JSON.stringify(originalRules)));
      setApplied(false);
    }
  };

  // ── Рендер ──

  return (
    <div className="space-y-4">
      {/* Заголовок */}
      <div className="flex items-center gap-2">
        <Settings size={18} className="text-brand" />
        <h3 className="font-semibold text-base">Управление правилами валидации</h3>
      </div>

      {/* Селектор шаблона */}
      <div>
        <label className="text-xs text-neutral-500 block mb-1">
          Выберите шаблон правил:
        </label>
        <select
          value={selectedTemplate}
          onChange={(e) => setSelectedTemplate(e.target.value)}
          aria-label="Выберите шаблон"
          className="w-full rounded border border-neutral-300 bg-white px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-brand"
        >
          {templates.map((t) => (
            <option key={t.id} value={t.id}>{t.label}</option>
          ))}
        </select>
        {selectedTemplate && templates.find((t) => t.id === selectedTemplate)?.description && (
          <p className="text-[11px] text-neutral-400 mt-1">
            {templates.find((t) => t.id === selectedTemplate)?.description}
          </p>
        )}
      </div>

      <div className="grid gap-2 text-xs text-neutral-600 sm:grid-cols-2">
        <div className="rounded border border-neutral-200 bg-neutral-50 px-3 py-2">
          <span className="font-medium text-neutral-800">Встроенная логика:</span>{" "}
          типы, уникальность, текст, регулярность, достаточность и базовая хронология.
        </div>
        <div className="rounded border border-neutral-200 bg-neutral-50 px-3 py-2">
          <span className="font-medium text-neutral-800">Правила предметной области:</span>{" "}
          форматы, диапазоны, бизнес-логика, допустимые наборы и ссылки.
        </div>
      </div>

      {/* Индикатор загрузки */}
      {loading && (
        <div className="flex items-center gap-2 text-sm text-neutral-500">
          <Loader2 size={16} className="animate-spin" />
          Загрузка правил...
        </div>
      )}

      {/* Ошибка */}
      {error && (
        <div className="flex items-start gap-2 text-sm text-red-600 bg-red-50 rounded px-3 py-2">
          <AlertCircle size={16} className="shrink-0 mt-0.5" />
          <span>{error}</span>
        </div>
      )}

      {/* Custom-плейсхолдер */}
      {selectedTemplate === "custom" && !loading && (
        <div className="space-y-3">
          <div className="text-sm text-neutral-500 bg-brand-light/50 rounded px-3 py-2">
            Системные правила определяют типы, структуру временного ряда и
            безопасные семантические ограничения. Справочники и предметные
            границы из фактических значений не генерируются.
          </div>
          <button
            onClick={handleApply}
            disabled={applyLoading}
            data-testid="apply-system-rules-btn"
            className="w-full flex items-center justify-center gap-1.5 rounded px-4 py-2 text-sm font-medium bg-brand text-white hover:bg-brand/90 transition-colors disabled:opacity-50"
          >
            {applyLoading ? <Loader2 size={14} className="animate-spin" /> : <Check size={14} />}
            {applyLoading ? "Применение..." : "Применить системные правила"}
          </button>
        </div>
      )}

      {/* Редактор диапазонов */}
      {rules && rules.ranges.length > 0 && !loading && (
        <div>
          <h4 className="font-medium text-sm mb-2">Редактор диапазонов ({rules.ranges.length} правил)</h4>
          <div className="space-y-2">
            {rules.ranges.map((rule, i) => (
              <div
                key={i}
                className="border border-neutral-200 rounded-md px-3 py-2 bg-white"
              >
                <div className="flex items-center justify-between mb-1">
                  <span className="text-sm font-medium text-neutral-800">
                    {rule.name || `Правило ${i + 1}`}
                  </span>
                  <span className="text-[11px] text-neutral-400">
                    {rule.keywords.length > 0 ? rule.keywords[0] : "—"}
                  </span>
                </div>
                {rule.description && (
                  <p className="text-[11px] text-neutral-500 mb-1.5">{rule.description}</p>
                )}
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className="text-[11px] text-neutral-500 block">
                      Минимум
                    </label>
                    <input
                      type="number"
                      value={rule.min ?? ""}
                      onChange={(e) => updateRangeMin(i, parseFloat(e.target.value) || 0)}
                      step="0.01"
                      className="w-full rounded border border-neutral-300 px-2 py-1 text-sm focus:outline-none focus:ring-1 focus:ring-brand"
                    />
                  </div>
                  <div>
                    <label className="text-[11px] text-neutral-500 block">
                      Максимум
                    </label>
                    <input
                      type="number"
                      value={rule.max ?? ""}
                      onChange={(e) => updateRangeMax(i, parseFloat(e.target.value) || 0)}
                      step="0.01"
                      className="w-full rounded border border-neutral-300 px-2 py-1 text-sm focus:outline-none focus:ring-1 focus:ring-brand"
                    />
                  </div>
                </div>
              </div>
            ))}
          </div>

          {/* Кнопки управления */}
          <div className="flex gap-3 mt-4">
            <button
              onClick={handleApply}
              disabled={applyLoading}
              data-testid="apply-rules-btn"
              className="flex-1 flex items-center justify-center gap-1.5 rounded px-4 py-2 text-sm font-medium bg-brand text-white hover:bg-brand/90 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {applyLoading ? <Loader2 size={14} className="animate-spin" /> : <Check size={14} />}
              {applyLoading ? "Применение..." : applied ? "Применено!" : "Применить правила"}
            </button>
            <button
              onClick={handleReset}
              data-testid="reset-rules-btn"
              className="flex-1 flex items-center justify-center gap-1.5 rounded px-4 py-2 text-sm font-medium border border-neutral-300 bg-white text-neutral-700 hover:bg-neutral-50 transition-colors"
            >
              <RotateCcw size={14} />
              Сбросить к исходным
            </button>
          </div>

          {/* Статус применения */}
          {applied && (
            <p className="text-xs text-green-600 mt-2">
              Правила сессии обновлены, валидация запущена повторно.
            </p>
          )}
        </div>
      )}

      {/* Нет правил */}
      {rules && rules.ranges.length === 0 && !loading && selectedTemplate !== "custom" && !error && (
        <p className="text-sm text-neutral-500 italic">
          Нет доступных правил диапазонов в этом шаблоне.
        </p>
      )}
    </div>
  );
}
