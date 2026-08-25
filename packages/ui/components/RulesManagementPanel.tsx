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
//   • Редакторы диапазонов и regex-форматов
//   • Кнопки «Применить правила» / «Сбросить к исходным»
//   • Статус загрузки / ошибки

import { useState, useEffect, useCallback } from "react";
import { Settings, Check, RotateCcw, AlertCircle, Loader2, Plus, Trash2 } from "lucide-react";

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
  draft?: boolean;
}

interface FormatRule {
  pattern: string;
  threshold: number;
  description?: string;
  draft?: boolean;
}

interface RulesContent {
  ranges: RangeRule[];
  inclusion?: Record<string, unknown>;
  consistency?: unknown[];
  formats?: Record<string, FormatRule>;
  referential?: unknown[];
  outliers?: Record<string, unknown>;
  sufficiency?: Record<string, unknown>;
}

interface SessionRulesSelection {
  templateId: string;
  overrides: Partial<RulesContent>;
}

const normalizeFormats = (formats: Record<string, unknown> = {}): Record<string, FormatRule> =>
  Object.fromEntries(
    Object.entries(formats).map(([column, value]) => [
      column,
      typeof value === "string"
        ? { pattern: value, threshold: 95 }
        : { ...(value as FormatRule), threshold: (value as FormatRule).threshold ?? 95 },
    ])
  );

const rulesCountLabel = (count: number) => {
  const mod100 = count % 100;
  const mod10 = count % 10;
  const noun = mod100 >= 11 && mod100 <= 14
    ? "правил"
    : mod10 === 1
      ? "правило"
      : mod10 >= 2 && mod10 <= 4
        ? "правила"
        : "правил";
  return `${count} ${noun}`;
};

// ── Компонент ─────────────────────────────────────────────────

export function RulesManagementPanel({ onRulesApplied = () => undefined }: { onRulesApplied?: () => void }) {
  // ── Состояние ──
  const [templates, setTemplates] = useState<Template[]>([]);
  const [selectedTemplate, setSelectedTemplate] = useState<string>("");
  const [rules, setRules] = useState<RulesContent | null>(null);
  const [originalRules, setOriginalRules] = useState<RulesContent | null>(null);
  const [sessionSelection, setSessionSelection] = useState<SessionRulesSelection | null>(null);
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
        setSessionSelection({
          templateId: storedTemplate,
          overrides: sessionData.overrides || {},
        });
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
      const rawContent = data.rules || {};
      const templateContent: RulesContent = {
        ...rawContent,
        ranges: Array.isArray(rawContent.ranges) ? rawContent.ranges : [],
        formats: normalizeFormats(rawContent.formats || {}),
      };
      const activeOverrides = sessionSelection?.templateId === templateId
        ? sessionSelection.overrides
        : {};
      const content: RulesContent = {
        ...templateContent,
        ...activeOverrides,
        ranges: Array.isArray(activeOverrides.ranges)
          ? activeOverrides.ranges
          : templateContent.ranges,
        formats: {
          ...(templateContent.formats || {}),
          ...normalizeFormats((activeOverrides.formats || {}) as Record<string, unknown>),
        },
      };
      setRules(content);
      // Сравниваем изменения с базовым шаблоном: уже сохранённые overrides
      // должны повторно уйти на сервер, иначе простое «Применить» их сотрёт.
      setOriginalRules(JSON.parse(JSON.stringify(templateContent))); // deep copy
    } catch (e) {
      setError("Сервер недоступен. Проверьте подключение к API.");
      setRules(null);
      setOriginalRules(null);
    } finally {
      setLoading(false);
    }
  }, [sessionSelection]);

  // Автозагрузка при смене шаблона
  useEffect(() => {
    if (selectedTemplate && selectedTemplate !== "custom") {
      loadTemplate(selectedTemplate);
    } else if (selectedTemplate === "custom") {
      const activeOverrides = sessionSelection?.templateId === "custom"
        ? sessionSelection.overrides
        : {};
      setRules({
        ...activeOverrides,
        ranges: Array.isArray(activeOverrides.ranges) ? activeOverrides.ranges : [],
        formats: normalizeFormats((activeOverrides.formats || {}) as Record<string, unknown>),
      });
      setOriginalRules({ ranges: [], formats: {} });
      setError(null);
    }
  }, [selectedTemplate, loadTemplate, sessionSelection]);

  // ── Обработчики редактора ──

  const updateRangeMin = (index: number, value: number | null) => {
    if (!rules) return;
    const newRanges = [...rules.ranges];
    newRanges[index] = { ...newRanges[index], min: value };
    setRules({ ...rules, ranges: newRanges });
  };

  const updateRangeMax = (index: number, value: number | null) => {
    if (!rules) return;
    const newRanges = [...rules.ranges];
    newRanges[index] = { ...newRanges[index], max: value };
    setRules({ ...rules, ranges: newRanges });
  };

  const updateRangeKeyword = (index: number, value: string) => {
    if (!rules) return;
    const newRanges = [...rules.ranges];
    const current = newRanges[index];
    const keywords = value.split(",").map((item) => item.trim()).filter(Boolean);
    newRanges[index] = {
      ...current,
      keywords: keywords.length > 0 ? keywords : [""],
      ...(current.draft ? { name: value.trim() ? `${value.trim()} — пользовательский диапазон` : "" } : {}),
    };
    setRules({ ...rules, ranges: newRanges });
  };

  const addRangeRule = () => {
    if (!rules) return;
    setRules({
      ...rules,
      ranges: [
        ...rules.ranges,
        { name: "", keywords: [""], min: null, max: null, draft: true },
      ],
    });
  };

  const removeRangeRule = (index: number) => {
    if (!rules) return;
    setRules({ ...rules, ranges: rules.ranges.filter((_rule, ruleIndex) => ruleIndex !== index) });
  };

  const updateFormatRule = (column: string, patch: Partial<FormatRule>) => {
    if (!rules) return;
    setRules({
      ...rules,
      formats: {
        ...(rules.formats || {}),
        [column]: { ...(rules.formats?.[column] || { pattern: "", threshold: 100 }), ...patch },
      },
    });
  };

  const renameFormatRule = (oldColumn: string, newColumn: string) => {
    if (!rules) return;
    const formats = { ...(rules.formats || {}) };
    const rule = formats[oldColumn];
    delete formats[oldColumn];
    formats[newColumn || oldColumn] = rule;
    setRules({ ...rules, formats });
  };

  const addFormatRule = () => {
    if (!rules) return;
    const formats = { ...(rules.formats || {}) };
    let index = 1;
    while (formats[`__new_${index}`]) index += 1;
    formats[`__new_${index}`] = { pattern: "", threshold: 100, draft: true };
    setRules({ ...rules, formats });
  };

  const removeFormatRule = (column: string) => {
    if (!rules) return;
    const formats = { ...(rules.formats || {}) };
    delete formats[column];
    setRules({ ...rules, formats });
  };

  const serializableFormats = (formats: Record<string, FormatRule> = {}) => Object.fromEntries(
    Object.entries(formats)
      .filter(([column]) => column.trim() && !column.startsWith("__new_"))
      .map(([column, rule]) => [column, {
        pattern: rule.pattern,
        threshold: rule.threshold,
        ...(rule.description ? { description: rule.description } : {}),
      }])
  );

  const serializableRanges = (ranges: RangeRule[] = []) => ranges.map((rule) => ({
    ...(rule.name ? { name: rule.name } : {}),
    keywords: rule.keywords.map((keyword) => keyword.trim()).filter(Boolean),
    min: rule.min,
    max: rule.max,
    ...(rule.description ? { description: rule.description } : {}),
  }));

  const [applyLoading, setApplyLoading] = useState(false);

  const handleApply = async () => {
    if (!rules || !selectedTemplate) return;
    setApplyLoading(true);
    setError(null);
    try {
      const currentFormats = serializableFormats(rules.formats);
      const originalFormats = serializableFormats(originalRules?.formats);
      const currentRanges = serializableRanges(rules.ranges);
      const originalRanges = serializableRanges(originalRules?.ranges);
      const incompleteRange = currentRanges.find(
        (rule) => rule.keywords.length === 0
          || (rule.min === null && rule.max === null)
          || (rule.min !== null && rule.max !== null && rule.min > rule.max)
      );
      if (incompleteRange) {
        setError("Для каждого диапазона задайте колонку и корректные min/max");
        return;
      }
      const incompleteRule = Object.entries(rules.formats || {}).find(
        ([column, rule]) => !column.trim() || column.startsWith("__new_") || !rule.pattern.trim()
      );
      if (incompleteRule) {
        setError("Заполните название колонки и regex во всех правилах форматов");
        return;
      }
      const overrides: Record<string, unknown> = {};
      if (JSON.stringify(currentRanges) !== JSON.stringify(originalRanges)) {
        overrides.ranges = currentRanges;
      }
      if (JSON.stringify(currentFormats) !== JSON.stringify(originalFormats)) {
        overrides.formats = currentFormats;
      }
      const resp = await fetch(`${API_BASE}/v1/session/dataset/validation-rules`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({
          template_id: selectedTemplate === "custom" ? "system" : selectedTemplate,
          overrides,
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

      {/* Системный слой не выдумывает предметные regex, но пользователь
          может добавить их ниже и сохранить как override сессии. */}
      {selectedTemplate === "custom" && !loading && (
        <div className="text-sm text-neutral-500 bg-brand-light/50 rounded px-3 py-2">
          Система распознаёт типы и безопасные диапазоны для цены, года и процентов.
          Другие предметные границы и regex не выводятся из самих значений: добавьте их в редакторах ниже.
        </div>
      )}

      {rules && !loading && (
        <div className="grid grid-cols-2 gap-2 text-xs">
          <span className="rounded bg-neutral-50 px-2 py-1 text-neutral-600">
            Диапазоны: {rulesCountLabel(rules.ranges.length)}
          </span>
          <span className={`rounded px-2 py-1 ${
            Object.keys(rules.formats || {}).length > 0
              ? "bg-green-50 text-green-700"
              : "bg-amber-50 text-amber-700"
          }`}>
            Форматы: {Object.keys(rules.formats || {}).length > 0
              ? rulesCountLabel(Object.keys(rules.formats || {}).length)
              : "не заданы"}
          </span>
        </div>
      )}

      {/* Редактор диапазонов доступен и для шаблона, и для custom-сессии. */}
      {rules && !loading && (
        <div>
          <div className="mb-2 flex items-center justify-between gap-2">
            <h4 className="text-sm font-medium">Редактор диапазонов ({rules.ranges.length} правил)</h4>
            <button
              type="button"
              onClick={addRangeRule}
              className="flex items-center gap-1 rounded border border-brand/40 px-2 py-1 text-xs font-medium text-brand hover:bg-brand/5"
            >
              <Plus size={13} /> Добавить правило диапазона
            </button>
          </div>
          {rules.ranges.length === 0 && (
            <p className="mb-2 rounded bg-amber-50 px-3 py-2 text-xs text-amber-800">
              Эталон диапазонов не задан. Добавьте числовую колонку и хотя бы одну границу.
            </p>
          )}
          <div className="space-y-2">
            {rules.ranges.map((rule, i) => {
              const isDraft = Boolean(rule.draft);
              const ariaSuffix = isDraft ? `правила диапазона ${i + 1}` : (rule.name || String(i + 1));
              return (
                <div key={i} className="rounded-md border border-neutral-200 bg-white px-3 py-2">
                  <div className="mb-2 grid gap-2 sm:grid-cols-[minmax(180px,1fr)_auto]">
                    <input
                      type="text"
                      value={rule.keywords.join(", ")}
                      onChange={(event) => updateRangeKeyword(i, event.target.value)}
                      readOnly={selectedTemplate !== "custom" && !isDraft}
                      aria-label={isDraft ? `Колонка правила диапазона ${i + 1}` : `Ключевые слова ${rule.name || i + 1}`}
                      placeholder="Колонка или ключевые слова"
                      className="min-w-0 rounded border border-neutral-300 px-2 py-1 text-sm read-only:bg-neutral-50 read-only:text-neutral-500"
                    />
                    {(selectedTemplate === "custom" || isDraft) && (
                      <button
                        type="button"
                        onClick={() => removeRangeRule(i)}
                        aria-label={`Удалить правило диапазона ${i + 1}`}
                        className="rounded p-1.5 text-red-600 hover:bg-red-50"
                      >
                        <Trash2 size={15} />
                      </button>
                    )}
                  </div>
                  {rule.name && <p className="mb-1 text-xs font-medium text-neutral-700">{rule.name}</p>}
                  {rule.description && <p className="mb-1.5 text-[11px] text-neutral-500">{rule.description}</p>}
                  <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className="block text-[11px] text-neutral-500">
                      Минимум
                    </label>
                    <input
                      type="number"
                      aria-label={`Минимум ${ariaSuffix}`}
                      value={rule.min ?? ""}
                      onChange={(event) => updateRangeMin(i, event.target.value === "" ? null : Number(event.target.value))}
                      step="0.01"
                      className="w-full rounded border border-neutral-300 px-2 py-1 text-sm focus:outline-none focus:ring-1 focus:ring-brand"
                    />
                  </div>
                  <div>
                    <label className="block text-[11px] text-neutral-500">
                      Максимум
                    </label>
                    <input
                      type="number"
                      aria-label={`Максимум ${ariaSuffix}`}
                      value={rule.max ?? ""}
                      onChange={(event) => updateRangeMax(i, event.target.value === "" ? null : Number(event.target.value))}
                      step="0.01"
                      className="w-full rounded border border-neutral-300 px-2 py-1 text-sm focus:outline-none focus:ring-1 focus:ring-brand"
                    />
                  </div>
                </div>
              </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Редактор форматов доступен и для шаблона, и для custom-сессии. */}
      {rules && !loading && (
        <div>
          <div className="mb-2 flex items-center justify-between gap-2">
            <h4 className="font-medium text-sm">
              Редактор форматов ({Object.keys(rules.formats || {}).length} правил)
            </h4>
            <button
              type="button"
              onClick={addFormatRule}
              className="flex items-center gap-1 rounded border border-brand/40 px-2 py-1 text-xs font-medium text-brand hover:bg-brand/5"
            >
              <Plus size={13} /> Добавить правило формата
            </button>
          </div>
          {Object.keys(rules.formats || {}).length === 0 && (
            <p className="rounded bg-amber-50 px-3 py-2 text-xs text-amber-800">
              Эталон форматов не задан. Добавьте колонку, regex и порог соответствия.
            </p>
          )}
          <div className="space-y-2">
            {Object.entries(rules.formats || {}).map(([column, rule], index) => {
              const isDraft = Boolean(rule.draft);
              return (
                <div key={column} className="rounded-md border border-neutral-200 bg-white px-3 py-2">
                  <div className="grid gap-2 sm:grid-cols-[minmax(110px,0.7fr)_minmax(180px,1.6fr)_90px_auto]">
                    <input
                      type="text"
                      value={column.startsWith("__new_") ? "" : column}
                      onChange={(event) => renameFormatRule(column, event.target.value)}
                      readOnly={selectedTemplate !== "custom" && !isDraft}
                      aria-label={isDraft ? `Колонка правила ${index + 1}` : `Колонка ${column}`}
                      placeholder="Колонка"
                      className="min-w-0 rounded border border-neutral-300 px-2 py-1 text-sm read-only:bg-neutral-50 read-only:text-neutral-500"
                    />
                    <input
                      type="text"
                      value={rule.pattern}
                      onChange={(event) => updateFormatRule(column, { pattern: event.target.value })}
                      aria-label={isDraft ? `Regex правила ${index + 1}` : `Regex для ${column}`}
                      placeholder="Регулярное выражение"
                      className="min-w-0 rounded border border-neutral-300 px-2 py-1 font-mono text-xs"
                    />
                    <input
                      type="number"
                      min="0"
                      max="100"
                      value={rule.threshold}
                      onChange={(event) => updateFormatRule(column, {
                        threshold: Math.min(100, Math.max(0, Number(event.target.value))),
                      })}
                      aria-label={`Порог для ${column.startsWith("__new_") ? `правила ${index + 1}` : column}`}
                      className="rounded border border-neutral-300 px-2 py-1 text-sm"
                    />
                    {(selectedTemplate === "custom" || isDraft) && (
                      <button
                        type="button"
                        onClick={() => removeFormatRule(column)}
                        aria-label={`Удалить правило ${column.startsWith("__new_") ? index + 1 : column}`}
                        className="rounded p-1.5 text-red-600 hover:bg-red-50"
                      >
                        <Trash2 size={15} />
                      </button>
                    )}
                  </div>
                  {rule.description && <p className="mt-1 text-[11px] text-neutral-500">{rule.description}</p>}
                </div>
              );
            })}
          </div>
        </div>
      )}

      {rules && !loading && (
        <div>
          <div className="flex gap-3">
            <button
              onClick={handleApply}
              disabled={applyLoading}
              data-testid={selectedTemplate === "custom" ? "apply-system-rules-btn" : "apply-rules-btn"}
              className="flex-1 flex items-center justify-center gap-1.5 rounded bg-brand px-4 py-2 text-sm font-medium text-white hover:bg-brand/90 disabled:opacity-50"
            >
              {applyLoading ? <Loader2 size={14} className="animate-spin" /> : <Check size={14} />}
              {applyLoading ? "Применение..." : applied ? "Применено!" : "Применить правила"}
            </button>
            <button
              onClick={handleReset}
              data-testid="reset-rules-btn"
              className="flex-1 flex items-center justify-center gap-1.5 rounded border border-neutral-300 bg-white px-4 py-2 text-sm font-medium text-neutral-700 hover:bg-neutral-50"
            >
              <RotateCcw size={14} /> Сбросить к исходным
            </button>
          </div>
          {applied && (
            <p className="mt-2 text-xs text-green-600">
              Правила сессии обновлены, валидация запущена повторно.
            </p>
          )}
        </div>
      )}
    </div>
  );
}
