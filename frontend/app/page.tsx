"use client";

import { useRef, useState } from "react";
import Link from "next/link";
import { ClaimCard } from "./components/ClaimCard";
import { SourceSentences } from "./components/SourceSentences";
import { SYNTHETIC_SAMPLES } from "./samples";
import { LANGUAGE_NAMES, OUTPUT_LANGUAGES } from "./languages";
import type {
  ClaimReview,
  Claim,
  DocumentRecord,
  ReviewAction,
} from "./types";
import { API, apiFetch, claimOverviewCounts } from "./utils";

export default function Home() {
  const [text, setText] = useState(SYNTHETIC_SAMPLES[0].text);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [isDraggingFile, setIsDraggingFile] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [selectedSampleId, setSelectedSampleId] = useState("");

  const [doc, setDoc] = useState<DocumentRecord | null>(null);
  const [language, setLanguage] = useState("en");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [selectedSource, setSelectedSource] = useState<string | null>(null);
const [reviewingClaim, setReviewingClaim] = useState<string | null>(null);
const [reviewError, setReviewError] = useState("");
  function handleSelectSource(sourceId: string, target: "source" | "claim") {
    setSelectedSource(sourceId);

    const targetClaim = claims.find((claim) => claim.source_ids.includes(sourceId));
    const targetId = target === "source"
      ? `source-${sourceId}`
      : targetClaim ? `claim-${targetClaim.id}` : `source-${sourceId}`;
    document.getElementById(targetId)?.scrollIntoView({
      behavior: "smooth",
      block: "center",
    });
  }

  async function submit() {
    setBusy(true);
    setError("");
    setDoc(null);
    setSelectedSource(null);

    try {
      let response: Response;
      if (selectedFile) {
        const formData = new FormData();
        formData.append("file", selectedFile);
        response = await apiFetch(`${API}/documents`, {
          method: "POST",
          body: formData,
        });
      } else {
        response = await apiFetch(`${API}/documents`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            text,
            source_name: "demo-pasted-summary",
          }),
        });
      }

      if (!response.ok) {
        throw new Error(
          `Document upload failed (${response.status}): ${await response.text()}`
        );
      }

      const created: DocumentRecord = await response.json();

      const explainResponse = await apiFetch(
        `${API}/documents/${created.id}/explain?lang=${language}`,
        { method: "POST" }
      );

      if (!explainResponse.ok) {
        throw new Error(
          `Explanation failed (${explainResponse.status}): ${await explainResponse.text()}`
        );
      }

      const result = await explainResponse.json();

      setDoc(result.document);
    } catch (e) {
      setError(
        e instanceof Error
          ? e.message
          : "Request failed. Is the backend running?"
      );
    } finally {
      setBusy(false);
    }
  }
  async function handleReview(
  claimId: string,
  action: ReviewAction,
  editedText?: string
): Promise<boolean> {
  setReviewingClaim(claimId);
  setReviewError("");

  const payload: {
    action: ReviewAction;
    reviewer: string;
    edited_text?: string;
  } = {
    action,
    reviewer: "demo-reviewer",
  };

  if (action === "edit") {
    if (!editedText?.trim()) {
      setReviewError("Please enter a non-empty explanation.");
      setReviewingClaim(null);
      return false;
    }

    payload.edited_text = editedText.trim();
  }

  try {
    const response = await apiFetch(`${API}/claims/${claimId}/review`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(payload),
    });

    if (!response.ok) {
      throw new Error(
        `Review failed (${response.status}): ${await response.text()}`
      );
    }

    const result: { state: Claim["state"]; document_id: string } = await response.json();

    const review: ClaimReview = {
      action,
      reviewer: payload.reviewer,
      ...(action === "edit"
        ? { edited_text: editedText!.trim() }
        : {}),
    };

    setDoc((current) => {
      if (!current) {
        return current;
      }

      return {
        ...current,
        claims: current.claims.map((claim) => {
          if (claim.id !== claimId) {
            return claim;
          }

          const updatedClaim = {
            ...claim,
            state: result.state,
            review,
          };

          if (action === "edit") {
            updatedClaim.text = editedText!.trim();

            if (
              !(updatedClaim.reason_codes ?? []).includes(
                "human_edit_requires_reverification"
              )
            ) {
              updatedClaim.reason_codes = [
                ...(updatedClaim.reason_codes ?? []),
                "human_edit_requires_reverification",
              ];
            }
          }

          return updatedClaim;
        }),
      };
    });

    return true;
  } catch (error) {
    setReviewError(
      error instanceof Error
        ? error.message
        : "Unable to record the review."
    );

    return false;
  } finally {
    setReviewingClaim(null);
  }
}

  async function deleteCurrentDocument() {
    if (!doc) return;
    setError("");
    try {
      const response = await apiFetch(`${API}/documents/${doc.id}`, { method: "DELETE" });
      if (!response.ok) {
        setError(`Document deletion failed (${response.status}): ${await response.text()}`);
        return;
      }
      setDoc(null);
      setSelectedSource(null);
    } catch {
      setError("Document deletion failed. Check the backend connection and try again.");
    }
  }

  const claims = doc?.claims ?? [];

  const { needsClinician, reviewSuggested, sourceSupported, verified } = claimOverviewCounts(claims);

  const selectedSentence = doc?.sentences.find(
    (sentence) => sentence.id === selectedSource
  );

  function chooseFile(file?: File) {
    if (!file) return;
    setSelectedFile(file);
    setSelectedSampleId("");
  }

  return (
    <main className="mx-auto max-w-7xl px-5 py-8 md:px-10 md:py-12">
      <header className="app-header mb-8">
        <div className="app-nav">
          <Link href="/" className="app-brand"><span className="brand-mark" aria-hidden="true">D</span><span>Care, made clearer</span></Link>
          <Link href="/review-queue" className="review-link">Reviewer queue <span aria-hidden="true">↗</span></Link>
        </div>
        <div className="hero-copy">
          <p className="eyebrow"><span className="eyebrow-dot" /> Discharge care · Demo</p>
          <h1>Understand what happens next.</h1>
          <p className="hero-description">Turn discharge notes into clear explanations linked to the original instructions.</p>
        </div>
      </header>

      <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm md:p-7">
        <div className="section-heading"><span className="step-number">1</span><div><h2 className="text-xl font-bold text-slate-950">Add a discharge summary</h2><p className="mt-1 text-sm leading-6 text-slate-600">Choose a synthetic file or use a sample note.</p></div></div>

        <p className="mt-2 text-sm leading-6 text-slate-600">Try a ready-made sample, paste demo text, or upload a synthetic PDF/TXT file.</p>

        <input
          ref={fileInputRef}
          id="summary-file"
          type="file"
          accept=".txt,.pdf,text/plain,application/pdf"
          onChange={(event) => {
            chooseFile(event.target.files?.[0]);
            event.currentTarget.value = "";
          }}
          className="sr-only"
        />

        <div
          role="button"
          tabIndex={0}
          aria-label="Choose a discharge summary file to upload"
          onClick={() => fileInputRef.current?.click()}
          onKeyDown={(event) => {
            if (event.key === "Enter" || event.key === " ") {
              event.preventDefault();
              fileInputRef.current?.click();
            }
          }}
          onDragOver={(event) => {
            event.preventDefault();
            setIsDraggingFile(true);
          }}
          onDragLeave={() => setIsDraggingFile(false)}
          onDrop={(event) => {
            event.preventDefault();
            setIsDraggingFile(false);
            chooseFile(event.dataTransfer.files?.[0]);
          }}
          className={`upload-dropzone mt-6 ${isDraggingFile ? "upload-dropzone-active" : ""} ${selectedFile ? "upload-dropzone-selected" : ""}`}
        >
          <span className="upload-icon" aria-hidden="true">
            {selectedFile ? "✓" : "↑"}
          </span>
          <span className="upload-title">
            {selectedFile ? selectedFile.name : "Drop your document here"}
          </span>
          <span className="upload-copy">
            {selectedFile
              ? `${(selectedFile.size / 1024).toFixed(0)} KB · ready to process`
              : "Click to browse or drag a synthetic file here"}
          </span>
          <span className="upload-formats">PDF or TXT · up to 5 MB</span>
        </div>

        <details open className="sample-panel mt-6 rounded-xl border border-slate-200 bg-slate-50 px-4 py-3">
          <summary className="cursor-pointer text-sm font-semibold text-slate-700">
            Try a sample or paste demo text
          </summary>

          <div className="mt-5 flex flex-wrap items-end gap-3">
            <div>
              <label
                htmlFor="sample-document"
                className="mb-2 block text-sm font-semibold text-slate-800"
              >
                Load a synthetic sample
              </label>
              <select
                id="sample-document"
                value={selectedSampleId}
                onChange={(event) => setSelectedSampleId(event.target.value)}
                className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm"
              >
                <option value="">Choose a sample</option>
                {SYNTHETIC_SAMPLES.map((sample) => (
                  <option key={sample.id} value={sample.id}>
                    {sample.title}
                  </option>
                ))}
              </select>
            </div>
            <button
              type="button"
              disabled={!selectedSampleId}
              onClick={() => {
                const sample = SYNTHETIC_SAMPLES.find(
                  (item) => item.id === selectedSampleId
                );
                if (sample) setText(sample.text);
                setSelectedFile(null);
              }}
              className="rounded-lg border border-slate-300 px-4 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50"
            >
              Load sample
            </button>
          </div>

          <label
            htmlFor="summary"
            className="mb-2 mt-5 block text-sm font-semibold text-slate-800"
          >
            Demo discharge summary text
          </label>

          <textarea
            id="summary"
            value={text}
            onChange={(event) => {
              setText(event.target.value);
              setSelectedSampleId("");
              setSelectedFile(null);
            }}
            rows={9}
            className="w-full rounded-xl border border-slate-300 bg-slate-50 p-4 font-mono text-sm leading-6 outline-none transition focus:border-slate-500 focus:ring-2 focus:ring-slate-200"
          />

        </details>

        <div className="submit-row mt-4 flex flex-wrap items-center gap-4">
          <label
            htmlFor="language"
            className="text-sm font-medium text-slate-700"
          >
            Output language
          </label>

          <select
            id="language"
            value={language}
            onChange={(event) => setLanguage(event.target.value)}
            className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm"
          >
            {OUTPUT_LANGUAGES.map(({ code, name }) => (
              <option key={code} value={code}>{name}</option>
            ))}
          </select>

          {language !== "en" && (
            <p role="note" className="basis-full rounded-lg border border-amber-300 bg-amber-50 p-3 text-sm text-amber-950">
              {LANGUAGE_NAMES[language] ?? language} output is machine-translated and not validated. A qualified bilingual reviewer must compare it with the English source before use.
            </p>
          )}

          <button
            onClick={submit}
            disabled={busy || (!selectedFile && !text.trim())}
            className="rounded-lg bg-slate-950 px-5 py-3 text-sm font-semibold text-white transition hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {busy ? <><span className="button-spinner" aria-hidden="true" /> Preparing explanation…</> : selectedFile ? "Explain this file" : "Explain this summary"}
          </button>
          {busy && language !== "en" && (
            <p role="status" aria-live="polite" className="basis-full text-sm text-slate-600">
              Translation runs claim by claim. For live progress and per-claim timing, check the backend terminal.
            </p>
          )}
        </div>

        {error && (
          <div
            role="alert"
            className="mt-4 whitespace-pre-wrap rounded-lg border border-rose-200 bg-rose-50 p-4 text-sm text-rose-800"
          >
            {error}
          </div>
        )}
      </section>

      {doc && (
        <>
          <section className="mt-8">
            {doc.input_warnings?.map((warning) => <div key={warning} role="alert" className="mb-4 rounded-lg border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900"><p>{warning}</p>{selectedFile?.name.toLowerCase().endsWith(".pdf") && <button type="button" onClick={() => window.open(URL.createObjectURL(selectedFile), "_blank", "noopener,noreferrer")} className="mt-2 font-semibold underline">Open the original PDF for comparison</button>}</div>)}
            <div className="mb-4">
              <div className="section-heading"><span className="step-number">2</span><div><h2 className="text-2xl font-bold text-slate-950">Review the explanation</h2><p className="mt-1 text-sm text-slate-600">Follow each item back to the source note.</p></div></div>

              <div className="flex flex-wrap items-center justify-between gap-3">
                <p className="mt-1 text-sm text-slate-600">Document ID: <span className="font-mono">{doc.id}</span></p>
                <button type="button" onClick={() => void deleteCurrentDocument()} className="rounded-lg border border-rose-300 px-3 py-2 text-sm font-semibold text-rose-800 hover:bg-rose-50">Delete document</button>
              </div>
            </div>

            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
              <div className="rounded-xl border border-slate-200 bg-white p-5">
                <p className="text-sm text-slate-500">Explanations</p>
                <p className="mt-2 text-3xl font-bold">{claims.length}</p>
              </div>

              <div className="rounded-xl border border-rose-200 bg-rose-50 p-5">
                <p className="text-sm text-rose-800">Needs clinician</p>
                <p className="mt-2 text-3xl font-bold text-rose-900">
                  {needsClinician}
                </p>
              </div>

              <div className="rounded-xl border border-blue-200 bg-blue-50 p-5">
                <p className="text-sm text-blue-800">Review suggested</p>
                <p className="mt-2 text-3xl font-bold text-blue-900">
                  {reviewSuggested}
                </p>
              </div>

              <div className="rounded-xl border border-emerald-200 bg-emerald-50 p-5">
                <p className="text-sm text-emerald-800">Source supported</p>
                <p className="mt-2 text-3xl font-bold text-emerald-900">{sourceSupported}</p>
              </div>

              <div className="rounded-xl border border-slate-200 bg-white p-5">
                <p className="text-sm text-slate-600">Marked verified</p>
                <p className="mt-2 text-3xl font-bold text-slate-800">
                  {verified}
                </p>
              </div>
            </div>

            <p className="mt-3 text-sm leading-6 text-slate-600">
              Exact source matches and narrowly recognized wording equivalents are marked source supported and leave the review queue. This confirms source fidelity only; it does not establish medical correctness.
            </p>
          </section>

          <section className="results-grid mt-8 grid items-start gap-6 lg:grid-cols-[0.9fr_1.1fr]">
            <SourceSentences
              doc={doc}
              selectedSource={selectedSource}
              onSelectSource={(sourceId) => handleSelectSource(sourceId, "claim")}
            />

            <div className="rounded-2xl border border-slate-200 bg-white p-5 md:p-6">
              <h2 className="text-xl font-bold text-slate-950">
                Plain-language explanations
              </h2>

              <p className="mb-5 mt-2 text-sm leading-6 text-slate-600">
                Inspect each explanation, follow its source references, and
                review the checks that were actually performed.
              </p>
              {reviewError && (
                <div
                  role="alert"
                  className="mb-4 whitespace-pre-wrap rounded-lg border border-rose-200 bg-rose-50 p-3 text-sm text-rose-800"
                >
                  {reviewError}
                </div>
              )}

              {claims.length === 0 && (
                <p className="rounded-lg bg-slate-50 p-4 text-sm text-slate-600">
                  No claims were generated for this document.
                </p>
              )}

             {claims.map((claim) => (
              <ClaimCard
                key={claim.id}
                claim={claim}
                doc={doc}
                onSelectSource={(sourceId) => handleSelectSource(sourceId, "source")}
                onReview={handleReview}
                reviewing={reviewingClaim === claim.id}
              />
            ))}
            </div>
          </section>

          {selectedSentence && (
            <section className="mt-6 rounded-xl border border-blue-200 bg-blue-50 p-4">
              <h2 className="font-semibold text-blue-950">
                Selected source: {selectedSentence.id}
              </h2>

              <p className="mt-2 text-sm leading-6 text-blue-950">
                {selectedSentence.text}
              </p>
            </section>
          )}

        </>
      )}

      <footer className="mt-10 border-t border-slate-200 pt-5 text-sm leading-6 text-slate-500">
        Discharge Explainer prototype · Synthetic data only · Automated
        verification is not a clinical determination.
      </footer>
    </main>
  );
}
