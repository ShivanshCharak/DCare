from __future__ import annotations

import io
import logging
import re
import shutil
import uuid
from typing import Optional

import pdfplumber
import json
from fastapi import FastAPI, File, HTTPException, Query, UploadFile, Request
from fastapi.middleware.cors import CORSMiddleware
from app.config import settings

from .models import (
    ClaimReviewRequest,
    ClaimReviewAuditEntry,
    DocumentCreateRequest,
    DocumentRecord,
    ExplainResponse,
    ReviewQueueItem,
    ReviewResult,
    Sentence,
    ReviewAction,
)
from .middleware import MaxRequestBodySize
from app.models import State
from .store import store
from .pipeline.parse import parse_and_split
from .pipeline.extract import validate_fact_sources
from .pipeline.structured_extract import extract_facts
from .pipeline.explain import explain_facts
from .pipeline.verify import verify_claims
from .pipeline.route import build_doctor_questions, combine_states
from .pipeline.translate import LANGUAGES, translate_claims

app = FastAPI(title="Discharge Explainer API", version="0.1.0")
logger = logging.getLogger(__name__)
app.add_middleware(MaxRequestBodySize, max_bytes=settings.max_request_bytes)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        origin.strip() for origin in settings.cors_origins.split(",") if origin.strip()
    ],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health():
    return {"status": "ok", "environment": settings.app_env}


@app.get("/health/model")
@app.get("/health/amd", include_in_schema=False)
def model_health():
    # This reports configuration only; it does not claim the model is reachable.
    return {
        "configured": bool(settings.llm_base_url and settings.model_id),
        "base_url": settings.llm_base_url,
        "model_id": settings.model_id,
        "provider": "local Ollama native chat API (configuration only)",
        "benchmark": None,
    }


@app.post("/documents", response_model=DocumentRecord)
async def create_document(
    request: Request,
    file: Optional[UploadFile] = File(default=None),
):
    content_type = request.headers.get("content-type", "")
    ocr_used = False
    ocr_failed = False

    if "application/json" in content_type:
        try:
            body = await request.json()
            payload = DocumentCreateRequest.model_validate(body)

        except Exception as exc:
            raise HTTPException(
                status_code=422,
                detail=f"Invalid JSON document payload: {exc}",
            ) from exc

        if not payload.text.strip():
            raise HTTPException(
                status_code=422,
                detail="Document text cannot be empty.",
            )

        text = payload.text
        source_name = payload.source_name or "pasted-text"

    elif "multipart/form-data" in content_type:
        form = await request.form()
        payload_text = form.get("payload")

        if payload_text:
            try:
                if isinstance(payload_text, str):
                    payload_data = json.loads(payload_text)
                else:
                    payload_data = payload_text

                payload = DocumentCreateRequest.model_validate(payload_data)
            except Exception as exc:
                raise HTTPException(
                    status_code=422,
                    detail=f"Invalid JSON in multipart payload: {exc}",
                ) from exc

            if not payload.text.strip():
                raise HTTPException(
                    status_code=422,
                    detail="Document text cannot be empty.",
                )

            text = payload.text
            source_name = payload.source_name or "pasted-text"

        elif file is not None:
            raw = await file.read()
            source_name = file.filename or "uploaded-file"

            if source_name.lower().endswith(".pdf"):
                try:
                    with pdfplumber.open(io.BytesIO(raw)) as pdf:
                        if len(pdf.pages) > settings.ocr_max_pages:
                            raise HTTPException(status_code=413, detail=f"PDF exceeds the {settings.ocr_max_pages}-page processing limit.")
                        page_text = []
                        for page in pdf.pages:
                            extracted = (page.extract_text() or "").strip()
                            if not extracted:
                                if not shutil.which("tesseract"):
                                    raise HTTPException(status_code=503, detail="Scanned PDF OCR requires the local Tesseract executable.")
                                try:
                                    import pytesseract
                                    image = page.to_image(resolution=200).original
                                    available = set(pytesseract.get_languages(config=""))
                                    languages = [code for code in ("eng", "hin") if code in available]
                                    extracted = pytesseract.image_to_string(
                                        image, lang="+".join(languages) if languages else "eng"
                                    ).strip()
                                    ocr_used = bool(extracted) or ocr_used
                                except ImportError as exc:
                                    raise HTTPException(status_code=503, detail="Scanned PDF OCR requires the local Tesseract executable and pytesseract package.") from exc
                                except Exception as exc:
                                    logger.warning("Local PDF OCR failed page=%d error=%s", page.page_number, type(exc).__name__)
                                    ocr_failed = True
                                if not extracted:
                                    ocr_failed = True
                            page_text.append(extracted)
                        if ocr_failed:
                            raise HTTPException(status_code=422, detail="At least one PDF page could not be read. The partial document was discarded; improve scan quality or provide a text-based copy.")
                        text = "\n".join(page_text).strip()
                except HTTPException:
                    raise
                except Exception as exc:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Could not parse PDF: {exc}",
                    ) from exc

                if not text:
                    raise HTTPException(
                        status_code=422,
                        detail=(
                            "No text could be extracted from this PDF. For scanned pages, check OCR support and document quality."
                        ),
                    )
            else:
                try:
                    text = raw.decode("utf-8")
                except UnicodeDecodeError as exc:
                    raise HTTPException(
                        status_code=415,
                        detail="Upload a UTF-8 text file or a text-based PDF.",
                    ) from exc

        else:
            raise HTTPException(
                status_code=422,
                detail="Provide JSON payload or upload a file.",
            )

    else:
        raise HTTPException(
            status_code=415,
            detail="Use application/json or multipart/form-data.",
        )

    sentences = parse_and_split(text)

    if not sentences:
        raise HTTPException(
            status_code=422,
            detail="No sentences could be extracted.",
        )

    try:
        logger.info(
            "Document sentence splitting completed source=%s sentences=%d",
            source_name, len(sentences),
        )
        facts = extract_facts(
            sentences,
            mode=settings.fact_extraction_mode,
        )
        validate_fact_sources(facts, sentences)
        logger.info(
            "Document fact extraction completed source=%s mode=%s facts=%d sentences=%d",
            source_name, settings.fact_extraction_mode, len(facts), len(sentences),
        )
    except Exception as exc:
        logger.exception("Fact extraction failed mode=%s", settings.fact_extraction_mode)
        raise HTTPException(
            status_code=502 if settings.fact_extraction_mode == "structured_llm" else 422,
            detail={
                "code": "fact_extraction_failed",
                "message": str(exc) or "Fact extraction did not complete validation.",
                "mode": settings.fact_extraction_mode,
            },
        ) from exc

    doc_id = str(uuid.uuid4())

    record = DocumentRecord(
        id=doc_id,
        source_name=source_name,
        original_text=text,
        sentences=sentences,
        facts=facts,
        claims=[],
        status="extracted",
        input_warnings=["Local OCR was used; review recognized source text before relying on any explanation."] if ocr_used else [],
    )

    store.documents[doc_id] = record

    return record


@app.post("/documents/{doc_id}/explain", response_model=ExplainResponse)
def explain_document(
    doc_id: str,
    lang: str = Query(default="en", pattern="^(" + "|".join(LANGUAGES) + ")$"),
):
    record = store.documents.get(doc_id)

    if record is None:
        raise HTTPException(
            status_code=404,
            detail="Document not found.",
        )

    facts = record.facts

    if not facts:
        logger.error(
            "Explanation refused because document has no extracted facts doc_id=%s sentences=%d",
            doc_id, len(record.sentences),
        )
        raise HTTPException(
            status_code=422,
            detail={
                "code": "no_extractable_facts",
                "message": "This document has no extracted facts to explain. Upload it again after checking section parsing.",
            },
        )

    try:
        validate_fact_sources(facts, record.sentences)
    except ValueError as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Stored fact validation failed: {exc}",
        ) from exc

    logger.info("Claim generation started doc_id=%s facts=%d", doc_id, len(facts))
    try:
        claims = explain_facts(facts)
    except Exception as exc:
        logger.exception("Claim generation failed doc_id=%s facts=%d", doc_id, len(facts))
        raise HTTPException(
            status_code=502,
            detail={"code": "claim_generation_failed", "message": str(exc)},
        ) from exc
    if not claims:
        logger.error("Claim generation returned no claims doc_id=%s facts=%d", doc_id, len(facts))
        raise HTTPException(
            status_code=502,
            detail={
                "code": "claim_generation_empty",
                "message": "Claim generation returned no claims for a document with extracted facts.",
            },
        )
    if len(claims) != len(facts):
        logger.error(
            "Claim generation count mismatch doc_id=%s facts=%d claims=%d",
            doc_id, len(facts), len(claims),
        )
        raise HTTPException(
            status_code=502,
            detail={"code": "claim_generation_incomplete", "message": "Claim generation did not return one claim per extracted fact."},
        )
    # Fact/claim counters restart per document; qualify claim IDs so review
    # requests cannot accidentally update a same-numbered claim in another doc.
    for claim in claims:
        claim.id = f"{doc_id}-{claim.id}"
        if record.input_warnings:
            claim.reason_codes.append("ocr_source_requires_review")

    try:
        claims = verify_claims(claims, record.sentences, facts)
    except Exception as exc:
        logger.exception("Claim verification failed doc_id=%s claims=%d", doc_id, len(claims))
        raise HTTPException(
            status_code=502,
            detail={"code": "claim_verification_failed", "message": str(exc)},
        ) from exc
    logger.info("Claim verification completed doc_id=%s claims=%d", doc_id, len(claims))

    if lang != "en":
        try:
            claims = translate_claims(claims, facts, lang)
        except Exception as exc:
            logger.exception("Local translation failed doc_id=%s language=%s", doc_id, lang)
            raise HTTPException(status_code=502, detail={"code": "translation_failed", "message": "Local translation did not complete; the English claims remain available for review."}) from exc

    record.claims = claims
    record.status = "explained"
    store.documents[doc_id] = record

    questions = build_doctor_questions(
        facts,
        claims,
    )

    return ExplainResponse(
        document=record,
        doctor_questions=questions,
    )


@app.get("/documents/{doc_id}", response_model=DocumentRecord)
def get_document(doc_id: str):
    record = store.documents.get(doc_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Document not found.")
    return record


@app.delete("/documents/{doc_id}", status_code=204)
def delete_document(doc_id: str):
    try:
        del store.documents[doc_id]
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Document not found.") from exc
    return None


@app.get("/review-queue", response_model=list[ReviewQueueItem])
def review_queue():
    result = []
    for doc in store.documents.values():
        fact_source_ids = {source_id for fact in doc.facts for source_id in fact.source_ids}
        for claim in doc.claims:
            if claim.state not in {State.VERIFIED, State.SOURCE_SUPPORTED} and (
                claim.review is None or claim.review.action == ReviewAction.EDIT
            ):
                result.append(
                    ReviewQueueItem(
                        item_type="claim",
                        document_id=doc.id,
                        source_name=doc.source_name,
                        claim=claim,
                        source_sentences=[
                            sentence
                            for sentence in doc.sentences
                            if sentence.id in claim.source_ids
                        ],
                        reviewer_questions=build_doctor_questions(doc.facts, [claim]),
                    )
                )
        for sentence in doc.sentences:
            if (
                sentence.id not in fact_source_ids
                and sentence.id not in doc.reviewed_source_sentence_ids
            ):
                result.append(ReviewQueueItem(
                    item_type="source_sentence",
                    document_id=doc.id,
                    source_name=doc.source_name,
                    source_sentence=sentence,
                    reviewer_questions=["Review this source sentence and decide whether it contains a clinical fact that needs extraction."],
                ))
    return sorted(result, key=lambda item: (
        item.item_type != "source_sentence",
        -(item.claim.review_priority_score or 0.0) if item.claim else -0.75,
    ))


def _is_document_metadata(text: str) -> bool:
    normalized = re.sub(r"\s+", " ", text).strip()
    return bool(re.match(r"^[A-Za-z][\w -]{1,48}:$", normalized) or re.match(
        r"^(?:synthetic\s+)?(?:discharge\s+summary|patient\s+(?:name|id|identifier)|"
        r"record\s+id|mrn|date(?:\s+of\s+discharge)?|generated\s+on|"
        r"this\s+(?:is\s+a\s+)?synthetic\s+(?:document|record)|"
        r"end\s+of\s+(?:document|report|summary))\s*[:#-]?\s*.*$",
        normalized,
        re.I,
    ))


@app.post("/documents/{doc_id}/sentences/{sentence_id}/review")
def review_source_sentence(doc_id: str, sentence_id: str):
    doc = store.documents.get(doc_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found.")
    sentence = next((item for item in doc.sentences if item.id == sentence_id), None)
    fact_source_ids = {source_id for fact in doc.facts for source_id in fact.source_ids}
    if sentence is None or sentence.id in fact_source_ids or _is_document_metadata(sentence.text):
        raise HTTPException(status_code=404, detail="Unclassified source sentence not found.")
    if sentence_id not in doc.reviewed_source_sentence_ids:
        doc.reviewed_source_sentence_ids.append(sentence_id)
        store.documents[doc_id] = doc
    return {"document_id": doc_id, "sentence_id": sentence_id, "recorded": True}


@app.post("/claims/{claim_id}/review", response_model=ReviewResult)
def review_claim(claim_id: str, payload: ClaimReviewRequest):
    # Validate the request before modifying any claim.
    if payload.action == ReviewAction.EDIT:
        if payload.edited_text is None or not payload.edited_text.strip():
            raise HTTPException(
                status_code=422,
                detail="edited_text is required for edit.",
            )

    matches = [
        (doc, claim)
        for doc in store.documents.values()
        for claim in doc.claims
        if claim.id == claim_id
    ]
    if not matches:
        raise HTTPException(status_code=404, detail="Claim not found.")
    if len(matches) > 1:
        raise HTTPException(
            status_code=409,
            detail="Claim ID is ambiguous across documents. Reload the document and retry.",
        )

    doc, claim = matches[0]
    state_before = claim.state
    claim.review = payload
    if payload.action == ReviewAction.EDIT:
        claim.text = payload.edited_text.strip()
        claim.reason_codes = [
            reason for reason in claim.reason_codes
            if reason not in {
                "human_edit_requires_reverification", "human_rejected",
                "llm_generation_failed", "llm_generation_not_configured",
            }
        ]
        verify_claims([claim], doc.sentences, doc.facts)
    elif payload.action == ReviewAction.REJECT:
        claim.state = State.NEEDS_CLINICIAN
        if "human_rejected" not in claim.reason_codes:
            claim.reason_codes.append("human_rejected")

    claim.review_history.append(
        ClaimReviewAuditEntry(
            **payload.model_dump(),
            state_before=state_before,
            state_after=claim.state,
        )
    )
    store.documents[doc.id] = doc
    return ReviewResult(
        claim_id=claim_id,
        document_id=doc.id,
        recorded=True,
        state=claim.state,
        reviewer_action=payload.action,
    )


@app.get("/doctor-questions/{doc_id}", response_model=list[str])
def doctor_questions(doc_id: str):
    record = store.documents.get(doc_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Document not found.")
    return build_doctor_questions(record.facts, record.claims)
