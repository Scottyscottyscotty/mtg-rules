"""Deterministic validation layer for Claude's analysis output.

Sits between Claude's raw JSON response and the final result. Cross-checks
AI classifications against oracle text patterns we can verify mechanically.

This catches the class of bugs where Claude:
- Lists a replacement-effect-only card in did_not_trigger
- Lists a card in both triggers AND did_not_trigger
- References a card not on the board
- Claims a trigger from oracle text that has no trigger clause
- Duplicates info across sections

Philosophy: trust Claude for semantic understanding (WHAT an ability does),
but verify structural classifications (IS it a trigger?) deterministically.
"""

import re
import logging

from app.models.card import Card

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Oracle text pattern detectors
# ---------------------------------------------------------------------------

# Triggered ability indicators: When, Whenever, At (the beginning/end of)
_TRIGGER_PATTERNS = [
    re.compile(r"\bwhen\b", re.IGNORECASE),
    re.compile(r"\bwhenever\b", re.IGNORECASE),
    re.compile(r"\bat the beginning of\b", re.IGNORECASE),
    re.compile(r"\bat end of\b", re.IGNORECASE),
    re.compile(r"\bat the end of\b", re.IGNORECASE),
]

# Replacement effect indicators: "instead", "if ... would ..., ... instead"
_REPLACEMENT_PATTERNS = [
    re.compile(r"\binstead\b", re.IGNORECASE),
    re.compile(r"\bif .+ would\b", re.IGNORECASE),
    re.compile(r"\bas though\b", re.IGNORECASE),
]

# Activated ability indicators: cost : effect
_ACTIVATED_PATTERN = re.compile(r"[^\"]*:.+", re.IGNORECASE)


def has_triggered_ability(oracle_text: str) -> bool:
    """Does this oracle text contain a triggered ability clause?"""
    if not oracle_text:
        return False
    return any(p.search(oracle_text) for p in _TRIGGER_PATTERNS)


def has_replacement_effect(oracle_text: str) -> bool:
    """Does this oracle text contain a replacement effect?"""
    if not oracle_text:
        return False
    return any(p.search(oracle_text) for p in _REPLACEMENT_PATTERNS)


# ---------------------------------------------------------------------------
# Main validation entry point
# ---------------------------------------------------------------------------

def validate_phase1(
    phase1: dict,
    card_data: dict[str, Card],
    board_card_names: set[str],
) -> dict:
    """Validate and reconcile Claude's Phase 1 output against oracle text.

    Mutates and returns the phase1 dict with corrections applied.
    Adds entries to phase1["warnings"] when corrections are made.

    Args:
        phase1: Claude's parsed JSON response.
        card_data: Card data keyed by name (from CardRegistry).
        board_card_names: Set of card names actually on the board.
    """
    warnings = phase1.setdefault("warnings", [])
    triggers = phase1.get("triggers", [])
    did_not_trigger = phase1.get("did_not_trigger", [])
    replacement_effects = phase1.get("replacement_effects", [])

    # Build lookup of card name -> oracle text
    oracle_lookup: dict[str, str] = {}
    for name in board_card_names:
        card = card_data.get(name)
        if card and card.oracle_text:
            oracle_lookup[name.lower()] = card.oracle_text
            oracle_lookup[card.name.lower()] = card.oracle_text

    # Track names used across sections for cross-referencing
    trigger_names = {t.get("permanent_name", "").lower() for t in triggers}
    replacement_names = {r.get("permanent_name", "").lower() for r in replacement_effects}

    # ── 1. Remove did_not_trigger entries for cards with no trigger text ──
    filtered_dnt: list[dict] = []
    for entry in did_not_trigger:
        name = entry.get("permanent_name", "")
        oracle = oracle_lookup.get(name.lower(), "")

        if not has_triggered_ability(oracle):
            # This card has no triggered abilities — it should never have
            # been in did_not_trigger at all.
            logger.info(
                "Validation: removed '%s' from did_not_trigger — "
                "no triggered ability in oracle text", name,
            )
            continue

        filtered_dnt.append(entry)

    phase1["did_not_trigger"] = filtered_dnt

    # ── 2. Remove cards that appear in BOTH triggers and did_not_trigger ──
    dnt_names = {d.get("permanent_name", "").lower() for d in filtered_dnt}
    contradiction_names = trigger_names & dnt_names
    if contradiction_names:
        # Card can't both trigger and not trigger — trust the trigger list
        phase1["did_not_trigger"] = [
            d for d in phase1["did_not_trigger"]
            if d.get("permanent_name", "").lower() not in contradiction_names
        ]
        for name in contradiction_names:
            logger.info(
                "Validation: removed '%s' from did_not_trigger — "
                "it appears in triggers (contradiction)", name,
            )

    # ── 3. Verify trigger claims against oracle text ─────────────────────
    verified_triggers: list[dict] = []
    for t in triggers:
        name = t.get("permanent_name", "")
        oracle = oracle_lookup.get(name.lower(), "")

        if not oracle:
            # No oracle text found — card may be missing from Scryfall or
            # may be a land/token with empty text. Skip unverifiable claims.
            logger.warning(
                "Validation: '%s' claimed as trigger but has no oracle text "
                "available — dropping unverifiable trigger", name,
            )
            warnings.append(
                f"'{name}' was listed as triggering but has no oracle text "
                f"available for verification. It was removed from triggers."
            )
            continue

        if not has_triggered_ability(oracle):
            # Claude says it triggers, but oracle text has no trigger clause.
            # This might be a replacement effect or static ability misclassified.
            logger.warning(
                "Validation: '%s' claimed as trigger but oracle has no "
                "When/Whenever/At clause — reclassifying", name,
            )
            # Check if it's actually a replacement effect
            if has_replacement_effect(oracle):
                # Move to replacement_effects if not already there
                if name.lower() not in replacement_names:
                    replacement_effects.append({
                        "permanent_name": name,
                        "controller": t.get("controller", "Unknown"),
                        "replacement_text": t.get("trigger_text", ""),
                        "what_it_replaces": t.get("trigger_condition", ""),
                        "what_happens_instead": t.get("resulting_effects", ""),
                    })
                    warnings.append(
                        f"'{name}' was reclassified from trigger to "
                        f"replacement effect based on oracle text."
                    )
                continue
            # If it's neither a trigger nor replacement, drop it with a warning
            warnings.append(
                f"'{name}' was listed as triggering but has no trigger clause "
                f"in its oracle text. It was removed from triggers."
            )
            continue

        verified_triggers.append(t)

    phase1["triggers"] = verified_triggers
    phase1["replacement_effects"] = replacement_effects

    # ── 4. Remove entries referencing cards not on the board ──────────────
    board_lower = {n.lower() for n in board_card_names}

    for section_key in ("triggers", "replacement_effects", "continuous_effects", "did_not_trigger"):
        items = phase1.get(section_key, [])
        original_len = len(items)
        phase1[section_key] = [
            item for item in items
            if item.get("permanent_name", "").lower() in board_lower
            or _find_card_by_canonical(item.get("permanent_name", ""), card_data) is not None
        ]
        removed = original_len - len(phase1[section_key])
        if removed:
            logger.info(
                "Validation: removed %d phantom entries from %s "
                "(cards not on the board)", removed, section_key,
            )

    return phase1


def _find_card_by_canonical(name: str, card_data: dict[str, Card]) -> Card | None:
    """Try to find a card by its canonical (Scryfall) name."""
    name_lower = name.lower()
    for card in card_data.values():
        if card.name.lower() == name_lower:
            return card
    return None
