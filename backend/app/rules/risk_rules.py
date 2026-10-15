from pathlib import Path
import re
import yaml

RULES_PATH = Path(__file__).resolve().parents[3] / "data" / "rules" / "high_alert.yaml"
MEDICATION_NAMES_PATH = RULES_PATH.with_name("medication_names.yaml")
FREQUENCY_POLICY_PATH = RULES_PATH.with_name("medication_frequency_policy.yaml")


def requires_frequency_review(text: str) -> bool:
    """Flag explicit daily frequencies above the configured prototype limit."""
    if not FREQUENCY_POLICY_PATH.exists():
        return False
    with FREQUENCY_POLICY_PATH.open("r", encoding="utf-8") as handle:
        policy = yaml.safe_load(handle) or {}
    threshold = policy.get("maximum_explicit_times_per_day")
    if not isinstance(threshold, int) or threshold < 1:
        return False
    return any(
        int(match.group(1)) > threshold
        for match in re.finditer(
            r"\b(\d+)\s+times?\s+(?:(?:a|per)\s+day|daily)\b",
            text,
            re.IGNORECASE,
        )
    )

def load_high_alert_rules() -> dict:
    if not RULES_PATH.exists():
        return {"medications": []}
    with RULES_PATH.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {"medications": []}


def find_high_alert_medications(text: str) -> list[str]:
    """Return configured high-alert medication names found in text.

    Matching is case-insensitive and uses word boundaries so short names
    do not match as substrings of unrelated words. The YAML list is a
    starter ruleset, not a complete medication safety reference.
    """
    matches: list[str] = []
    rules = load_high_alert_rules()

    for medication in rules.get("medications", []):
        names = [medication.get("generic", ""), *medication.get("aliases", [])]
        for name in names:
            name = name.strip()
            if name and re.search(rf"(?<!\w){re.escape(name)}(?!\w)", text, re.IGNORECASE):
                matches.append(name)
                break

    return matches


def find_known_medication_entities(text: str) -> set[str]:
    """Return canonical names for configured medication aliases found in text.

    Combines the partial high-alert subset with a separate supplemental
    generic-name subset. This is lexical matching, not a complete drug NER.
    """
    configured = list(load_high_alert_rules().get("medications", []))
    if MEDICATION_NAMES_PATH.exists():
        with MEDICATION_NAMES_PATH.open("r", encoding="utf-8") as handle:
            supplement = yaml.safe_load(handle) or {}
        configured.extend(supplement.get("medications", []))

    found: set[str] = set()
    for item in configured:
        aliases = [item.get("generic", ""), *item.get("aliases", [])]
        if any(
            alias.strip()
            and re.search(rf"(?<!\w){re.escape(alias.strip())}(?!\w)", text, re.IGNORECASE)
            for alias in aliases
        ):
            found.add(item.get("generic", "").casefold())
    return found
