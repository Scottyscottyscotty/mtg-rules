"""Board state analyzer — hybrid AI + deterministic rules engine.

Two-phase approach:
  Phase 1 (AI): Claude reads oracle text and identifies what triggers,
    what replacement effects apply, and what continuous effects exist.
    This is the part that requires language understanding.

  Phase 2 (Deterministic): Code handles the mechanical rules:
    - State-based actions (rule 704): what dies from toughness reduction
    - Layer ordering (rule 613): continuous effects in correct order
    - APNAP stack ordering (rule 101.4): whose triggers resolve when
    - Stack resolution (rule 405): LIFO

Claude focuses on WHAT happens. The code ensures the ORDER is correct.
"""

import asyncio
import json
import logging
import os
import re

import anthropic

logger = logging.getLogger(__name__)

CLAUDE_MODEL = os.environ.get("CLAUDE_MODEL", "claude-sonnet-4-6")

from app.models.board import (
    BoardAnalysisRequest,
    BoardAnalysisResult,
    BoardState,
    CascadeStep,
    DetectedTrigger,
    DidNotTrigger,
    EventType,
    GameEvent,
    PlayerState,
    ReplacementEffect,
)
from app.models.card import Card
from app.services.game_rules import (
    check_sbas,
    SBAResult,
    sort_effects_by_layer,
    LayerEffect,
    order_triggers_apnap,
    StackItem,
)
from app.services.game_rules.layers import classify_layer, get_layer_name
from app.services.game_rules.stack import describe_stack, resolution_order
from app.services.scryfall import fetch_card

# ---------------------------------------------------------------------------
# Phase 1 prompt: Claude identifies triggers, effects, and interactions.
# We explicitly tell it NOT to worry about ordering — the code handles that.
# ---------------------------------------------------------------------------

PHASE1_SYSTEM = """\
You are an expert Magic: The Gathering judge. Your job is to READ card oracle \
text and IDENTIFY what happens — which abilities trigger, which replacement \
effects apply, and what continuous effects are active.

You do NOT need to worry about:
- APNAP ordering (the code handles stack ordering)
- Layer ordering for continuous effects (the code handles that)
- State-based action checks for toughness (the code checks P/T math)

You DO need to:
- Read each card's oracle text carefully and determine if it triggers from the event
- Identify ALL replacement effects that would modify events
- Identify continuous effects (like "creatures you control get +1/+1")
- Identify P/T modifications from continuous effects (e.g., Massacre Wurm's -2/-2)
- Explain WHY each ability does or does not trigger (the rules distinction)
- Note any edge cases or ambiguities

CRITICAL: You are provided with EXACT card data from Scryfall. Use ONLY the \
provided oracle text — do NOT rely on your training data for card details.\
"""

PHASE1_PROMPT = """\
Analyze this board state and event. Identify ALL triggers, replacement effects, \
and continuous effects — but do NOT worry about ordering (the code handles APNAP \
and layer ordering).

## Board State

{board_description}

## Event

{event_description}

## Card Data (from Scryfall — the ONLY source of truth)

{card_texts}

## Pre-computed State-Based Actions

The code has already checked these SBAs deterministically:

{sba_results}

## Instructions

Respond with a JSON object. Do NOT include anything outside the JSON — no markdown fences.

{{
  "triggers": [
    {{
      "permanent_name": "<card that triggers>",
      "controller": "<who controls it>",
      "trigger_text": "<the relevant triggered ability text from oracle>",
      "trigger_condition": "<what event/condition caused this to trigger>",
      "resulting_effects": "<what the trigger does when it resolves>",
      "caused_by_event_type": "<event_type enum value>"
    }}
  ],
  "replacement_effects": [
    {{
      "permanent_name": "<card with replacement>",
      "controller": "<who controls it>",
      "replacement_text": "<the replacement ability text>",
      "what_it_replaces": "<what event is being replaced>",
      "what_happens_instead": "<the modified outcome>"
    }}
  ],
  "continuous_effects": [
    {{
      "permanent_name": "<card producing the effect>",
      "controller": "<who controls it>",
      "effect_text": "<the continuous effect text>",
      "pt_modification": [0, 0],
      "affects": "<what it affects, e.g., 'all creatures opponents control'>"
    }}
  ],
  "did_not_trigger": [
    {{
      "permanent_name": "<card that did NOT trigger>",
      "controller": "<who controls it>",
      "reason": "<clear explanation of WHY it didn't trigger — cite the specific rules distinction>"
    }}
  ],
  "cascade_events": [
    "<describe each new event that results from triggers resolving, so the code can check for further SBAs and triggers>"
  ],
  "warnings": ["<any edge cases, ambiguities, or missing card data>"]
}}

CRITICAL rules for trigger identification:
- "When/Whenever/At" = triggered ability. Check if the condition matches the event.
- -X/-X from a continuous effect is NOT the same as -1/-1 counters
- Losing life is NOT the same as being dealt damage
- Sacrifice is NOT the same as destroy (both cause "dying" though)
- "Leaves the battlefield" includes dying; "dies" is specifically going to graveyard
- "Cast" triggers happen when spell goes on stack; ETB triggers when it resolves
- For EACH permanent with triggered abilities that didn't fire, explain WHY in did_not_trigger\
"""

# ---------------------------------------------------------------------------
# Phase 2 prompt: after deterministic processing, Claude writes the summary
# ---------------------------------------------------------------------------

SUMMARY_SYSTEM = """\
You are an expert Magic: The Gathering judge writing a clear explanation of \
what happens during a game interaction. You will be given the full resolved \
sequence of events (triggers, SBAs, stack order) that was computed by a rules \
engine. Your job is to explain it clearly — both technically and in plain English.\
"""

SUMMARY_PROMPT = """\
Write a summary of this resolved board interaction. You'll get the full \
sequence that was computed by the rules engine.

## Original Event
{event_description}

## Board State
{board_description}

## Resolved Sequence

### State-Based Actions (computed deterministically)
{sba_section}

### Triggers Identified (from oracle text analysis)
{triggers_section}

### Stack Order (APNAP-ordered by rules engine)
{stack_section}

### Cards That Did NOT Trigger
{did_not_trigger_section}

### Warnings
{warnings_section}

## Instructions

Respond with JSON:
{{
  "summary": "<technical step-by-step summary>",
  "plain_english": "<casual, friendly explanation. Start with 'Okay, so here\\'s what happens...' and walk through each thing in plain language. After explaining what DOES happen, add 'What does NOT trigger:' explaining which permanents might LOOK like they should trigger but don't, and why. Call out common confusions (e.g., -2/-2 effects vs counters, life loss vs damage).>"
}}\
"""


async def analyze_board_event(request: BoardAnalysisRequest) -> BoardAnalysisResult:
    """Analyze what happens when an event occurs on a given board state.

    Two-phase hybrid approach:
      Phase 1: Claude identifies triggers, replacements, continuous effects
      Phase 2: Deterministic code orders everything (SBAs, layers, APNAP)
      Final: Claude writes the human-readable summary
    """
    board = request.board
    event = request.event
    warnings: list[str] = []

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        raise ValueError(
            "ANTHROPIC_API_KEY environment variable is not set. "
            "Set it in your .env file to use the board analyzer."
        )

    # ── Fetch card data from Scryfall ─────────────────────────────────────
    card_data = await _fetch_all_cards(board, warnings)

    # ── Phase 1a: Deterministic SBA check ─────────────────────────────────
    # Check what dies / what SBAs apply BEFORE asking Claude.
    # This gives Claude concrete facts ("these creatures die") rather than
    # making it do the math.
    sba_results = check_sbas(board, card_data)
    sba_text = _format_sba_results(sba_results)

    # ── Phase 1b: Claude identifies triggers and effects ──────────────────
    board_desc = _describe_board(board)
    event_desc = _describe_event(event)
    cards_desc = _describe_cards(card_data)

    prompt = PHASE1_PROMPT.format(
        board_description=board_desc,
        event_description=event_desc,
        card_texts=cards_desc,
        sba_results=sba_text,
    )

    client = anthropic.AsyncAnthropic(api_key=api_key)
    response = await client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=4000,
        system=PHASE1_SYSTEM,
        messages=[{"role": "user", "content": prompt}],
    )

    raw_text = response.content[0].text
    phase1 = _parse_json_response(raw_text)

    if phase1 is None:
        return BoardAnalysisResult(
            original_event=event,
            warnings=["Failed to parse Phase 1 response. Raw output in summary."],
            summary=raw_text,
            plain_english=raw_text,
        )

    # ── Phase 2: Deterministic ordering ───────────────────────────────────

    # 2a. Classify continuous effects by layer
    layer_effects = []
    for i, ce in enumerate(phase1.get("continuous_effects", [])):
        effect = LayerEffect(
            source_card=ce.get("permanent_name", "Unknown"),
            controller=ce.get("controller", "Unknown"),
            effect_text=ce.get("effect_text", ""),
            layer=classify_layer(ce.get("effect_text", "")),
            timestamp=i,  # use position as proxy for timestamp
        )
        layer_effects.append(effect)

    sorted_effects = sort_effects_by_layer(layer_effects)

    # 2b. Check if continuous effects cause additional SBAs
    # (e.g., -2/-2 killing creatures that Claude identified)
    pt_mods: dict[str, tuple[int, int]] = {}
    for ce in phase1.get("continuous_effects", []):
        pt_mod = ce.get("pt_modification", [0, 0])
        if pt_mod and (pt_mod[0] != 0 or pt_mod[1] != 0):
            affects = ce.get("affects", "")
            # Apply this modification to creatures it affects
            # For now, apply to all opponent creatures (Claude told us who it affects)
            for player in board.players:
                for perm in player.permanents:
                    card = card_data.get(perm.card_name)
                    if card and "Creature" in card.type_line:
                        # Check if this creature is affected
                        if _is_affected_by(
                            perm, player.name, ce, board
                        ):
                            existing = pt_mods.get(perm.card_name, (0, 0))
                            pt_mods[perm.card_name] = (
                                existing[0] + pt_mod[0],
                                existing[1] + pt_mod[1],
                            )

    # Re-check SBAs with continuous effect modifications applied
    if pt_mods:
        sba_with_effects = check_sbas(board, card_data, pt_mods)
        # Merge new SBAs (avoid duplicates)
        existing_descs = {s.description for s in sba_results}
        for sba in sba_with_effects:
            if sba.description not in existing_descs:
                sba_results.append(sba)

    # 2c. Order triggers by APNAP
    triggers_raw = phase1.get("triggers", [])
    stack_items = [
        StackItem(
            description=t.get("resulting_effects", ""),
            controller=t.get("controller", "Unknown"),
            source_card=t.get("permanent_name", "Unknown"),
            trigger_text=t.get("trigger_text", ""),
        )
        for t in triggers_raw
    ]

    active_player = board.active_player or (
        board.players[0].name if board.players else "Unknown"
    )
    player_order = [p.name for p in board.players]

    ordered_stack = order_triggers_apnap(stack_items, active_player, player_order)
    stack_descriptions = describe_stack(ordered_stack)

    # ── Build cascade steps ───────────────────────────────────────────────
    cascade = _build_cascade(event, sba_results, triggers_raw, sorted_effects)

    # ── Parse did_not_trigger from Claude's response ──────────────────────
    did_not_trigger = [
        DidNotTrigger(
            permanent_name=d.get("permanent_name", "Unknown"),
            controller=d.get("controller", "Unknown"),
            reason=d.get("reason", ""),
        )
        for d in phase1.get("did_not_trigger", [])
    ]

    # Merge warnings
    claude_warnings = phase1.get("warnings", [])
    all_warnings = warnings + claude_warnings

    # ── Final phase: Claude writes the human-readable summary ─────────────
    summary_prompt = SUMMARY_PROMPT.format(
        event_description=event_desc,
        board_description=board_desc,
        sba_section=sba_text if sba_results else "(none)",
        triggers_section=_format_triggers(triggers_raw),
        stack_section="\n".join(stack_descriptions) if stack_descriptions else "(empty stack)",
        did_not_trigger_section=_format_did_not_trigger(did_not_trigger),
        warnings_section="\n".join(f"- {w}" for w in all_warnings) if all_warnings else "(none)",
    )

    summary_response = await client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=2000,
        system=SUMMARY_SYSTEM,
        messages=[{"role": "user", "content": summary_prompt}],
    )

    summary_data = _parse_json_response(summary_response.content[0].text)
    summary = (summary_data or {}).get("summary", "")
    plain_english = (summary_data or {}).get("plain_english", "")

    return BoardAnalysisResult(
        original_event=event,
        cascade=cascade,
        stack_order=stack_descriptions,
        warnings=all_warnings,
        did_not_trigger=did_not_trigger,
        summary=summary,
        plain_english=plain_english,
    )


# ---------------------------------------------------------------------------
# Helpers: formatting
# ---------------------------------------------------------------------------

def _describe_board(board: BoardState) -> str:
    """Build a human-readable board description for the prompt."""
    lines = []
    lines.append(f"Active player: {board.active_player or 'not specified'}")
    lines.append(f"Number of players: {len(board.players)}")
    lines.append("")

    for player in board.players:
        lines.append(f"### {player.name} (Life: {player.life})")
        if player.permanents:
            for perm in player.permanents:
                ctrl = ""
                if perm.controller and perm.controller != perm.owner:
                    ctrl = f" (controlled by {perm.controller})"
                tapped = " [TAPPED]" if perm.tapped else ""
                counters = ""
                if perm.counters:
                    parts = [f"{v} {k}" for k, v in perm.counters.items()]
                    counters = f" [{', '.join(parts)}]"
                lines.append(f"  - {perm.card_name}{ctrl}{tapped}{counters}")
        else:
            lines.append("  - (no permanents)")
        lines.append("")

    return "\n".join(lines)


def _describe_event(event: GameEvent) -> str:
    """Build a human-readable event description."""
    parts = [f"Type: {event.event_type.value}"]
    if event.source_card:
        parts.append(f"Source card: {event.source_card}")
    if event.source_player:
        parts.append(f"Source player: {event.source_player}")
    if event.target_card:
        parts.append(f"Target card: {event.target_card}")
    if event.target_player:
        parts.append(f"Target player: {event.target_player}")
    if event.details:
        parts.append(f"Details: {event.details}")
    if event.amount is not None:
        parts.append(f"Amount: {event.amount}")
    return "\n".join(parts)


def _describe_cards(card_data: dict[str, Card]) -> str:
    """Format full card data for the prompt."""
    if not card_data:
        return "(No card data was retrieved — Scryfall lookups may have failed)"

    lines = []
    for name, card in card_data.items():
        lines.append(f"**{card.name}** (looked up as: {name})")
        if card.mana_cost:
            lines.append(f"  Mana cost: {card.mana_cost}")
        lines.append(f"  Type: {card.type_line}")
        if card.oracle_text:
            lines.append(f"  Oracle text: {card.oracle_text}")
        if card.power is not None and card.toughness is not None:
            lines.append(f"  Power/Toughness: {card.power}/{card.toughness}")
        if card.keywords:
            lines.append(f"  Keywords: {', '.join(card.keywords)}")
        lines.append("")
    return "\n".join(lines)


def _format_sba_results(results: list[SBAResult]) -> str:
    """Format SBA results for inclusion in the prompt."""
    if not results:
        return "(No state-based actions apply at this time)"

    lines = []
    for sba in results:
        lines.append(f"- [{sba.rule}] {sba.description}")
    return "\n".join(lines)


def _format_triggers(triggers: list[dict]) -> str:
    """Format identified triggers for the summary prompt."""
    if not triggers:
        return "(No triggers fired)"

    lines = []
    for t in triggers:
        card = t.get("permanent_name", "Unknown")
        controller = t.get("controller", "Unknown")
        text = t.get("trigger_text", "")
        effect = t.get("resulting_effects", "")
        lines.append(f"- {card} ({controller}): \"{text}\" -> {effect}")
    return "\n".join(lines)


def _format_did_not_trigger(items: list[DidNotTrigger]) -> str:
    """Format did-not-trigger items for the summary prompt."""
    if not items:
        return "(All permanents with triggered abilities either triggered or have no relevant triggers)"

    lines = []
    for item in items:
        lines.append(f"- {item.permanent_name} ({item.controller}): {item.reason}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Helpers: building cascade from deterministic + AI results
# ---------------------------------------------------------------------------

def _build_cascade(
    original_event: GameEvent,
    sbas: list[SBAResult],
    triggers: list[dict],
    layer_effects: list[LayerEffect],
) -> list[CascadeStep]:
    """Build the cascade sequence from SBAs, triggers, and layer effects."""
    steps: list[CascadeStep] = []
    step_num = 1

    # Step 1: The original event
    steps.append(CascadeStep(
        step_number=step_num,
        event=original_event,
        triggers_fired=[],
        replacements_applied=[],
        notes=[f"Event: {original_event.details or original_event.event_type.value}"],
    ))
    step_num += 1

    # Step 2: Layer effects apply (if any)
    if layer_effects:
        layer_notes = []
        for effect in layer_effects:
            layer_name = get_layer_name(effect.layer)
            layer_notes.append(
                f"{effect.source_card}'s effect applies in {layer_name}: "
                f"{effect.effect_text}"
            )
        steps.append(CascadeStep(
            step_number=step_num,
            event=GameEvent(
                event_type=EventType.TRIGGERED_ABILITY,
                details="Continuous effects applied in layer order",
            ),
            notes=layer_notes,
        ))
        step_num += 1

    # Step 3: State-based actions
    if sbas:
        for sba in sbas:
            sba_events = sba.events or []
            sba_triggers: list[DetectedTrigger] = []

            # Find triggers that were caused by this SBA
            for t in triggers:
                caused_by = t.get("caused_by_event_type", "")
                if caused_by in ("dies", "lose_life"):
                    # Check if this trigger relates to this SBA
                    for sba_event in sba_events:
                        if (sba_event.source_card and
                                t.get("trigger_condition", "").lower().find(
                                    sba_event.source_card.lower()) >= 0):
                            sba_triggers.append(DetectedTrigger(
                                permanent_name=t.get("permanent_name", "Unknown"),
                                controller=t.get("controller", "Unknown"),
                                trigger_text=t.get("trigger_text", ""),
                                caused_by=sba_event,
                            ))

            steps.append(CascadeStep(
                step_number=step_num,
                event=sba_events[0] if sba_events else GameEvent(
                    event_type=EventType.DIES,
                    details=sba.description,
                ),
                triggers_fired=sba_triggers,
                notes=[f"[{sba.rule}] {sba.description}"],
            ))
            step_num += 1

    # Remaining triggers not tied to SBAs
    sba_trigger_cards = set()
    for step in steps:
        for t in step.triggers_fired:
            sba_trigger_cards.add(t.permanent_name)

    remaining = [
        t for t in triggers
        if t.get("permanent_name", "") not in sba_trigger_cards
    ]

    if remaining:
        for t in remaining:
            caused_by_type = t.get("caused_by_event_type", "triggered_ability")
            try:
                evt_type = EventType(caused_by_type)
            except ValueError:
                evt_type = EventType.TRIGGERED_ABILITY

            steps.append(CascadeStep(
                step_number=step_num,
                event=GameEvent(
                    event_type=EventType.TRIGGERED_ABILITY,
                    source_card=t.get("permanent_name"),
                    details=t.get("resulting_effects", ""),
                ),
                triggers_fired=[DetectedTrigger(
                    permanent_name=t.get("permanent_name", "Unknown"),
                    controller=t.get("controller", "Unknown"),
                    trigger_text=t.get("trigger_text", ""),
                    caused_by=GameEvent(
                        event_type=evt_type,
                        details=t.get("trigger_condition", ""),
                    ),
                )],
                notes=[t.get("resulting_effects", "")],
            ))
            step_num += 1

    return steps


def _is_affected_by(
    perm: "PermanentOnBoard",
    player_name: str,
    continuous_effect: dict,
    board: BoardState,
) -> bool:
    """Heuristic: does a continuous effect affect this permanent?

    Uses keywords in the 'affects' field to determine scope.
    """
    affects = continuous_effect.get("affects", "").lower()
    effect_controller = continuous_effect.get("controller", "")
    source_card = continuous_effect.get("permanent_name", "")

    # Don't affect self (usually)
    if perm.card_name == source_card:
        return False

    if "all creatures" in affects:
        return True
    if "each creature" in affects:
        return True
    if "creatures opponents control" in affects or "opponent" in affects:
        return player_name != effect_controller
    if "creatures you control" in affects:
        return player_name == effect_controller
    if "other creatures" in affects:
        return perm.card_name != source_card

    # Default: assume it affects the permanent (Claude told us it's relevant)
    return True


# ---------------------------------------------------------------------------
# Helpers: data fetching and JSON parsing
# ---------------------------------------------------------------------------

async def _fetch_all_cards(
    board: BoardState, warnings: list[str]
) -> dict[str, Card]:
    """Fetch full card data for every unique card on the board, concurrently."""
    card_names = set()
    for player in board.players:
        for permanent in player.permanents:
            card_names.add(permanent.card_name)

    async def _fetch_one(name: str) -> tuple[str, Card | None]:
        card = await fetch_card(name)
        return name, card

    results = await asyncio.gather(
        *[_fetch_one(name) for name in card_names]
    )

    cards: dict[str, Card] = {}
    for name, card in results:
        if card and card.oracle_text:
            cards[name] = card
        elif card and not card.oracle_text:
            warnings.append(
                f"Card '{name}' was found but has no oracle text "
                f"(land or token?). It won't trigger anything."
            )
        else:
            warnings.append(
                f"Could not find card '{name}' on Scryfall. "
                f"Check the spelling — this card's abilities will be ignored."
            )

    if not cards:
        warnings.append(
            "No card data was retrieved for ANY card on the board. "
            "The analyzer cannot detect triggers without card data."
        )
    return cards


def _parse_json_response(raw_text: str) -> dict | None:
    """Parse JSON from Claude's response, handling markdown fences."""
    try:
        return json.loads(raw_text)
    except json.JSONDecodeError:
        json_match = re.search(r"```(?:json)?\s*(.*?)```", raw_text, re.DOTALL)
        if json_match:
            try:
                return json.loads(json_match.group(1))
            except json.JSONDecodeError:
                return None
        return None
