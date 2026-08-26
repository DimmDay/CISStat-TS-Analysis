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
//   • Редакторы диапазонов, regex-форматов и типизированной логики
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
  editorId?: string;
}

interface ConsistencyRule {
  name?: string;
  type?: string;
  columns?: string[];
  operator?: string;
  group_column?: string;
  description?: string;
  condition?: string;
  draft?: boolean;
  [key: string]: unknown;
}

interface InclusionRule {
  allowed_values: Array<string | number | boolean>;
  default_value?: string | number | boolean;
  draft?: boolean;
  editorId?: string;
  allowedDraft?: string;
}

interface ReferentialRule {
  name: string;
  child_column: string;
  allowed_values: Array<string | number | boolean>;
  default_value?: string | number | boolean;
  draft?: boolean;
  editorId?: string;
  allowedDraft?: string;
}

interface TextQualityRule {
  min_length?: number;
  max_length?: number;
  garbage_chars?: string[];
  allowed_patterns?: Record<string, string>;
  garbageDraft?: string;
}

interface RegularityRule {
  date_column?: string;
  entity_column?: string;
  frequency?: string;
  gap_threshold_multiplier?: number;
}

interface RulesContent {
  ranges: RangeRule[];
  inclusion?: Record<string, InclusionRule>;
  consistency?: ConsistencyRule[];
  uniqueness?: { composite_key?: string[]; description?: string };
  formats?: Record<string, FormatRule>;
  referential?: ReferentialRule[];
  text_quality?: TextQualityRule;
  regularity?: RegularityRule;
  outliers?: Record<string, unknown>;
  sufficiency?: Record<string, unknown>;
}

interface SessionRulesSelection {
  templateId: string;
  overrides: Partial<RulesContent>;
}

const normalizeFormats = (formats: Record<string, unknown> = {}): Record<string, FormatRule> =>
  Object.fromEntries(Object.entries(formats).map(([column, value]) => {
    const normalized: FormatRule = typeof value === "string"
        ? { pattern: value, threshold: 95 }
        : { ...(value as FormatRule), threshold: (value as FormatRule).threshold ?? 95 };
    return [column, {
      ...normalized,
      editorId: normalized.editorId || `format:${column}`,
    }];
  }));

const normalizeInclusion = (inclusion: Record<string, unknown> = {}): Record<string, InclusionRule> =>
  Object.fromEntries(Object.entries(inclusion).map(([column, value]) => {
    const normalized: InclusionRule = Array.isArray(value)
      ? { allowed_values: value }
      : { ...(value as InclusionRule), allowed_values: Array.isArray((value as InclusionRule)?.allowed_values) ? (value as InclusionRule).allowed_values : [] };
    return [column, {
      ...normalized,
      editorId: normalized.editorId || `inclusion:${column}`,
      allowedDraft: normalized.allowed_values.map(String).join(", "),
    }];
  }));

const normalizeReferential = (referential: unknown[] = []): ReferentialRule[] =>
  referential.filter((value): value is Record<string, unknown> => Boolean(value) && typeof value === "object").map((value, index) => {
    const allowedValues = Array.isArray(value.allowed_values)
      ? value.allowed_values as Array<string | number | boolean>
      : [];
    return {
      name: String(value.name || ""),
      child_column: String(value.child_column || value.column || ""),
      allowed_values: allowedValues,
      ...(value.default_value !== undefined ? { default_value: value.default_value as string | number | boolean } : {}),
      editorId: String(value.editorId || `referential:${index}:${value.child_column || value.column || "rule"}`),
      allowedDraft: allowedValues.map(String).join(", "),
    };
  });

const normalizeTextQuality = (value: unknown): TextQualityRule => {
  const raw = value && typeof value === "object" ? value as TextQualityRule : {};
  const garbageChars = Array.isArray(raw.garbage_chars) ? raw.garbage_chars.map(String) : [];
  return {
    ...raw,
    garbage_chars: garbageChars,
    allowed_patterns: raw.allowed_patterns && typeof raw.allowed_patterns === "object" ? raw.allowed_patterns : {},
    garbageDraft: garbageChars.join(", "),
  };
};

let formatDraftSequence = 0;
let inclusionDraftSequence = 0;
let referentialDraftSequence = 0;

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
  // Храним пользовательский ввод отдельно от нормализованного массива:
  // иначе промежуточные "," и пробел исчезают при каждом onChange.
  const [uniquenessKeyDraft, setUniquenessKeyDraft] = useState("");
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
        inclusion: normalizeInclusion(rawContent.inclusion || {}),
        referential: normalizeReferential(rawContent.referential || []),
        text_quality: normalizeTextQuality(rawContent.text_quality),
        consistency: Array.isArray(rawContent.consistency) ? rawContent.consistency : [],
        uniqueness: rawContent.uniqueness || {},
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
        consistency: Array.isArray(activeOverrides.consistency)
          ? activeOverrides.consistency as ConsistencyRule[]
          : templateContent.consistency,
        uniqueness: activeOverrides.uniqueness
          ? activeOverrides.uniqueness as RulesContent["uniqueness"]
          : templateContent.uniqueness,
        formats: {
          ...(templateContent.formats || {}),
          ...normalizeFormats((activeOverrides.formats || {}) as Record<string, unknown>),
        },
        inclusion: {
          ...(templateContent.inclusion || {}),
          ...normalizeInclusion((activeOverrides.inclusion || {}) as Record<string, unknown>),
        },
        referential: Array.isArray(activeOverrides.referential)
          ? normalizeReferential(activeOverrides.referential)
          : templateContent.referential,
        text_quality: activeOverrides.text_quality
          ? normalizeTextQuality({
              ...(templateContent.text_quality || {}),
              ...(activeOverrides.text_quality as TextQualityRule),
              allowed_patterns: {
                ...(templateContent.text_quality?.allowed_patterns || {}),
                ...((activeOverrides.text_quality as TextQualityRule).allowed_patterns || {}),
              },
            })
          : templateContent.text_quality,
        regularity: activeOverrides.regularity
          ? {
              ...(templateContent.regularity || {}),
              ...(activeOverrides.regularity as RegularityRule),
            }
          : templateContent.regularity,
      };
      setRules(content);
      setUniquenessKeyDraft(content.uniqueness?.composite_key?.join(", ") || "");
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
      const content: RulesContent = {
        ...activeOverrides,
        ranges: Array.isArray(activeOverrides.ranges) ? activeOverrides.ranges : [],
        formats: normalizeFormats((activeOverrides.formats || {}) as Record<string, unknown>),
        inclusion: normalizeInclusion((activeOverrides.inclusion || {}) as Record<string, unknown>),
        referential: normalizeReferential(Array.isArray(activeOverrides.referential) ? activeOverrides.referential : []),
        text_quality: activeOverrides.text_quality
          ? normalizeTextQuality(activeOverrides.text_quality)
          : undefined,
        consistency: Array.isArray(activeOverrides.consistency)
          ? activeOverrides.consistency as ConsistencyRule[]
          : [],
        uniqueness: activeOverrides.uniqueness as RulesContent["uniqueness"] || {},
      };
      setRules(content);
      setUniquenessKeyDraft(content.uniqueness?.composite_key?.join(", ") || "");
      setOriginalRules({ ranges: [], formats: {}, consistency: [], uniqueness: {}, inclusion: {}, referential: [], text_quality: undefined, regularity: undefined });
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
    formats[`__new_${index}`] = {
      pattern: "",
      threshold: 100,
      draft: true,
      editorId: `format-draft:${++formatDraftSequence}`,
    };
    setRules({ ...rules, formats });
  };

  const removeFormatRule = (column: string) => {
    if (!rules) return;
    const formats = { ...(rules.formats || {}) };
    delete formats[column];
    setRules({ ...rules, formats });
  };

  const addConsistencyRule = () => {
    if (!rules) return;
    setRules({
      ...rules,
      consistency: [
        ...(rules.consistency || []),
        { name: "", type: "chronology", columns: [""], group_column: "", draft: true },
      ],
    });
  };

  const updateConsistencyRule = (index: number, patch: Partial<ConsistencyRule>) => {
    if (!rules) return;
    const next = [...(rules.consistency || [])];
    const current = next[index];
    const nextType = patch.type || current.type;
    next[index] = {
      ...current,
      ...patch,
      ...(patch.type ? {
        columns: nextType === "chronology"
          ? [current.columns?.[0] || ""]
          : [current.columns?.[0] || "", current.columns?.[1] || ""],
        ...(nextType === "chronology" ? { operator: undefined } : { group_column: undefined, operator: current.operator || "<=" }),
      } : {}),
    };
    setRules({ ...rules, consistency: next });
  };

  const updateConsistencyColumn = (index: number, columnIndex: number, value: string) => {
    if (!rules) return;
    const current = rules.consistency?.[index];
    if (!current) return;
    const columns = [...(current.columns || [])];
    columns[columnIndex] = value;
    updateConsistencyRule(index, { columns });
  };

  const removeConsistencyRule = (index: number) => {
    if (!rules) return;
    setRules({
      ...rules,
      consistency: (rules.consistency || []).filter((_rule, ruleIndex) => ruleIndex !== index),
    });
  };

  const updateInclusionRule = (column: string, patch: Partial<InclusionRule>) => {
    if (!rules) return;
    setRules({
      ...rules,
      inclusion: {
        ...(rules.inclusion || {}),
        [column]: { ...(rules.inclusion?.[column] || { allowed_values: [] }), ...patch },
      },
    });
  };

  const renameInclusionRule = (oldColumn: string, newColumn: string) => {
    if (!rules) return;
    const inclusion = { ...(rules.inclusion || {}) };
    const rule = inclusion[oldColumn];
    delete inclusion[oldColumn];
    inclusion[newColumn || oldColumn] = rule;
    setRules({ ...rules, inclusion });
  };

  const addInclusionRule = () => {
    if (!rules) return;
    const inclusion = { ...(rules.inclusion || {}) };
    let index = 1;
    while (inclusion[`__new_${index}`]) index += 1;
    inclusion[`__new_${index}`] = {
      allowed_values: [], allowedDraft: "", draft: true,
      editorId: `inclusion-draft:${++inclusionDraftSequence}`,
    };
    setRules({ ...rules, inclusion });
  };

  const removeInclusionRule = (column: string) => {
    if (!rules) return;
    const inclusion = { ...(rules.inclusion || {}) };
    delete inclusion[column];
    setRules({ ...rules, inclusion });
  };

  const updateReferentialRule = (index: number, patch: Partial<ReferentialRule>) => {
    if (!rules) return;
    const referential = [...(rules.referential || [])];
    referential[index] = { ...referential[index], ...patch };
    setRules({ ...rules, referential });
  };

  const addReferentialRule = () => {
    if (!rules) return;
    setRules({
      ...rules,
      referential: [
        ...(rules.referential || []),
        {
          name: "",
          child_column: "",
          allowed_values: [],
          allowedDraft: "",
          draft: true,
          editorId: `referential-draft:${++referentialDraftSequence}`,
        },
      ],
    });
  };

  const removeReferentialRule = (index: number) => {
    if (!rules) return;
    setRules({
      ...rules,
      referential: (rules.referential || []).filter((_rule, ruleIndex) => ruleIndex !== index),
    });
  };

  const updateTextQuality = (patch: Partial<TextQualityRule>) => {
    if (!rules) return;
    setRules({ ...rules, text_quality: { ...(rules.text_quality || {}), ...patch } });
  };

  const updateRegularity = (patch: Partial<RegularityRule>) => {
    if (!rules) return;
    setRules({ ...rules, regularity: { ...(rules.regularity || {}), ...patch } });
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

  const serializableInclusion = (inclusion: Record<string, InclusionRule> = {}) => Object.fromEntries(
    Object.entries(inclusion)
      .filter(([column]) => column.trim() && !column.startsWith("__new_"))
      .map(([column, rule]) => [column, {
        allowed_values: rule.allowed_values,
        ...(rule.default_value !== undefined && String(rule.default_value).trim() !== ""
          ? { default_value: rule.default_value }
          : {}),
      }])
  );

  const serializableReferential = (referential: ReferentialRule[] = []) => referential.map((rule) => ({
    name: rule.name.trim(),
    child_column: rule.child_column.trim(),
    allowed_values: rule.allowed_values,
    ...(rule.default_value !== undefined && String(rule.default_value).trim() !== ""
      ? { default_value: rule.default_value }
      : {}),
  }));

  const serializableTextQuality = (rule?: TextQualityRule) => {
    if (!rule) return {};
    return {
      ...(rule.min_length !== undefined ? { min_length: rule.min_length } : {}),
      ...(rule.max_length !== undefined ? { max_length: rule.max_length } : {}),
      ...(rule.garbage_chars !== undefined ? { garbage_chars: rule.garbage_chars } : {}),
      ...(rule.allowed_patterns && Object.keys(rule.allowed_patterns).length > 0
        ? { allowed_patterns: rule.allowed_patterns }
        : {}),
    };
  };

  const serializableRegularity = (rule?: RegularityRule) => {
    if (!rule) return {};
    return {
      ...(rule.date_column?.trim() ? { date_column: rule.date_column.trim() } : {}),
      ...(rule.entity_column?.trim() ? { entity_column: rule.entity_column.trim() } : {}),
      ...(rule.frequency?.trim() ? { frequency: rule.frequency.trim() } : {}),
      ...(rule.gap_threshold_multiplier !== undefined
        ? { gap_threshold_multiplier: rule.gap_threshold_multiplier }
        : {}),
    };
  };

  const serializableConsistency = (consistency: ConsistencyRule[] = []) => consistency.map((rule) => {
    const { draft: _draft, ...serialized } = rule;
    const columns = (rule.columns || []).map((column) => column.trim()).filter(Boolean);
    return {
      ...serialized,
      name: rule.name?.trim(),
      type: rule.type,
      columns,
      ...(rule.type === "chronology"
        ? { ...(rule.group_column?.trim() ? { group_column: rule.group_column.trim() } : {}) }
        : {}),
      ...(rule.type === "comparison" ? { operator: rule.operator || "<=" } : {}),
    };
  });

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
      const currentConsistency = serializableConsistency(rules.consistency);
      const originalConsistency = serializableConsistency(originalRules?.consistency);
      const currentInclusion = serializableInclusion(rules.inclusion);
      const originalInclusion = serializableInclusion(originalRules?.inclusion);
      const currentReferential = serializableReferential(rules.referential);
      const originalReferential = serializableReferential(originalRules?.referential);
      const currentTextQuality = serializableTextQuality(rules.text_quality);
      const originalTextQuality = serializableTextQuality(originalRules?.text_quality);
      const currentRegularity = serializableRegularity(rules.regularity);
      const originalRegularity = serializableRegularity(originalRules?.regularity);
      const normalizedUniquenessKey = uniquenessKeyDraft
        .split(",")
        .map((column) => column.trim())
        .filter(Boolean);
      const currentUniqueness = uniquenessKeyDraft.trim() || (rules.uniqueness && "composite_key" in rules.uniqueness)
        ? { ...rules.uniqueness, composite_key: normalizedUniquenessKey }
        : {};
      const originalUniqueness = originalRules?.uniqueness?.composite_key?.length
        ? { ...originalRules.uniqueness, composite_key: originalRules.uniqueness.composite_key.map((column) => column.trim()).filter(Boolean) }
        : {};
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
      const incompleteConsistency = currentConsistency.find((rule) =>
        !rule.name
        || !rule.type
        || (rule.type === "chronology" && rule.columns.length !== 1)
        || (rule.type === "comparison" && (rule.columns.length !== 2 || !rule.operator))
      );
      if (incompleteConsistency) {
        setError("Заполните название, тип и колонки во всех правилах логики");
        return;
      }
      const incompleteInclusion = Object.entries(rules.inclusion || {}).find(
        ([column, rule]) => !column.trim() || column.startsWith("__new_") || rule.allowed_values.length === 0
          || (rule.default_value !== undefined && String(rule.default_value).trim() !== "" && !rule.allowed_values.some((value) => String(value) === String(rule.default_value)))
      );
      if (incompleteInclusion) {
        setError("Для каждого набора задайте колонку, допустимые значения и корректное значение по умолчанию");
        return;
      }
      const referentialChanged = JSON.stringify(currentReferential) !== JSON.stringify(originalReferential);
      if (referentialChanged) {
        const incompleteReferential = currentReferential.find((rule) =>
          !rule.name
          || !rule.child_column
          || rule.allowed_values.length === 0
          || (rule.default_value !== undefined
            && !rule.allowed_values.some((value) => String(value) === String(rule.default_value)))
        );
        if (incompleteReferential) {
          setError("Для каждой связи задайте название, дочернюю колонку, родительские ключи и корректный default");
          return;
        }
      }
      const overrides: Record<string, unknown> = {};
      if (JSON.stringify(currentRanges) !== JSON.stringify(originalRanges)) {
        overrides.ranges = currentRanges;
      }
      if (JSON.stringify(currentFormats) !== JSON.stringify(originalFormats)) {
        overrides.formats = currentFormats;
      }
      if (JSON.stringify(currentConsistency) !== JSON.stringify(originalConsistency)) {
        overrides.consistency = currentConsistency;
      }
      if (JSON.stringify(currentUniqueness) !== JSON.stringify(originalUniqueness)) {
        overrides.uniqueness = currentUniqueness;
      }
      if (JSON.stringify(currentInclusion) !== JSON.stringify(originalInclusion)) {
        overrides.inclusion = currentInclusion;
      }
      if (referentialChanged) {
        overrides.referential = currentReferential;
      }
      if (JSON.stringify(currentTextQuality) !== JSON.stringify(originalTextQuality)) {
        overrides.text_quality = currentTextQuality;
      }
      if (JSON.stringify(currentRegularity) !== JSON.stringify(originalRegularity)) {
        overrides.regularity = currentRegularity;
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
      setRules((current) => current ? {
        ...current,
        uniqueness: currentUniqueness,
        inclusion: normalizeInclusion(currentInclusion),
        referential: normalizeReferential(currentReferential),
        text_quality: Object.keys(currentTextQuality).length > 0
          ? normalizeTextQuality(currentTextQuality)
          : undefined,
        regularity: Object.keys(currentRegularity).length > 0
          ? currentRegularity
          : undefined,
      } : current);
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
      setUniquenessKeyDraft(originalRules.uniqueness?.composite_key?.join(", ") || "");
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
          Система распознаёт типы, безопасные диапазоны и базовую хронологию по временной колонке.
          Предметные границы, regex и связи между колонками не выводятся из самих значений: добавьте их в редакторах ниже.
        </div>
      )}

      {rules && !loading && (
        <div className="grid gap-2 text-xs sm:grid-cols-2 lg:grid-cols-6">
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
          <span className={`rounded px-2 py-1 ${
            (rules.consistency || []).length > 0
              ? "bg-green-50 text-green-700"
              : "bg-amber-50 text-amber-700"
          }`}>
            Логика: {(rules.consistency || []).length > 0
              ? rulesCountLabel((rules.consistency || []).length)
              : "не задана"}
          </span>
          <span className={`rounded px-2 py-1 ${
            rules.uniqueness?.composite_key?.length
              ? "bg-green-50 text-green-700"
              : "bg-neutral-50 text-neutral-600"
          }`}>
            Уникальность: {rules.uniqueness?.composite_key?.length
              ? rules.uniqueness.composite_key.join(" + ")
              : "системный ключ"}
          </span>
          <span className={`rounded px-2 py-1 ${
            Object.keys(rules.inclusion || {}).length
              ? "bg-green-50 text-green-700"
              : "bg-amber-50 text-amber-700"
          }`}>
            Наборы: {Object.keys(rules.inclusion || {}).length
              ? rulesCountLabel(Object.keys(rules.inclusion || {}).length)
              : "не заданы"}
          </span>
          <span className={`rounded px-2 py-1 ${
            (rules.referential || []).length
              ? "bg-green-50 text-green-700"
              : "bg-amber-50 text-amber-700"
          }`}>
            Связи: {(rules.referential || []).length
              ? rulesCountLabel((rules.referential || []).length)
              : "не заданы"}
          </span>
        </div>
      )}

      {/* Редактор диапазонов доступен и для шаблона, и для custom-сессии. */}
      {rules && !loading && (
        <div>
          <h4 className="mb-2 text-sm font-medium">Редактор уникальности</h4>
          <div className="rounded-md border border-neutral-200 bg-white px-3 py-2">
            <label className="mb-1 block text-[11px] text-neutral-500" htmlFor="uniqueness-composite-key">
              Составной ключ (колонки через запятую)
            </label>
            <input
              id="uniqueness-composite-key"
              type="text"
              value={uniquenessKeyDraft}
              onChange={(event) => setUniquenessKeyDraft(event.target.value)}
              placeholder="Например: Country, Year"
              className="w-full rounded border border-neutral-300 px-2 py-1 text-sm"
            />
            <p className="mt-1 text-[11px] text-neutral-500">
              Пустое поле включает системный выбор: сущность + время, а при отсутствии времени — полные строки.
            </p>
          </div>
        </div>
      )}

      {rules && !loading && (
        <div>
          <div className="mb-2 flex items-center justify-between gap-2">
            <h4 className="text-sm font-medium">Редактор ссылочной целостности ({(rules.referential || []).length} правил)</h4>
            <button type="button" onClick={addReferentialRule} className="flex items-center gap-1 rounded border border-brand/40 px-2 py-1 text-xs font-medium text-brand hover:bg-brand/5">
              <Plus size={13} /> Добавить связь
            </button>
          </div>
          {(rules.referential || []).length === 0 && (
            <p className="mb-2 rounded bg-amber-50 px-3 py-2 text-xs text-amber-800">
              Правила ссылочной целостности не заданы. Добавьте дочернюю колонку и эталон родительских ключей.
            </p>
          )}
          <div className="space-y-2">
            {(rules.referential || []).map((rule, index) => {
              const isDraft = Boolean(rule.draft);
              return (
                <div key={rule.editorId || index} className="rounded-md border border-neutral-200 bg-white px-3 py-2">
                  <div className="grid gap-2 sm:grid-cols-[minmax(140px,1fr)_minmax(110px,0.8fr)_minmax(180px,1.5fr)_minmax(110px,0.7fr)_auto]">
                    <input
                      type="text"
                      value={rule.name}
                      onChange={(event) => updateReferentialRule(index, { name: event.target.value })}
                      readOnly={selectedTemplate !== "custom" && !isDraft}
                      aria-label={`Название связи ${index + 1}`}
                      placeholder="Название связи"
                      className="min-w-0 rounded border border-neutral-300 px-2 py-1 text-sm read-only:bg-neutral-50 read-only:text-neutral-500"
                    />
                    <input
                      type="text"
                      value={rule.child_column}
                      onChange={(event) => updateReferentialRule(index, { child_column: event.target.value })}
                      readOnly={selectedTemplate !== "custom" && !isDraft}
                      aria-label={`Дочерняя колонка связи ${index + 1}`}
                      placeholder="Дочерняя колонка"
                      className="min-w-0 rounded border border-neutral-300 px-2 py-1 text-sm read-only:bg-neutral-50 read-only:text-neutral-500"
                    />
                    <input
                      type="text"
                      value={rule.allowedDraft ?? rule.allowed_values.map(String).join(", ")}
                      onChange={(event) => updateReferentialRule(index, {
                        allowedDraft: event.target.value,
                        allowed_values: event.target.value.split(",").map((value) => value.trim()).filter(Boolean),
                      })}
                      aria-label={`Родительские ключи связи ${index + 1}`}
                      placeholder="Ключи через запятую"
                      className="min-w-0 rounded border border-neutral-300 px-2 py-1 text-sm"
                    />
                    <input
                      type="text"
                      value={rule.default_value === undefined ? "" : String(rule.default_value)}
                      onChange={(event) => updateReferentialRule(index, { default_value: event.target.value })}
                      aria-label={`Значение по умолчанию связи ${index + 1}`}
                      placeholder="По умолчанию"
                      className="min-w-0 rounded border border-neutral-300 px-2 py-1 text-sm"
                    />
                    {(selectedTemplate === "custom" || isDraft) && <button type="button" onClick={() => removeReferentialRule(index)} aria-label={`Удалить связь ${index + 1}`} className="rounded p-1.5 text-red-600 hover:bg-red-50"><Trash2 size={15} /></button>}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {rules && !loading && (
        <div>
          <div className="mb-2 flex items-center justify-between gap-2">
            <h4 className="text-sm font-medium">Редактор допустимых наборов ({Object.keys(rules.inclusion || {}).length} правил)</h4>
            <button type="button" onClick={addInclusionRule} className="flex items-center gap-1 rounded border border-brand/40 px-2 py-1 text-xs font-medium text-brand hover:bg-brand/5">
              <Plus size={13} /> Добавить допустимый набор
            </button>
          </div>
          {Object.keys(rules.inclusion || {}).length === 0 && (
            <p className="mb-2 rounded bg-amber-50 px-3 py-2 text-xs text-amber-800">
              Эталон допустимых наборов не задан. Добавьте колонку и значения предметного справочника.
            </p>
          )}
          <div className="space-y-2">
            {Object.entries(rules.inclusion || {}).map(([column, rule], index) => {
              const isDraft = Boolean(rule.draft);
              return (
                <div key={rule.editorId || column} className="rounded-md border border-neutral-200 bg-white px-3 py-2">
                  <div className="grid gap-2 sm:grid-cols-[minmax(110px,0.8fr)_minmax(180px,1.8fr)_minmax(120px,0.8fr)_auto]">
                    <input
                      type="text"
                      value={column.startsWith("__new_") ? "" : column}
                      onChange={(event) => renameInclusionRule(column, event.target.value)}
                      readOnly={selectedTemplate !== "custom" && !isDraft}
                      aria-label={isDraft ? `Колонка правила набора ${index + 1}` : `Колонка набора ${column}`}
                      placeholder="Колонка"
                      className="min-w-0 rounded border border-neutral-300 px-2 py-1 text-sm read-only:bg-neutral-50 read-only:text-neutral-500"
                    />
                    <input
                      type="text"
                      value={rule.allowedDraft ?? rule.allowed_values.map(String).join(", ")}
                      onChange={(event) => updateInclusionRule(column, {
                        allowedDraft: event.target.value,
                        allowed_values: event.target.value.split(",").map((value) => value.trim()).filter(Boolean),
                      })}
                      aria-label={isDraft ? `Допустимые значения правила набора ${index + 1}` : `Допустимые значения для ${column}`}
                      placeholder="Значения через запятую"
                      className="min-w-0 rounded border border-neutral-300 px-2 py-1 text-sm"
                    />
                    <input
                      type="text"
                      value={rule.default_value === undefined ? "" : String(rule.default_value)}
                      onChange={(event) => updateInclusionRule(column, { default_value: event.target.value })}
                      aria-label={isDraft ? `Значение по умолчанию правила набора ${index + 1}` : `Значение по умолчанию для ${column}`}
                      placeholder="По умолчанию"
                      className="min-w-0 rounded border border-neutral-300 px-2 py-1 text-sm"
                    />
                    {(selectedTemplate === "custom" || isDraft) && <button type="button" onClick={() => removeInclusionRule(column)} aria-label={`Удалить допустимый набор ${index + 1}`} className="rounded p-1.5 text-red-600 hover:bg-red-50"><Trash2 size={15} /></button>}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {rules && !loading && (
        <div>
          <div className="mb-2 flex items-center justify-between gap-2">
            <h4 className="text-sm font-medium">Редактор целостности текста</h4>
            <span className="text-[11px] text-neutral-500">Системная проверка активна автоматически</span>
          </div>
          <div className="rounded-md border border-neutral-200 bg-white px-3 py-2">
            <div className="grid gap-2 sm:grid-cols-[120px_120px_minmax(220px,1fr)]">
              <label className="text-[11px] text-neutral-500">
                Мин. длина
                <input
                  type="number"
                  min={0}
                  aria-label="Минимальная длина текста"
                  value={rules.text_quality?.min_length ?? 1}
                  onChange={(event) => updateTextQuality({ min_length: Number(event.target.value) })}
                  className="mt-1 w-full rounded border border-neutral-300 px-2 py-1 text-sm text-neutral-800"
                />
              </label>
              <label className="text-[11px] text-neutral-500">
                Макс. длина
                <input
                  type="number"
                  min={1}
                  aria-label="Максимальная длина текста"
                  value={rules.text_quality?.max_length ?? 500}
                  onChange={(event) => updateTextQuality({ max_length: Number(event.target.value) })}
                  className="mt-1 w-full rounded border border-neutral-300 px-2 py-1 text-sm text-neutral-800"
                />
              </label>
              <label className="text-[11px] text-neutral-500">
                Дополнительные мусорные маркеры
                <input
                  type="text"
                  aria-label="Мусорные маркеры текста"
                  value={rules.text_quality?.garbageDraft ?? rules.text_quality?.garbage_chars?.join(", ") ?? ""}
                  onChange={(event) => updateTextQuality({
                    garbageDraft: event.target.value,
                    garbage_chars: event.target.value.split(",").map((value) => value.trim()).filter(Boolean),
                  })}
                  placeholder="\\x00, ï¿½"
                  className="mt-1 w-full rounded border border-neutral-300 px-2 py-1 text-sm text-neutral-800"
                />
              </label>
            </div>
            <p className="mt-2 text-[11px] text-neutral-500">
              Управляющие символы, U+FFFD/BOM, пустые строки и лишние пробелы проверяются системой всегда. Шаблоны отдельных колонок наследуются из выбранного шаблона.
            </p>
          </div>
        </div>
      )}

      {rules && !loading && (
        <div>
          <div className="mb-2 flex items-center justify-between gap-2">
            <h4 className="text-sm font-medium">Редактор равномерности шага</h4>
            <span className="text-[11px] text-neutral-500">Пустые поля определяются системой</span>
          </div>
          <div className="rounded-md border border-neutral-200 bg-white px-3 py-2">
            <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
              <label className="text-[11px] text-neutral-500">Временная колонка
                <input type="text" aria-label="Временная колонка равномерности" value={rules.regularity?.date_column ?? ""} onChange={(event) => updateRegularity({ date_column: event.target.value })} placeholder="Например: Date" className="mt-1 w-full rounded border border-neutral-300 px-2 py-1 text-sm text-neutral-800" />
              </label>
              <label className="text-[11px] text-neutral-500">Группирующая колонка
                <input type="text" aria-label="Группирующая колонка равномерности" value={rules.regularity?.entity_column ?? ""} onChange={(event) => updateRegularity({ entity_column: event.target.value })} placeholder="Например: Country" className="mt-1 w-full rounded border border-neutral-300 px-2 py-1 text-sm text-neutral-800" />
              </label>
              <label className="text-[11px] text-neutral-500">Частота (pandas)
                <input type="text" aria-label="Частота равномерности" value={rules.regularity?.frequency ?? ""} onChange={(event) => updateRegularity({ frequency: event.target.value })} placeholder="D, W, MS, YS…" className="mt-1 w-full rounded border border-neutral-300 px-2 py-1 font-mono text-sm text-neutral-800" />
              </label>
              <label className="text-[11px] text-neutral-500">Множитель разрыва
                <input type="number" min={1.01} step={0.1} aria-label="Множитель порога разрыва" value={rules.regularity?.gap_threshold_multiplier ?? 1.5} onChange={(event) => updateRegularity({ gap_threshold_multiplier: Number(event.target.value) })} className="mt-1 w-full rounded border border-neutral-300 px-2 py-1 text-sm text-neutral-800" />
              </label>
            </div>
            <p className="mt-2 text-[11px] text-neutral-500">Проверка всегда выполняется отдельно внутри каждой группы. Явная частота используется для подсчёта пропущенных периодов и построения сетки исправления.</p>
          </div>
        </div>
      )}

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

      {/* Базовая хронология определяется системой, предметные сравнения
          задаются только явно. Шаблонные legacy-правила показываем
          read-only; пользовательский редактор поддерживает безопасные
          chronology/comparison без выполнения произвольного кода. */}
      {rules && !loading && (
        <div>
          <div className="mb-2 flex items-center justify-between gap-2">
            <h4 className="text-sm font-medium">Редактор логики ({(rules.consistency || []).length} правил)</h4>
            {selectedTemplate === "custom" && (
              <button
                type="button"
                onClick={addConsistencyRule}
                className="flex items-center gap-1 rounded border border-brand/40 px-2 py-1 text-xs font-medium text-brand hover:bg-brand/5"
              >
                <Plus size={13} /> Добавить правило логики
              </button>
            )}
          </div>
          {(rules.consistency || []).length === 0 && (
            <p className="mb-2 rounded bg-amber-50 px-3 py-2 text-xs text-amber-800">
              Предметные правила не заданы. Система проверит базовую хронологию, если распознает временную колонку.
            </p>
          )}
          <div className="space-y-2">
            {(rules.consistency || []).map((rule, index) => {
              const editable = selectedTemplate === "custom";
              const ruleNumber = index + 1;
              if (!editable) {
                return (
                  <div key={index} className="rounded-md border border-neutral-200 bg-neutral-50 px-3 py-2 text-xs text-neutral-600">
                    <div className="flex items-center justify-between gap-2">
                      <span className="font-medium text-neutral-800">{rule.name || `Правило ${ruleNumber}`}</span>
                      <span className="font-mono text-[10px]">{rule.type || "condition"}</span>
                    </div>
                    <p className="mt-1">{rule.columns?.join(" ↔ ") || rule.condition || "Колонки определяются шаблоном"}</p>
                  </div>
                );
              }
              const chronology = rule.type !== "comparison";
              return (
                <div key={index} className="rounded-md border border-neutral-200 bg-white px-3 py-2">
                  <div className="grid gap-2 sm:grid-cols-[minmax(170px,1fr)_145px_auto]">
                    <input
                      type="text"
                      value={rule.name || ""}
                      onChange={(event) => updateConsistencyRule(index, { name: event.target.value })}
                      aria-label={`Название правила логики ${ruleNumber}`}
                      placeholder="Название правила"
                      className="min-w-0 rounded border border-neutral-300 px-2 py-1 text-sm"
                    />
                    <select
                      value={chronology ? "chronology" : "comparison"}
                      onChange={(event) => updateConsistencyRule(index, { type: event.target.value })}
                      aria-label={`Тип правила логики ${ruleNumber}`}
                      className="rounded border border-neutral-300 bg-white px-2 py-1 text-sm"
                    >
                      <option value="chronology">Хронология</option>
                      <option value="comparison">Сравнение колонок</option>
                    </select>
                    <button
                      type="button"
                      onClick={() => removeConsistencyRule(index)}
                      aria-label={`Удалить правило логики ${ruleNumber}`}
                      className="rounded p-1.5 text-red-600 hover:bg-red-50"
                    >
                      <Trash2 size={15} />
                    </button>
                  </div>
                  {chronology ? (
                    <div className="mt-2 grid grid-cols-2 gap-2">
                      <input
                        type="text"
                        value={rule.columns?.[0] || ""}
                        onChange={(event) => updateConsistencyColumn(index, 0, event.target.value)}
                        aria-label={`Временная колонка правила логики ${ruleNumber}`}
                        placeholder="Временная колонка"
                        className="rounded border border-neutral-300 px-2 py-1 text-sm"
                      />
                      <input
                        type="text"
                        value={rule.group_column || ""}
                        onChange={(event) => updateConsistencyRule(index, { group_column: event.target.value })}
                        aria-label={`Группирующая колонка правила логики ${ruleNumber}`}
                        placeholder="Группа (необязательно)"
                        className="rounded border border-neutral-300 px-2 py-1 text-sm"
                      />
                    </div>
                  ) : (
                    <div className="mt-2 grid gap-2 sm:grid-cols-[1fr_80px_1fr]">
                      <input
                        type="text"
                        value={rule.columns?.[0] || ""}
                        onChange={(event) => updateConsistencyColumn(index, 0, event.target.value)}
                        aria-label={`Левая колонка правила логики ${ruleNumber}`}
                        placeholder="Левая колонка"
                        className="rounded border border-neutral-300 px-2 py-1 text-sm"
                      />
                      <select
                        value={rule.operator || "<="}
                        onChange={(event) => updateConsistencyRule(index, { operator: event.target.value })}
                        aria-label={`Оператор правила логики ${ruleNumber}`}
                        className="rounded border border-neutral-300 bg-white px-2 py-1 text-sm"
                      >
                        {["<", "<=", ">", ">=", "==", "!="].map((operator) => (
                          <option key={operator} value={operator}>{operator}</option>
                        ))}
                      </select>
                      <input
                        type="text"
                        value={rule.columns?.[1] || ""}
                        onChange={(event) => updateConsistencyColumn(index, 1, event.target.value)}
                        aria-label={`Правая колонка правила логики ${ruleNumber}`}
                        placeholder="Правая колонка"
                        className="rounded border border-neutral-300 px-2 py-1 text-sm"
                      />
                    </div>
                  )}
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
                <div key={rule.editorId || column} className="rounded-md border border-neutral-200 bg-white px-3 py-2">
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
