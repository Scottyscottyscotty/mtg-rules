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
    GameEvent,
    PlayerState,
    ReplacementEffect,
)
from app.services.event_detector import (
    detect_replacements,
    detect_static_modifications,
    detect_triggers,
)
from app.services.scryfall import fetch_card

# Safety limit to prevent infinite loops
MAX_CASCADE_DEPTH = 20


async def analyze_board_event(request: BoardAnalysisRequest) -> BoardAnalysisResult:
    """Analyze what happens when an event occurs on a given board state."""
    board = request.board
    event = request.event

    # Fetch oracle text for all permanents on the board
    card_texts = await _fetch_all_card_texts(board)

    # Resolve the cascade
    cascade: list[CascadeStep] = []
    warnings: list[str] = []
    stack_order: list[str] = []

    # Determine APNAP order (Active Player, Non-Active Player)
    apnap_order = _get_apnap_order(board)

    # Process the initial event through the cascade
    events_to_process = [event]
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

    return BoardAnalysisResult(
        original_event=event,
        cascade=cascade,
        stack_order=list(reversed(stack_order)),  # LIFO — last added resolves first
        warnings=warnings,
        summary=summary,
    )


async def _fetch_all_card_texts(board: BoardState) -> dict[str, str]:
    """Fetch oracle text for every unique card on the board."""
    card_names = set()
    for player in board.players:
        for permanent in player.permanents:
            card_names.add(permanent.card_name)

    texts: dict[str, str] = {}
    for name in card_names:
        card = await fetch_card(name)
        if card and card.oracle_text:
            texts[name] = card.oracle_text
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
