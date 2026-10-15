export type Sentence = {
  id: string;
  text: string;
  section: string;
};

export type Fact = {
  id: string;
  kind: string;
  text_en: string;
  attrs: Record<string, string>;
  source_ids: string[];
};

export type ReviewAction = "approve" | "edit" | "reject";

export type ClaimReview = {
  action: ReviewAction;
  reviewer: string;
  note?: string | null;
  edited_text?: string | null;
};

export type VerificationCheck = {
  name: string;
  status: string;
  reason_code?: string | null;
  message: string;
  source_text?: string | null;
  claim_text: string;
  performed: boolean;
};

export type ClaimReviewAuditEntry = ClaimReview & {
  state_before: Claim["state"];
  state_after: Claim["state"];
};

export type Claim = {
  id: string;
  text: string;
  language: string;
  review_priority_score?: number | null;
  source_language_text?: string | null;
  fact_ids: string[];
  source_ids: string[];
  state: "verified" | "source_supported" | "review_suggested" | "needs_clinician";
  reason_codes?: Array<string | null> | null;
  checks?: Record<string, string | null> | null;
  check_details?: Record<string, Partial<VerificationCheck> | string | null> | null;
  review?: ClaimReview | null;
  review_history: ClaimReviewAuditEntry[];
};

export type DocumentRecord = {
  id: string;
  source_name: string;
  original_text: string;
  sentences: Sentence[];
  facts: Fact[];
  claims: Claim[];
  status: string;
  created_at: string;
  input_warnings: string[];
};

export type ReviewQueueItem = {
  item_type: "claim" | "source_sentence";
  document_id: string;
  source_name: string;
  claim?: Claim | null;
  source_sentences: Sentence[];
  source_sentence?: Sentence | null;
  reviewer_questions: string[];
};
