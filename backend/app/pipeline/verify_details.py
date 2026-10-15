import re

from ..models import Claim, Fact


def check_warning_sign_urgency(
    claim: Claim,
    linked_facts: list[Fact],
) -> tuple[str, list[str]]:
    """Catch a narrowed response level for urgent warning-sign instructions."""
    warning_facts = [fact for fact in linked_facts if fact.kind == "warning_sign"]
    if not warning_facts:
        return "not_applicable", []
    source_text = " ".join(fact.text_en for fact in warning_facts)
    urgent_level = re.compile(
        r"\b(?:urgent medical care|urgent care|emergency (?:care|room|services)|call 911)\b",
        re.I,
    )
    softened_level = re.compile(
        r"\b(?:see|call|contact) (?:a|your) (?:doctor|physician|clinic|provider)\b",
        re.I,
    )
    if urgent_level.search(source_text) and softened_level.search(claim.text) and not urgent_level.search(claim.text):
        return "failed", ["warning_sign_escalation_softened"]
    return "passed", []


def check_unsupported_attributions(
    claim: Claim,
    linked_facts: list[Fact],
) -> tuple[str, list[str]]:
    """Flag explicit clinician-attribution phrases absent from linked facts."""
    attribution_pattern = re.compile(
        r"\b(?:the|your|a)\s+"
        r"(?:doctor|physician|clinician|nurse|provider|prescriber|"
        r"healthcare provider|health care provider)\s+"
        r"(?:told|said|explained|advised|instructed|recommended|informed)\b",
        re.IGNORECASE,
    )
    attribution_by_pattern = re.compile(
        r"\b(?:as\s+)?(?:directed|prescribed|ordered|recommended)\s+by\s+"
        r"(?:the|your|a)\s+(?:doctor|physician|clinician|nurse|provider|"
        r"prescriber|healthcare provider|health care provider)\b",
        re.IGNORECASE,
    )

    if not linked_facts:
        return "not_run", []
    if not attribution_pattern.search(claim.text) and not attribution_by_pattern.search(
        claim.text
    ):
        return "passed", []

    source_text = " ".join(fact.text_en for fact in linked_facts)
    if not attribution_pattern.search(
        source_text
    ) and not attribution_by_pattern.search(source_text):
        return "failed", ["unsupported_attribution"]
    return "passed", []


def check_unsupported_medication_context(
    claim: Claim,
    linked_facts: list[Fact],
) -> tuple[str, list[str]]:
    """Catch medication class or purpose explanations added from outside knowledge."""
    medication_facts = [fact for fact in linked_facts if fact.kind == "medication"]
    if not medication_facts:
        return "not_applicable", []
    source_text = " ".join(fact.text_en for fact in medication_facts)
    claim_text = claim.text
    additions = (
        (r"\b(?:which\s+is\s+)?(?:a\s+)?type\s+of\s+(?:an?\s+)?(?:antibiotic|painkiller|blood thinner|steroid)\b", r"\b(?:antibiotic|painkiller|blood thinner|steroid)\b"),
        (r"\b(?:for|to treat|used to treat)\s+(?:pain|inflammation|infection|fever)\b", r"\b(?:pain|inflammation|infection|fever)\b"),
    )
    for claim_pattern, source_pattern in additions:
        if re.search(claim_pattern, claim_text, re.I) and not re.search(source_pattern, source_text, re.I):
            return "failed", ["unsupported_medication_context"]
    return "passed", []


def _numeric_details(text: str) -> list[str]:
    """Extract dates and numeric values, canonicalizing clear date formats."""
    devanagari_digits = str.maketrans("०१२३४५६७८९", "0123456789")
    normalized = text.translate(devanagari_digits)
    date_pattern = re.compile(r"(?<!\w)\d{1,4}[/-]\d{1,2}[/-]\d{1,4}(?!\w)")
    date_matches = list(date_pattern.finditer(normalized))
    dates: list[str] = []
    for match in date_matches:
        raw = match.group(0)
        parts = [int(part) for part in re.split(r"[/-]", raw)]
        year: int | None = None
        month: int | None = None
        day: int | None = None
        if len(str(parts[0])) == 4:
            year, month, day = parts
        elif len(str(parts[2])) == 4:
            year = parts[2]
            first, second = parts[:2]
            if first > 12 and second <= 12:
                day, month = first, second
            elif second > 12 and first <= 12:
                month, day = first, second
        if year and month and day and 1 <= month <= 12 and 1 <= day <= 31:
            dates.append(f"date:{year:04d}-{month:02d}-{day:02d}")
        else:
            dates.append(f"date:ambiguous:{raw}")

    month_names = {
        name.casefold(): index
        for index, name in enumerate(
            (
                "January",
                "February",
                "March",
                "April",
                "May",
                "June",
                "July",
                "August",
                "September",
                "October",
                "November",
                "December",
            ),
            start=1,
        )
    }
    month_pattern = re.compile(
        r"\b(" + "|".join(month_names) + r")\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})\b",
        re.IGNORECASE,
    )
    day_month_pattern = re.compile(
        r"\b(\d{1,2})(?:st|nd|rd|th)?\s+(" + "|".join(month_names) + r")\s+(\d{4})\b",
        re.IGNORECASE,
    )
    textual_matches = list(month_pattern.finditer(normalized))
    textual_matches.extend(day_month_pattern.finditer(normalized))
    for match in textual_matches:
        if match.re is month_pattern:
            month, day, year = (
                month_names[match.group(1).casefold()],
                int(match.group(2)),
                int(match.group(3)),
            )
        else:
            day, month, year = (
                int(match.group(1)),
                month_names[match.group(2).casefold()],
                int(match.group(3)),
            )
        if 1 <= day <= 31:
            dates.append(f"date:{year:04d}-{month:02d}-{day:02d}")

    # Keep a dose as one canonical detail so formatting variants such as
    # "200-mg" and "200 mg" do not leave a misleading bare number behind.
    dose_pattern = re.compile(r"(?<!\w)(\d+(?:\.\d+)?)\s*-?\s*(mg|mcg|g|ml|units?)\b", re.I)
    doses = [f"dose:{m.group(1)}:{m.group(2).casefold()}" for m in dose_pattern.finditer(normalized)]
    without_dates = date_pattern.sub(" ", normalized)
    without_dates = dose_pattern.sub(" ", without_dates)
    without_dates = month_pattern.sub(" ", without_dates)
    without_dates = day_month_pattern.sub(" ", without_dates)
    numbers = re.findall(r"(?<!\w)\d+(?:[.,]\d+)?(?!\w)", without_dates)
    return dates + doses + numbers


def check_unsupported_numeric_details(
    claim: Claim,
    linked_facts: list[Fact],
) -> tuple[str, list[str]]:
    """Flag numeric values or dates in a claim absent from its linked facts."""
    if not linked_facts:
        return "not_run", []

    source_details = _numeric_details(" ".join(fact.text_en for fact in linked_facts))
    claim_details = _numeric_details(claim.text)
    available = {}
    for detail in source_details:
        available[detail] = available.get(detail, 0) + 1

    for detail in claim_details:
        if available.get(detail, 0) == 0:
            return "failed", ["unsupported_numeric_detail"]
        available[detail] -= 1
    return "passed", []


def check_instruction_polarity(
    claim: Claim,
    linked_facts: list[Fact],
) -> tuple[str, list[str]]:
    """Flag changes to explicit negation or stop/continue wording."""
    if not linked_facts:
        return "not_run", []

    negative_pattern = re.compile(
        r"\b(?:no|not|never|without|neither|nor|cannot|can't|"
        r"don't|doesn't|didn't|isn't|aren't|wasn't|weren't|"
        r"won't|shouldn't|mustn't)\b",
        re.IGNORECASE,
    )
    stop_pattern = re.compile(
        r"\b(?:stop|stopped|discontinue|discontinued|hold)\b", re.IGNORECASE
    )
    continue_pattern = re.compile(
        r"\b(?:continue|continues|continued|keep\s+taking)\b",
        re.IGNORECASE,
    )

    source_text = " ".join(fact.text_en for fact in linked_facts)
    informational_status = re.compile(
        r"\bnot yet (?:available|ready|reported|completed|returned|finished|complete)\b",
        re.IGNORECASE,
    )
    informational_synthetic = re.compile(
        r"\bnot (?:a )?natural(?:ly)? occurring\b|\bnot natural(?:ly)?\b",
        re.IGNORECASE,
    )
    source_for_polarity = informational_status.sub("pending", source_text)
    claim_for_polarity = informational_status.sub("pending", claim.text)
    source_for_polarity = informational_synthetic.sub("synthetic", source_for_polarity)
    claim_for_polarity = informational_synthetic.sub("synthetic", claim_for_polarity)
    source_negative = bool(negative_pattern.search(source_for_polarity))
    claim_negative = bool(negative_pattern.search(claim_for_polarity))
    source_stops = bool(stop_pattern.search(source_text))
    claim_stops = bool(stop_pattern.search(claim.text))
    source_continues = bool(continue_pattern.search(source_text))
    claim_continues = bool(continue_pattern.search(claim.text))

    changed_negation = source_negative != claim_negative
    unsupported_action = (claim_stops and not source_stops) or (
        claim_continues and not source_continues
    )
    conflicting_action = (source_stops and claim_continues) or (
        source_continues and claim_stops
    )
    dropped_continue = source_continues and not claim_continues

    if changed_negation or unsupported_action or conflicting_action or dropped_continue:
        return "failed", ["instruction_polarity_mismatch"]
    return "passed", []


def check_clause_preservation(claim: Claim, linked_facts: list[Fact]) -> tuple[str, list[str]]:
    """Require explicit exception/condition clauses to remain in the claim."""
    source_text = " ".join(fact.text_en for fact in linked_facts)
    for marker in ("except", "unless"):
        clauses = re.findall(rf"\b{marker}\b(.+?)(?:[.;]|$)", source_text, re.I)
        if clauses and not re.search(rf"\b{marker}\b", claim.text, re.I):
            return "failed", ["source_clause_omitted"]
        if clauses:
            for clause in clauses:
                keywords = [word.casefold() for word in re.findall(r"\b[a-zA-Z]{4,}\b", clause)]
                if keywords and not any(word in claim.text.casefold() for word in keywords):
                    return "failed", ["source_clause_omitted"]
    return "passed", []


def check_synonym_drift(claim: Claim, linked_facts: list[Fact]) -> tuple[str, list[str]]:
    """Catch familiar rewrites that change the source's clinical certainty/state."""
    source_text = " ".join(fact.text_en for fact in linked_facts).casefold()
    claim_text = claim.text.casefold()
    drift_pairs = (
        (r"\bstable condition\b", r"\bgood health\b"),
        (r"\bimproved\b", r"\b(?:resolved|recovered|cured)\b"),
        (r"\bpending\b", r"\bnegative\b"),
    )
    for source_pattern, claim_pattern in drift_pairs:
        if re.search(source_pattern, source_text) and re.search(claim_pattern, claim_text):
            return "failed", ["clinical_synonym_drift"]
    return "passed", []
