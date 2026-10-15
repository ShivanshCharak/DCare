"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import type { ReviewQueueItem, ReviewAction } from "../types";
import { LANGUAGE_NAMES } from "../languages";
import { API, apiFetch, checkClasses, checkLabel, checkPurpose, reasonDescription, statusClasses, STATUS_LABELS, verificationRows, meaningfulReasons, verificationDetailMessage } from "../utils";

export default function ReviewQueuePage() {
  const [items, setItems] = useState<ReviewQueueItem[]>([]);
  const [busy, setBusy] = useState(true);
  const [activeClaim, setActiveClaim] = useState<string | null>(null);
  const [editingClaim, setEditingClaim] = useState<string | null>(null);
  const [editedText, setEditedText] = useState("");
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");

  const claimItems = items.filter((item) => item.claim);
  const needsReview = claimItems.filter(({ claim }) => claim?.state === "needs_clinician").length;
  const suggested = claimItems.filter(({ claim }) => claim?.state === "review_suggested").length;

  const loadQueue = useCallback(async () => {
    setBusy(true);
    setError("");
    try {
      const response = await apiFetch(`${API}/review-queue`);
      if (!response.ok) {
        throw new Error(`Queue request failed (${response.status}): ${await response.text()}`);
      }
      setItems(await response.json());
    } catch (e) {
      setError(e instanceof Error ? e.message : "Unable to load the review queue.");
    } finally {
      setBusy(false);
    }
  }, []);

  useEffect(() => { void loadQueue(); }, [loadQueue]);

  async function review(claimId: string, action: ReviewAction, editText?: string) {
    if (action === "edit" && !editText?.trim()) {
      setError("Enter a non-empty explanation before saving the edit.");
      return;
    }
    setActiveClaim(claimId);
    setError("");
    setNotice("");
    try {
      const response = await apiFetch(`${API}/claims/${claimId}/review`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          action,
          reviewer: "demo-reviewer",
          ...(action === "edit" ? { edited_text: editText!.trim() } : {}),
        }),
      });
      if (!response.ok) {
        throw new Error(`Review failed (${response.status}): ${await response.text()}`);
      }
      if (action === "edit") {
        setNotice("Edit recorded. This claim remains unverified and requires re-verification before it is used.");
        setEditingClaim(null);
        setEditedText("");
      } else if (action === "reject") {
        setNotice("Rejection recorded. The claim remains unverified.");
      } else {
        setNotice("Approval recorded as a workflow decision. The claim is not marked clinically verified.");
      }
      await loadQueue();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Unable to record the review.");
    } finally {
      setActiveClaim(null);
    }
  }

  async function markSourceReviewed(documentId: string, sentenceId: string) {
    const key = `${documentId}-${sentenceId}`;
    setActiveClaim(key);
    setError("");
    setNotice("");
    try {
      const response = await apiFetch(`${API}/documents/${documentId}/sentences/${sentenceId}/review`, { method: "POST" });
      if (!response.ok) throw new Error(`Review failed (${response.status}): ${await response.text()}`);
      setNotice(`Source sentence ${sentenceId} marked reviewed. No clinical fact was created automatically.`);
      await loadQueue();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Unable to record the source review.");
    } finally {
      setActiveClaim(null);
    }
  }

  return (
    <main className="queue-page">
      <header className="queue-header">
        <Link href="/" className="brand-lockup" aria-label="Discharge Explainer home"><span className="brand-mark">d</span><span>Discharge <b>Explainer</b></span></Link>
        <div className="queue-nav"><span className="nav-current">Review queue</span><Link href="/">Explainer</Link></div>
      </header>

      <section className="queue-intro">
        <div>
          <p className="eyebrow"><span className="eyebrow-dot" /> Synthetic prototype · Human review</p>
          <h1>Reviewer queue</h1>
          <p className="intro-copy">A focused workspace for reviewing explanations and recording workflow decisions.</p>
        </div>
        <button type="button" onClick={() => void loadQueue()} disabled={busy} className="refresh-button"><span aria-hidden="true">↻</span>{busy ? "Refreshing" : "Refresh queue"}</button>
      </section>

      <section className="queue-stats" aria-label="Queue summary">
        <div className="stat-card"><span className="stat-label">Awaiting review</span><strong>{busy || (error && items.length === 0) ? "—" : items.length}</strong><span className="stat-note">Claims and source sentences</span></div>
        <div className="stat-card stat-alert"><span className="stat-label">Clinician attention</span><strong>{busy || (error && items.length === 0) ? "—" : needsReview}</strong><span className="stat-note">Requires clinician review</span></div>
        <div className="stat-card"><span className="stat-label">Review suggested</span><strong>{busy || (error && items.length === 0) ? "—" : suggested}</strong><span className="stat-note">Additional review recommended</span></div>
        <div className="workflow-note"><span className="workflow-icon" aria-hidden="true">i</span><p>Approval records a workflow action. It does not mark a claim clinically verified.</p></div>
      </section>

      <div className="queue-list-heading"><div><p className="eyebrow">WORKSPACE</p><h2>Items to review</h2></div><span className="queue-count">{busy ? "Loading" : error && items.length === 0 ? "Unavailable" : `${items.length} ${items.length === 1 ? "item" : "items"}`}</span>
      </div>

      <div className="queue-content">

      {error && <div role="alert" className="queue-message queue-error">{error}</div>}
      {notice && <div role="status" className="queue-message queue-success">{notice}</div>}
      {busy ? <div className="queue-empty"><span className="loading-dot"/><p>Loading the review queue…</p></div> : error && items.length === 0 ? (
        <div className="queue-empty"><span className="empty-error">!</span><h3>Queue couldn’t load</h3><p>Check the backend connection, then try again.</p><button type="button" onClick={() => void loadQueue()} className="action-secondary retry-button">Try again</button></div>
      ) : items.length === 0 ? (
        <div className="queue-empty"><span className="empty-check">✓</span><h3>You’re all caught up</h3><p>There are no claims waiting for review right now.</p></div>
      ) : items.map((item) => {
        const { document_id, source_name, claim, source_sentences = [], reviewer_questions = [] } = item;
        if (!claim && item.source_sentence) return (
          <article key={`${document_id}-${item.source_sentence.id}`} className="queue-card">
            <div className="claim-topline"><div><span className="claim-id">{item.source_sentence.id}</span><span className="claim-doc">Document {document_id}</span></div><span className="rounded-full border px-3 py-1 text-xs font-semibold text-amber-800">No fact linked · review</span></div>
            <p className="source-name"><span aria-hidden="true">↳</span> {source_name}</p>
            <p className="claim-copy">{item.source_sentence.text}</p>
            <div className="reason-box"><span className="detail-label">WHY THIS NEEDS REVIEW</span><p>No extracted fact is linked to this sentence. It may contain clinically important information, so a reviewer should assess it.</p></div>
            <button type="button" onClick={() => void markSourceReviewed(document_id, item.source_sentence!.id)} disabled={activeClaim !== null} className="action-primary">{activeClaim === `${document_id}-${item.source_sentence.id}` ? "Saving…" : "Mark source sentence reviewed"}</button>
          </article>
        );
        if (!claim) return null;
        return (
        <article key={claim.id} className="queue-card">
          <div className="claim-topline">
            <div><span className="claim-id">{claim.id}</span><span className="claim-doc">Document {document_id}</span></div>
            <span className={`rounded-full border px-3 py-1 text-xs font-semibold ${statusClasses(claim.state)}`}>{STATUS_LABELS[claim.state]}</span>
          </div>
          <p className="source-name"><span aria-hidden="true">↳</span> {source_name}</p>
          <p className="mt-1 text-xs text-slate-500">Language: {claim.language === "en" ? "English" : `${LANGUAGE_NAMES[claim.language] ?? claim.language} · machine translation, not validated`}</p>
          {claim.language !== "en" && <p role="note" className="mt-2 rounded-lg border border-amber-300 bg-amber-50 p-3 text-sm text-amber-950">Have a qualified bilingual reviewer compare this translation with the English source before use.</p>}
          {typeof claim.review_priority_score === "number" && <p className="mt-2 text-xs text-slate-500">Review priority score: {claim.review_priority_score.toFixed(2)} / 1.00 · higher scores appear first; not a probability.</p>}
          {editingClaim === claim.id ? (
            <div className="edit-panel">
              <label htmlFor={`queue-edit-${claim.id}`}>Edit explanation</label>
              <textarea id={`queue-edit-${claim.id}`} value={editedText} onChange={(event) => setEditedText(event.target.value)} rows={4} />
              <div className="action-row">
                <button type="button" onClick={() => void review(claim.id, "edit", editedText)} disabled={activeClaim !== null || !editedText.trim()} className="action-primary">{activeClaim === claim.id ? "Saving…" : "Save edit"}</button>
                <button type="button" onClick={() => { setEditingClaim(null); setEditedText(""); }} disabled={activeClaim !== null} className="action-secondary">Cancel</button>
              </div>
            </div>
          ) : <p className="claim-copy">{claim.text}</p>}
          {claim.source_language_text && claim.language !== "en" && <details className="source-details"><summary>English draft for comparison</summary><div className="source-detail-body"><p>{claim.source_language_text}</p></div></details>}
          <div className="reference-row" aria-label="Source sentence references"><span className="detail-label">SOURCES</span>
            <div className="reference-pills">{claim.source_ids.map((id) => <span key={id}>{id}</span>)}{claim.source_ids.length === 0 && <span className="no-reference">No source references provided.</span>}</div>
          </div>
          {source_sentences.length > 0 && <details className="source-details"><summary>View supporting source text <span>{source_sentences.length} {source_sentences.length === 1 ? "sentence" : "sentences"}</span></summary><div className="source-detail-body">{source_sentences.map((sentence) => <p key={sentence.id}><span>{sentence.id}</span>{sentence.text}</p>)}</div></details>}
          <div className="reason-box"><span className="detail-label">WHY THIS NEEDS REVIEW</span>{meaningfulReasons(claim.reason_codes).length > 0 ? <ul>{meaningfulReasons(claim.reason_codes).map((reason) => <li key={reason}><strong>{checkLabel(reason)}: </strong>{reasonDescription(reason)}</li>)}</ul> : <p>Configured checks found no specific discrepancy. Human review is still required because automated checks cannot establish clinical correctness.</p>}</div>
          {reviewer_questions.length > 0 && <details className="source-details"><summary>Reviewer-only clarification prompts <span>{reviewer_questions.length}</span></summary><div className="source-detail-body">{reviewer_questions.map((question) => <p key={question}>{question}</p>)}</div></details>}
          {claim.review_history?.length > 0 && <details className="source-details"><summary>Review audit history <span>{claim.review_history.length} actions</span></summary><div className="source-detail-body">{claim.review_history.map((entry, index) => <p key={`${entry.action}-${index}`}>{entry.reviewer} recorded {entry.action}: {STATUS_LABELS[entry.state_before]} → {STATUS_LABELS[entry.state_after]}{entry.note ? ` · ${entry.note}` : ""}</p>)}</div></details>}
          <details className="source-details verification-details">
            <summary>Verification results <span>{verificationRows(claim.checks).length} checks</span></summary>
            <div className="source-detail-body verification-result-list">
              {verificationRows(claim.checks).map(([name, result]) => {
                const detail = claim.check_details?.[name];
                const explanation = verificationDetailMessage(detail, name, result, claim.reason_codes);
                const detailObject = detail && typeof detail === "object" ? detail : undefined;
                const showEvidence = result !== "passed" && result !== "informational" && result !== "not_run" && result !== "not_configured" && result !== "not_applicable";
                return <details key={name} className="verification-result" open={result === "failed" || result === "review_suggested"}>
                  <summary><strong>{checkLabel(name)}</strong><span className={`verification-status ${checkClasses(result ?? "not_run")}`}>{result ? checkLabel(result) : "Status unavailable"}</span></summary>
                  <p className="verification-explanation">{checkPurpose(name)}</p>
                  {explanation && <p className="verification-explanation"><strong>Finding:</strong> {explanation}</p>}
                  {showEvidence && <div className="verification-evidence">
                    <p><strong>Source wording:</strong> {detailObject?.source_text || source_sentences.map((sentence) => sentence.text).join(" ") || "The cited source sentence is unavailable."}</p>
                    <p><strong>Generated explanation:</strong> {detailObject?.claim_text || claim.text}</p>
                  </div>}
                  {result !== "passed" && result !== "informational" && result !== "not_applicable" && <p className="verification-explanation"><strong>Action:</strong> {claim.state === "needs_clinician" ? "Clinician review required before use." : "Additional review required before this claim can be approved in the workflow."}</p>}
                </details>;
              })}
            </div>
          </details>
          <div className="action-row card-actions">
            {editingClaim !== claim.id && <>
              <button type="button" onClick={() => void review(claim.id, "approve")} disabled={activeClaim !== null} className="action-primary">{activeClaim === claim.id ? "Saving…" : "Record approval"}</button>
              <button type="button" onClick={() => { setEditingClaim(claim.id); setEditedText(claim.text); setError(""); }} disabled={activeClaim !== null} className="action-secondary">Edit explanation</button>
              <button type="button" onClick={() => void review(claim.id, "reject")} disabled={activeClaim !== null} className="action-danger">Record rejection</button>
            </>}
          </div>
        </article>
      ); })}
      </div>
      <footer className="queue-footer"><span>Discharge Explainer · Reviewer workspace</span><span>Configured SQLite database · Synthetic data only</span></footer>
    </main>
  );
}
