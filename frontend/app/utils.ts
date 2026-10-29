import type { Claim } from "./types";

export const VERIFICATION_CHECKS = ["source_ids", "fact_extraction", "exact_match", "risk_rules", "ambiguous_medication_details", "medication_names", "medication_context", "high_alert_medication", "unsupported_details", "numeric_details", "instruction_polarity", "clause_preservation", "synonym_drift", "medication_contradictions", "entailment_judge", "back_translation", "translation", "translation_judge"] as const;
const CHECK_PURPOSES: Record<string, string> = {
  source_ids: "Checks that the claim and its linked facts point to valid source sentences.",
  fact_extraction: "Checks that the claim has linked extracted facts to compare against.",
  exact_match: "Checks whether the claim wording exactly matches a source sentence or linked fact. A match does not establish clinical safety.",
  medication_context: "Checks whether a medication class or purpose was added beyond the source wording.",
  risk_rules: "Compares medication dose, frequency, duration, and timing with the linked medication instructions, and flags configured safety concerns.",
  ambiguous_medication_details: "Checks whether numeric medication details can be identified as a clear dose or schedule.",
  medication_names: "Checks configured medication names in the claim against the linked medication facts.",
  high_alert_medication: "Checks for medications on the prototype's configured high-alert list.",
  unsupported_details: "Checks for clinician attributions or other details that are not supported by linked facts.",
  numeric_details: "Checks whether numbers and dates in the claim appear in the linked facts.",
  instruction_polarity: "Checks that negation and stop or continue instructions have not changed.",
  clause_preservation: "Checks that source exceptions and conditions remain in the explanation.",
  synonym_drift: "Checks for wording substitutions that change the source's clinical meaning.",
  medication_contradictions: "Checks linked medication facts for conflicting directions.",
  entailment_judge: "Checks whether the linked facts support the meaning of the claim.",
  back_translation: "Checks a translated claim by translating it back and comparing its meaning with the original.",
  warning_sign_urgency: "Checks that an urgent warning-sign instruction keeps its response level in the explanation.",
  translation: "Checks preservation of medication names and numeric details. This does not verify the full meaning of the translation.",
  translation_judge: "A second model pass checks the selected translation against the English for omissions, additions, meaning changes, and clarity. It may suggest a correction, but does not replace qualified human review.",
};
export function checkPurpose(name: string): string {
  return CHECK_PURPOSES[name as keyof typeof CHECK_PURPOSES] ?? "Describes the verification performed for this category.";
}
export function verificationRows(checks?: Record<string, string | null> | null) {
  const supplied = checks && typeof checks === "object" ? checks : {};
  const names = [...VERIFICATION_CHECKS, ...Object.keys(supplied).filter((name) => !VERIFICATION_CHECKS.includes(name as typeof VERIFICATION_CHECKS[number]))];
  return names
    .filter((name) => typeof supplied[name] === "string" && supplied[name]!.trim())
    .filter((name) => supplied[name] !== "not_applicable")
    .map((name) => [name, supplied[name]!] as const);
}
export function meaningfulReasons(reasons?: Array<string | null> | null): string[] {
  return Array.isArray(reasons) ? Array.from(new Set(reasons.filter((reason): reason is string => typeof reason === "string" && reason.trim().length > 0 && reason.trim() !== "-").map((reason) => reason.trim()))) : [];
}

export function verificationDetailMessage(
  detail: { message?: string | null } | string | null | undefined,
  check: string,
  status: string | null,
  reasons?: Array<string | null> | null,
): string {
  const suppliedMessage = typeof detail === "string" ? detail : detail?.message;
  if (typeof suppliedMessage === "string" && suppliedMessage.trim()) return suppliedMessage.trim();
  if (status) return checkFailureDescription(check, status, reasons) ?? "No additional details were returned for this check.";
  return "No status or additional details were returned for this check.";
}

export function claimOverviewCounts(claims: Array<{ state: string }>) {
  return claims.reduce((counts, claim) => {
    if (claim.state === "needs_clinician") counts.needsClinician += 1;
    else if (claim.state === "review_suggested") counts.reviewSuggested += 1;
    else if (claim.state === "verified") counts.verified += 1;
    else if (claim.state === "source_supported") counts.sourceSupported += 1;
    return counts;
  }, { needsClinician: 0, reviewSuggested: 0, sourceSupported: 0, verified: 0 });
}

export const API = (
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000"
).replace(/\/+$/, ""); // strip any trailing slashes

export async function apiFetch(
  input: RequestInfo | URL,
  init: RequestInit = {},
): Promise<Response> {
  return fetch(input, init);
}

export const STATUS_LABELS: Record<Claim["state"], string> = {
  verified: "Verified",
  source_supported: "Source supported",
  review_suggested: "Review suggested",
  needs_clinician: "Needs clinician",
};

export function statusClasses(state: Claim["state"]): string {
  switch (state) {
    case "verified":
      return "border-slate-300 bg-slate-100 text-slate-800";

    case "source_supported":
      return "border-emerald-200 bg-emerald-50 text-emerald-800";

    case "review_suggested":
      return "border-blue-200 bg-blue-50 text-blue-800";

    case "needs_clinician":
      return "border-rose-200 bg-rose-50 text-rose-800";
  }
}

const CHECK_LABELS: Record<string, string> = {
  sources: "Source references",
  fact_extraction: "Fact extraction mode",
  structured_extraction_requires_review: "Structured extraction requires human review",
  source_ids: "Source references",
  facts: "Fact references",
  exact_match: "Exact text match",
  source_supported: "Source supported",
  medication_context: "Medication class or purpose",
  numeric_details: "Numbers and dates",
  instruction_polarity: "Negation and instruction wording",
  clause_preservation: "Exceptions and conditions",
  synonym_drift: "Clinical wording drift",
  medication_contradictions: "Medication instruction conflicts",
  medication_consistency: "Medication consistency",
  risk_rules: "Medication risk rules",
  unsupported_details: "Unsupported details",
  ambiguous_medication_details: "Ambiguous medication dose or schedule",
  high_alert_medication: "High-alert medication",
  medication_names: "Known medication names",
  unsupported_medication_name: "Medication name not found in linked source",
  unsupported_numeric_detail: "Unsupported number or date",
  unsupported_attribution: "Unsupported clinician attribution",
  translation_protected_detail_missing: "Translation changed a protected detail",
  translation_requires_human_review: "Translation needs bilingual review",
  translation_failed: "Translation failed",
  ocr_source_requires_review: "OCR source needs review",
  unsupported_claim_detail: "Claim detail not supported by linked source facts",
  uncertain_claim_entailment: "Claim support is uncertain and needs review",
  entailment_judge_failed: "Claim support check could not run",
  instruction_polarity_mismatch: "Negation or instruction wording changed",
  source_clause_omitted: "Source exception or condition omitted",
  clinical_synonym_drift: "Clinical wording changed meaning",
  contradictory_medication_instructions: "Conflicting medication instructions",
  high_alert_medication_review: "High-alert medication needs review",
  appointment_timeframes: "Appointment timeframe",
  entailment: "Clinical entailment",
  back_translation: "Back-translation",
  translation_judge: "Translation review",
  warning_sign_urgency: "Warning-sign urgency",
  as_needed_duration_added: "As-needed wording changed",
  warning_sign_escalation_softened: "Urgent response level softened",
  human_review_recommended: "Human review still recommended",
  passed: "Passed",
  failed: "Failed",
  failed_or_not_exact: "Wording differs",
  informational: "Wording differs · informational",
  not_run: "Not run",
  not_applicable: "Not applicable",
  not_configured: "Not configured",
  review_suggested: "Review suggested",
  corrected: "Correction suggested",
  flagged: "Flagged for review",
};

export function checkLabel(value: string): string {
  if (CHECK_LABELS[value]) {
    return CHECK_LABELS[value];
  }

  return value
    .replaceAll("_", " ")
    .replace(/\b\w/g, (character) => character.toUpperCase());
}

export function checkClasses(result: string): string {
  if (result === "passed") {
    return "text-emerald-700";
  }

  if (
    result === "failed"
  ) {
    return "text-rose-700";
  }

  if (["not_applicable", "not_configured", "not_run", "informational", "failed_or_not_exact"].includes(result)) {
    return "text-slate-500";
  }

  return "text-amber-700";
}

const REASON_DETAILS: Record<string, string> = {
  translation_protected_detail_missing:
    "A medication name, number, dose, unit, or date changed or disappeared during translation. Compare both the source sentence and English draft.",
  translation_requires_human_review:
    "Protected tokens were preserved, but translation meaning has not been independently validated. A bilingual human reviewer must check it.",
  translation_failed:
    "Local translation did not complete. The English claim is retained and must be reviewed.",
  ocr_source_requires_review:
    "Local OCR produced the source text. Compare the recognized text with the scanned page before relying on the explanation.",
  invalid_or_missing_source:
    "The claim is missing a valid source sentence, or its cited sentence does not support the linked fact. A reviewer cannot trace this explanation reliably to the document.",
  invalid_or_missing_fact:
    "One or more facts linked to this claim are missing or invalid. The verification checks could not compare the explanation against a reliable set of extracted facts.",
  medication_dose_mismatch:
    "The medication dose in the generated explanation differs from the dose found in the linked medication instruction. Do not use the generated dose until a clinician compares both wordings.",
  medication_frequency_mismatch:
    "The medication frequency in the generated explanation differs from the frequency found in the linked source instruction. The system cannot determine which schedule is correct; a clinician must review it.",
  as_needed_duration_added:
    "The source says to take this medicine as needed. The explanation changes that to “as long as needed,” which can read like a duration. Preserve the as-needed wording.",
  warning_sign_escalation_softened:
    "The source says to seek urgent medical care, but the explanation tells the patient to see a doctor. That may lower the response level; preserve the urgent escalation instruction.",
  human_review_recommended:
    "Configured checks found no specific discrepancy. This prototype leaves claims in human review because passing checks do not establish clinical correctness.",
  medication_frequency_requires_clinician_review:
    "The explicit source frequency exceeds the prototype's configured review threshold. The system has not inferred or substituted another schedule; a clinician must assess the original instruction.",
  medication_duration_mismatch:
    "The treatment duration in the generated explanation differs from the duration stated in the linked source instruction. A clinician should confirm the intended duration before this explanation is used.",
  ambiguous_medication_schedule:
    "The source medication wording does not establish a clear schedule. The generated explanation may have interpreted that wording, so a clinician must clarify the intended instructions.",
  ambiguous_medication_details:
    "The source medication wording does not contain a schedule the verifier can confidently identify. This is uncertainty, not confirmation that the generated instruction is correct.",
  unsupported_attribution:
    "The explanation says a doctor or other clinician gave an instruction, but the linked source facts do not say that. This attribution has been added without source support.",
  unsupported_numeric_detail:
    "The explanation contains a number or date that does not appear in the linked source facts. Check the generated wording against the original document before relying on it.",
  unsupported_medication_name:
    "A medication name in the explanation was not found among the configured medication names in the linked source. The system has not inferred or corrected the name; verify it against the document.",
  unsupported_medication_context:
    "The explanation adds a medication class or purpose that the source does not state. It may be true in general, but it is not supported by this document.",
  medication_name_unrecognized:
    "The configured medication-name list could not match a name in the explanation. This does not mean the name is incorrect; the system has not inferred or corrected it, so verify it against the source.",
  instruction_polarity_mismatch:
    "The explanation changes or omits an instruction such as stop, continue, or do not take. That can reverse the meaning of the source and needs direct review.",
  contradictory_medication_instructions:
    "The linked medication facts contain conflicting directions for the same recognized medication. The system cannot resolve the conflict; a clinician must review the original instructions.",
  high_alert_medication_review:
    "A medication in this claim matches the configured high-alert list. The explanation is flagged for clinician review under the prototype's safety rules.",
  structured_extraction_requires_review:
    "At least one linked fact came from structured model extraction. The source references are shown, but model extraction alone does not establish that every detail was preserved correctly.",
  verification_layers_not_fully_configured:
    "The verification results above name each layer that is not configured or did not run. This claim remains in review.",
  unsupported_claim_detail:
    "The explanation includes a detail that the linked source facts do not support. Review the generated text and source wording to identify the added information.",
  unsupported_details_check_incomplete:
    "The deterministic rules checked specific details, but the broader source-support judge is not configured. This check cannot establish that every other claim detail is supported.",
  uncertain_claim_entailment:
    "The local language model was inconclusive about this paraphrase. This is a weak screening signal; compare the wording with the source directly.",
  entailment_judge_failed:
    "The optional claim support check encountered an error and did not complete. No conclusion about whether the source supports the claim can be drawn from this check.",
  llm_generation_failed:
    "Explanation generation failed. The displayed text may be incomplete or unavailable and should not be used as a reliable explanation.",
  llm_generation_not_configured:
    "Explanation generation is not configured, so the system could not produce and verify a generated explanation.",
  translation_not_configured:
    "Translation verification is not configured. The translated wording has not been independently checked by this layer.",
  medication_timing_mismatch:
    "The explanation changes when the medication should be taken, such as morning, evening, or with food. A clinician should compare the two instructions.",
  unsupported_medication_frequency:
    "The source does not establish the frequency stated in the generated medication explanation. A clinician must clarify it before use.",
  medication_attribute_unrecognized:
    "The medication schedule includes wording the verifier could not interpret reliably. This comparison is incomplete and must not be treated as a pass.",
  interpreted_ambiguous_medication_schedule:
    "The generated explanation turns an ambiguous source schedule into a definite frequency or duration that the source does not establish.",
  human_rejected:
    "A reviewer rejected this claim. It must not be presented as approved or verified.",
  human_edit_requires_reverification:
    "A reviewer edited this explanation. The edited text must be checked against the source again before it can be relied on.",
};

export function reasonDescription(reason: string): string {
  return REASON_DETAILS[reason] ??
    `The verification process flagged “${checkLabel(reason)}”. The available result does not include a more specific explanation, so compare the generated explanation with its linked source text and have a reviewer resolve the issue.`;
}

export function checkFailureDescription(
  check: string,
  status: string,
  reasonCodes?: Array<string | null> | null,
): string | null {
  if (check === "back_translation" && status === "passed") {
    return "The English back-translation was consistent with the original English claim in the details assessed. This model-based screening does not validate translation quality; a qualified bilingual reviewer must still review the translation.";
  }
  if (check === "back_translation" && status === "review_suggested") {
    return "The English back-translation left meaning uncertain. A qualified bilingual reviewer must compare the source, translation, and round trip.";
  }
  if (check === "exact_match" && ["failed_or_not_exact", "informational"].includes(status)) {
    return "The wording differs from the source. This is informational and does not count as a verification failure.";
  }
  if (check === "medication_names" && status === "not_configured") {
    return "Medication-name validation was not configured, so this check did not establish whether the name is recognized. The system has not corrected or replaced the name.";
  }
  const reasonForCheck: Record<string, string[]> = {
    source_ids: ["invalid_or_missing_source", "invalid_or_missing_fact"],
    fact_extraction: ["structured_extraction_requires_review"],
    risk_rules: ["medication_dose_mismatch", "medication_frequency_mismatch", "as_needed_duration_added", "medication_duration_mismatch", "medication_timing_mismatch", "unsupported_medication_frequency", "medication_attribute_unrecognized", "medication_frequency_requires_clinician_review", "ambiguous_medication_schedule", "interpreted_ambiguous_medication_schedule"],
    ambiguous_medication_details: ["ambiguous_medication_details"],
    medication_names: ["unsupported_medication_name", "medication_name_unrecognized"],
    high_alert_medication: ["high_alert_medication_review"],
    unsupported_details: ["unsupported_attribution", "unsupported_claim_detail", "unsupported_medication_frequency", "interpreted_ambiguous_medication_schedule", "uncertain_claim_entailment", "unsupported_details_check_incomplete"],
    numeric_details: ["unsupported_numeric_detail"],
    instruction_polarity: ["instruction_polarity_mismatch"],
    clause_preservation: ["source_clause_omitted"],
    synonym_drift: ["clinical_synonym_drift"],
    medication_contradictions: ["contradictory_medication_instructions"],
    entailment_judge: ["uncertain_claim_entailment", "entailment_judge_failed"],
    warning_sign_urgency: ["warning_sign_escalation_softened"],
    back_translation: ["unsupported_claim_detail", "uncertain_claim_entailment", "entailment_judge_failed"],
  };
  const matchingReasons = meaningfulReasons(reasonCodes).filter((reason) => reasonForCheck[check]?.includes(reason));
  if (matchingReasons.length) return matchingReasons.map(reasonDescription).join(" ");
  if (status === "failed") {
    return "This check ran and detected a problem. Compare the source wording and generated explanation below to see what needs review.";
  }
  if (status === "not_run" || status === "not_configured") {
    return "This check did not run, so it provides no evidence that the explanation is correct.";
  }
  if (status === "review_suggested") {
    return "This check identified uncertainty that needs human review before the explanation is relied on.";
  }
  if (status === "passed") {
    return "This check ran and found no issue in the information it evaluates. It does not establish clinical correctness by itself.";
  }
  if (status === "not_applicable") {
    return "This check does not apply to this claim type.";
  }
  if (status === "failed_or_not_exact") {
    return "The wording differs from the source. A wording difference alone does not establish a change in meaning.";
  }
  if (status === "informational") {
    return "The wording differs from the source. This is informational and does not count as a verification failure.";
  }
  return null;
}
