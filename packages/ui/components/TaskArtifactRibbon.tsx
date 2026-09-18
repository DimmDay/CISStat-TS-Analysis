"use client";

// packages/ui/components/TaskArtifactRibbon.tsx
//
// Лента артефактов сессии на хабе «Задачи» (v1.1,
// spec_tasks_ia_addendum_v1_1.md §9.2).
//
// Сквозной принцип платформы: интерфейс показывает реально вычисленные
// факты сессии, а не статичный текст. Лента размещается между шапкой
// хаба и сеткой карточек задач и рисует ТОЛЬКО реально существующие
// артефакты; отсутствующий артефакт НЕ рисуется как «пусто» — его
// просто нет в ленте. Свежая сессия (ни один этап не "done") —
// компонент возвращает null: ленты нет вовсе.
//
// Наполнение чипов — из уже посчитанных фактов (§9.2):
//   Датасет    (validated)   — activeDataset из AppShellContext
//                              (гидратация GET /v1/session/current);
//                              без гидратации — факт «загружен»;
//   Model Card (model_card)  — точечный вызов GET /v1/session/modeling/card
//                              (fetchCardSummaries): имя последней карты +
//                              счётчик при нескольких; отказ похода —
//                              деградация к факту «создана» (fail-soft);
//   Прогноз    (forecast_run) — факт наличия (stages.forecasting === "done")
//                              без похода за деталями: состав чипа
//                              детализируется вместе с v2 «Мониторинга».
//
// Порядок чипов = порядок артефактов §4 (validated -> model_card ->
// forecast_run). Чипы — переиспользование Metric-карточек (по образцу
// DatasetPassportPanel), не новый компонент; ссылок внутри нет —
// счётчики ссылок хаба (тесты контракта §4) не меняются.

import { useEffect, useRef, useState } from "react";
import { Metric } from "./Metric";
import { useAppShell } from "../context/AppShellContext";
import { fetchCardSummaries } from "../lib/forecasting";
import { StageStatus } from "../lib/stages";

/** Сводка карты в объёме, достаточном чипу (подмножество CardSummary). */
interface CardChipSummary {
  card_id: string;
  model_id: string | null;
  model_name: string | null;
  created_at: string | null;
}

export function TaskArtifactRibbon() {
  const { activeDataset, stages } = useAppShell();
  const safeStages: Record<string, StageStatus> = stages ?? {};

  // Артефакт существует <=> его этап-владелец дошёл до "done" (§4).
  const hasValidated = safeStages.validation === "done";
  const hasModelCard = safeStages.modeling === "done";
  const hasForecastRun = safeStages.forecasting === "done";

  // Точечный поход за картами — только когда артефакт model_card
  // существует; отказ НЕ ломает ленту (fail-soft к факту «создана»).
  const [cardChip, setCardChip] = useState<string | null>(
    hasModelCard ? "создана" : null
  );
  const alive = useRef(true);
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);
  useEffect(() => {
    if (!hasModelCard) return;
    let cancelled = false;
    fetchCardSummaries()
      .then((cards: CardChipSummary[]) => {
        if (cancelled || !alive.current) return;
        if (!cards || cards.length === 0) return; // факт «создана» остаётся
        const sorted = [...cards].sort((a, b) =>
          String(a.created_at ?? "").localeCompare(String(b.created_at ?? ""))
        );
        const latest = sorted[sorted.length - 1];
        const name =
          latest.model_name ?? latest.model_id ?? latest.card_id ?? "карта";
        setCardChip(
          sorted.length > 1 ? `${name} × ${sorted.length}` : String(name)
        );
      })
      .catch(() => {
        // Отказ похода: чип остаётся с фактом «создана» (честная маркировка).
      });
    return () => {
      cancelled = true;
    };
  }, [hasModelCard]);

  // Свежая сессия: ленты нет вовсе (§13 дополнения: «не "пусто"»).
  if (!hasValidated && !hasModelCard && !hasForecastRun) return null;

  return (
    <div
      className="flex flex-wrap items-stretch gap-3 px-6"
      role="list"
      aria-label="Артефакты сессии"
    >
      {hasValidated && (
        <div role="listitem" className="min-w-0 max-w-full">
          <Metric
            label="Датасет"
            value={
              activeDataset
                ? `${activeDataset.name} · ${activeDataset.rows} набл.`
                : "загружен"
            }
          />
        </div>
      )}
      {hasModelCard && (
        <div role="listitem" className="min-w-0 max-w-full">
          <Metric label="Model Card" value={cardChip ?? "создана"} />
        </div>
      )}
      {hasForecastRun && (
        <div role="listitem" className="min-w-0 max-w-full">
          <Metric label="Прогноз" value="построен" />
        </div>
      )}
    </div>
  );
}
