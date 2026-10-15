"""Generate a deterministic synthetic clean/trap corpus and exact gold labels."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SYNTHETIC = ROOT / "synthetic"
GOLD = ROOT / "gold"

HEADINGS = [
    ("Diagnosis", "diagnosis"),
    ("Medications", "medication"),
    ("Follow-up", "appointment"),
    ("Restrictions", "restriction"),
    ("Warning signs", "warning_sign"),
    ("Pending tests", "pending_test"),
]

MEDICATIONS = [
    "amlodipine", "acetaminophen", "amoxicillin", "azithromycin", "ibuprofen",
    "aspirin", "atorvastatin", "lisinopril", "metformin", "omeprazole",
    "pantoprazole", "levothyroxine", "albuterol", "losartan", "furosemide",
    "prednisone", "ondansetron", "cephalexin", "doxycycline", "sertraline",
]
FOLLOW_UP_DAYS = [3, 5, 7, 10, 12, 14, 21]
RESTRICTIONS = [
    "Follow the written activity restrictions in the discharge paperwork.",
    "Use the mobility aid as described in the discharge paperwork.",
    "Keep the support wrap in place until the scheduled review.",
    "Avoid the activity listed in the discharge instructions until review.",
    "Follow the written lifting restriction until the follow-up visit.",
]
WARNINGS = [
    "Contact the care team if the warning signs listed in the discharge paperwork occur.",
    "Use the contact instructions in the discharge paperwork if symptoms worsen.",
    "Contact the care team if a new concern described in the paperwork occurs.",
    "Follow the written urgent-contact instructions if the listed warning signs occur.",
]
PENDING_TESTS = [
    "The final laboratory report is pending.",
    "A culture result is pending review.",
    "The final imaging report is pending.",
    "A follow-up test result is pending.",
]
TRAP_MEDICATIONS = [
    "warfarin", "insulin", "apixaban", "methotrexate", "morphine",
    "glimepiride", "heparin", "fentanyl", "potassium chloride", "amlodipine",
]
DIAGNOSES = [
    "A synthetic condition from scenario {number:02d} was documented during this hospital stay.",
    "The discharge team recorded a synthetic condition for scenario {number:02d}.",
    "Scenario {number:02d} includes a documented synthetic diagnosis.",
    "A diagnosis was entered for synthetic scenario {number:02d} before discharge.",
    "The synthetic discharge record lists a condition for scenario {number:02d}.",
]
MEDICATION_INSTRUCTIONS = [
    "Follow the discharge medication instructions for {medication}.",
    "See the written medication list for instructions about {medication}.",
    "Use the discharge paperwork for the instructions on {medication}.",
    "The medication plan for {medication} is listed in the discharge paperwork.",
    "Refer to the discharge medication list for how to take {medication}.",
]
FOLLOW_UP_TEMPLATES = [
    "Attend the follow-up appointment in {days} days.",
    "A follow-up appointment is scheduled for {days} days from discharge.",
    "Please attend a follow-up visit in {days} days.",
    "Your follow-up appointment should take place in {days} days.",
    "Arrange the listed follow-up visit within {days} days.",
]
TRAP_CONTINUE_TEMPLATES = [
    "Continue taking {medication} as written in the discharge medication instructions.",
    "Keep taking {medication} as directed in the discharge paperwork.",
    "Continue {medication} according to the written medication list.",
]
TRAP_STOP_TEMPLATES = [
    "Stop taking {medication} as written in the discharge medication instructions.",
    "Discontinue {medication} as directed in the discharge paperwork.",
    "Stop {medication} according to the written medication list.",
]

# Curated narrative-style cases broaden section-heading and sentence-phrase
# coverage. They contain only fictional, fixed facts and are intentionally not
# medication-dose examples.
NARRATIVE_CASES = [
    {
        "number": 51,
        "intro": "This fictional discharge note is software test scenario 51 and does not describe a real person.",
        "facts": [
            ("Clinical diagnosis", "diagnosis", "The discharge record notes a synthetic condition for scenario 51."),
            ("Medication list", "medication", "The fictional medication list includes amlodipine and says to follow the instructions printed there."),
            ("Follow-up plan", "appointment", "A follow-up appointment is set for 7 days after discharge."),
            ("Activity limits", "restriction", "Do not lift objects heavier than 5 kg until the follow-up visit."),
            ("When to get help", "warning_sign", "Seek urgent help if difficulty breathing occurs."),
            ("Results pending", "pending_test", "The final laboratory report is pending."),
        ],
    },
    {
        "number": 52,
        "intro": "Scenario 52 is a fictional example prepared only to exercise the discharge-summary parser.",
        "facts": [
            ("Discharge diagnosis", "diagnosis", "A synthetic condition is listed in the discharge record for scenario 52."),
            ("Discharge medicines", "medication", "Amlodipine appears on the fictional medication list with its instructions."),
            ("Next appointment", "appointment", "Please attend the follow-up visit scheduled for 7 days after discharge."),
            ("Activity guidance", "restriction", "Before the follow-up, do not lift anything heavier than 5 kg."),
            ("When to seek urgent help", "warning_sign", "Get urgent help if breathing becomes difficult."),
            ("Pending test results", "pending_test", "The final laboratory report has not yet been completed."),
        ],
    },
    {
        "number": 53,
        "intro": "Fictional evaluation record 53 contains invented facts and no real patient information.",
        "facts": [
            ("Diagnosis", "diagnosis", "Discharge documentation notes a synthetic condition for scenario 53."),
            ("Medication list", "medication", "The printed fictional medication instructions include amlodipine."),
            ("Follow up", "appointment", "The next appointment is arranged for 7 days from discharge."),
            ("Restrictions", "restriction", "A 5 kg lifting limit applies until the follow-up visit."),
            ("Warning signs", "warning_sign", "If breathing difficulty develops, seek urgent medical help."),
            ("Pending tests", "pending_test", "Final laboratory results remain pending."),
        ],
    },
    {
        "number": 54,
        "intro": "This is fictional software-test scenario 54, not a real discharge record.",
        "facts": [
            ("Clinical diagnosis", "diagnosis", "The discharge summary records a synthetic condition for scenario 54."),
            ("Discharge medications", "medication", "The fictional medication list names amlodipine and directs the reader to its printed instructions."),
            ("Follow-up plan", "appointment", "The follow-up appointment is due 7 days after leaving the hospital."),
            ("Activity limits", "restriction", "Keep lifting below 5 kg through the follow-up visit."),
            ("When to get help", "warning_sign", "Difficulty breathing is a reason to seek urgent help."),
            ("Results pending", "pending_test", "The final laboratory report is not yet available."),
        ],
    },
    {
        "number": 55,
        "intro": "Fictional scenario 55 is included to test alternate headings and wording in this software.",
        "facts": [
            ("Discharge diagnosis", "diagnosis", "A synthetic condition was documented for fictional scenario 55."),
            ("Discharge medicines", "medication", "Amlodipine is named in the fictional medication record; use the instructions printed with that list."),
            ("Next appointment", "appointment", "A follow-up appointment is scheduled in 7 days."),
            ("Activity guidance", "restriction", "Do not lift any object heavier than 5 kg before the follow-up."),
            ("When to seek urgent help", "warning_sign", "Seek urgent assistance for difficulty breathing."),
            ("Pending test results", "pending_test", "The final laboratory result has not yet returned."),
        ],
    },
]

CONFLICT_TRAP_CASES = [
    {
        "number": 56,
        "trap_type": "dose_conflict",
        "intro": "Fictional software trap scenario 56 contains two conflicting medication directions.",
        "facts": [
            "The fictional discharge medication list says to take warfarin 2 mg once daily.",
            "A separate line in that fictional list says to take warfarin 5 mg once daily.",
        ],
    },
    {
        "number": 57,
        "trap_type": "frequency_conflict",
        "intro": "Fictional software trap scenario 57 contains inconsistent schedule wording.",
        "facts": [
            "The fictional medication instructions say to take insulin once daily.",
            "Another line in the fictional instructions says to take insulin twice daily.",
        ],
    },
    {
        "number": 58,
        "trap_type": "duration_conflict",
        "intro": "Fictional software trap scenario 58 includes two different medication durations.",
        "facts": [
            "The fictional medication list says to take apixaban 5 mg twice daily for 5 days.",
            "A second fictional instruction says to take apixaban 5 mg twice daily for 10 days.",
        ],
    },
    {
        "number": 59,
        "trap_type": "dose_conflict",
        "intro": "Fictional software trap scenario 59 has inconsistent directions for one listed medicine.",
        "facts": [
            "One fictional instruction says to take methotrexate 2.5 mg once weekly.",
            "A second fictional instruction says to take methotrexate 5 mg once weekly.",
        ],
    },
]


def document_facts(number: int, trap: bool) -> list[tuple[str, str]]:
    medication = TRAP_MEDICATIONS[number - 41] if trap else MEDICATIONS[(number - 6) % len(MEDICATIONS)]
    variant = (number - 1) % len(FOLLOW_UP_TEMPLATES)
    facts = [
        (
            "diagnosis",
            DIAGNOSES[(number - 1) % len(DIAGNOSES)].format(number=number),
        ),
    ]
    if trap:
        continue_template = TRAP_CONTINUE_TEMPLATES[(number - 41) % len(TRAP_CONTINUE_TEMPLATES)]
        stop_template = TRAP_STOP_TEMPLATES[(number - 41) % len(TRAP_STOP_TEMPLATES)]
        facts.extend(
            [
                ("medication", continue_template.format(medication=medication)),
                ("medication", stop_template.format(medication=medication)),
            ]
        )
    else:
        facts.append(
            ("medication", MEDICATION_INSTRUCTIONS[(number - 6) % len(MEDICATION_INSTRUCTIONS)].format(medication=medication))
        )
    facts.extend(
        [
            (
                "appointment",
                FOLLOW_UP_TEMPLATES[variant].format(days=FOLLOW_UP_DAYS[(number - 1) % len(FOLLOW_UP_DAYS)]),
            ),
            ("restriction", RESTRICTIONS[(number - 1) % len(RESTRICTIONS)]),
            ("warning_sign", WARNINGS[(number - 1) % len(WARNINGS)]),
            ("pending_test", PENDING_TESTS[(number - 1) % len(PENDING_TESTS)]),
        ]
    )
    return facts


def write_document(number: int, trap: bool) -> None:
    doc_id = f"doc_{number:03d}"
    facts = document_facts(number, trap)
    sections: dict[str, list[tuple[str, str]]] = {}
    for kind, text in facts:
        sections.setdefault(kind, []).append((kind, text))

    heading_for_kind = dict((kind, heading) for heading, kind in HEADINGS)
    text_parts: list[str] = []
    gold_facts: list[dict] = []
    sentence_id = 0
    fact_id = 0
    for _heading, kind in HEADINGS:
        rows = sections.get(kind, [])
        if not rows:
            continue
        text_parts.append(f"{heading_for_kind[kind]}:")
        for _, sentence in rows:
            sentence_id += 1
            fact_id += 1
            text_parts.append(sentence)
            gold_facts.append(
                {
                    "id": f"F{fact_id}",
                    "kind": kind,
                    "text_en": sentence,
                    "source_ids": [f"S{sentence_id}"],
                }
            )

    (SYNTHETIC / f"{doc_id}.txt").write_text("\n".join(text_parts) + "\n", encoding="utf-8")
    gold_data = {
        "document_id": doc_id,
        "synthetic": True,
        "set": "trap" if trap else "clean",
        "facts": gold_facts,
    }
    if trap:
        gold_data["trap_type"] = "stop_continue_conflict"
    (GOLD / f"{doc_id}.json").write_text(
        json.dumps(gold_data, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def write_narrative_document(case: dict) -> None:
    """Write a curated narrative-style fixture and exact sentence references."""
    number = case["number"]
    doc_id = f"doc_{number:03d}"
    text_parts = [case["intro"]]
    gold_facts = []
    for index, (heading, kind, sentence) in enumerate(case["facts"], start=1):
        text_parts.extend([f"{heading}:", sentence])
        gold_facts.append(
            {
                "id": f"F{index}",
                "kind": kind,
                "text_en": sentence,
                "source_ids": [f"S{index + 1}"],
            }
        )

    (SYNTHETIC / f"{doc_id}.txt").write_text(
        "\n".join(text_parts) + "\n", encoding="utf-8"
    )
    (GOLD / f"{doc_id}.json").write_text(
        json.dumps(
            {
                "document_id": doc_id,
                "synthetic": True,
                "set": "clean",
                "narrative_style": True,
                "authoring": "curated synthetic facts",
                "facts": gold_facts,
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )


def write_conflict_trap_document(case: dict) -> None:
    """Write a fictional document with two conflicting instructions."""
    number = case["number"]
    doc_id = f"doc_{number:03d}"
    facts = []
    text_parts = [case["intro"], "Medication instructions:"]
    for index, sentence in enumerate(case["facts"], start=1):
        text_parts.append(sentence)
        facts.append(
            {
                "id": f"F{index}",
                "kind": "medication",
                "text_en": sentence,
                "source_ids": [f"S{index + 1}"],
            }
        )

    (SYNTHETIC / f"{doc_id}.txt").write_text(
        "\n".join(text_parts) + "\n", encoding="utf-8"
    )
    (GOLD / f"{doc_id}.json").write_text(
        json.dumps(
            {
                "document_id": doc_id,
                "synthetic": True,
                "set": "trap",
                "trap_type": case["trap_type"],
                "narrative_style": True,
                "authoring": "curated synthetic facts",
                "facts": facts,
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )


def main() -> None:
    SYNTHETIC.mkdir(parents=True, exist_ok=True)
    GOLD.mkdir(parents=True, exist_ok=True)
    for number in range(6, 41):
        write_document(number, trap=False)
    for number in range(41, 51):
        write_document(number, trap=True)
    for case in NARRATIVE_CASES:
        write_narrative_document(case)
    for case in CONFLICT_TRAP_CASES:
        write_conflict_trap_document(case)
    print(
        "Generated 40 clean and 14 trap synthetic documents (doc_006 through "
        "doc_059), including five curated clean narratives and four varied "
        "medication-conflict traps."
    )


if __name__ == "__main__":
    main()
