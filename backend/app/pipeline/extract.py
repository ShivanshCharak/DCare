import json
import re
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from ..models import Fact, Sentence
from app.config import Settings

# These aliases must match the section names produced by parse.py.
SECTION_KIND_MAP = {
    "diagnosis": "diagnosis",
    "diagnoses": "diagnosis",
    "medication": "medication",
    "medications": "medication",
    "meds": "medication",
    "follow_up": "appointment",
    "follow-up": "appointment",
    "follow up": "appointment",
    "appointment": "appointment",
    "appointments": "appointment",
    "restriction": "restriction",
    "restrictions": "restriction",
    "activity": "restriction",
    "warning_sign": "warning_sign",
    "warning_signs": "warning_sign",
    "warning signs": "warning_sign",
    "pending_test": "pending_test",
    "pending_tests": "pending_test",
    "tests_pending": "pending_test",
    "allergy": "allergy",
    "allergies": "allergy",
    "vitals": "vital",
    "vital_signs": "vital",
    "symptoms": "symptom",
}

ALLOWED_KINDS = set(SECTION_KIND_MAP.values())


def _normalize_section(section: str) -> str:
    """Normalize a section name without guessing its medical meaning."""
    return section.strip().lower().replace(" ", "_")


def _extract_medication_attributes(text: str) -> dict[str, str]:
    """
    Extract basic medication attributes when explicitly written.

    This is a lightweight baseline, not a clinical medication parser.
    """
    attrs: dict[str, str] = {}

    dose_match = re.search(
        r"\b\d+(?:\.\d+)?\s*(?:mg|mcg|g|ml|mL|units?)\b",
        text,
        flags=re.IGNORECASE,
    )

    if dose_match:
        attrs["dose"] = dose_match.group(0)

    frequency_patterns = [
        r"\b\d+\s+times?\s+(?:(?:a|per)\s+(?:day|week|month)|daily)\b",
        r"\bonce\s+(?:daily|a day|per day)\b",
        r"\btwice\s+(?:daily|a day|per day)\b",
        r"\b(?:three|four) times\s+(?:daily|a day|per day)\b",
        r"\bevery\s+\d+\s+hours?\b",
        r"\bevery day\b",
        r"\bdaily\b",
        r"\bas needed\b",
    ]
    for pattern in frequency_patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            attrs["frequency"] = match.group(0)
            break

    duration_match = re.search(
        r"\bfor\s+(?:\d+|one|two|three|four|five|six|seven|eight|nine|ten)\s+"
        r"(?:hours?|days?|weeks?|months?|years?)\b",
        text,
        flags=re.IGNORECASE,
    )
    if duration_match:
        attrs["duration"] = duration_match.group(0)

    timing_patterns = [
        r"\b(?:in the morning|every morning|each morning)\b",
        r"\b(?:in the evening|every evening|each evening)\b",
        r"\b(?:at bedtime|before bed|at night)\b",
        r"\bwith (?:food|a meal|meals)\b",
        r"\b(?:before|prior to) (?:food|a meal|meals)\b",
        r"\bafter (?:food|a meal|meals)\b",
    ]
    timing_matches = [
        match.group(0)
        for pattern in timing_patterns
        if (match := re.search(pattern, text, flags=re.IGNORECASE))
    ]
    if timing_matches:
        attrs["timing"] = "; ".join(timing_matches)
    if re.search(r"\b\d+\s+days?\s+(?:a|per)\s+week\b", text, re.IGNORECASE):
        attrs["schedule_ambiguous"] = "true"

    return attrs


def _eligible_sentences(
    sentences: list[Sentence],
) -> list[tuple[Sentence, str]]:
    """Return sentences whose sections map to recognized fact kinds."""
    eligible = []

    for sentence in sentences:
        kind = SECTION_KIND_MAP.get(_normalize_section(sentence.section))

        # Detect common clinical facts under unfamiliar headings as well.
        if kind is None:
            text = sentence.text.casefold()
            if re.search(r"\b(?:allerg(?:y|ies|ic)|allergic to)\b", text):
                kind = "allergy"
            elif re.search(r"\b(?:pending|awaiting)\b.{0,50}\b(?:lab|test|culture|result|blood work)\b|\b(?:lab|test|culture)\b.{0,50}\b(?:pending|awaiting)\b", text):
                kind = "pending_test"
            elif re.search(r"\b(?:blood pressure|\bbp\b|\b\d{2,3}\s*/\s*\d{2,3}\s*mmhg|heart rate|pulse|temperature|oxygen saturation|spo2|\d+\s*(?:°?c|°?f|mmhg|bpm|%))\b", text):
                kind = "vital"
            elif re.search(r"\b(?:denies?|no|without)\b.{0,40}\b(?:pain|fever|nausea|vomiting|cough|shortness of breath|chest pain|symptoms?)\b|\b(?:pain|fever|nausea|vomiting|cough|shortness of breath|chest pain)\b", text):
                kind = "symptom"
            elif re.search(r"\b\d{1,2}\s+(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\s+\d{4}\b|\b(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\s+\d{1,2},?\s+\d{4}\b|\b\d{4}-\d{1,2}-\d{1,2}\b|\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b", text):
                kind = "date"

        if kind and sentence.text.strip():
            eligible.append((sentence, kind))

    return eligible


def _extract_facts_deterministically(
    sentences: list[Sentence],
) -> list[Fact]:
    """Use the existing conservative, section-based extraction method."""
    facts: list[Fact] = []
    seen: set[tuple[str, str]] = set()

    for sentence, kind in _eligible_sentences(sentences):
        text = sentence.text.strip()
        deduplication_key = (kind, text.casefold())

        if deduplication_key in seen:
            continue

        seen.add(deduplication_key)

        attrs: dict[str, str] = {
            "extraction_mode": "deterministic",
        }

        if kind == "medication":
            attrs.update(_extract_medication_attributes(text))

        facts.append(
            Fact(
                id=f"F{len(facts) + 1}",
                kind=kind,
                text_en=text,
                attrs=attrs,
                source_ids=[sentence.id],
            )
        )

    return facts


def _call_structured_llm(
    sentences: list[Sentence],
    settings,
) -> dict:
    """
    Call the configured OpenAI-compatible local model.

    The model must return JSON containing a list of source-linked facts.
    """
    eligible = _eligible_sentences(sentences)

    if not eligible:
        return {"facts": []}

    source_payload = [
        {
            "source_id": sentence.id,
            "section": sentence.section,
            "allowed_kind": kind,
            "text": sentence.text,
        }
        for sentence, kind in eligible
    ]

    system_prompt = """
You extract structured facts from synthetic discharge summaries.

Return ONLY a JSON object in this format:
{
  "facts": [
    {
      "source_id": "S1",
      "kind": "diagnosis",
      "text_en": "an exact excerpt from the source sentence"
    }
  ]
}

Rules:
- Extract only facts explicitly stated in the provided source sentences.
- Use only these kinds:
  diagnosis, medication, appointment, restriction,
  warning_sign, pending_test, allergy, symptom, vital, date.
- Each fact must use the allowed_kind provided for its source sentence.
- source_id must be copied exactly from the input.
- text_en must be an EXACT, contiguous excerpt of the source sentence.
- Do not paraphrase, translate, correct, or rewrite source text.
- Preserve every number, medication name, dose, frequency,
  duration, negation, and instruction exactly.
- Never infer a medically typical dose or schedule.
- Do not invent facts or source IDs.
- If you cannot extract a fact safely, omit it.
- Do not include markdown fences or explanatory text.
""".strip()

    base_url = settings.llm_base_url.rstrip("/")
    endpoint = f"{base_url}/chat/completions"

    payload = {
        "model": settings.model_id,
        "temperature": 0,
        "response_format": {"type": "json_object"},
        "messages": [
            {
                "role": "system",
                "content": system_prompt,
            },
            {
                "role": "user",
                "content": json.dumps(
                    {"source_sentences": source_payload},
                    ensure_ascii=False,
                ),
            },
        ],
    }

    headers = {
        "Content-Type": "application/json",
    }

    api_key = getattr(settings, "llm_api_key", "")

    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    request = Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )

    try:
        with urlopen(request, timeout=90) as response:
            response_data = json.loads(response.read().decode("utf-8"))

    except HTTPError as exc:
        raise RuntimeError(
            f"Structured extraction API returned HTTP {exc.code}."
        ) from exc

    except (URLError, TimeoutError) as exc:
        raise RuntimeError(f"Could not reach the configured LLM: {exc}") from exc

    try:
        content = response_data["choices"][0]["message"]["content"]

        # Handle models that include a thinking block or markdown fences.
        content = re.sub(
            r"<think>.*?</think>",
            "",
            content,
            flags=re.DOTALL,
        ).strip()

        content = re.sub(
            r"^```(?:json)?\s*|\s*```$",
            "",
            content,
            flags=re.IGNORECASE,
        ).strip()

        result = json.loads(content)

    except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
        raise RuntimeError(
            "The LLM did not return valid structured extraction JSON."
        ) from exc

    if not isinstance(result, dict) or not isinstance(result.get("facts"), list):
        raise RuntimeError("The LLM response must contain a 'facts' list.")

    return result


def _extract_facts_with_llm(
    sentences: list[Sentence],
    settings,
) -> list[Fact]:
    """
    Extract facts with an LLM, then validate every returned fact
    against its original source sentence.
    """
    eligible = _eligible_sentences(sentences)

    if not eligible:
        return []

    result = _call_structured_llm(sentences, settings)

    sentence_by_id = {sentence.id: sentence for sentence, _ in eligible}

    kind_by_id = {sentence.id: kind for sentence, kind in eligible}

    raw_facts = result["facts"]

    if not raw_facts:
        raise RuntimeError("The LLM returned no facts for recognized source sentences.")

    facts: list[Fact] = []
    seen: set[tuple[str, str, str]] = set()
    selected_source_ids: set[str] = set()

    for item in raw_facts:
        if not isinstance(item, dict):
            raise RuntimeError("The LLM returned a fact that is not a JSON object.")

        source_id = item.get("source_id")
        kind = item.get("kind")
        text_en = item.get("text_en")

        if not all(
            isinstance(value, str) and value.strip()
            for value in (source_id, kind, text_en)
        ):
            raise RuntimeError("An extracted fact has missing or invalid fields.")

        if source_id not in sentence_by_id:
            raise RuntimeError(f"The LLM returned unknown source ID: {source_id}")

        if kind not in ALLOWED_KINDS:
            raise RuntimeError(f"The LLM returned unsupported fact kind: {kind}")

        if kind != kind_by_id[source_id]:
            raise RuntimeError(
                f"Fact kind mismatch for source {source_id}: "
                f"expected {kind_by_id[source_id]}, received {kind}"
            )

        source_sentence = sentence_by_id[source_id]

        # Require the full sentence so structured extraction cannot quietly
        # omit a dose, schedule, negation, or other potentially important detail.
        if text_en.strip() != source_sentence.text.strip():
            raise RuntimeError(
                f"Extracted text for {source_id} does not preserve the full "
                "source sentence."
            )

        deduplication_key = (
            source_id,
            kind,
            text_en.casefold(),
        )

        if deduplication_key in seen:
            continue

        seen.add(deduplication_key)
        selected_source_ids.add(source_id)

        attrs: dict[str, str] = {
            "extraction_mode": "structured_llm",
        }

        # Derive these attributes from the validated source excerpt,
        # not from unsupported LLM-generated attribute values.
        if kind == "medication":
            attrs.update(_extract_medication_attributes(text_en))

        facts.append(
            Fact(
                id=f"F{len(facts) + 1}",
                kind=kind,
                text_en=text_en,
                attrs=attrs,
                source_ids=[source_id],
            )
        )

    if not facts:
        raise RuntimeError("No valid facts remained after source validation.")

    omitted_source_ids = set(sentence_by_id) - selected_source_ids
    if omitted_source_ids:
        raise RuntimeError(
            "Structured extraction omitted recognized source sentences: "
            + ", ".join(sorted(omitted_source_ids))
        )

    return facts


def extract_facts(
    sentences: list[Sentence],
    mode="deterministic",
) -> list[Fact]:
    """
    Select the configured extraction mode.

    Structured LLM failures raise an error; they do not silently
    fall back to deterministic extraction.
    """

    if mode == "deterministic":
        facts = _extract_facts_deterministically(sentences)

    elif mode == "structured_llm":
        facts = _extract_facts_with_llm(sentences, Settings())

    else:
        raise ValueError(f"Unsupported fact extraction mode: {mode}")

    return validate_fact_sources(facts, sentences)


def validate_fact_sources(
    facts: list[Fact],
    sentences: list[Sentence],
) -> list[Fact]:
    """Reject facts whose source IDs do not reference parsed sentences."""
    sentence_by_id = {sentence.id: sentence for sentence in sentences}

    for fact in facts:
        if not fact.source_ids:
            raise ValueError(f"Fact {fact.id} has no source sentence IDs.")

        invalid_ids = set(fact.source_ids) - set(sentence_by_id)

        if invalid_ids:
            raise ValueError(
                f"Fact {fact.id} references unknown sentence IDs: "
                f"{sorted(invalid_ids)}"
            )

        for source_id in fact.source_ids:
            sentence = sentence_by_id[source_id]
            expected_kind = SECTION_KIND_MAP.get(_normalize_section(sentence.section))
            if expected_kind is not None and expected_kind != fact.kind:
                raise ValueError(
                    f"Fact {fact.id} kind {fact.kind} conflicts with source "
                    f"{source_id} section {sentence.section}."
                )
            if fact.text_en.strip() != sentence.text.strip():
                raise ValueError(
                    f"Fact {fact.id} text does not preserve source sentence {source_id}."
                )

    return facts
