"""Board state analyzer with cascade resolution.

Given a board state (all players' permanents) and a game event,
determines:
1. Which replacement effects modify the event before it happens
2. Which triggered abilities fire from the event
3. What new events those triggers produce
4. Recursively resolves the full cascade (triggers causing triggers)
5. Determines APNAP stack ordering for multiplayer

This is the heart of the multiplayer interaction engine.
"""

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
from app.services.event_detector import (
    detect_replacements,
    detect_static_modifications,
    detect_triggers,
)
import asyncio

from app.services.scryfall import fetch_card

# Safety limit to prevent infinite loops
MAX_CASCADE_DEPTH = 20


async def analyze_board_event(request: BoardAnalysisRequest) -> BoardAnalysisResult:
    """Analyze what happens when an event occurs on a given board state."""
    board = request.board
    event = request.event

    # Fetch oracle text for all permanents on the board
    card_texts = await _fetch_all_card_texts(board, warnings)

    # Resolve the cascade
    cascade: list[CascadeStep] = []
    warnings: list[str] = []
    stack_order: list[str] = []

    # Determine APNAP order (Active Player, Non-Active Player)
    apnap_order = _get_apnap_order(board)

    # Process the initial event through the cascade.
    # Sacrifice implies death — queue both events so "dies" triggers also fire.
    events_to_process = [event]
    if event.event_type == EventType.SACRIFICE:
        dies_event = GameEvent(
            event_type=EventType.DIES,
            source_card=event.source_card,
            source_player=event.source_player,
            target_card=event.target_card,
            target_player=event.target_player,
            details=f"{event.source_card or 'A permanent'} was sacrificed and dies",
        )
        events_to_process.append(dies_event)
    depth = 0

    while events_to_process and depth < MAX_CASCADE_DEPTH:
        current_event = events_to_process.pop(0)
        step = CascadeStep(
            step_number=depth + 1,
            event=current_event,
        )

        # 1. Check replacement effects first (they modify the event)
        all_replacements: list[ReplacementEffect] = []
        for player in board.players:
            for permanent in player.permanents:
                oracle = card_texts.get(permanent.card_name, "")
                if not oracle:
                    continue
                replacements = detect_replacements(
                    permanent, oracle, current_event
                )
                all_replacements.extend(replacements)

        if all_replacements:
            step.replacements_applied = all_replacements
            if len(all_replacements) > 1:
                affected = current_event.target_player or current_event.source_player
                step.notes.append(
                    f"Multiple replacement effects apply to this event. "
                    f"The affected player ({affected or 'controller'}) "
                    f"chooses which to apply first (rule 616.1)."
                )
            for r in all_replacements:
                step.notes.append(
                    f"  Replacement from {r.permanent_name} "
                    f"(controlled by {r.controller}): {r.replacement_text}"
                )

        # 2. Check static ability modifications
        for player in board.players:
            for permanent in player.permanents:
                oracle = card_texts.get(permanent.card_name, "")
                if not oracle:
                    continue
                static_notes = detect_static_modifications(oracle, current_event)
                step.notes.extend(
                    f"[{permanent.card_name}] {n}" for n in static_notes
                )

        # 3. Detect triggered abilities in APNAP order
        all_triggers: list[DetectedTrigger] = []
        for player_name in apnap_order:
            player = _find_player(board, player_name)
            if not player:
                continue
            player_triggers: list[DetectedTrigger] = []
            for permanent in player.permanents:
                oracle = card_texts.get(permanent.card_name, "")
                if not oracle:
                    continue
                triggers = detect_triggers(permanent, oracle, current_event)
                player_triggers.extend(triggers)

            if player_triggers:
                all_triggers.extend(player_triggers)
                # In APNAP, active player's triggers go on stack first
                # (so they resolve last — LIFO)
                for t in player_triggers:
                    stack_order.append(
                        f"{t.permanent_name} ({t.controller}): {t.trigger_text}"
                    )

        step.triggers_fired = all_triggers

        if all_triggers:
            step.notes.append(
                f"{len(all_triggers)} triggered ability(ies) fire in APNAP order."
            )
            for t in all_triggers:
                step.notes.append(
                    f"  {t.permanent_name} ({t.controller}): {t.trigger_text}"
                )
                # Queue the resulting events for cascade processing
                events_to_process.extend(t.resulting_events)

        cascade.append(step)
        depth += 1

    if depth >= MAX_CASCADE_DEPTH:
        warnings.append(
            f"Cascade depth limit ({MAX_CASCADE_DEPTH}) reached. "
            "There may be additional triggers not shown. This can happen "
            "with infinite or near-infinite loops."
        )

    # Build summary
    summary = _build_board_summary(event, cascade, stack_order, warnings, board)
    plain_english = _build_plain_english(event, cascade, stack_order, board)

    return BoardAnalysisResult(
        original_event=event,
        cascade=cascade,
        stack_order=list(reversed(stack_order)),  # LIFO — last added resolves first
        warnings=warnings,
        summary=summary,
        plain_english=plain_english,
    )


async def _fetch_all_card_texts(
    board: BoardState, warnings: list[str]
) -> dict[str, str]:
    """Fetch oracle text for every unique card on the board."""
    card_names = set()
    for player in board.players:
        for permanent in player.permanents:
            card_names.add(permanent.card_name)

    texts: dict[str, str] = {}
    for i, name in enumerate(card_names):
        if i > 0:
            await asyncio.sleep(0.1)  # Scryfall rate limit: 50-100ms between requests
        card = await fetch_card(name)
        if card and card.oracle_text:
            texts[name] = card.oracle_text
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

    if not texts:
        warnings.append(
            "No card oracle text was retrieved for ANY card on the board. "
            "The analyzer cannot detect triggers without oracle text."
        )
    return texts


def _get_apnap_order(board: BoardState) -> list[str]:
    """Get Active Player, Non-Active Player ordering.

    The active player's triggers go on the stack first, then each
    other player in turn order. Since they go on first, they resolve
    last (LIFO).
    """
    player_names = [p.name for p in board.players]
    if board.active_player and board.active_player in player_names:
        idx = player_names.index(board.active_player)
        return player_names[idx:] + player_names[:idx]
    return player_names


def _find_player(board: BoardState, name: str) -> PlayerState | None:
    for p in board.players:
        if p.name == name:
            return p
    return None


def _build_board_summary(
    event: GameEvent,
    cascade: list[CascadeStep],
    stack_order: list[str],
    warnings: list[str],
    board: BoardState,
) -> str:
    parts = []

    # Header
    event_desc = f"{event.event_type.value}"
    if event.source_card:
        event_desc += f" ({event.source_card})"
    if event.source_player:
        event_desc += f" by {event.source_player}"
    parts.append(f"Event: {event_desc}")
    parts.append(f"Players: {', '.join(p.name for p in board.players)}")

    # Board overview
    parts.append("\nBoard state:")
    for player in board.players:
        perm_names = [p.card_name for p in player.permanents]
        parts.append(f"  {player.name} ({player.life} life): {', '.join(perm_names) or 'no permanents'}")

    # Cascade summary
    total_triggers = sum(len(s.triggers_fired) for s in cascade)
    total_replacements = sum(len(s.replacements_applied) for s in cascade)
    parts.append(f"\nCascade: {len(cascade)} step(s), {total_triggers} trigger(s), {total_replacements} replacement(s)")

    # Step-by-step
    for step in cascade:
        parts.append(f"\nStep {step.step_number}: {step.event.event_type.value}")
        if step.event.source_card:
            parts.append(f"  Source: {step.event.source_card}")
        for note in step.notes:
            parts.append(f"  {note}")

    # Stack resolution order
    if stack_order:
        parts.append("\nStack (resolves top to bottom):")
        for i, item in enumerate(stack_order, 1):
            parts.append(f"  {i}. {item}")

    # Warnings
    for w in warnings:
        parts.append(f"\nWarning: {w}")

    return "\n".join(parts)


# Friendly names for event types
_EVENT_DESCRIPTIONS = {
    "cast_spell": "casts a spell",
    "enters_battlefield": "enters the battlefield",
    "leaves_battlefield": "leaves the battlefield",
    "dies": "dies",
    "sacrifice": "sacrifices a permanent",
    "draw_card": "draws a card",
    "discard": "discards",
    "damage_dealt": "deals damage",
    "gain_life": "gains life",
    "lose_life": "loses life",
    "attacks": "attacks",
    "blocks": "blocks",
    "create_token": "creates a token",
    "activate_ability": "activates an ability",
    "triggered_ability": "triggers an ability",
    "spell_resolves": "has a spell resolve",
    "spell_countered": "has a spell countered",
    "combat_damage": "deals combat damage",
    "counter_placed": "has counters placed",
    "counter_removed": "has counters removed",
    "mill": "mills cards",
    "upkeep": "begins their upkeep",
    "draw_step": "begins their draw step",
    "end_step": "begins the end step",
}

_EFFECT_DESCRIPTIONS = {
    "draw_card": "draw",
    "damage_dealt": "deal damage",
    "gain_life": "gain life",
    "lose_life": "lose life",
    "create_token": "create a token",
    "dies": "destroy something",
    "sacrifice": "sacrifice something",
    "discard": "discard",
    "leaves_battlefield": "exile something",
    "spell_countered": "counter a spell",
    "counter_placed": "put counters on something",
    "mill": "mill",
}


def _build_plain_english(
    event: GameEvent,
    cascade: list[CascadeStep],
    stack_order: list[str],
    board: BoardState,
) -> str:
    """Build a plain English walkthrough of what happens.

    Written like you'd explain it to someone at the table:
    "Okay so here's what happens..."
    """
    lines = []

    # Opening — describe what kicked this off
    event_desc = _EVENT_DESCRIPTIONS.get(event.event_type.value, event.event_type.value)
    who = event.source_player or "A player"
    what_card = f" ({event.source_card})" if event.source_card else ""
    lines.append(f"Okay, so {who} {event_desc}{what_card}. Here's what happens:\n")

    # Check if anything actually triggers
    total_triggers = sum(len(s.triggers_fired) for s in cascade)
    total_replacements = sum(len(s.replacements_applied) for s in cascade)

    if total_triggers == 0 and total_replacements == 0:
        lines.append(
            "Nothing on the board cares about this. "
            "It just happens normally — no triggers, no funny business."
        )
        return "\n".join(lines)

    # Walk through replacements first (they happen before the event)
    step_num = 1
    has_replacements = False
    for step in cascade:
        if not step.replacements_applied:
            continue
        if not has_replacements:
            lines.append("BEFORE it happens:")
            has_replacements = True
        for r in step.replacements_applied:
            lines.append(
                f"  {step_num}. Hold on — {r.permanent_name} "
                f"({r.controller}'s) changes how this works. "
                f"Instead of the normal thing, {r.replacement_text}"
            )
            step_num += 1

        if len(step.replacements_applied) > 1:
            affected = step.event.target_player or step.event.source_player or "the affected player"
            lines.append(
                f"\n  (Multiple things are trying to change this event. "
                f"{affected} gets to pick which one applies first.)\n"
            )

    # Walk through triggers in the order they resolve (stack order is already reversed)
    if total_triggers > 0:
        lines.append("\nTHEN, a bunch of things trigger:\n")

        # Group triggers by cascade step for narrative flow
        trigger_num = 1
        for step in cascade:
            if not step.triggers_fired:
                continue

            step_event_desc = _EVENT_DESCRIPTIONS.get(
                step.event.event_type.value, step.event.event_type.value
            )

            # If this isn't the first event, explain what caused this wave
            if step.step_number > 1:
                source = step.event.source_card or "that"
                lines.append(
                    f"\n  ...and because of {source}, even MORE things trigger:\n"
                )

            for trigger in step.triggers_fired:
                # Describe the trigger in plain English
                effect_parts = []
                for resulting in trigger.resulting_events:
                    desc = _EFFECT_DESCRIPTIONS.get(
                        resulting.event_type.value, resulting.event_type.value
                    )
                    if resulting.amount:
                        desc = f"{desc} ({resulting.amount})"
                    effect_parts.append(desc)

                effect_str = ""
                if effect_parts:
                    effect_str = f" This is going to {', '.join(effect_parts)}."

                lines.append(
                    f"  {trigger_num}. {trigger.controller}'s "
                    f"{trigger.permanent_name} sees this and triggers.{effect_str}"
                )
                trigger_num += 1

    # Explain resolution order
    if total_triggers > 1:
        lines.append("\nHOW IT RESOLVES:")
        lines.append(
            "All these triggers go on the stack. Remember, the stack is "
            "last-in-first-out, so the LAST thing added resolves FIRST.\n"
        )

        # Explain APNAP in plain terms if multiplayer
        if len(board.players) > 2:
            active = board.active_player or board.players[0].name
            lines.append(
                f"Since this is multiplayer, {active}'s triggers go on the stack "
                f"first (because they're the active player), then each other player "
                f"in turn order. That means {active}'s triggers actually resolve "
                f"LAST.\n"
            )

        reversed_stack = list(reversed(stack_order))
        lines.append("So in order, here's what actually happens:")
        for i, item in enumerate(reversed_stack, 1):
            # Simplify the stack item
            lines.append(f"  {i}. {item}")

    # Closing — any chain reactions?
    if len(cascade) > 1:
        lines.append(
            f"\nHeads up: this creates a chain reaction "
            f"({len(cascade)} waves of triggers total). Each trigger's effect "
            f"can cause MORE triggers, so pay attention to the order."
        )

    return "\n".join(lines)
