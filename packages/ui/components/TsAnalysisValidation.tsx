"use client";

// packages/ui/components/TsAnalysisValidation.tsx
//
// ОБЩИЙ компонент фичи "Валидация" -- используется И embedded-,
// И standalone-приложением. По структуре повторяет 3-колоночный
// лейаут TsAnalysisPreprocessing, но с собственным набором проверок
// (10 критериев Data Quality) и заголовком модуля со справкой.
//
// Компоновка:
//   [Левая ~240px]     [Центр flex-1]         [Правая ~320px]
//   ▼ Признак: price   Описание               Панель управления
//   3/10 ████░░         [текстовое поле]       описание
//   ┌─Типы данных──⚠─┐  Обзор: Типы данных    [бейдж нарушения]
//   ├─Форматы────⚠─┤   [график]               [Метрики и алгоритм]
//   └────────────────┘  [Строк][Проп][Выбр]    [Полный пайплайн]
//   [Запустить валидацию]                         [действия этапа]
//
// Справка по стандартам DQ раскрывается в центральном текстовом окне
// при нажатии кнопки «Справка» в заголовке модуля.

import { useState, useRef, useEffect, useCallback } from "react";
import { Settings, ChevronDown, ChevronUp } from "lucide-react";
import { Button } from "./Button";
import { Metric } from "./Metric";
import { StatusIcon, type CheckStatus } from "./StatusIcon";
import { RulesManagementPanel } from "./RulesManagementPanel";
import { StepperNextModuleButton } from "./StepperNextModuleButton";
import { ValidationCheckChart, type ValidationCheckData } from "./ValidationCheckChart";
import {
  ValidationTypeMatrix,
  type TypeValidationMode,
  type ValidationTypeProfileItem,
} from "./ValidationTypeMatrix";
import { ValidationTypePipeline } from "./ValidationTypePipeline";
import { ValidationFormatPipeline } from "./ValidationFormatPipeline";
import { ValidationRangeOverview } from "./ValidationRangeOverview";
import { ValidationRangePipeline } from "./ValidationRangePipeline";
import { ValidationConsistencyOverview } from "./ValidationConsistencyOverview";
import { ValidationConsistencyPipeline } from "./ValidationConsistencyPipeline";
import { ValidationUniquenessOverview } from "./ValidationUniquenessOverview";
import { ValidationUniquenessPipeline } from "./ValidationUniquenessPipeline";
import { ValidationInclusionOverview } from "./ValidationInclusionOverview";
import { ValidationInclusionPipeline } from "./ValidationInclusionPipeline";
import { ValidationReferentialOverview } from "./ValidationReferentialOverview";
import { ValidationReferentialPipeline } from "./ValidationReferentialPipeline";
import { ValidationTextQualityOverview } from "./ValidationTextQualityOverview";
import { ValidationTextQualityPipeline } from "./ValidationTextQualityPipeline";
import { ValidationRegularityOverview } from "./ValidationRegularityOverview";
import { ValidationRegularityPipeline } from "./ValidationRegularityPipeline";
import { ValidationSufficiencyOverview } from "./ValidationSufficiencyOverview";
import { ValidationSufficiencyPipeline } from "./ValidationSufficiencyPipeline";
import { useAppShell } from "../context/AppShellContext";
import { sessionApiUrl } from "../lib/apiClient";
import { DatasetPassportPanel } from "./DatasetPassportPanel";
import { useTargetColumn } from "../hooks/useTargetColumn";
import { describeNode } from "../lib/knowledge/knowledge";

// ── Типы ──────────────────────────────────────────────────────

interface Check {
  id: string;
  label: string;
  status: CheckStatus;
  count: number | null;
  description: string;
  ruleSource: "system" | "template" | "session" | "not_applicable";
  mode: CheckMode;
  statusReason: CheckStatusReason;
}

type CheckMode = "auto" | "enabled" | "disabled";
type CheckStatusReason = "not_required" | "disabled" | "needs_rule" | null;

interface CheckMeta {
  id: string;
  label: string;
  description: string;
}

// ── 10 критериев Data Quality (маппинг на Streamlit app.py, шаги 1-10) ──
//
// ТОЛЬКО label/description -- документационный текст, не данные. Реальные
// status/count/items приходят из GET /v1/session/dataset/validate (см.
// apps/api/routers/session.py::get_dataset_validate,
// validation/engine.py::_run_all_checks) -- подключено 2026-08-14,
// раньше весь массив (включая status/count) был статическим моком.

const CHECK_META: CheckMeta[] = [
  { id: "data_types", label: "Типы данных",
    description: "Фактический профиль фиксирует dtype и семантический класс каждой колонки. Система строит безопасный эталон типов по dtype, приводимости значений и семантике названия; сохранённая схема сессии или выбранный шаблон имеет более высокий приоритет." },
  { id: "formats", label: "Форматы и шаблоны",
    description: "Значения, не прошедшие regex-проверку (email, телефон, ИНН, дата), не могут быть использованы в автоматическом пайплайне. Проверка validate_formats выявляет все нарушения по шаблонам из rules.yaml." },
  { id: "ranges", label: "Диапазоны значений",
    description: "Выход за допустимые min/max (отрицательная цена, дата вне горизонта, процент > 100) искажает статистику и ломает модели. validate_ranges проверяет границы из rules.yaml." },
  { id: "consistency", label: "Логика и хронология",
    description: "Нарушение бизнес-правил (close < open для цен, хронология дат, монотонность индекса) делает данные внутренне противоречивыми. validate_consistency проверяет логику и хронологию." },
  { id: "uniqueness", label: "Уникальность",
    description: "Дублирующиеся строки и временные метки ломают уникальность индекса и искажают агрегации. check_uniqueness выявляет полные и частичные дубликаты." },
  { id: "inclusion", label: "Принадлежность к набору",
    description: "Значения, не входящие в допустимый справочник (код региона, категория, единица измерения), не могут быть интерпретированы. check_inclusion проверяет membership по словарям из rules.yaml." },
  { id: "referential", label: "Ссылочная целостность",
    description: "Внешние ключи, ссылающиеся на несуществующие записи в связанных таблицах, ломают JOIN-операции. validate_referential проверяет все FK-связи. Без явного правила режим «Авто» помечает остановку как «Не требуется»; режим «Включена» запрашивает настройку." },
  { id: "text_quality", label: "Целостность текста",
    description: "Мусорные символы, некорректная кодировка, пустые строки и дубликаты пробелов искажают категориальный анализ и полнотекстовый поиск. validate_text_quality выявляет все нарушения." },
  { id: "regularity", label: "Равномерность шага",
    description: "Нерегулярный временной шаг (пропуски дат, дублирование, сбой частоты) мешает STL-декомпозиции, ACF/PACF и моделям ARIMA/SARIMA. validate_regular_step проверяет частоту и gaps." },
  { id: "sufficiency", label: "Достаточность наблюдений",
    description: "Недостаточное число наблюдений для идентификации параметров модели (минимум 2×сезонный_период для SARIMA, 30+ для ADF). validate_sufficiency оценивает длину ряда и выдаёт рекомендации." },
];

const DEFAULT_CHECK_MODES: Record<string, CheckMode> = Object.fromEntries(
  CHECK_META.map(({ id }) => [id, "auto"])
);

const RULE_SOURCE_LABELS: Record<Check["ruleSource"], string> = {
  system: "Системное правило",
  template: "Шаблон правил",
  session: "Правило сессии",
  not_applicable: "Правило не задано",
};

// NUMERIC_FEATURES-мок убран (2026-08-14) -- реальные колонки приходят
// из useTargetColumn().availableColumns (тот же GET /target-column, что
// и в Загрузке/Моделировании). Раньше "Price" в этом селекторе было
// совпадением: мок-список тикеров содержал 'price' первым, никак не
// связано с реальным выбором пользователя на Загрузке.

// ── Справка по стандартам качества данных ────────────────────






















// ── Компонент ─────────────────────────────────────────────────

export function TsAnalysisValidation() {
  const { activeDataset } = useAppShell();
  const [activeCheckId, setActiveCheckId] = useState(CHECK_META[0].id);
  // Инвариант информативности (2026-09-15): активная остановка степпера
  // АВТОМАТИЧЕСКИ загружает в «Описание» содержимое «Метрики и алгоритм»
  // данной остановки (и делает кнопку активной) — вне зависимости от статуса
  // остановки. Контент метрик — статические константы (без зависимостей от
  // /dataset/validate и наличия датасета), поэтому автозагрузка возможна
  // всегда. Секция null более не производится: начальное состояние —
  // "metrics", клик по остановке степпера и закрытие Справки/Правил
  // возвращают к "metrics".
  const [descriptionSection, setDescriptionSection] = useState<"metrics" | "pipeline" | "help" | "rules" | null>("metrics");
  const [descriptionExpanded, setDescriptionExpanded] = useState(false);
  const [hasOverflow, setHasOverflow] = useState(false);
  const descRef = useRef<HTMLDivElement>(null);

  // ── Единый "исследуемый признак" (target_column) для всей платформы
  // (2026-08-14) -- тот же хук, что и в Загрузке. Раньше activeFeature
  // был отдельным useState(NUMERIC_FEATURES[0]) -- мок-список тикеров,
  // никак не связанный с реальным выбором пользователя на Загрузке.
  const {
    targetColumn: activeFeature,
    availableColumns: numericFeatures,
    setColumn: setActiveFeature,
    refetch: refetchTargetColumn,
    passportResetNotice,
  } = useTargetColumn(activeDataset?.name);

  // ── Реальная валидация датасета сессии (GET /dataset/validate) ──
  // Заменяет статический мок -- см. apps/api/routers/session.py::get_dataset_validate,
  // validation/engine.py::_run_all_checks (подключено 2026-08-14).
  // column=activeFeature (2026-08-14) -- часть проверок (ranges/formats/
  // inclusion/referential/text_quality/sufficiency) скоупятся до
  // выбранного признака, часть принципиально dataset-wide -- см.
  // ValidationCheckData.scope и докстринг _run_all_checks.
  const [checksData, setChecksData] = useState<Record<string, ValidationCheckData> | null>(null);
  const [checksLoading, setChecksLoading] = useState(false);
  const [datasetSummary, setDatasetSummary] = useState<{ totalRows: number; totalColumns: number } | null>(null);
  const [typeProfile, setTypeProfile] = useState<ValidationTypeProfileItem[]>([]);
  const [typeValidationMode, setTypeValidationMode] = useState<TypeValidationMode>("profile");
  const [validationError, setValidationError] = useState<string | null>(null);
  const [validationHasRun, setValidationHasRun] = useState(false);
  const [validationVersion, setValidationVersion] = useState(0);
  const [checkModes, setCheckModes] = useState<Record<string, CheckMode>>(DEFAULT_CHECK_MODES);
  const [modeSaving, setModeSaving] = useState<string | null>(null);
  const [modeError, setModeError] = useState<{ checkId: string; message: string } | null>(null);
  const validationRequestId = useRef(0);

  const fetchValidation = useCallback(async () => {
    if (!activeDataset) {
      setChecksData(null);
      setDatasetSummary(null);
      setTypeProfile([]);
      setTypeValidationMode("profile");
      setValidationError(null);
      setValidationHasRun(false);
      setChecksLoading(false);
      return;
    }
    const requestId = ++validationRequestId.current;
    setChecksLoading(true);
    setValidationError(null);
    const url = sessionApiUrl("/dataset/validate");
    try {
      const response = await fetch(url, { credentials: "include" });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const data = await response.json();
      if (requestId !== validationRequestId.current || !data) return;
      setChecksData(data.checks);
      setCheckModes((current) => ({
        ...current,
        ...Object.fromEntries(
          Object.entries(data.checks ?? {})
            .filter(([, value]) => Boolean((value as ValidationCheckData).mode))
            .map(([id, value]) => [id, (value as ValidationCheckData).mode as CheckMode])
        ),
      }));
      setDatasetSummary({ totalRows: data.total_rows, totalColumns: data.total_columns });
      setTypeProfile(Array.isArray(data.type_profile) ? data.type_profile : []);
      setTypeValidationMode(data.type_validation_mode === "schema" ? "schema" : "profile");
      setValidationHasRun(true);
      setValidationVersion((current) => current + 1);
    } catch {
      if (requestId !== validationRequestId.current) return;
      setChecksData(null);
      setDatasetSummary(null);
      setTypeProfile([]);
      setTypeValidationMode("profile");
      setValidationError("Не удалось выполнить проверку");
      setValidationHasRun(true);
    } finally {
      if (requestId === validationRequestId.current) setChecksLoading(false);
    }
  }, [activeDataset]);

  useEffect(() => {
    validationRequestId.current += 1;
    setChecksData(null);
    setDatasetSummary(null);
    setTypeProfile([]);
    setTypeValidationMode("profile");
    setValidationError(null);
    setValidationHasRun(false);
    setValidationVersion(0);
    setCheckModes(DEFAULT_CHECK_MODES);
    setModeSaving(null);
    setModeError(null);
    setChecksLoading(false);
    return () => {
      validationRequestId.current += 1;
    };
  }, [activeDataset?.name]);

  useEffect(() => {
    if (!activeDataset) return;
    let cancelled = false;
    const fetchModes = async () => {
      try {
        const response = await fetch(sessionApiUrl("/dataset/validation-check-modes"), {
          credentials: "include",
        });
        if (!response.ok) return;
        const data = await response.json();
        if (!cancelled && data?.modes) {
          setCheckModes({ ...DEFAULT_CHECK_MODES, ...data.modes });
        }
      } catch {
        // Старый API не блокирует основную валидацию: остаётся режим «Авто».
      }
    };
    void fetchModes();
    return () => {
      cancelled = true;
    };
  }, [activeDataset?.name]);

  // Реальные status/count поверх статических label/description. Пока
  // датасет не загружен или проверка ещё не пришла -- честное "pending",
  // не фейковый 0.
  const CHECKS: Check[] = CHECK_META.map((meta) => ({
    ...meta,
    status: checksData?.[meta.id]?.status ?? "pending",
    count: checksData?.[meta.id]?.count ?? null,
    ruleSource: checksData?.[meta.id]?.rule_source ?? "not_applicable",
    mode: checksData?.[meta.id]?.mode ?? checkModes[meta.id] ?? "auto",
    statusReason: checksData?.[meta.id]?.status_reason ?? null,
  }));

  // Сворачиваем при смене секции
  useEffect(() => {
    setDescriptionExpanded(false);
  }, [descriptionSection]);

  // Click-outside: сворачиваем при клике вне description box
  const handleOutsideClick = useCallback((e: MouseEvent) => {
    if (descRef.current && !descRef.current.contains(e.target as Node)) {
      setDescriptionExpanded(false);
    }
  }, []);
  useEffect(() => {
    if (descriptionExpanded) {
      document.addEventListener("mousedown", handleOutsideClick);
      return () => document.removeEventListener("mousedown", handleOutsideClick);
    }
  }, [descriptionExpanded, handleOutsideClick]);

  // Отключённые и автоматически неприменимые остановки нейтральны: они
  // исключаются из DQ Score и знаменателя прогресса. Pending означает,
  // что включённая аналитиком проверка ещё требует настройки.
  const applicableChecks = CHECKS.filter((c) => c.status !== "skipped");
  const evaluatedChecks = applicableChecks.filter((c) => c.status === "done" || c.status === "warning");
  const doneCount = evaluatedChecks.filter((c) => c.status === "done").length;
  const dqScore = evaluatedChecks.length > 0 ? doneCount / evaluatedChecks.length : null;
  const progressPct = applicableChecks.length > 0
    ? Math.round((evaluatedChecks.length / applicableChecks.length) * 100)
    : 100;
  const activeCheck = CHECKS.find((c) => c.id === activeCheckId)!;

  const orderedChecks = [...CHECKS].sort((a, b) =>
    a.id === activeCheckId ? -1 : b.id === activeCheckId ? 1 : 0
  );

  const displayedStatus = (check: Check): CheckStatus =>
    check.status === "pending" && check.statusReason === "needs_rule" ? "warning" : check.status;

  // Переключение секции описания в центральном текстовом поле
  const handleDescriptionClick = (check: Check, section: "metrics" | "pipeline") => {
    setActiveCheckId(check.id);
    setDescriptionSection(section);
  };

  const runValidation = () => {
    if (!activeDataset) return;
    void fetchValidation();
  };

  const handleCheckModeChange = async (checkId: string, mode: CheckMode) => {
    if (!activeDataset || modeSaving) return;
    const previousModes = checkModes;
    setCheckModes((current) => ({ ...current, [checkId]: mode }));
    setModeSaving(checkId);
    setModeError(null);
    try {
      const response = await fetch(sessionApiUrl("/dataset/validation-check-modes"), {
        method: "PUT",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ modes: { [checkId]: mode } }),
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const data = await response.json();
      if (data?.modes) setCheckModes({ ...DEFAULT_CHECK_MODES, ...data.modes });
      if (validationHasRun) await fetchValidation();
    } catch {
      setCheckModes(previousModes);
      setModeError({ checkId, message: "Не удалось сохранить режим проверки" });
    } finally {
      setModeSaving(null);
    }
  };

  // Показать справку по стандартам DQ (toggle: закрытие возвращает
  // к метрикам активной остановки — инвариант информативности)
  const handleHelpClick = () => {
    setDescriptionSection((prev) => prev === "help" ? "metrics" : "help");
  };

  // Показать/скрыть «Управление правилами» (toggle: закрытие возвращает
  // к метрикам активной остановки — инвариант информативности)
  const handleRulesClick = () => {
    setDescriptionSection((prev) => prev === "rules" ? "metrics" : "rules");
  };

  // ── Overflow detection для expandable description ──
  useEffect(() => {
    const el = descRef.current;
    if (!el) return;
    const checkOverflow = () => {
      setHasOverflow(el.scrollHeight > el.clientHeight + 2);
    };
    checkOverflow();
    const observer = new ResizeObserver(checkOverflow);
    observer.observe(el);
    return () => observer.disconnect();
  }, [descriptionSection]); // ResizeObserver отслеживает контент

  // Текст описания для центрального поля — из единого реестра справки
  // (Шаг 3, ревизия 2026-09-22: describeNode по (stage_id, node_id, facet);
  // паритет миграции застрахован фиксстурой help-parity.fixture.json, §13)
  const descriptionContent = (() => {
    if (descriptionSection === "help") {
      return describeNode("validation", null, "module_help")?.text ?? null;
    }
    if (descriptionSection === "rules") return null; // RulesManagementPanel рендерится отдельно
    if (!descriptionSection) return null;
    return (
      describeNode("validation", activeCheck.id, descriptionSection)?.text ??
      // defense-in-depth: проверка без записи в реестре (инвариант покрытия
      // гарантирует отсутствие этого пути для 10 реализованных проверок)
      (descriptionSection === "metrics"
        ? `Метрики и алгоритм: ${activeCheck.label}\n\n${activeCheck.description}\n\nАлгоритм выявления: автоматический скрининг с порогом по умолчанию, ручная верификация аналитиком.`
        : `Полный пайплайн: ${activeCheck.label.toLowerCase()}\n\n1. Обнаружение → 2. Диагностика → 3. Преобразование → 4. Верификация\n\n${activeCheck.description}`)
    );
  })();

  // Подзаголовок центрального поля
  const descriptionSubtitle = (() => {
    if (descriptionSection === "help") return "Справка по стандартам качества данных";
    if (descriptionSection === "rules") return "Управление правилами валидации";
    if (!descriptionSection) return "Выберите раздел в боковой панели";
    if (descriptionSection === "metrics") return `Метрики и алгоритм — ${activeCheck.label}`;
    if (activeCheck.id === "data_types") return "Мастер исправления типов";
    if (activeCheck.id === "formats") return "Мастер исправления форматов и шаблонов";
    if (activeCheck.id === "ranges") return "Мастер исправления диапазонов";
    if (activeCheck.id === "consistency") return "Мастер исправления логики и хронологии";
    if (activeCheck.id === "uniqueness") return "Мастер исправления уникальности";
    if (activeCheck.id === "inclusion") return "Мастер исправления принадлежности к набору";
    if (activeCheck.id === "referential") return "Мастер исправления ссылочной целостности";
    if (activeCheck.id === "text_quality") return "Мастер исправления целостности текста";
    if (activeCheck.id === "regularity") return "Мастер исправления равномерности шага";
    if (activeCheck.id === "sufficiency") return "Мастер решений по достаточности";
    return `Полный пайплайн — ${activeCheck.label}`;
  })();

  return (
    <div className="space-y-5">
      <div className="flex gap-6">
        {/* ── ЛЕВАЯ КОЛОНКА: селектор признака + прогресс + степпер ── */}
        <aside className="w-60 shrink-0 flex flex-col gap-3 pt-1">
        {/* Заголовок модуля + справка */}
        <div className="mb-1">
          <div className="flex items-center justify-between">
            <h2 className="text-lg font-semibold text-neutral-800">
              Data Quality
            </h2>
            <button
              onClick={handleHelpClick}
              className={`text-xs px-2 py-1 rounded transition-colors ${
                descriptionSection === "help"
                  ? "bg-brand text-white"
                  : "bg-brand-light text-neutral-700 hover:bg-brand-light/80"
              }`}
            >
              Справка
            </button>
          </div>
          <p className="text-[11px] text-neutral-500 mt-0.5">
            Контроль качества данных
          </p>
        </div>

        {/* Селектор числового признака */}
        {numericFeatures.length > 0 && (
          <div>
            <label className="text-[11px] text-neutral-500 block mb-1">
              Исследуемый признак:
            </label>
            <select
              value={activeFeature ?? numericFeatures[0]}
              onChange={(e) => setActiveFeature(e.target.value)}
              className="w-full rounded border border-neutral-300 bg-white px-2 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-brand"
            >
              {numericFeatures.map((f) => (
                <option key={f} value={f}>{f}</option>
              ))}
            </select>
          </div>
        )}

        <Button
          disabled={!activeDataset || checksLoading}
          onClick={runValidation}
          className="w-full disabled:cursor-not-allowed disabled:opacity-50"
        >
          {checksLoading ? "Валидация выполняется…" : "Запустить валидацию"}
        </Button>

        {/* Прогресс */}
        <div className="flex items-center gap-2">
          <p className="text-[11px] text-neutral-500 tabular-nums">
            {evaluatedChecks.length}/{applicableChecks.length}
          </p>
          <div className="flex-1 bg-neutral-200 rounded-full h-1.5">
            <div
              className="bg-brand h-1.5 rounded-full transition-all"
              style={{ width: `${progressPct}%` }}
            />
          </div>
        </div>

        {/* Степпер: прямоугольные карточки с текстом + иконка.
            Паттерн «Моделирования»: пройденная остановка (зелёная галочка,
            status done) подсвечивается светло-зелёным с зелёным текстом;
            при других статусах кнопка не окрашивается. Активная остановка
            сохраняет приоритет индиго, как в эталоне. Спец-бейджи
            («Отключено», «Настроить», «Нет эталона») не влияют на окраску. */}
        <div className="flex flex-col gap-1.5">
          {CHECKS.map((check) => (
            <button
              key={check.id}
              onClick={() => {
                setActiveCheckId(check.id);
                // Инвариант информативности (2026-09-15): переключение
                // остановки автозагружает её «Метрики и алгоритм» (вместо
                // прежнего сброса в placeholder). Клик по УЖЕ активной
                // остановке секцию не меняет (открытая Справка/Правилы
                // остаются) — прежняя семантика сохранена.
                if (check.id !== activeCheckId) setDescriptionSection("metrics");
              }}
              className={`w-full flex items-center justify-between rounded-md border px-3 py-2 text-sm transition-colors ${
                check.id === activeCheckId
                  ? "bg-brand text-white border-brand"
                  : check.status === "done"
                  ? "bg-green-50 border-green-200 text-green-800"
                  : "bg-white border-neutral-200 hover:bg-neutral-50 text-neutral-800"
              }`}
            >
              <span className="truncate">{check.label}</span>
              <span className="ml-2 shrink-0">
                {validationHasRun && check.status === "skipped" ? (
                  <span className={`rounded px-1.5 py-0.5 text-[10px] font-medium ${
                    check.id === activeCheckId ? "bg-white/20 text-white" : "bg-neutral-100 text-neutral-600"
                  }`}>
                    {check.statusReason === "disabled" ? "Отключено" : "Не требуется"}
                  </span>
                ) : validationHasRun && check.status === "pending" && check.statusReason === "needs_rule" ? (
                  <span className={`rounded px-1.5 py-0.5 text-[10px] font-medium ${
                    check.id === activeCheckId ? "bg-white/20 text-white" : "bg-amber-50 text-amber-700"
                  }`}>
                    Настроить
                  </span>
                ) : validationHasRun && ["formats", "ranges", "consistency", "uniqueness", "inclusion"].includes(check.id) && check.status === "pending" && check.ruleSource === "not_applicable" ? (
                  <span className={`rounded px-1.5 py-0.5 text-[10px] font-medium ${
                    check.id === activeCheckId ? "bg-white/20 text-white" : "bg-amber-50 text-amber-700"
                  }`}>
                    Нет эталона
                  </span>
                ) : (
                  <StatusIcon status={displayedStatus(check)} />
                )}
              </span>
            </button>
          ))}
        </div>

        {/* ── Кнопка «Управление правилами» — внизу степпера ── */}
        {/* Визуально отличается от степпер-бейджей: dashed border, */}
        {/* brand-colored text, Settings icon — не заливка, а outline-стиль */}
        <div className="mt-3 pt-3 border-t border-neutral-200">
          <button
            onClick={handleRulesClick}
            data-testid="rules-management-btn"
            className={`w-full flex items-center justify-center gap-2 rounded-md border-2 border-dashed px-3 py-2.5 text-sm font-medium transition-colors ${
              descriptionSection === "rules"
                ? "border-brand bg-brand/10 text-brand"
                : "border-brand/40 text-brand hover:border-brand hover:bg-brand/5"
            }`}
          >
            <Settings size={16} />
            Управление правилами
          </button>
        </div>

        {/* ── Приглашение «Перейти к предобработке» — паттерн Загрузки ──
            Общий StepperNextModuleButton ("Ведём исследователя за руку"):
            тот же дизайн, что на «Загрузке» (геометрия степпер-кнопок,
            пастельная заливка, индиго при наведении); светло-серая полоса
            border-t встроена в обёртку компонента. Ставится строго ниже
            кнопки правил: это переход к ДРУГОМУ модулю пайплайна. */}
        <StepperNextModuleButton label="Перейти к предобработке" href="/preprocessing" />
      </aside>

      {/* ── ЦЕНТРАЛЬНАЯ КОЛОНКА: описание + график + метрики ── */}
      <section className="flex-1 min-w-0">
        {/* Блок «Описание» — текстовое поле над графиком */}
        <div className="mb-5">
          <h3 className="font-semibold mb-1">
            Описание
          </h3>
          <p className="text-xs text-neutral-500 mb-2">
            {descriptionSubtitle}
          </p>
          {/* ── Expandable Description Box ──
              collapsed: min-h=220px, max-h=220px, scroll (in-flow)
              expanded: position:absolute overlay over graph, max-h=calc(100vh-180px)
              chevron: shown only when hasOverflow
          */}
          <div className="relative min-h-[220px]">
            <div
              ref={descRef}
              className={`rounded-lg border border-neutral-200 px-4 py-3 overflow-y-auto text-sm text-neutral-600 whitespace-pre-wrap ${
                descriptionExpanded
                  ? "absolute top-0 left-0 right-0 z-20 max-h-[calc(100vh-180px)] shadow-lg border-brand/30 min-h-[220px] bg-brand-light"
                  : "max-h-[220px] min-h-[220px] bg-brand-light/50"
              }`}
            >
              {descriptionSection === "rules" ? (
                <RulesManagementPanel onRulesApplied={runValidation} />
              ) : descriptionContent ? (
                descriptionContent
              ) : (
                <span className="text-neutral-400 italic">
                  Нажмите «Метрики и алгоритм», «Исправить этап проверки», «Справка» или «Управление правилами»
                </span>
              )}
              {/* Collapse chevron — sticky прилипает к низу scroll-области */}
              {descriptionExpanded && (
                <div className="sticky bottom-0 flex justify-center py-1 bg-brand-light rounded-b-lg">
                  <button
                    onClick={() => setDescriptionExpanded(false)}
                    className="flex items-center justify-center w-8 h-5 rounded-t bg-brand/10 hover:bg-brand/20 text-brand transition-colors"
                    aria-label="Свернуть описание"
                    data-testid="desc-collapse-btn"
                  >
                    <ChevronUp size={14} />
                  </button>
                </div>
              )}
            </div>
            {/* Expand chevron — только при overflow, collapsed */}
            {hasOverflow && !descriptionExpanded && (
              <button
                onClick={() => setDescriptionExpanded(true)}
                className="absolute bottom-1 left-1/2 -translate-x-1/2 flex items-center justify-center w-8 h-5 rounded-t bg-brand/10 hover:bg-brand/20 text-brand transition-colors"
                aria-label="Развернуть описание"
                data-testid="desc-expand-btn"
              >
                <ChevronDown size={14} />
              </button>
            )}
          </div>
        </div>

        {/* График */}
        <div>
          <h3 className="font-semibold mb-1">
            {activeCheckId === "data_types" && descriptionSection === "pipeline"
              ? "Мастер исправления типов"
              : activeCheckId === "formats" && descriptionSection === "pipeline"
              ? "Мастер исправления форматов и шаблонов"
              : activeCheckId === "ranges" && descriptionSection === "pipeline"
              ? "Мастер исправления диапазонов"
              : activeCheckId === "consistency" && descriptionSection === "pipeline"
              ? "Мастер исправления логики и хронологии"
              : activeCheckId === "uniqueness" && descriptionSection === "pipeline"
              ? "Мастер исправления уникальности"
              : activeCheckId === "inclusion" && descriptionSection === "pipeline"
              ? "Мастер исправления принадлежности к набору"
              : activeCheckId === "referential" && descriptionSection === "pipeline"
              ? "Мастер исправления ссылочной целостности"
              : activeCheckId === "text_quality" && descriptionSection === "pipeline"
              ? "Мастер исправления целостности текста"
              : activeCheckId === "regularity" && descriptionSection === "pipeline"
              ? "Мастер исправления равномерности шага"
              : activeCheckId === "sufficiency" && descriptionSection === "pipeline"
              ? "Мастер решений по достаточности"
              : `Обзор: ${activeCheck.label}`}
          </h3>
          <p className="text-xs text-neutral-500 mb-3">
            {activeCheckId === "data_types" && descriptionSection === "pipeline"
              ? "Выберите преобразования, проверьте последствия и примените их к активному датасету."
              : activeCheckId === "formats" && descriptionSection === "pipeline"
              ? "Выберите правила и стратегию, проверьте последствия и примените исправления к активному датасету."
              : activeCheckId === "ranges" && descriptionSection === "pipeline"
              ? "Выберите проблемные колонки и стратегию, оцените последствия и примените исправления."
              : activeCheckId === "consistency" && descriptionSection === "pipeline"
              ? "Выберите нарушенные правила и совместимую стратегию, проверьте последствия и примените исправления."
              : activeCheckId === "uniqueness" && descriptionSection === "pipeline"
              ? "Проверьте ключ, выберите стратегию, оцените точное число удаляемых строк и примените исправление."
              : activeCheckId === "inclusion" && descriptionSection === "pipeline"
              ? "Проверьте справочник, выберите стратегию, оцените последствия и примените исправления."
              : activeCheckId === "referential" && descriptionSection === "pipeline"
              ? "Проверьте связи, выберите стратегию, оцените последствия и устраните сиротские ключи."
              : activeCheckId === "text_quality" && descriptionSection === "pipeline"
              ? "Выберите колонки и стратегию, оцените последствия очистки и примените исправления."
              : activeCheckId === "regularity" && descriptionSection === "pipeline"
              ? "Проверьте временную сетку, выберите стратегию, оцените последствия и примените исправление."
              : activeCheckId === "sufficiency" && descriptionSection === "pipeline"
              ? "Проверьте длину рядов, выберите безопасное решение и сохраните план анализа."
              : activeCheckId === "data_types"
              ? "Распределение фактических типов и построчная матрица колонок."
              : activeCheckId === "ranges"
              ? "Соотношение корректных и нарушающих значения, фактические и допустимые границы."
              : activeCheckId === "consistency"
              ? "Соблюдение хронологических и предметных правил, затронутые строки и примеры конфликтов."
              : activeCheckId === "uniqueness"
              ? "Распределение строк и группы повторов по активному составному или системному ключу."
              : activeCheckId === "inclusion"
              ? "Соотношение допустимых и недопустимых значений и матрица активных справочников."
              : activeCheckId === "referential"
              ? "Соотношение связанных и сиротских записей и матрица активных внешних ключей."
              : activeCheckId === "text_quality"
              ? "Соотношение чистых и проблемных значений и матрица причин по текстовым колонкам."
              : activeCheckId === "regularity"
              ? "Равномерность временной сетки по группам, разрывы, дубли и нарушения сортировки."
              : activeCheckId === "sufficiency"
              ? "Достаточные и ограниченные группы, валидные наблюдения, сезонные циклы и доступные классы методов."
              : "Визуализация результатов проверки по активному критерию."}
          </p>

          {activeCheckId === "data_types" && descriptionSection === "pipeline" ? (
            <ValidationTypePipeline
              profile={typeProfile}
              activeTargetColumn={activeFeature}
              onApplied={(nextProfile, targetColumnReset) => {
                setTypeProfile(nextProfile);
                runValidation();
                if (targetColumnReset) void refetchTargetColumn();
              }}
              onSchemaSaved={runValidation}
            />
          ) : activeCheckId === "formats" && descriptionSection === "pipeline" ? (
            <ValidationFormatPipeline
              onApplied={runValidation}
              onOpenRules={() => setDescriptionSection("rules")}
            />
          ) : activeCheckId === "ranges" && descriptionSection === "pipeline" ? (
            <ValidationRangePipeline
              onApplied={runValidation}
              onOpenRules={() => setDescriptionSection("rules")}
            />
          ) : activeCheckId === "consistency" && descriptionSection === "pipeline" ? (
            <ValidationConsistencyPipeline
              onApplied={runValidation}
              onOpenRules={() => setDescriptionSection("rules")}
            />
          ) : activeCheckId === "uniqueness" && descriptionSection === "pipeline" ? (
            <ValidationUniquenessPipeline onApplied={runValidation} />
          ) : activeCheckId === "inclusion" && descriptionSection === "pipeline" ? (
            <ValidationInclusionPipeline
              onApplied={runValidation}
              onOpenRules={() => setDescriptionSection("rules")}
            />
          ) : activeCheckId === "referential" && descriptionSection === "pipeline" ? (
            <ValidationReferentialPipeline
              onApplied={runValidation}
              onOpenRules={() => setDescriptionSection("rules")}
            />
          ) : activeCheckId === "text_quality" && descriptionSection === "pipeline" ? (
            <ValidationTextQualityPipeline onApplied={runValidation} />
          ) : activeCheckId === "regularity" && descriptionSection === "pipeline" ? (
            <ValidationRegularityPipeline
              onApplied={runValidation}
              onOpenRules={() => setDescriptionSection("rules")}
            />
          ) : activeCheckId === "sufficiency" && descriptionSection === "pipeline" ? (
            <ValidationSufficiencyPipeline
              onApplied={runValidation}
              onOpenRules={() => setDescriptionSection("rules")}
            />
          ) : validationHasRun && activeCheck.status === "skipped" ? (
            <div className="flex h-[468px] items-center justify-center rounded-lg bg-brand-light px-8 text-center text-sm text-neutral-500">
              {activeCheck.statusReason === "disabled"
                ? `Проверка «${activeCheck.label}» отключена аналитиком и не участвует в DQ Score.`
                : `Проверка «${activeCheck.label}» не требуется для текущего датасета в режиме «Авто».`}
            </div>
          ) : activeCheckId === "data_types" ? (
            validationHasRun || checksLoading ? (
              <ValidationTypeMatrix
                profile={typeProfile}
                mode={typeValidationMode}
                loading={checksLoading}
                hasDataset={Boolean(activeDataset)}
              />
            ) : (
              <div className="rounded-lg h-[468px] flex items-center justify-center bg-brand-light px-8 text-center text-sm text-neutral-500">
                Запустите валидацию, чтобы построить матрицу типов и получить статусы проверок.
              </div>
            )
          ) : activeCheckId === "ranges" ? (
            validationHasRun ? (
              <ValidationRangeOverview refreshKey={validationVersion} />
            ) : (
              <div className="flex h-[468px] items-center justify-center rounded-lg bg-brand-light px-8 text-center text-sm text-neutral-500">
                Запустите валидацию, чтобы построить профиль диапазонов и получить статус проверки.
              </div>
            )
          ) : activeCheckId === "consistency" ? (
            validationHasRun ? (
              <ValidationConsistencyOverview refreshKey={validationVersion} />
            ) : (
              <div className="flex h-[468px] items-center justify-center rounded-lg bg-brand-light px-8 text-center text-sm text-neutral-500">
                Запустите валидацию, чтобы построить профиль логики и хронологии и получить статус проверки.
              </div>
            )
          ) : activeCheckId === "uniqueness" ? (
            validationHasRun ? (
              <ValidationUniquenessOverview refreshKey={validationVersion} />
            ) : (
              <div className="flex h-[468px] items-center justify-center rounded-lg bg-brand-light px-8 text-center text-sm text-neutral-500">
                Запустите валидацию, чтобы построить профиль уникальности и получить статус проверки.
              </div>
            )
          ) : activeCheckId === "inclusion" ? (
            validationHasRun ? (
              <ValidationInclusionOverview refreshKey={validationVersion} />
            ) : (
              <div className="flex h-[468px] items-center justify-center rounded-lg bg-brand-light px-8 text-center text-sm text-neutral-500">
                Запустите валидацию, чтобы проверить принадлежность значениям предметных справочников.
              </div>
            )
          ) : activeCheckId === "referential" ? (
            validationHasRun ? (
              <ValidationReferentialOverview refreshKey={validationVersion} />
            ) : (
              <div className="flex h-[468px] items-center justify-center rounded-lg bg-brand-light px-8 text-center text-sm text-neutral-500">
                Запустите валидацию, чтобы проверить внешние ключи относительно предметных справочников.
              </div>
            )
          ) : activeCheckId === "text_quality" ? (
            validationHasRun ? (
              <ValidationTextQualityOverview refreshKey={validationVersion} />
            ) : (
              <div className="flex h-[468px] items-center justify-center rounded-lg bg-brand-light px-8 text-center text-sm text-neutral-500">
                Запустите валидацию, чтобы построить профиль целостности текстовых колонок.
              </div>
            )
          ) : activeCheckId === "regularity" ? (
            validationHasRun ? (
              <ValidationRegularityOverview refreshKey={validationVersion} />
            ) : (
              <div className="flex h-[468px] items-center justify-center rounded-lg bg-brand-light px-8 text-center text-sm text-neutral-500">
                Запустите валидацию, чтобы проверить равномерность временной сетки по каждой сущности.
              </div>
            )
          ) : activeCheckId === "sufficiency" ? (
            validationHasRun ? (
              <ValidationSufficiencyOverview refreshKey={validationVersion} />
            ) : (
              <div className="flex h-[468px] items-center justify-center rounded-lg bg-brand-light px-8 text-center text-sm text-neutral-500">
                Запустите валидацию, чтобы оценить применимость методов по длине каждого временного ряда.
              </div>
            )
          ) : (
            <ValidationCheckChart
              checkLabel={activeCheck.label}
              data={checksData?.[activeCheckId] ?? null}
              loading={checksLoading}
              selectedColumn={activeFeature}
            />
          )}

          <div className="grid grid-cols-4 gap-3 mt-4">
            <Metric label="Строк" value={datasetSummary ? String(datasetSummary.totalRows) : "—"} />
            <Metric label="Нарушений" value={activeCheck.count !== null ? String(activeCheck.count) : "—"} />
            <Metric label="DQ Score" value={dqScore !== null ? dqScore.toFixed(2) : "—"} />
            <Metric label="Колонок" value={datasetSummary ? String(datasetSummary.totalColumns) : "—"} />
          </div>
        </div>
      </section>

      {/* ── ПРАВАЯ КОЛОНКА: панель управления + список проверок ── */}
      <aside className="w-80 shrink-0 pt-1">
        <div className="mb-4">
          <h2 className="text-lg font-semibold text-neutral-800">
            Панель управления
          </h2>
        </div>
        <div className="max-h-[830px] overflow-y-auto pr-2 space-y-5 feed-scroll">
          {orderedChecks.map((check) => (
            <article
              key={check.id}
              className={`pb-5 border-b border-neutral-100 ${
                check.id === activeCheckId ? "border-l-4 border-l-brand pl-3" : ""
              }`}
            >
              <h3 className="font-semibold mb-1">
                <StatusIcon status={displayedStatus(check)} /> Проверка: {check.label}
              </h3>

              <p className="text-sm text-neutral-600 mb-2">{check.description}</p>

              <label className="mb-2 block text-[11px] font-medium text-neutral-600">
                Режим проверки
                <select
                  aria-label={`Режим проверки ${check.label}`}
                  value={checkModes[check.id] ?? check.mode}
                  disabled={!activeDataset || modeSaving !== null}
                  onChange={(event) => void handleCheckModeChange(check.id, event.target.value as CheckMode)}
                  className="mt-1 w-full rounded border border-neutral-300 bg-white px-2 py-1.5 text-sm font-normal text-neutral-800 focus:outline-none focus:ring-1 focus:ring-brand disabled:cursor-not-allowed disabled:opacity-50"
                >
                  <option value="auto">Авто</option>
                  <option value="enabled">Включена</option>
                  <option value="disabled">Отключена</option>
                </select>
              </label>
              {modeSaving === check.id && (
                <p role="status" className="mb-2 text-[11px] text-brand">Сохранение режима…</p>
              )}
              {modeError?.checkId === check.id && (
                <p role="alert" className="mb-2 text-[11px] text-red-700">{modeError.message}</p>
              )}

              {checksLoading && (
                <p role="status" className="text-sm text-brand bg-brand-light rounded px-3 py-2 mb-2">
                  Проверка выполняется
                </p>
              )}
              {!checksLoading && validationHasRun && (validationError || checksData?.[check.id]?.error) && (
                <p role="alert" className="text-sm text-red-700 bg-red-50 rounded px-3 py-2 mb-2">
                  Ошибка выполнения
                </p>
              )}
              {!checksLoading && !validationHasRun && (
                <p role="status" className="text-sm text-neutral-600 bg-neutral-50 rounded px-3 py-2 mb-2">
                  Проверка не запускалась
                </p>
              )}
              {!checksLoading && validationHasRun && !validationError && !checksData?.[check.id]?.error && check.status === "warning" && (
                <p role="status" className="text-sm text-amber-700 bg-amber-50 rounded px-3 py-2 mb-2">
                  Найдены проблемы: {check.count ?? 0}
                </p>
              )}
              {!checksLoading && validationHasRun && !validationError && !checksData?.[check.id]?.error && check.status === "done" && (
                <p role="status" className="text-sm text-green-700 bg-green-50 rounded px-3 py-2 mb-2">
                  Проверка пройдена
                </p>
              )}
              {!checksLoading && validationHasRun && !validationError && !checksData?.[check.id]?.error && check.status === "skipped" && (
                <p role="status" className="text-sm text-neutral-600 bg-neutral-50 rounded px-3 py-2 mb-2">
                  {check.statusReason === "disabled" ? "Отключено" : "Не требуется"}
                </p>
              )}
              {!checksLoading && validationHasRun && !validationError && !checksData?.[check.id]?.error && check.status === "pending" && (
                <p role="status" className={`text-sm rounded px-3 py-2 mb-2 ${
                  check.statusReason === "needs_rule"
                    ? "text-amber-700 bg-amber-50"
                    : "text-neutral-600 bg-neutral-50"
                }`}>
                  {check.statusReason === "needs_rule"
                    ? "Требуется настройка"
                    : check.id === "formats" && check.ruleSource === "not_applicable"
                    ? "Эталон форматов не задан"
                    : check.id === "ranges" && check.ruleSource === "not_applicable"
                  ? "Эталон диапазонов не задан"
                    : check.id === "consistency" && check.ruleSource === "not_applicable"
                    ? "Эталон логики и хронологии не задан"
                    : check.id === "uniqueness" && check.ruleSource === "not_applicable"
                    ? "Ключ уникальности неприменим"
                    : check.id === "inclusion" && check.ruleSource === "not_applicable"
                    ? "Эталон допустимых наборов не задан"
                    : "Не применимо: правило или необходимые данные отсутствуют"}
                </p>
              )}

              {validationHasRun && !checksLoading && check.status !== "skipped" && (
                <p className="mb-2 text-[11px] font-medium text-neutral-500">
                  {RULE_SOURCE_LABELS[check.ruleSource]}
                </p>
              )}

              {/* Кнопка «Метрики и алгоритм» — активирует контент в центральном поле */}
              <button
                onClick={() => handleDescriptionClick(check, "metrics")}
                className={`w-full mb-2 rounded px-3 py-2 text-sm text-left font-medium transition-colors ${
                  check.id === activeCheckId && descriptionSection === "metrics"
                    ? "bg-brand text-white"
                    : "bg-brand-light hover:bg-brand-light/80 text-neutral-800"
                }`}
              >
                Метрики и алгоритм
              </button>

              {/* Для реализованных остановок открываются специализированные мастера. */}
              <button
                onClick={() => handleDescriptionClick(check, "pipeline")}
                className={`w-full mb-3 rounded px-3 py-2 text-sm text-left font-medium transition-colors ${
                  check.id === activeCheckId && descriptionSection === "pipeline"
                    ? "bg-brand text-white"
                    : "bg-brand-light hover:bg-brand-light/80 text-neutral-800"
                }`}
              >
                {check.id === "data_types"
                  ? "Исправить типы данных"
                  : check.id === "formats"
                  ? "Исправить форматы и шаблоны"
                  : check.id === "ranges"
                  ? "Исправить диапазоны значений"
                  : check.id === "consistency"
                  ? "Исправить логику и хронологию"
                  : check.id === "uniqueness"
                  ? "Исправить уникальность"
                  : check.id === "inclusion"
                  ? "Исправить принадлежность к набору"
                  : check.id === "referential"
                  ? "Исправить ссылочную целостность"
                  : check.id === "text_quality"
                  ? "Исправить целостность текста"
                  : check.id === "regularity"
                  ? "Исправить равномерность шага"
                  : check.id === "sufficiency"
                  ? "Настроить план анализа"
                  : "Полный пайплайн"}
              </button>

            </article>
          ))}
        </div>
        </aside>
      </div>
      <DatasetPassportPanel
        stage="validation"
        targetColumn={activeFeature}
        historyResetNotice={passportResetNotice
          ? `Смена исследуемого признака «${passportResetNotice.previousColumn}» → «${passportResetNotice.newColumn}» сбросила цепочку паспортов.`
          : null}
      />
    </div>
  );
}
