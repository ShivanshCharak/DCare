import re

import pysbd

from ..models import Sentence

_segmenter = pysbd.Segmenter(language="en", clean=False)

SECTION_NAMES = {
    "diagnosis": "diagnosis",
    "discharge diagnosis": "diagnosis",
    "clinical diagnosis": "diagnosis",
    "medications": "medications",
    "medication": "medications",
    "medication list": "medications",
    "medication instructions": "medications",
    "discharge medications": "medications",
    "discharge medicines": "medications",
    "follow-up": "follow_up",
    "follow up": "follow_up",
    "follow-up plan": "follow_up",
    "next appointment": "follow_up",
    "warning signs": "warning_signs",
    "when to get help": "warning_signs",
    "when to seek urgent help": "warning_signs",
    "restrictions": "restrictions",
    "home care": "restrictions",
    "activity limits": "restrictions",
    "activity guidance": "restrictions",
    "pending tests": "pending_tests",
    "pending test results": "pending_tests",
    "results pending": "pending_tests",
}

# Explicit document-ending markers, not medical instructions.
DOCUMENT_END_MARKERS = {
    "END OF DOCUMENT",
    "END OF REPORT",
    "END OF DISCHARGE SUMMARY",
    "END OF SYNTHETIC DISCHARGE SUMMARY",
}

_NUMBERED_SECTION_PREFIX = re.compile(r"^section\s+\d+\s*[—–-]\s*", re.IGNORECASE)
_NUMBERED_SECTION_HEADING = re.compile(r"^section\s+\d+\s*[—–-]\s*.+$", re.IGNORECASE)


def _section_heading(line: str) -> str | None:
    """Resolve known headings, including numbered synthetic-summary headings."""
    heading = line.rstrip(":").strip().lower()
    heading = _NUMBERED_SECTION_PREFIX.sub("", heading).strip()
    if heading in SECTION_NAMES:
        return SECTION_NAMES[heading]

    # Numbered sections often add a short descriptor to a recognized topic.
    # Only explicit topic phrases are mapped; unknown sections remain unknown.
    if heading.startswith("diagnosis and "):
        return "diagnosis"
    if heading.startswith("warning signs and "):
        return "warning_signs"
    return None


def _is_document_end_marker(line: str) -> bool:
    """Identify known document-ending markers without filtering normal prose."""
    normalized = re.sub(r"\s+", " ", line).strip().rstrip(" .:").upper()
    return normalized in DOCUMENT_END_MARKERS


def parse_and_split(text: str) -> list[Sentence]:
    """Split text into stable sentence IDs and infer coarse section headings."""
    current_section = "unknown"
    output: list[Sentence] = []

    for line in text.splitlines():
        stripped = line.strip()

        if not stripped:
            continue

        if _is_document_end_marker(stripped):
            continue

        heading = _section_heading(stripped)

        if heading is not None:
            current_section = heading
            continue

        if _NUMBERED_SECTION_HEADING.match(stripped):
            # A new but unsupported section must not inherit the previous
            # section's fact kind.
            current_section = "unknown"
            continue

        for sentence in _segmenter.segment(stripped):
            sentence = re.sub(r"\s+", " ", sentence).strip()

            if sentence:
                output.append(
                    Sentence(
                        id=f"S{len(output) + 1}",
                        text=sentence,
                        section=current_section,
                    )
                )

    return output
