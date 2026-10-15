from enum import Enum
from typing import Literal
from pydantic import BaseModel, Field
from datetime import datetime, timezone

FactKind = Literal[
    "diagnosis",
    "medication",
    "appointment",
    "restriction",
    "warning_sign",
    "pending_test",
    "allergy",
    "symptom",
    "vital",
    "date",
]


class State(str, Enum):
    VERIFIED = "verified"
    SOURCE_SUPPORTED = "source_supported"
    REVIEW_SUGGESTED = "review_suggested"
    NEEDS_CLINICIAN = "needs_clinician"
    PENDING_VERIFACATION = "pending_verification"


class ReviewAction(str, Enum):
    APPROVE = "approve"
    EDIT = "edit"
    REJECT = "reject"


class Sentence(BaseModel):
    id: str
    text: str
    section: str = "unknown"


class Fact(BaseModel):
    id: str
    kind: FactKind
    text_en: str
    attrs: dict[str, str] = Field(default_factory=dict)
    source_ids: list[str]


class ClaimReviewRequest(BaseModel):
    action: ReviewAction
    reviewer: str = "demo-reviewer"
    note: str | None = None
    edited_text: str | None = None


class VerificationCheck(BaseModel):
    name: str
    status: str
    reason_code: str | None = None
    message: str
    source_text: str | None = None
    claim_text: str
    performed: bool


class ClaimReviewAuditEntry(ClaimReviewRequest):
    state_before: State
    state_after: State


class Claim(BaseModel):
    id: str
    text: str
    language: Literal["en", "hi", "bn", "gu", "kn", "ml", "mr", "or", "pa", "ta", "te"] = "en"
    review_priority_score: float | None = None
    source_language_text: str | None = None
    fact_ids: list[str]
    source_ids: list[str]
    state: State = State.NEEDS_CLINICIAN
    reason_codes: list[str] = Field(default_factory=list)
    checks: dict[str, str] = Field(default_factory=dict)
    check_details: dict[str, VerificationCheck] = Field(default_factory=dict)
    review: ClaimReviewRequest | None = None
    review_history: list[ClaimReviewAuditEntry] = Field(default_factory=list)


class DocumentCreateRequest(BaseModel):
    text: str
    source_name: str | None = None


class DocumentRecord(BaseModel):
    id: str
    source_name: str
    original_text: str
    sentences: list[Sentence]
    facts: list[Fact] = Field(default_factory=list)
    claims: list[Claim] = Field(default_factory=list)
    status: str = "uploaded"
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    input_warnings: list[str] = Field(default_factory=list)
    reviewed_source_sentence_ids: list[str] = Field(default_factory=list)


class ExplainResponse(BaseModel):
    document: DocumentRecord
    doctor_questions: list[str]


class ReviewQueueItem(BaseModel):
    item_type: Literal["claim", "source_sentence"] = "claim"
    document_id: str
    source_name: str
    claim: Claim | None = None
    source_sentences: list[Sentence] = Field(default_factory=list)
    source_sentence: Sentence | None = None
    reviewer_questions: list[str] = Field(default_factory=list)


class ReviewResult(BaseModel):
    claim_id: str
    document_id: str
    recorded: bool
    state: State
    reviewer_action: ReviewAction
