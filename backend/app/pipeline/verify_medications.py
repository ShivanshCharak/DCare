import re

from ..models import Claim, Fact
from ..rules.risk_rules import find_known_medication_entities
from ..rules.risk_rules import requires_frequency_review


def extract_doses(text: str) -> list[str]:
    """Extract numeric doses with common medication units."""
    pattern = r"\b\d+(?:\.\d+)?\s*(milligrams?|mg|micrograms?|mcg|grams?|g|millilit(?:er|re)s?|ml|units?)\b"
    aliases = {
        "milligram": "mg", "milligrams": "mg",
        "microgram": "mcg", "micrograms": "mcg",
        "gram": "g", "grams": "g",
        "milliliter": "ml", "milliliters": "ml",
        "millilitre": "ml", "millilitres": "ml",
        "unit": "units", "units": "units",
    }
    doses = []
    for match in re.finditer(pattern, text, flags=re.IGNORECASE):
        number, unit = re.match(r"(\d+(?:\.\d+)?)\s*(.*)", match.group(0)).groups()
        doses.append(number.casefold() + aliases.get(unit.casefold(), unit.casefold()))
    return doses


def extract_frequencies(text: str) -> list[str]:
    """Extract explicitly supported medication frequency expressions."""
    patterns = [
        (r"\b(\d+)\s+times?\s+(?:(?:a|per)\s+(day|week|month)|(daily))\b", "numeric"),
        (r"\bonce\s+(?:daily|a day|per day)\b|\bone time\s+(?:daily|a day|per day)\b", "once"),
        (r"\btwice\s+(?:daily|a day|per day)\b|\btwo times\s+(?:daily|a day|per day)\b", "twice"),
        (r"\bthree times\s+(?:daily|a day|per day)\b", "three"),
        (r"\bfour times\s+(?:daily|a day|per day)\b", "four"),
        (r"\bevery \d+ hours?\b", "interval"),
        (r"\bevery day\b|\bdaily\b", "once"),
        (
            r"\b(?:(?<!long )as needed|if needed|if (?:you )?need(?: it)?|"
            r"when needed|when (?:you )?need(?: it)?|as necessary|when necessary|"
            r"whenever (?:you )?need(?: it)?|"
            r"when (?:you )?(?:have|run) (?:a )?(?:fever|temperature))\b",
            "as_needed",
        ),
    ]

    normalized = text.casefold()
    frequencies: list[str] = []

    for pattern, canonical in patterns:
        for match in re.finditer(pattern, normalized):
            if canonical == "interval":
                hours = re.search(r"\bevery (\d+) hours?\b", match.group(0))
                if hours:
                    frequencies.append(f"every_{hours.group(1)}_hours")

            elif canonical == "numeric":
                number, period = match.group(1), match.group(2) or "day"
                number = str(int(number))
                if period == "week" and int(number) > 7:
                    # Keep out-of-range weekly counts out of the recognized
                    # frequency vocabulary; has_ambiguous_schedule flags them.
                    continue
                if period == "day" and number == "1":
                    frequencies.append("once_daily")
                elif period == "day" and number == "2":
                    frequencies.append("twice_daily")
                elif period != "day" or number not in {"3", "4"}:
                    frequencies.append(f"{number}_times_per_{period}")
                else:
                    frequencies.append({"3": "three_times_daily", "4": "four_times_daily"}[number])

            else:
                if canonical == "once" and match.group(0) == "daily":
                    prefix = normalized[max(0, match.start() - 20) : match.start()]
                    if re.search(
                        r"\b(?:once|twice|three times|four times|\d+ times)\s+$",
                        prefix,
                    ):
                        continue
                frequencies.append({
                    "once": "once_daily",
                    "twice": "twice_daily",
                    "three": "three_times_daily",
                    "four": "four_times_daily",
                    "as_needed": "as_needed",
                }[canonical])

    return list(dict.fromkeys(frequencies))


def extract_durations(text: str) -> list[str]:
    """Extract explicitly stated durations."""
    number_words = {
        "one": 1,
        "two": 2,
        "three": 3,
        "four": 4,
        "five": 5,
        "six": 6,
        "seven": 7,
        "eight": 8,
        "nine": 9,
        "ten": 10,
        "eleven": 11,
        "twelve": 12,
        "thirteen": 13,
        "fourteen": 14,
        "fifteen": 15,
        "sixteen": 16,
        "seventeen": 17,
        "eighteen": 18,
        "nineteen": 19,
        "twenty": 20,
    }
    number = r"(?:\d+(?:\.\d+)?|" + "|".join(number_words) + r")"
    pattern = r"\bfor\s+(" + number + r")\s+(hours?|days?|weeks?|months?|years?)\b"
    normalized = text.casefold()
    durations = []
    for match in re.finditer(pattern, normalized):
        raw_number = match.group(1)
        canonical_number = str(number_words.get(raw_number, raw_number))
        unit = match.group(2).rstrip("s")
        durations.append(f"for {canonical_number} {unit}")
    return durations


def extract_timings(text: str) -> list[str]:
    """Extract timing separately from how often a medication is taken."""
    patterns = {
        "morning": r"\b(?:in the morning|every morning|each morning)\b",
        "evening": r"\b(?:in the evening|every evening|each evening)\b",
        "bedtime": r"\b(?:at bedtime|before bed|at night)\b",
        "with_food": r"\bwith (?:food|a meal|meals)\b",
        "before_food": r"\b(?:before|prior to) (?:food|a meal|meals)\b",
        "after_food": r"\bafter (?:food|a meal|meals)\b",
    }
    normalized = text.casefold()
    return [name for name, pattern in patterns.items() if re.search(pattern, normalized)]


def has_ambiguous_schedule(text: str) -> bool:
    normalized = text.casefold()

    return bool(
        re.search(
            r"\b(?:\d+|one|two|three|four|five|six|seven|eight|nine|ten|"
            r"eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|"
            r"eighteen|nineteen|twenty)\s+days?\s+(?:a|per)\s+week\b",
            normalized,
        )
        or re.search(
            # A weekly frequency above seven is malformed/ambiguous. Preserve
            # the wording for review instead of normalizing it to a schedule.
            r"\b(?:\d+|one|two|three|four|five|six|seven|eight|nine|ten|"
            r"eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|"
            r"eighteen|nineteen|twenty)\s+times?\s+(?:a|per)\s+week\b",
            normalized,
        )
    )


def check_medication_consistency(
    claim: Claim,
    linked_facts: list[Fact],
) -> tuple[str, list[str]]:
    """Compare medication dose, frequency, duration, and timing independently."""
    medication_facts = [fact for fact in linked_facts if fact.kind == "medication"]
    if not medication_facts:
        return "not_applicable", []

    problems: list[str] = []
    claim_names = find_known_medication_entities(claim.text)
    if len(medication_facts) > 1 and claim_names:
        matching_facts = [
            fact for fact in medication_facts
            if find_known_medication_entities(fact.text_en).intersection(claim_names)
        ]
        if matching_facts:
            medication_facts = matching_facts
        elif len(claim_names) > 0:
            return "review_suggested", ["medication_attribute_unrecognized"]
    if len(medication_facts) > 1 and not claim_names:
        return "review_suggested", ["medication_attribute_unrecognized"]

    claim_doses = extract_doses(claim.text)
    claim_frequencies = extract_frequencies(claim.text)
    claim_durations = extract_durations(claim.text)
    claim_timings = extract_timings(claim.text)

    for fact in medication_facts:
        if requires_frequency_review(fact.text_en) or requires_frequency_review(claim.text):
            problems.append("medication_frequency_requires_clinician_review")
        if has_ambiguous_schedule(fact.text_en) or has_ambiguous_schedule(claim.text):
            problems.append("ambiguous_medication_schedule")
            if not has_ambiguous_schedule(claim.text) and (
                extract_frequencies(claim.text) or extract_durations(claim.text)
            ):
                problems.append("interpreted_ambiguous_medication_schedule")
            continue
        source_doses = extract_doses(fact.text_en)
        source_frequencies = extract_frequencies(fact.text_en)
        source_durations = extract_durations(fact.text_en)
        source_timings = extract_timings(fact.text_en)
        source_is_as_needed = "as_needed" in source_frequencies
        claim_adds_duration_to_as_needed = bool(
            re.search(r"\bas long as (?:needed|required|necessary)\b", claim.text, re.I)
        )
        if source_is_as_needed and claim_adds_duration_to_as_needed:
            problems.append("as_needed_duration_added")
        if source_doses != claim_doses:
            problems.append("medication_dose_mismatch")
        if source_frequencies and source_frequencies != claim_frequencies:
            problems.append("medication_frequency_mismatch")
        elif not source_frequencies and claim_frequencies:
            problems.append("unsupported_medication_frequency")
        if source_durations != claim_durations:
            problems.append("medication_duration_mismatch")
        if source_timings != claim_timings:
            problems.append("medication_timing_mismatch")

    problems = list(dict.fromkeys(problems))
    if problems:
        confirmed = {
            "medication_dose_mismatch",
            "medication_frequency_mismatch",
            "medication_duration_mismatch",
            "medication_timing_mismatch",
            "unsupported_medication_frequency",
            "as_needed_duration_added",
            "interpreted_ambiguous_medication_schedule",
        }
        return ("failed" if set(problems).intersection(confirmed) else "review_suggested"), problems
    return "passed", []


def check_ambiguous_medication_details(
    linked_facts: list[Fact],
) -> tuple[str, list[str]]:
    """Flag medication facts whose schedule cannot be parsed confidently."""
    medication_facts = [fact for fact in linked_facts if fact.kind == "medication"]
    if not medication_facts:
        return "not_applicable", []

    for fact in medication_facts:
        has_dose_unit = bool(extract_doses(fact.text_en))
        has_frequency = bool(extract_frequencies(fact.text_en))
        has_duration = bool(extract_durations(fact.text_en))
        remaining_numbers = fact.text_en.casefold()
        for pattern in (
            r"\b\d+(?:\.\d+)?\s*(?:mg|mcg|g|ml|units?)\b",
            r"\b\d+\s+times?\s+(?:(?:a|per)\s+(?:day|week|month)|daily)\b",
            r"\bevery\s+\d+\s+hours?\b",
            r"\bfor\s+(?:\d+(?:\.\d+)?|one|two|three|four|five|six|seven|eight|nine|ten)\s+(?:hours?|days?|weeks?|months?|years?)\b",
        ):
            remaining_numbers = re.sub(pattern, " ", remaining_numbers)
        has_unrecognized_numeric = bool(re.search(r"\b\d+(?:\.\d+)?\b", remaining_numbers))
        if (
            has_unrecognized_numeric
            or not has_frequency
            or (has_dose_unit and not has_frequency)
            or (has_duration and not has_frequency)
        ):
            return "review_suggested", ["ambiguous_medication_details"]
    return "passed", []


def check_unsupported_medication_names(
    claim: Claim,
    linked_facts: list[Fact],
) -> tuple[str, list[str]]:
    """Flag configured medication names in a claim that are absent from facts."""
    medication_facts = [fact for fact in linked_facts if fact.kind == "medication"]
    if not medication_facts:
        return "not_applicable", []

    claim_names = find_known_medication_entities(claim.text)
    if not claim_names:
        return "review_suggested", ["medication_name_unrecognized"]

    source_names = find_known_medication_entities(
        " ".join(fact.text_en for fact in linked_facts)
    )
    if claim_names - source_names:
        return "failed", ["unsupported_medication_name"]
    return "passed", []


def find_conflicting_medication_fact_ids(facts: list[Fact]) -> set[str]:
    """Find configured medications with conflicting explicit directions."""
    medications = [fact for fact in facts if fact.kind == "medication"]
    conflicting_fact_ids: set[str] = set()

    def actions(text: str) -> set[str]:
        found: set[str] = set()
        patterns = {
            "stop": re.compile(
                r"\b(?:stop(?:ped)?|discontinue[sd]?|hold|withhold)\b", re.IGNORECASE
            ),
            "continue": re.compile(
                r"\b(?:continue[sd]?|resume[sd]?|keep\s+taking)\b", re.IGNORECASE
            ),
        }
        for action, pattern in patterns.items():
            for match in pattern.finditer(text):
                prefix = text[max(0, match.start() - 24) : match.start()]
                if re.search(
                    r"\b(?:do\s+not|don't|never|not)\s*$", prefix, re.IGNORECASE
                ):
                    continue
                found.add(action)
        return found

    fact_details = [
        (
            fact,
            find_known_medication_entities(fact.text_en),
            actions(fact.text_en),
            {
                "dose": extract_doses(fact.text_en),
                "frequency": extract_frequencies(fact.text_en),
                "duration": extract_durations(fact.text_en),
            },
        )
        for fact in medications
    ]

    for index, (left, left_keys, left_actions, left_details) in enumerate(fact_details):
        for right, right_keys, right_actions, right_details in fact_details[
            index + 1 :
        ]:
            if not left_keys.intersection(right_keys):
                continue
            action_conflict = (
                "stop" in left_actions and "continue" in right_actions
            ) or ("continue" in left_actions and "stop" in right_actions)
            detail_conflict = any(
                left_details[name]
                and right_details[name]
                and set(left_details[name]) != set(right_details[name])
                for name in ("dose", "frequency", "duration")
            )
            if action_conflict or detail_conflict:
                conflicting_fact_ids.update((left.id, right.id))

    return conflicting_fact_ids
