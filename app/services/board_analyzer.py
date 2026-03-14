"""Board state analyzer powered by Claude API.

Given a board state (all players' permanents) and a game event,
sends everything to Claude to determine:
1. Which replacement effects modify the event
2. Which triggered abilities fire
3. What state-based actions occur (e.g., creatures dying from -2/-2)
4. The full cascade of triggers causing more triggers
5. APNAP stack ordering for multiplayer
6. Plain English explanation

This replaces the regex-based approach, which couldn't handle implicit
effects like creatures dying from toughness reduction, continuous
effects, or complex card interactions.
"""

import asyncio
import json
import os

import anthropic

from app.models.board import (
    BoardAnalysisRequest,
    BoardAnalysisResult,
    BoardState,
    CascadeStep,
    DetectedTrigger,
    EventType,
    GameEvent,
    PlayerState,
    ReplacementEffect,
)
from app.models.card import Card
from app.services.scryfall import fetch_card

BOARD_ANALYSIS_SYSTEM = """\
You are an expert Magic: The Gathering judge analyzing a board state interaction. \
You have perfect knowledge of the comprehensive rules, including:
- The stack (rule 405) and LIFO resolution
- Priority and APNAP ordering (rule 101.4) for multiplayer
- State-based actions (rule 704) — creatures with 0 or less toughness die, etc.
- Triggered abilities (rule 603) — "when", "whenever", "at"
- Replacement effects (rule 614) — "if ... would ... instead"
- Continuous effects and the layer system (rule 613)
- How sacrifice works (the permanent dies after being sacrificed)

CRITICAL: You are provided with EXACT card data from Scryfall (the official MTG database). \
Use ONLY the provided card stats (name, type, oracle text, power/toughness, mana cost). \
Do NOT rely on your memory for card details — your training data may have incorrect or \
outdated card information. If a card's data is not provided, say so in warnings rather \
than guessing.

You must trace through the COMPLETE chain of events, including:
- Effects that cause state-based actions (e.g., -2/-2 killing creatures)
- Triggers that fire from those state-based actions
- Cascading triggers (triggers causing more triggers)
- Which player controls each trigger for APNAP ordering
- Use the ACTUAL power/toughness values provided to determine what dies

Be thorough. Walk through every single thing that happens in order.\
"""

ANALYSIS_PROMPT_TEMPLATE = """\
Analyze this board state and event. Trace through EVERYTHING that happens, \
step by step, including state-based actions, cascading triggers, and APNAP ordering.

## Board State

{board_description}

## Event

{event_description}

## Card Data (from Scryfall — the ONLY source of truth for card stats)

{card_texts}

IMPORTANT: The card data above is fetched LIVE from Scryfall and is authoritative. \
Use ONLY these stats (power/toughness, oracle text, type line) for your analysis. \
Do NOT use any card information from your training data — it may be wrong.

## Instructions

Respond with a JSON object matching this exact structure. Do NOT include anything \
outside the JSON object — no markdown fences, no commentary.

{{
  "cascade": [
    {{
      "step_number": 1,
      "event": {{
        "event_type": "<one of: cast_spell, enters_battlefield, dies, sacrifice, draw_card, damage_dealt, gain_life, lose_life, discard, attacks, blocks, leaves_battlefield, create_token, upkeep, end_step, activate_ability, triggered_ability, spell_resolves, spell_countered, combat_damage, counter_placed, counter_removed, mill, draw_step>",
        "source_card": "<card name or null>",
        "source_player": "<player name or null>",
        "target_card": "<card name or null>",
        "target_player": "<player name or null>",
        "details": "<what's happening>",
        "amount": null
      }},
      "triggers_fired": [
        {{
          "permanent_name": "<card that triggers>",
          "controller": "<who controls it>",
          "trigger_text": "<the relevant ability text>",
          "caused_by": {{
            "event_type": "<event type>",
            "source_card": null,
            "source_player": null,
            "details": "<brief description>"
          }},
          "resulting_events": []
        }}
      ],
      "replacements_applied": [
        {{
          "permanent_name": "<card>",
          "controller": "<player>",
          "replacement_text": "<the replacement text>",
          "original_event": {{
            "event_type": "<event type>",
            "details": "<what was going to happen>"
          }}
        }}
      ],
      "notes": ["<explanation of what happens in this step>"]
    }}
  ],
  "stack_order": ["<item 1 (resolves first)>", "<item 2>"],
  "warnings": ["<any rules edge cases or ambiguities>"],
  "summary": "<technical step-by-step summary>",
  "plain_english": "<casual, friendly explanation written like you're explaining it to someone at the table. Start with 'Okay, so here\\'s what happens...' and walk through each thing that occurs in plain language. Mention which players are affected and why. Use a conversational tone.>"
}}

Important:
- Include ALL cascade steps, including state-based actions causing deaths
- event_type values must be exactly one of the enum values listed above
- Every trigger must reference which event caused it
- Stack order should be listed in resolution order (last in, first out)
- For multiplayer, active player's triggers go on stack first (resolve last per APNAP)
- The plain_english field should be thorough but readable — like a judge explaining at the table
- If a card's oracle text wasn't provided (not found on Scryfall), mention it in warnings\
"""


async def analyze_board_event(request: BoardAnalysisRequest) -> BoardAnalysisResult:
    """Analyze what happens when an event occurs on a given board state."""
    board = request.board
    event = request.event
    warnings: list[str] = []

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        raise ValueError(
            "ANTHROPIC_API_KEY environment variable is not set. "
            "Set it in your .env file to use the board analyzer."
        )

    # Fetch full card data for all permanents on the board
    card_data = await _fetch_all_cards(board, warnings)

    # Build the prompt
    board_desc = _describe_board(board)
    event_desc = _describe_event(event)
    cards_desc = _describe_cards(card_data)

    prompt = ANALYSIS_PROMPT_TEMPLATE.format(
        board_description=board_desc,
        event_description=event_desc,
        card_texts=cards_desc,
    )

    # Call Claude
    client = anthropic.AsyncAnthropic(api_key=api_key)
    response = await client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=4000,
        system=BOARD_ANALYSIS_SYSTEM,
        messages=[{"role": "user", "content": prompt}],
    )

    raw_text = response.content[0].text

    # Parse the JSON response
    try:
        data = json.loads(raw_text)
    except json.JSONDecodeError:
        # Try to extract JSON from markdown fences
        import re
        json_match = re.search(r"```(?:json)?\s*(.*?)```", raw_text, re.DOTALL)
        if json_match:
            data = json.loads(json_match.group(1))
        else:
            # Return a readable error with the raw response
            return BoardAnalysisResult(
                original_event=event,
                cascade=[],
                stack_order=[],
                warnings=["Failed to parse Claude's response. Raw output included in summary."],
                summary=raw_text,
                plain_english=raw_text,
            )

    # Convert the JSON into our typed models
    return _parse_analysis_response(data, event, warnings)


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
                lines.append(f"  - {perm.card_name}{ctrl}{tapped}")
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
    """Format full card data for the prompt — type, P/T, oracle text, everything."""
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


async def _fetch_all_cards(
    board: BoardState, warnings: list[str]
) -> dict[str, Card]:
    """Fetch full card data for every unique card on the board, concurrently."""
    card_names = set()
    for player in board.players:
        for permanent in player.permanents:
            card_names.add(permanent.card_name)

    # Fetch all cards concurrently (Scryfall cache handles rate limiting
    # for already-cached cards; new cards go through fetch_card which
    # hits the API one at a time)
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


def _parse_analysis_response(
    data: dict,
    original_event: GameEvent,
    warnings: list[str],
) -> BoardAnalysisResult:
    """Convert Claude's JSON response into typed BoardAnalysisResult."""
    cascade = []
    for step_data in data.get("cascade", []):
        step = CascadeStep(
            step_number=step_data.get("step_number", 0),
            event=_parse_event(step_data.get("event", {})),
            triggers_fired=[
                _parse_trigger(t) for t in step_data.get("triggers_fired", [])
            ],
            replacements_applied=[
                _parse_replacement(r)
                for r in step_data.get("replacements_applied", [])
            ],
            notes=step_data.get("notes", []),
        )
        cascade.append(step)

    # Merge any warnings from Claude with our fetch warnings
    claude_warnings = data.get("warnings", [])
    all_warnings = warnings + claude_warnings

    return BoardAnalysisResult(
        original_event=original_event,
        cascade=cascade,
        stack_order=data.get("stack_order", []),
        warnings=all_warnings,
        summary=data.get("summary", ""),
        plain_english=data.get("plain_english", ""),
    )


def _parse_event(data: dict) -> GameEvent:
    """Parse a GameEvent from Claude's JSON."""
    event_type_str = data.get("event_type", "triggered_ability")
    try:
        event_type = EventType(event_type_str)
    except ValueError:
        event_type = EventType.TRIGGERED_ABILITY

    return GameEvent(
        event_type=event_type,
        source_card=data.get("source_card"),
        source_player=data.get("source_player"),
        target_card=data.get("target_card"),
        target_player=data.get("target_player"),
        details=data.get("details", ""),
        amount=data.get("amount"),
    )


def _parse_trigger(data: dict) -> DetectedTrigger:
    """Parse a DetectedTrigger from Claude's JSON."""
    return DetectedTrigger(
        permanent_name=data.get("permanent_name", "Unknown"),
        controller=data.get("controller", "Unknown"),
        trigger_text=data.get("trigger_text", ""),
        caused_by=_parse_event(data.get("caused_by", {})),
        resulting_events=[
            _parse_event(e) for e in data.get("resulting_events", [])
        ],
    )


def _parse_replacement(data: dict) -> ReplacementEffect:
    """Parse a ReplacementEffect from Claude's JSON."""
    return ReplacementEffect(
        permanent_name=data.get("permanent_name", "Unknown"),
        controller=data.get("controller", "Unknown"),
        replacement_text=data.get("replacement_text", ""),
        original_event=_parse_event(data.get("original_event", {})),
    )
