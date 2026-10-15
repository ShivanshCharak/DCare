"use client";

import { useState } from "react";
import type {
  Claim,
  DocumentRecord,
  ReviewAction,
} from "../types";
import { LANGUAGE_NAMES } from "../languages";

import {
  checkClasses,
  checkLabel,
  reasonDescription,
  statusClasses,
  STATUS_LABELS,
  verificationRows,
  meaningfulReasons,
  checkPurpose,
  verificationDetailMessage,
} from "../utils";

type ClaimCardProps = {
  claim: Claim;
  doc: DocumentRecord;
  onSelectSource: (sourceId: string) => void;
  onReview: (
    claimId: string,
    action: ReviewAction,
    editedText?: string
  ) => Promise<boolean>;
  reviewing: boolean;
};

export function ClaimCard({
  claim,
  doc,
  onSelectSource,
  onReview,
  reviewing,
}: ClaimCardProps) {
  const [isEditing, setIsEditing] = useState(false);
  const [editedText, setEditedText] = useState(claim.text);

  async function submitEdit() {
    if (!editedText.trim()) {
      return;
    }

    const succeeded = await onReview(
      claim.id,
      "edit",
      editedText.trim()
    );

    if (succeeded) {
      setIsEditing(false);
    }
  }

  return (
    <article id={`claim-${claim.id}`} className="claim-card mb-4 scroll-mt-6 rounded-xl border border-slate-200 p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="font-mono text-xs font-semibold text-slate-500">
            {claim.id}
          </p>

          <p className="mt-1 text-xs text-slate-500">
            Language: {claim.language === "en" ? "English" : `${LANGUAGE_NAMES[claim.language] ?? claim.language} (machine translation, not validated)`}
          </p>
          {typeof claim.review_priority_score === "number" && <p className="mt-1 text-xs text-slate-500">Review priority score: {claim.review_priority_score.toFixed(2)} / 1.00 · higher scores appear first; not a probability.</p>}
        </div>

        <span
          className={`rounded-full border px-3 py-1 text-xs font-semibold ${statusClasses(
            claim.state
          )}`}
        >
          {STATUS_LABELS[claim.state]}
        </span>
      </div>

      {claim.state === "needs_clinician" && (
        <div role="alert" className="mt-4 rounded-lg border border-rose-300 bg-rose-50 p-3 text-sm font-semibold leading-6 text-rose-900">
          Do not rely on this explanation until a clinician reviews it.
        </div>
      )}

      {claim.state === "source_supported" && (
        <div role="note" className="mt-4 rounded-lg border border-emerald-200 bg-emerald-50 p-3 text-sm leading-6 text-emerald-950">
          This wording matches its source or a recognized equivalent. It has been removed from the review queue; this status does not assess whether the source instruction itself is medically correct.
        </div>
      )}

      {claim.language !== "en" && (
        <div role="note" className="mt-4 rounded-lg border border-amber-300 bg-amber-50 p-3 text-sm leading-6 text-amber-950">
          {LANGUAGE_NAMES[claim.language] ?? claim.language} output is machine-translated and not validated. A qualified bilingual reviewer must compare it with the English source before use.
        </div>
      )}

      <div className="mt-4">
        <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">
          Plain-language explanation
        </p>

        {isEditing ? (
          <div className="mt-2">
            <label
              htmlFor={`edit-${claim.id}`}
              className="mb-2 block text-sm font-medium text-slate-700"
            >
              Edit explanation
            </label>

            <textarea
              id={`edit-${claim.id}`}
              value={editedText}
              onChange={(event) => setEditedText(event.target.value)}
              rows={4}
              className="w-full rounded-lg border border-slate-300 p-3 text-sm leading-6 outline-none focus:border-slate-500 focus:ring-2 focus:ring-slate-200"
            />

            <div className="mt-3 flex flex-wrap gap-2">
              <button
                type="button"
                onClick={submitEdit}
                disabled={reviewing || !editedText.trim()}
                className="rounded-lg bg-slate-950 px-4 py-2 text-sm font-semibold text-white hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {reviewing ? "Saving…" : "Save edit"}
              </button>

              <button
                type="button"
                onClick={() => {
                  setEditedText(claim.text);
                  setIsEditing(false);
                }}
                disabled={reviewing}
                className="rounded-lg border border-slate-300 px-4 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-50 disabled:opacity-50"
              >
                Cancel
              </button>
            </div>
          </div>
        ) : (
          <p className="claim-explanation mt-2 text-sm leading-6 text-slate-900">
            {claim.text}
          </p>
        )}
        {claim.source_language_text && claim.language !== "en" && <details className="mt-3 rounded-lg bg-slate-50 p-3"><summary className="cursor-pointer text-sm font-semibold text-slate-700">English draft for comparison</summary><p className="mt-2 text-sm leading-6 text-slate-700">{claim.source_language_text}</p></details>}
      </div>

      <div className="mt-4">
        <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">
          Based on these source sentences
        </p>

        {claim.source_ids.length > 0 ? (
          <div className="flex flex-wrap gap-2">
            {claim.source_ids.map((sourceId) => {
              const exists = doc.sentences.some(
                (sentence) => sentence.id === sourceId
              );

              return (
                <button
                  key={sourceId}
                  type="button"
                  disabled={!exists}
                  onClick={() => onSelectSource(sourceId)}
                  className="rounded-md border border-slate-300 px-2 py-1 font-mono text-xs text-slate-700 hover:bg-slate-100 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  {sourceId}
                </button>
              );
            })}
          </div>
        ) : (
          <p className="text-sm text-rose-700">
            No source references provided.
          </p>
        )}
      </div>

      <details className="mt-4 rounded-lg bg-slate-50 p-3">
        <summary className="cursor-pointer text-sm font-semibold text-slate-800">
          Verification checks ({verificationRows(claim.checks).length})
        </summary>

        <div className="mt-3 space-y-3">
          {verificationRows(claim.checks).map(([name, result]) => {
            const detail = claim.check_details?.[name];
            const explanation = verificationDetailMessage(detail, name, result, claim.reason_codes);
            const detailObject = detail && typeof detail === "object" ? detail : undefined;
            const sourceText = detailObject?.source_text ?? claim.source_ids.map((id) => doc.sentences.find((sentence) => sentence.id === id)?.text).filter(Boolean).join(" ");
            const claimText = detailObject?.claim_text ?? claim.text;
            const showEvidence = result !== "passed" && result !== "not_run" && result !== "not_configured" && result !== "not_applicable";
            return (
              <details key={name} open={result !== "passed"} className="rounded-md border border-slate-200 bg-white px-3 py-2">
                <summary className="flex cursor-pointer list-none flex-wrap justify-between gap-2 text-sm">
                  <span className="font-medium text-slate-700">{checkLabel(name)}</span>
                  <span className={`font-semibold ${checkClasses(result ?? "not_run")}`}>{result ? checkLabel(result) : "Status unavailable"}</span>
                </summary>
                <p className="mt-1 text-xs leading-5 text-slate-500">{checkPurpose(name)}</p>
                {explanation && (
                  <div className="mt-2 space-y-2 text-sm leading-6 text-slate-600">
                    <p><span className="font-semibold">Finding: </span>{explanation}</p>
                    {showEvidence && (
                      <div className="grid gap-2 rounded-md bg-slate-50 p-2 text-xs leading-5 sm:grid-cols-2">
                        <p><span className="font-semibold text-slate-700">Source wording: </span>{sourceText || "The cited source sentence is unavailable."}</p>
                        <p><span className="font-semibold text-slate-700">Generated explanation: </span>{claimText}</p>
                      </div>
                    )}
                    {result !== "passed" && result !== "not_applicable" && (
                      <p className="text-xs font-semibold text-rose-800">Action: {claim.state === "needs_clinician" ? "Clinician review required before use." : "Additional review required before this claim can be verified."}</p>
                    )}
                  </div>
                )}
              </details>
            );
          })}

        </div>
      </details>

      <details open={claim.state === "needs_clinician"} className="mt-3 rounded-lg border border-slate-200 p-3">
        <summary className="cursor-pointer text-sm font-semibold text-slate-800">
          Review reasons ({meaningfulReasons(claim.reason_codes).length})
        </summary>

        {meaningfulReasons(claim.reason_codes).length > 0 ? (
          <ul className="mt-3 list-disc space-y-2 pl-5 text-sm text-slate-600">
            {meaningfulReasons(claim.reason_codes).map((reason) => (
            <li key={reason}>
              <span className="font-semibold text-slate-700">{checkLabel(reason)}: </span>
              {reasonDescription(reason)}
            </li>
            ))}
          </ul>
        ) : (
          <p className="mt-3 text-sm text-slate-500">
            No reason details were returned. Compare the linked source wording with the explanation and review the individual check results.
          </p>
        )}
      </details>

      <div className="mt-4 border-t border-slate-200 pt-4">
        {claim.review ? (
          <div className="rounded-lg border border-slate-200 bg-slate-50 p-3">
            <p className="text-sm font-semibold text-slate-800">
              Human review recorded
            </p>

            <p className="mt-1 text-sm text-slate-600">
              Decision:{" "}
              <span className="font-semibold">
                {claim.review.action === "approve"
                  ? "Approved"
                  : claim.review.action === "edit"
                    ? "Edited"
                    : "Rejected"}
              </span>
            </p>

            <p className="mt-1 text-xs leading-5 text-slate-500">
              This records a review decision. It does not establish clinical
              correctness or automatically mark the claim as verified.
            </p>
            {claim.review_history?.length > 0 && (
              <details className="mt-3 border-t border-slate-200 pt-2">
                <summary className="cursor-pointer text-xs font-semibold text-slate-700">
                  Review audit history ({claim.review_history.length})
                </summary>
                <ol className="mt-2 space-y-2 text-xs leading-5 text-slate-600">
                  {claim.review_history.map((entry, index) => (
                    <li key={`${entry.action}-${index}`}>
                      {entry.reviewer} recorded {entry.action} ({STATUS_LABELS[entry.state_before]} → {STATUS_LABELS[entry.state_after]}).
                      {entry.note ? ` Note: ${entry.note}` : ""}
                    </li>
                  ))}
                </ol>
              </details>
            )}
          </div>
        ) : (
          <>
            <p className="mb-3 text-sm font-semibold text-slate-800">
              Human review
            </p>

            <div className="flex flex-wrap gap-2">
              <button
                type="button"
                onClick={() => onReview(claim.id, "approve")}
                disabled={reviewing || isEditing}
                className="rounded-lg border border-slate-300 px-4 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {reviewing ? "Recording…" : "Approve"}
              </button>

              <button
                type="button"
                onClick={() => {
                  setEditedText(claim.text);
                  setIsEditing(true);
                }}
                disabled={reviewing || isEditing}
                className="rounded-lg border border-slate-300 px-4 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50"
              >
                Edit
              </button>

              <button
                type="button"
                onClick={() => onReview(claim.id, "reject")}
                disabled={reviewing || isEditing}
                className="rounded-lg border border-rose-300 px-4 py-2 text-sm font-semibold text-rose-800 hover:bg-rose-50 disabled:cursor-not-allowed disabled:opacity-50"
              >
                Reject
              </button>
            </div>
          </>
        )}
      </div>
    </article>
  );
}
