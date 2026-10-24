"use client";

// packages/ui/components/Doclog9ProfileControls.tsx
//
// DOCLOG-9 (спека §12.2 «Действия», §12.3 состояния, §15, §19 строка
// DOCLOG-9 «выбранный профиль подтверждён валидатором и organisational
// policy, не названием файла»): панель выпуска по организационному
// профилю для форматов DOCX/PDF-A. Панель загружает АКТИВНЫЕ профили
// организации выбранного формата (GET /org-profiles?format=), выбор
// профиля -- обязательный шаг (безымянный выпуск PDF/A запрещён,
// сервер ответит 422 org_profile_invalid); заказ рендера уходит с
// org_profile_id; после готовности панель запрашивает записи
// валидации (GET validations) и показывает статус ТЕКСТОМ (цвет НЕ
// единственный носитель статуса, §12.3); для подписанных профилей --
// кнопка «Проверить подпись» (HMAC-манифест, НЕ юридическая ЭП).
// Данные -- ответы сервера; панель ничего не вычисляет (§19.1).

import { useCallback, useEffect, useState } from "react";
import {
  getRenditionValidations,
  listOrgProfiles,
  requestRendition,
  verifyRenditionSignature,
  type JobPayload,
  type OrgProfileSummary,
  type RenditionValidationRecord,
  type SignatureVerification,
} from "../lib/documentation";

const PROFILE_FORMAT_LABELS: Record<string, string> = {
  docx: "DOCX",
  pdfa: "PDF/A-1b",
};

function guaranteesLabel(profile: OrgProfileSummary): string {
  const bits: string[] = [];
  if (profile.validate_conformance) bits.push("валидатор");
  if (profile.sign_contents) bits.push("подпись (HMAC, не юридическая ЭП)");
  if (profile.anchor_registry) bits.push("якорь");
  if (profile.worm_lock) bits.push("WORM-холд");
  return bits.length > 0 ? bits.join(", ") : "без дополнительных гарантий";
}

function validationLabel(record: RenditionValidationRecord): string {
  const tail = record.findings.length > 0 ? `: ${record.findings.join("; ")}` : "";
  return `${record.validator} — ${record.result === "passed" ? "пройдена" : "не пройдена"}${tail}`;
}

export function Doclog9ProfileControls({
  format,
  activeRevisionId,
}: {
  format: "docx" | "pdfa";
  activeRevisionId: string | null | undefined;
}) {
  const [phase, setPhase] = useState<"loading" | "ready" | "empty" | "forbidden" | "error">("loading");
  const [profiles, setProfiles] = useState<OrgProfileSummary[]>([]);
  const [selectedId, setSelectedId] = useState<string>("");
  const [job, setJob] = useState<JobPayload | null>(null);
  const [orderError, setOrderError] = useState<string>("");
  const [validations, setValidations] = useState<RenditionValidationRecord[] | null>(null);
  const [verification, setVerification] = useState<SignatureVerification | null>(null);
  const [verificationBusy, setVerificationBusy] = useState(false);

  const loadProfiles = useCallback(async () => {
    setPhase("loading");
    setValidations(null);
    setVerification(null);
    setJob(null);
    setOrderError("");
    const result = await listOrgProfiles(format);
    if (!result.ok) {
      setPhase(result.status === 404 || result.status === 403 ? "forbidden" : "error");
      return;
    }
    const active = (result.data?.profiles ?? []).filter(
      (profile) => profile.status === "active",
    );
    setProfiles(active);
    setSelectedId(active.length > 0 ? active[0].profile_id : "");
    setPhase(active.length > 0 ? "ready" : "empty");
  }, [format]);

  useEffect(() => {
    void loadProfiles();
  }, [loadProfiles]);

  const handleOrder = useCallback(async () => {
    if (!activeRevisionId || !selectedId) return;
    setOrderError("");
    setJob(null);
    setValidations(null);
    setVerification(null);
    const result = await requestRendition(activeRevisionId, format, {
      org_profile_id: selectedId,
    });
    if (!result.ok) {
      const detail = (result as { detail?: { message?: string } }).detail;
      setOrderError(
        detail?.message
          ? `Выпуск не заказан: ${detail.message}`
          : `Выпуск не заказан (HTTP ${result.status})`,
      );
      return;
    }
    setJob(result.data?.job ?? null);
  }, [activeRevisionId, format, selectedId]);

  // После готовности задания -- статус валидации (доказательство
  // «профиль подтверждён валидатором»).
  useEffect(() => {
    if (!job || job.state !== "ready" || !job.rendition_id) return;
    let cancelled = false;
    void (async () => {
      const result = await getRenditionValidations(job.rendition_id as string);
      if (!cancelled && result.ok) {
        setValidations(result.data?.validations ?? []);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [job]);

  const handleVerifySignature = useCallback(async () => {
    if (!job?.rendition_id) return;
    setVerificationBusy(true);
    const result = await verifyRenditionSignature(job.rendition_id);
    setVerificationBusy(false);
    if (result.ok) {
      setVerification(result.data?.verification ?? null);
    }
  }, [job]);

  const selectedProfile = profiles.find((profile) => profile.profile_id === selectedId) ?? null;
  const formatLabel = PROFILE_FORMAT_LABELS[format] ?? format.toUpperCase();

  return (
    <div
      data-testid="doclog9-profile-panel"
      className="rounded-lg border border-neutral-200 p-3 text-sm dark:border-neutral-700"
    >
      <p className="text-xs font-semibold text-neutral-700 dark:text-neutral-200">
        Выпуск {formatLabel} по профилю организации
      </p>
      <p className="mt-1 text-xs text-neutral-500">
        Профиль подтверждается валидатором и организационной политикой, а не
        названием файла (§19).
      </p>

      {phase === "loading" && (
        <p role="status" className="mt-2 text-xs text-neutral-500">
          Загрузка профилей организации…
        </p>
      )}

      {phase === "forbidden" && (
        <p role="alert" className="mt-2 text-xs text-neutral-600 dark:text-neutral-300">
          Профили организации недоступны для этого запроса (нет права или
          контур скрыт — честный отказ, §12.3).
        </p>
      )}

      {phase === "error" && (
        <p role="alert" className="mt-2 text-xs text-neutral-600 dark:text-neutral-300">
          Сервис профилей недоступен. Попробуйте позже.
        </p>
      )}

      {phase === "empty" && (
        <p className="mt-2 text-xs text-neutral-600 dark:text-neutral-300">
          Активных профилей для {formatLabel} нет. Профиль создаёт
          администратор политики (policy.admin, §15).
        </p>
      )}

      {phase === "ready" && (
        <div className="mt-2 flex flex-col gap-2">
          <label className="text-xs text-neutral-600 dark:text-neutral-300">
            Профиль организации:
            <select
              data-testid="doclog9-profile-select"
              value={selectedId}
              onChange={(event) => setSelectedId(event.target.value)}
              className="ml-2 rounded-md border border-neutral-300 bg-white px-2 py-1 text-xs dark:border-neutral-600 dark:bg-neutral-900"
            >
              {profiles.map((profile) => (
                <option key={profile.profile_id} value={profile.profile_id}>
                  {profile.name} · v{profile.version_no}
                  {profile.organization ? ` · ${profile.organization}` : ""}
                </option>
              ))}
            </select>
          </label>
          {selectedProfile && (
            <p className="text-xs text-neutral-500">
              Гарантии: {guaranteesLabel(selectedProfile)}.
            </p>
          )}
          <div>
            <button
              type="button"
              data-testid="doclog9-order-button"
              onClick={() => void handleOrder()}
              disabled={!activeRevisionId || !selectedId}
              className="rounded-full bg-brand/10 px-3 py-1 text-xs font-medium text-brand focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand disabled:opacity-50"
            >
              Собрать {formatLabel} по профилю
            </button>
          </div>
        </div>
      )}

      {orderError && (
        <p role="alert" className="mt-2 text-xs text-neutral-700 dark:text-neutral-200">
          {orderError}
        </p>
      )}

      {job && (
        <p role="status" data-testid="doclog9-job-state" className="mt-2 text-xs text-neutral-600 dark:text-neutral-300">
          Задание {job.job_id ? `${job.job_id.slice(0, 12)}…` : ""}:{" "}
          {job.state === "ready"
            ? "готово"
            : job.state === "failed"
              ? `не выполнено (${job.error_code ?? "render_failed"})`
              : job.state === "queued"
                ? "в очереди"
                : "рендерится"}
        </p>
      )}

      {validations && validations.length > 0 && (
        <ul className="mt-2 space-y-1 text-xs text-neutral-600 dark:text-neutral-300" data-testid="doclog9-validations">
          {validations.map((record) => (
            <li key={record.validation_id}>Валидация {validationLabel(record)}</li>
          ))}
        </ul>
      )}

      {job?.state === "ready" && job.rendition_id && (
        <div className="mt-2">
          <button
            type="button"
            onClick={() => void handleVerifySignature()}
            disabled={verificationBusy}
            className="rounded-full border border-neutral-300 px-3 py-1 text-xs text-neutral-600 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand dark:border-neutral-600 dark:text-neutral-300 disabled:opacity-50"
          >
            Проверить подпись
          </button>
          {verification && (
            <p role="status" className="mt-1 text-xs text-neutral-600 dark:text-neutral-300">
              Подпись:{" "}
              {verification.result === "passed"
                ? "совпадает с байтами (HMAC)"
                : verification.result === "not_signed"
                  ? "подпись не зафиксирована"
                  : `не совпадает: ${verification.findings.join("; ")}`}
              . Подпись не является юридической электронной подписью (§7).
            </p>
          )}
        </div>
      )}
    </div>
  );
}
