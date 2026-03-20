"""Unified analysis pipeline — replaces board_analyzer.py and interaction_resolver.py.

Single entry point for all card/board analysis:
  - analyze_board(): Full board state analysis (triggers, SBAs, cascade)
  - analyze_interaction(): Card interaction analysis (replaces regex approach)

Both use the same Claude call structure + deterministic post-processing.
Rules engine context is fed to Claude for more accurate results.
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
from app.models.card import Card, InteractionResult
from app.services.card_registry import card_registry
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
from app.services.response_validator import validate_phase1
from app.services.rules_engine import rules_engine
from app.services.summary_renderer import render_summary

# ---------------------------------------------------------------------------
# Rules engine context lookup — maps events/keywords to rule sections
# ---------------------------------------------------------------------------

EVENT_TO_RULES: dict[str, list[str]] = {
    "enters_battlefield": ["603"],
    "leaves_battlefield": ["603"],
    "dies": ["603", "704"],
    "sacrifice": ["701.17"],
    "cast_spell": ["601"],
    "spell_resolves": ["608"],
    "spell_countered": ["701.5"],
    "attacks": ["506", "507", "508"],
    "blocks": ["509"],
    "combat_damage": ["510", "120"],
    "draw_card": ["121"],
    "discard": ["701.8"],
    "gain_life": ["119"],
    "lose_life": ["119"],
    "damage_dealt": ["120"],
    "counter_placed": ["122"],
    "counter_removed": ["122"],
    "triggered_ability": ["603"],
    "activate_ability": ["602"],
    "create_token": ["111"],
    "upkeep": ["503"],
    "draw_step": ["504"],
    "end_step": ["513"],
}

KEYWORD_TO_RULES: dict[str, str] = {
    "deathtouch": "702.2",
    "defender": "702.3",
    "double strike": "702.4",
    "first strike": "702.7",
    "flash": "702.8",
    "flying": "702.9",
    "haste": "702.10",
    "hexproof": "702.11",
    "indestructible": "702.12",
    "lifelink": "702.15",
    "menace": "702.110",
    "protection": "702.16",
    "reach": "702.17",
    "trample": "702.19",
    "vigilance": "702.20",
    "ward": "702.21",
}


def _get_rules_context(
    event_type: str | None = None,
    card_keywords: list[str] | None = None,
    include_sbas: bool = False,
) -> str:
    """Look up relevant rules sections to feed to Claude as context."""
    if not rules_engine._loaded:
        return ""

    parts: list[str] = []
    seen_sections: set[str] = set()

    # Event-based rules
    if event_type:
        section_nums = EVENT_TO_RULES.get(event_type, [])
        for num in section_nums:
            if num in seen_sections:
                continue
            seen_sections.add(num)
            section = rules_engine.get_section(num)
            if section:
                rules_text = "\n".join(
                    f"  {r.number}. {r.text}" for r in section.rules[:10]
                )
                parts.append(f"Rule section {section.number} — {section.title}:\n{rules_text}")

    # Keyword-based rules
    if card_keywords:
        for kw in card_keywords:
            rule_num = KEYWORD_TO_RULES.get(kw.lower())
            if rule_num and rule_num not in seen_sections:
                seen_sections.add(rule_num)
                rule = rules_engine.get_rule(rule_num)
                if rule:
                    parts.append(f"Rule {rule.number}: {rule.text}")

    # SBA rules
    if include_sbas and "704" not in seen_sections:
        section = rules_engine.get_section("704")
        if section:
            rules_text = "\n".join(
                f"  {r.number}. {r.text}" for r in section.rules[:15]
            )
            parts.append(f"Rule section 704 — {section.title}:\n{rules_text}")

    if not parts:
        return ""

    return (
        "\n## Relevant Comprehensive Rules (authoritative)\n\n"
        + "\n\n".join(parts)
    )


# ---------------------------------------------------------------------------
# Phase 1 prompt: Claude identifies triggers, effects, and interactions
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
- Cite specific rule numbers when possible (rules context is provided)

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
{rules_context}

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
      "caused_by_event_type": "<event_type enum value>",
      "rule_reference": "<rule number, e.g. 603.1>"
    }}
  ],
  "replacement_effects": [
    {{
      "permanent_name": "<card with replacement>",
      "controller": "<who controls it>",
      "replacement_text": "<the replacement ability text>",
      "what_it_replaces": "<what event is being replaced>",
      "what_happens_instead": "<the modified outcome>",
      "rule_reference": "<rule number>"
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
- For EACH permanent that HAS a triggered ability (When/Whenever/At clause) in its oracle text \
but that trigger did NOT fire from this event, explain WHY in did_not_trigger
- Do NOT include cards in did_not_trigger if they have no triggered abilities at all — cards with \
only replacement effects, static abilities, or keywords should NOT appear in did_not_trigger. \
Replacement effects are NOT triggers.\
"""

# ---------------------------------------------------------------------------
# Interaction analysis prompt (for card-vs-card analysis without board state)
# ---------------------------------------------------------------------------

INTERACTION_SYSTEM = """\
You are an expert Magic: The Gathering judge. Analyze how the given cards \
interact with each other mechanically. Consider the stack, layer system, \
replacement effects, triggered abilities, and keyword interactions.

CRITICAL: Use ONLY the provided oracle text from Scryfall. Cite rule numbers \
when possible.\
"""

INTERACTION_PROMPT = """\
Analyze how these cards interact with each other.

## Card Data (from Scryfall — the ONLY source of truth)

{card_texts}
{rules_context}

## Instructions

Respond with a JSON object. Do NOT include anything outside the JSON.

{{
  "stack_interactions": [
    "<how these cards interact on the stack>"
  ],
  "layer_interactions": [
    "<how continuous effects interact through the layer system>"
  ],
  "triggered_interactions": [
    "<triggered abilities that fire between these cards>"
  ],
  "replacement_interactions": [
    "<replacement effects that modify events between these cards>"
  ],
  "keyword_interactions": [
    "<notable keyword ability interactions (e.g., deathtouch + trample)>"
  ],
  "summary": "<comprehensive summary of how these cards interact>",
  "warnings": ["<edge cases or ambiguities>"]
}}\
"""


# ===========================================================================
# Board analysis — full board state with triggers, SBAs, cascade
# ===========================================================================

async def analyze_board(request: BoardAnalysisRequest) -> BoardAnalysisResult:
    """Analyze what happens when an event occurs on a given board state.

    Single-phase hybrid approach:
      1. Fetch all card data via CardRegistry
      2. Run deterministic SBA checks
      3. Gather rules context for the event/keywords
      4. Claude identifies triggers, replacements, continuous effects
      5. Deterministic code orders everything (layers, APNAP, stack)
      6. Summary renderer generates prose (no second Claude call)
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

    # ── Fetch card data via CardRegistry ──────────────────────────────────
    card_names = _collect_card_names(board)
    card_data = await card_registry.get_cards(list(card_names))
    _check_missing_cards(card_names, card_data, warnings)

    # ── Deterministic SBA check ───────────────────────────────────────────
    sba_results = check_sbas(board, card_data)
    sba_text = _format_sba_results(sba_results)

    # ── Gather rules context ──────────────────────────────────────────────
    all_keywords = _collect_keywords(card_data)
    rules_context = _get_rules_context(
        event_type=event.event_type.value,
        card_keywords=all_keywords,
        include_sbas=True,
    )

    # ── Claude identifies triggers and effects ────────────────────────────
    board_desc = _describe_board(board)
    event_desc = _describe_event(event)
    cards_desc = _describe_cards(card_data)

    prompt = PHASE1_PROMPT.format(
        board_description=board_desc,
        event_description=event_desc,
        card_texts=cards_desc,
        sba_results=sba_text,
        rules_context=rules_context,
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
            warnings=["Failed to parse AI response. Raw output in summary."],
            summary=raw_text,
            plain_english=raw_text,
        )

    # ── Validate Claude's output against oracle text ──────────────────────
    phase1 = validate_phase1(phase1, card_data, card_names)

    # ── Deterministic ordering ────────────────────────────────────────────

    # Classify continuous effects by layer
    layer_effects = []
    for i, ce in enumerate(phase1.get("continuous_effects", [])):
        effect = LayerEffect(
            source_card=ce.get("permanent_name", "Unknown"),
            controller=ce.get("controller", "Unknown"),
            effect_text=ce.get("effect_text", ""),
            layer=classify_layer(ce.get("effect_text", "")),
            timestamp=i,
        )
        layer_effects.append(effect)

    sorted_effects = sort_effects_by_layer(layer_effects)

    # Check if continuous effects cause additional SBAs
    pt_mods: dict[str, tuple[int, int]] = {}
    for ce in phase1.get("continuous_effects", []):
        pt_mod = ce.get("pt_modification", [0, 0])
        if pt_mod and (pt_mod[0] != 0 or pt_mod[1] != 0):
            for player in board.players:
                for perm in player.permanents:
                    card = card_data.get(perm.card_name)
                    if card and "Creature" in card.type_line:
                        if _is_affected_by(perm, player.name, ce, board):
                            existing = pt_mods.get(perm.card_name, (0, 0))
                            pt_mods[perm.card_name] = (
                                existing[0] + pt_mod[0],
                                existing[1] + pt_mod[1],
                            )

    if pt_mods:
        sba_with_effects = check_sbas(board, card_data, pt_mods)
        existing_descs = {s.description for s in sba_results}
        for sba in sba_with_effects:
            if sba.description not in existing_descs:
                sba_results.append(sba)

    # Order triggers by APNAP
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

    # ── Parse did_not_trigger ─────────────────────────────────────────────
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

    # ── Deterministic summary (no second Claude call) ─────────────────────
    summary, plain_english = render_summary(
        event=event,
        cascade=cascade,
        stack_order=stack_descriptions,
        sba_results=sba_results,
        triggers=triggers_raw,
        did_not_trigger=did_not_trigger,
        layer_effects=sorted_effects,
        warnings=all_warnings,
    )

    return BoardAnalysisResult(
        original_event=event,
        cascade=cascade,
        stack_order=stack_descriptions,
        warnings=all_warnings,
        did_not_trigger=did_not_trigger,
        summary=summary,
        plain_english=plain_english,
    )


# ===========================================================================
# Interaction analysis — card-vs-card without board state
# ===========================================================================

async def analyze_interaction(cards: list[Card]) -> InteractionResult:
    """Analyze how cards interact using Claude + rules context.

    Replaces the regex-based interaction_resolver with the same Claude
    approach used by board analysis, for consistent quality.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        raise ValueError(
            "ANTHROPIC_API_KEY environment variable is not set. "
            "Set it to use the interaction analyzer."
        )

    # Gather rules context from card keywords
    all_keywords: list[str] = []
    for card in cards:
        all_keywords.extend(kw.lower() for kw in card.keywords)

    rules_context = _get_rules_context(card_keywords=all_keywords)

    # Build card descriptions
    cards_desc = _describe_cards({card.name: card for card in cards})

    prompt = INTERACTION_PROMPT.format(
        card_texts=cards_desc,
        rules_context=rules_context,
    )

    client = anthropic.AsyncAnthropic(api_key=api_key)
    response = await client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=3000,
        system=INTERACTION_SYSTEM,
        messages=[{"role": "user", "content": prompt}],
    )

    raw_text = response.content[0].text
    data = _parse_json_response(raw_text)

    if data is None:
        # Fallback: return raw text as summary
        return InteractionResult(
            cards=cards,
            rulings=_collect_relevant_rulings(cards),
            stack_notes=[],
            layer_notes=[],
            replacement_notes=[],
            summary=raw_text,
        )

    # Collect card rulings for context
    rulings = _collect_relevant_rulings(cards)

    return InteractionResult(
        cards=cards,
        rulings=rulings,
        stack_notes=data.get("stack_interactions", []),
        layer_notes=data.get("layer_interactions", []),
        replacement_notes=data.get("replacement_interactions", []),
        summary=data.get("summary", ""),
    )


# ---------------------------------------------------------------------------
# Helpers: card name collection
# ---------------------------------------------------------------------------

def _collect_card_names(board: BoardState) -> set[str]:
    """Collect all unique card names from a board state."""
    names = set()
    for player in board.players:
        for permanent in player.permanents:
            names.add(permanent.card_name)
    return names


def _collect_keywords(card_data: dict[str, Card]) -> list[str]:
    """Collect all keywords from fetched cards."""
    keywords: list[str] = []
    for card in card_data.values():
        keywords.extend(kw.lower() for kw in card.keywords)
    return keywords


def _check_missing_cards(
    expected: set[str],
    found: dict[str, Card],
    warnings: list[str],
) -> None:
    """Add warnings for cards that couldn't be fetched."""
    for name in expected:
        card = found.get(name)
        if card and not card.oracle_text:
            warnings.append(
                f"Card '{name}' was found but has no oracle text "
                f"(land or token?). It won't trigger anything."
            )
        elif not card:
            warnings.append(
                f"Could not find card '{name}' on Scryfall. "
                f"Check the spelling — this card's abilities will be ignored."
            )
    if not found:
        warnings.append(
            "No card data was retrieved for ANY card on the board. "
            "The analyzer cannot detect triggers without card data."
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
        if card.rulings:
            lines.append(f"  Rulings: {'; '.join(card.rulings[:3])}")
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


def _collect_relevant_rulings(cards: list[Card]) -> list[str]:
    """Collect rulings from all cards."""
    all_rulings = []
    for card in cards:
        for ruling in card.rulings:
            all_rulings.append(f"[{card.name}] {ruling}")
    return all_rulings


# ---------------------------------------------------------------------------
# Helpers: cascade building and effect targeting
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

            for t in triggers:
                caused_by = t.get("caused_by_event_type", "")
                if caused_by in ("dies", "lose_life"):
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
    """Heuristic: does a continuous effect affect this permanent?"""
    affects = continuous_effect.get("affects", "").lower()
    effect_controller = continuous_effect.get("controller", "")
    source_card = continuous_effect.get("permanent_name", "")

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

    return True


# ---------------------------------------------------------------------------
# Helpers: JSON parsing
# ---------------------------------------------------------------------------

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
