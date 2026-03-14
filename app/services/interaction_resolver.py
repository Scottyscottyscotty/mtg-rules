"""Resolves interactions between MTG cards.

Analyzes card oracle text, keywords, and official rulings to explain
how cards interact on the stack, through the layer system, and with
replacement effects.
"""

import re

from app.models.card import Card, InteractionResult
from app.services.rules_engine import rules_engine

# Patterns that indicate specific interaction types
REPLACEMENT_PATTERNS = [
    r"\binstead\b",
    r"\bif .+ would .+, .+ instead\b",
]
TRIGGERED_PATTERNS = [
    r"\bwhen(ever)?\b",
    r"\bat the beginning of\b",
    r"\bat end of\b",
]
STATIC_ABILITY_PATTERNS = [
    r"\ball .+ get [+-]\d+/[+-]\d+\b",
    r"\b\w+ have \w+\b",
    r"\bcosts? .+ (more|less)\b",
]
PROTECTION_PATTERNS = [
    r"\bprotection from\b",
    r"\bhexproof\b",
    r"\bshroud\b",
    r"\bindestructible\b",
    r"\bward\b",
]
COUNTER_PATTERNS = [
    r"\bcounter target\b",
    r"\bcan't be countered\b",
]

# Layer assignments per rule 613
LAYERS = {
    1: "Copy effects",
    2: "Control-changing effects",
    3: "Text-changing effects",
    4: "Type-changing effects",
    5: "Color-changing effects",
    6: "Ability-adding/removing effects",
    7: "Power/toughness-changing effects",
}

LAYER_7_SUBLAYERS = {
    "a": "Characteristic-defining abilities",
    "b": "Set P/T to specific value",
    "c": "Modifications from +X/+Y (not counters)",
    "d": "P/T changes from counters",
    "e": "Effects that switch P/T",
}


def analyze_interaction(cards: list[Card]) -> InteractionResult:
    """Analyze how a set of cards interact with each other."""
    rulings = _collect_relevant_rulings(cards)
    stack_notes = _analyze_stack_interaction(cards)
    layer_notes = _analyze_layer_interaction(cards)
    replacement_notes = _analyze_replacement_effects(cards)
    summary = _build_summary(cards, stack_notes, layer_notes, replacement_notes)

    return InteractionResult(
        cards=cards,
        rulings=rulings,
        stack_notes=stack_notes,
        layer_notes=layer_notes,
        replacement_notes=replacement_notes,
        summary=summary,
    )


def _collect_relevant_rulings(cards: list[Card]) -> list[str]:
    """Collect rulings from all cards, filtering for cross-card relevance."""
    all_rulings = []
    card_names = {c.name.lower() for c in cards}
    for card in cards:
        for ruling in card.rulings:
            # Include rulings that mention other cards in the interaction
            # or that discuss general interaction mechanics
            ruling_lower = ruling.lower()
            mentions_other = any(
                name in ruling_lower
                for name in card_names
                if name != card.name.lower()
            )
            has_interaction_keyword = any(
                kw in ruling_lower
                for kw in ["stack", "trigger", "replace", "instead", "layer",
                           "counter", "priority", "resolve", "response"]
            )
            if mentions_other or has_interaction_keyword:
                all_rulings.append(f"[{card.name}] {ruling}")
            else:
                all_rulings.append(f"[{card.name}] {ruling}")
    return all_rulings


def _analyze_stack_interaction(cards: list[Card]) -> list[str]:
    """Analyze how cards interact on the stack."""
    notes = []
    has_instant_speed = []
    has_counter = []
    has_uncounterable = []
    has_split_second = False

    for card in cards:
        oracle = (card.oracle_text or "").lower()
        type_line = card.type_line.lower()

        if "instant" in type_line or "flash" in oracle:
            has_instant_speed.append(card.name)
        if re.search(r"\bcounter target\b", oracle):
            has_counter.append(card.name)
        if "can't be countered" in oracle:
            has_uncounterable.append(card.name)
        if "split second" in oracle or "Split second" in (card.oracle_text or ""):
            has_split_second = True
            notes.append(
                f"{card.name} has split second — while it's on the stack, "
                "players can't cast spells or activate non-mana abilities."
            )

    if has_counter and has_uncounterable:
        for c in has_counter:
            for u in has_uncounterable:
                notes.append(
                    f"{c} cannot counter {u} because it can't be countered."
                )

    if len(has_instant_speed) > 1:
        notes.append(
            f"Both {' and '.join(has_instant_speed)} can be cast at instant speed, "
            "so they can respond to each other on the stack."
        )

    # Check for triggered abilities that stack
    triggered_cards = []
    for card in cards:
        oracle = (card.oracle_text or "").lower()
        if any(re.search(p, oracle) for p in TRIGGERED_PATTERNS):
            triggered_cards.append(card.name)

    if len(triggered_cards) > 1:
        notes.append(
            f"Multiple cards have triggered abilities ({', '.join(triggered_cards)}). "
            "If they trigger simultaneously, the active player's triggers go on the "
            "stack first (APNAP order), then the non-active player's."
        )

    if not notes:
        notes.append(
            "Standard stack interaction: spells resolve in LIFO (last in, first out) "
            "order. Each player receives priority to respond before each resolution."
        )

    return notes


def _analyze_layer_interaction(cards: list[Card]) -> list[str]:
    """Analyze continuous effect interactions through the layer system."""
    notes = []
    layer_effects: dict[int, list[str]] = {}

    for card in cards:
        oracle = (card.oracle_text or "").lower()

        # Check for P/T modifications (Layer 7)
        if re.search(r"[+-]\d+/[+-]\d+", oracle):
            layer_effects.setdefault(7, []).append(card.name)

        # Check for type changes (Layer 4)
        if re.search(r"\bis a?\b.*\b(in addition to|instead of)\b", oracle) or \
           re.search(r"\bbecomes? a\b", oracle):
            layer_effects.setdefault(4, []).append(card.name)

        # Check for ability granting (Layer 6)
        if re.search(r"\bgains?\b.*\b(flying|trample|haste|deathtouch)\b", oracle) or \
           re.search(r"\bhas\b.*\b(flying|trample|haste|deathtouch)\b", oracle) or \
           re.search(r"\bhave\b.*\b(flying|trample|haste|deathtouch)\b", oracle):
            layer_effects.setdefault(6, []).append(card.name)

        # Check for color changes (Layer 5)
        if re.search(r"\bis\b.*\b(white|blue|black|red|green)\b.*\binstead\b", oracle):
            layer_effects.setdefault(5, []).append(card.name)

        # Check for control changes (Layer 2)
        if re.search(r"\bgain control\b", oracle):
            layer_effects.setdefault(2, []).append(card.name)

        # Check for copy effects (Layer 1)
        if re.search(r"\bcopy\b|becomes? a copy\b", oracle):
            layer_effects.setdefault(1, []).append(card.name)

    if layer_effects:
        for layer_num in sorted(layer_effects.keys()):
            card_names = layer_effects[layer_num]
            notes.append(
                f"Layer {layer_num} ({LAYERS[layer_num]}): "
                f"Involves {', '.join(card_names)}. "
                f"Effects in this layer apply in timestamp order."
            )

        if len(layer_effects) > 1:
            layers = sorted(layer_effects.keys())
            notes.append(
                f"Multiple layers are involved ({', '.join(str(l) for l in layers)}). "
                "Effects are applied in layer order (lower layers first), "
                "regardless of timestamp."
            )

    return notes


def _analyze_replacement_effects(cards: list[Card]) -> list[str]:
    """Analyze replacement effect interactions."""
    notes = []
    replacement_cards = []
    prevention_cards = []

    for card in cards:
        oracle = (card.oracle_text or "").lower()
        if any(re.search(p, oracle) for p in REPLACEMENT_PATTERNS):
            replacement_cards.append(card.name)
        if "prevent" in oracle and ("damage" in oracle or "all damage" in oracle):
            prevention_cards.append(card.name)

    if len(replacement_cards) > 1:
        notes.append(
            f"Multiple replacement effects ({', '.join(replacement_cards)}) may apply "
            "to the same event. The affected player or controller of the affected "
            "object chooses which to apply first (rule 616.1)."
        )

    if replacement_cards and prevention_cards:
        notes.append(
            "Both replacement and prevention effects are present. Prevention effects "
            "are a type of replacement effect — if multiple apply, the affected "
            "player/controller chooses the order."
        )

    return notes


def _build_summary(
    cards: list[Card],
    stack_notes: list[str],
    layer_notes: list[str],
    replacement_notes: list[str],
) -> str:
    """Build a human-readable summary of the interaction."""
    parts = []
    card_names = [c.name for c in cards]
    parts.append(f"Interaction analysis for: {', '.join(card_names)}")

    # Check format legality overlaps
    formats_legal = None
    for card in cards:
        card_formats = {
            fmt for fmt, status in card.legalities.items() if status == "legal"
        }
        if formats_legal is None:
            formats_legal = card_formats
        else:
            formats_legal &= card_formats

    if formats_legal:
        parts.append(
            f"Both/all cards are legal together in: {', '.join(sorted(formats_legal))}"
        )
    else:
        parts.append(
            "Warning: These cards may not be legal together in any format."
        )

    # Check for keyword interactions
    all_keywords = set()
    for card in cards:
        all_keywords.update(kw.lower() for kw in card.keywords)

    notable_combos = []
    if "deathtouch" in all_keywords and "trample" in all_keywords:
        notable_combos.append(
            "Deathtouch + Trample: Only 1 damage needs to be assigned to "
            "each blocking creature (since deathtouch makes any amount lethal), "
            "the rest tramples over."
        )
    if "deathtouch" in all_keywords and "first strike" in all_keywords:
        notable_combos.append(
            "Deathtouch + First Strike: Deals lethal damage in the first strike "
            "step before regular combat damage."
        )
    if "lifelink" in all_keywords and "double strike" in all_keywords:
        notable_combos.append(
            "Lifelink + Double Strike: You gain life from both the first strike "
            "and regular combat damage steps."
        )
    if "indestructible" in all_keywords and "deathtouch" in all_keywords:
        notable_combos.append(
            "Indestructible vs Deathtouch: Deathtouch makes damage lethal, but "
            "indestructible prevents destruction from lethal damage. The creature "
            "survives."
        )
    if "hexproof" in all_keywords or "shroud" in all_keywords:
        targeting_cards = [
            c.name for c in cards
            if "target" in (c.oracle_text or "").lower()
        ]
        if targeting_cards:
            notable_combos.append(
                f"Hexproof/Shroud is present — {', '.join(targeting_cards)} "
                "may not be able to target the protected permanent."
            )
    if "protection" in " ".join(all_keywords).lower():
        notable_combos.append(
            "Protection prevents DEBT: Damage, Enchanting/Equipping, "
            "Blocking, and Targeting from sources with the specified quality."
        )

    if notable_combos:
        parts.append("\nNotable keyword interactions:")
        parts.extend(f"  - {combo}" for combo in notable_combos)

    if stack_notes:
        parts.append("\nStack interaction:")
        parts.extend(f"  - {note}" for note in stack_notes)

    if layer_notes:
        parts.append("\nLayer system:")
        parts.extend(f"  - {note}" for note in layer_notes)

    if replacement_notes:
        parts.append("\nReplacement effects:")
        parts.extend(f"  - {note}" for note in replacement_notes)

    return "\n".join(parts)
