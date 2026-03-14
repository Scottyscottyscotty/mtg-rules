"""Event detection engine.

Parses card oracle text to determine what game events a permanent
cares about (triggers, replacements, static effects) and what events
its abilities produce when they fire.
"""

import re

from app.models.board import (
    DetectedTrigger,
    EventType,
    GameEvent,
    PermanentOnBoard,
    ReplacementEffect,
)

# Maps oracle text patterns to the event types they trigger from.
# Each entry: (regex_pattern, event_type, description_template)
TRIGGER_PATTERNS: list[tuple[str, EventType, str]] = [
    # Casting triggers
    (r"whenever (?:a player|an opponent|you) casts? (?:a |an )?(.*?)spell",
     EventType.CAST_SPELL, "Triggers when a {0} spell is cast"),
    (r"whenever (?:a player|an opponent|you) casts? a (creature|instant|sorcery|enchantment|artifact|planeswalker)",
     EventType.CAST_SPELL, "Triggers when a {0} is cast"),

    # ETB triggers
    (r"when(?:ever)? .* enters(?: the battlefield)?",
     EventType.ENTERS_BATTLEFIELD, "Triggers on enter the battlefield"),
    (r"whenever another creature enters",
     EventType.ENTERS_BATTLEFIELD, "Triggers when another creature ETBs"),

    # Death triggers
    (r"when(?:ever)? .* dies",
     EventType.DIES, "Triggers when something dies"),
    (r"whenever a( nontoken)? creature( you control)? dies",
     EventType.DIES, "Triggers when a creature dies"),

    # Draw triggers
    (r"whenever (?:a player|an opponent|you) draws? (?:a |one or more )?cards?",
     EventType.DRAW_CARD, "Triggers on card draw"),
    (r"whenever you draw your (second|third) card",
     EventType.DRAW_CARD, "Triggers on specific card draw"),

    # Life gain/loss
    (r"whenever (?:a player|an opponent|you) gains? life",
     EventType.GAIN_LIFE, "Triggers on life gain"),
    (r"whenever (?:a player|an opponent|you) lose(?:s)? life",
     EventType.LOSE_LIFE, "Triggers on life loss"),

    # Damage triggers
    (r"whenever .* deals? (?:combat )?damage",
     EventType.DAMAGE_DEALT, "Triggers on damage dealt"),
    (r"whenever you are dealt damage",
     EventType.DAMAGE_DEALT, "Triggers when you are dealt damage"),

    # Combat triggers
    (r"whenever .* attacks",
     EventType.ATTACKS, "Triggers on attack"),
    (r"whenever .* blocks",
     EventType.BLOCKS, "Triggers on block"),

    # Discard triggers
    (r"whenever (?:a player|an opponent|you) discards? (?:a |one or more )?cards?",
     EventType.DISCARD, "Triggers on discard"),

    # Counter triggers
    (r"whenever (?:a|one or more) .*counters? (?:is|are) (?:placed|put) on",
     EventType.COUNTER_PLACED, "Triggers when counters are placed"),

    # Token triggers
    (r"whenever (?:a player|you) creates? (?:a |one or more )?tokens?",
     EventType.CREATE_TOKEN, "Triggers on token creation"),

    # Leave battlefield
    (r"whenever .* leaves the battlefield",
     EventType.LEAVES_BATTLEFIELD, "Triggers when something leaves the battlefield"),

    # Phase triggers
    (r"at the beginning of (?:each |your )?upkeep",
     EventType.UPKEEP, "Triggers at upkeep"),
    (r"at the beginning of (?:each |your )?end step",
     EventType.END_STEP, "Triggers at end step"),
]

# Patterns that indicate the card produces these events as output
EFFECT_PATTERNS: list[tuple[str, EventType]] = [
    (r"draw(?:s)? (?:a |(\d+) )?cards?", EventType.DRAW_CARD),
    (r"deals? (\d+) damage", EventType.DAMAGE_DEALT),
    (r"gains? (\d+) life", EventType.GAIN_LIFE),
    (r"lose(?:s)? (\d+) life", EventType.LOSE_LIFE),
    (r"create(?:s)? .* tokens?", EventType.CREATE_TOKEN),
    (r"destroy(?:s)? (?:target |all )", EventType.DIES),
    (r"sacrifice(?:s)? ", EventType.DIES),
    (r"discard(?:s)? ", EventType.DISCARD),
    (r"exile(?:s)? ", EventType.LEAVES_BATTLEFIELD),
    (r"counter(?:s)? target", EventType.SPELL_COUNTERED),
    (r"put(?:s)? .* counters? on", EventType.COUNTER_PLACED),
    (r"mill(?:s)? ", EventType.MILL),
]

# Replacement effect patterns
REPLACEMENT_PATTERNS: list[tuple[str, EventType]] = [
    (r"if (?:a player|an opponent|you) would draw a card.*instead",
     EventType.DRAW_CARD),
    (r"if (?:a player|an opponent|you) would gain life.*instead",
     EventType.GAIN_LIFE),
    (r"if (?:a player|an opponent|you) would lose life.*instead",
     EventType.LOSE_LIFE),
    (r"if .* would die.*instead", EventType.DIES),
    (r"if .* would deal damage.*instead", EventType.DAMAGE_DEALT),
    (r"if .* would enter the battlefield.*instead",
     EventType.ENTERS_BATTLEFIELD),
    (r"damage .* would deal .* is dealt to .* instead",
     EventType.DAMAGE_DEALT),
]


def detect_triggers(
    permanent: PermanentOnBoard,
    oracle_text: str,
    event: GameEvent,
) -> list[DetectedTrigger]:
    """Check if a permanent's oracle text triggers from a game event."""
    triggers = []
    oracle_lower = oracle_text.lower()

    for pattern, event_type, desc_template in TRIGGER_PATTERNS:
        if event.event_type != event_type:
            continue
        match = re.search(pattern, oracle_lower)
        if not match:
            continue

        # Check scope narrowing (e.g., "creature spell" vs any spell)
        if not _scope_matches(oracle_lower, pattern, event):
            continue

        # Determine what events this trigger produces
        resulting_events = _detect_produced_events(
            oracle_lower, permanent, event
        )

        trigger = DetectedTrigger(
            permanent_name=permanent.card_name,
            controller=permanent.effective_controller(),
            trigger_text=_extract_ability_text(oracle_text, match.start()),
            caused_by=event,
            resulting_events=resulting_events,
        )
        triggers.append(trigger)

    return triggers


def detect_replacements(
    permanent: PermanentOnBoard,
    oracle_text: str,
    event: GameEvent,
) -> list[ReplacementEffect]:
    """Check if a permanent has a replacement effect for a game event."""
    replacements = []
    oracle_lower = oracle_text.lower()

    for pattern, event_type in REPLACEMENT_PATTERNS:
        if event.event_type != event_type:
            continue
        match = re.search(pattern, oracle_lower)
        if not match:
            continue

        replacement = ReplacementEffect(
            permanent_name=permanent.card_name,
            controller=permanent.effective_controller(),
            replacement_text=_extract_ability_text(oracle_text, match.start()),
            original_event=event,
        )
        replacements.append(replacement)

    return replacements


def detect_static_modifications(
    oracle_text: str,
    event: GameEvent,
) -> list[str]:
    """Detect static abilities that modify how an event works.

    E.g., "Spells cost {1} more to cast" or "Creatures you control have haste."
    """
    notes = []
    oracle_lower = oracle_text.lower()

    # Cost modifications
    cost_patterns = [
        (r"(.*?) spells? (?:your opponents cast )?costs? \{?(\d+)\}? more",
         "increases cost"),
        (r"(.*?) spells? (?:you cast )?costs? \{?(\d+)\}? less",
         "decreases cost"),
    ]
    if event.event_type == EventType.CAST_SPELL:
        for pattern, effect in cost_patterns:
            match = re.search(pattern, oracle_lower)
            if match:
                notes.append(
                    f"Static effect: {match.group(0).strip()} ({effect})"
                )

    # "Can't" restrictions
    cant_patterns = [
        r"players? can't draw (?:more than \w+ )?cards?",
        r"players? can't gain life",
        r"players? can't cast .* spells?",
        r"creatures? can't attack",
        r"creatures? can't block",
        r"damage (?:that would be dealt .* )?can't be prevented",
    ]
    for pattern in cant_patterns:
        if re.search(pattern, oracle_lower):
            notes.append(f"Restriction: {re.search(pattern, oracle_lower).group(0)}")

    return notes


def _scope_matches(oracle_lower: str, pattern: str, event: GameEvent) -> bool:
    """Check if the trigger's scope (e.g. 'creature spell') matches the event."""
    # For now, broad matching — refinement would check event.details
    # against the specific card types mentioned in the trigger text
    if event.event_type == EventType.CAST_SPELL and event.details:
        # If the trigger says "creature spell" but the cast spell is an instant
        spell_type_match = re.search(
            r"(creature|instant|sorcery|enchantment|artifact|planeswalker|noncreature)",
            oracle_lower,
        )
        if spell_type_match:
            required_type = spell_type_match.group(1)
            event_details_lower = event.details.lower()
            if required_type == "noncreature":
                if "creature" in event_details_lower and "noncreature" not in event_details_lower:
                    return False
            elif required_type not in event_details_lower:
                return False
    return True


def _detect_produced_events(
    oracle_lower: str,
    permanent: PermanentOnBoard,
    triggering_event: GameEvent,
) -> list[GameEvent]:
    """Detect what events a triggered ability produces when it fires."""
    events = []
    for pattern, event_type in EFFECT_PATTERNS:
        match = re.search(pattern, oracle_lower)
        if match:
            amount = None
            for group in match.groups():
                if group and group.isdigit():
                    amount = int(group)
                    break

            events.append(GameEvent(
                event_type=event_type,
                source_card=permanent.card_name,
                source_player=permanent.effective_controller(),
                amount=amount,
                details=f"From {permanent.card_name}'s triggered ability",
            ))
    return events


def _extract_ability_text(oracle_text: str, match_start: int) -> str:
    """Extract the full ability text around a regex match position."""
    # Find the sentence/ability containing the match
    # Abilities are typically separated by newlines or periods followed by caps
    text = oracle_text
    # Find start of this ability (previous newline or start)
    start = text.rfind("\n", 0, match_start)
    start = start + 1 if start >= 0 else 0
    # Find end of this ability (next newline or end)
    end = text.find("\n", match_start)
    end = end if end >= 0 else len(text)
    return text[start:end].strip()
