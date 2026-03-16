"""State-based actions (rule 704).

State-based actions are checked whenever a player would receive priority.
They don't use the stack — they just happen. Multiple SBAs can be performed
at once, and you keep checking until none apply.

This module checks the deterministic SBAs that can be evaluated from
board state data (life totals, power/toughness, counters, etc.).
"""

from dataclasses import dataclass, field
from app.models.board import BoardState, EventType, GameEvent, PermanentOnBoard
from app.models.card import Card


@dataclass
class SBAResult:
    """A state-based action that should be performed."""
    rule: str  # e.g., "704.5f"
    description: str
    events: list[GameEvent] = field(default_factory=list)


def check_sbas(
    board: BoardState,
    card_data: dict[str, Card],
    pt_modifications: dict[str, tuple[int, int]] | None = None,
) -> list[SBAResult]:
    """Check all state-based actions on the current board.

    Args:
        board: Current board state with all players and permanents.
        card_data: Card data from Scryfall, keyed by card name.
        pt_modifications: Optional dict of card_name -> (power_mod, toughness_mod)
            representing continuous effects like -2/-2 from Massacre Wurm.
            These are ADDITIVE to the card's base P/T.

    Returns:
        List of SBAs that apply. Empty list means no SBAs to perform.
    """
    results: list[SBAResult] = []
    mods = pt_modifications or {}

    for player in board.players:
        # 704.5a — Player at 0 or less life loses (checked elsewhere, but noted)
        if player.life <= 0:
            results.append(SBAResult(
                rule="704.5a",
                description=f"{player.name} has {player.life} life and loses the game.",
                events=[GameEvent(
                    event_type=EventType.LOSE_LIFE,
                    target_player=player.name,
                    details=f"{player.name} loses the game (life total: {player.life})",
                )],
            ))

        for perm in player.permanents:
            card = card_data.get(perm.card_name)
            if not card:
                continue

            # Only check P/T SBAs for creatures
            if not _is_creature(card):
                continue

            base_power, base_toughness = _get_base_pt(card)
            if base_toughness is None:
                continue

            # Apply any continuous effect modifications
            p_mod, t_mod = mods.get(perm.card_name, (0, 0))

            # Apply +1/+1 and -1/-1 counter modifications
            plus_counters = perm.counters.get("+1/+1", 0)
            minus_counters = perm.counters.get("-1/-1", 0)

            # 704.5q — +1/+1 and -1/-1 counters cancel out
            if plus_counters > 0 and minus_counters > 0:
                cancelled = min(plus_counters, minus_counters)
                results.append(SBAResult(
                    rule="704.5q",
                    description=(
                        f"{perm.card_name}: {cancelled} +1/+1 and "
                        f"{cancelled} -1/-1 counters cancel out."
                    ),
                ))
                plus_counters -= cancelled
                minus_counters -= cancelled

            effective_p = base_power + p_mod + plus_counters - minus_counters
            effective_t = base_toughness + t_mod + plus_counters - minus_counters

            controller = perm.effective_controller()

            # 704.5f — Creature with toughness 0 or less is put into graveyard
            if effective_t <= 0:
                results.append(SBAResult(
                    rule="704.5f",
                    description=(
                        f"{perm.card_name} (controlled by {controller}) has "
                        f"effective toughness {effective_t} and dies. "
                        f"(Base: {base_power}/{base_toughness}"
                        f"{f', modification: {p_mod:+d}/{t_mod:+d}' if (p_mod or t_mod) else ''}"
                        f"{f', +1/+1 counters: {plus_counters}' if plus_counters else ''}"
                        f"{f', -1/-1 counters: {minus_counters}' if minus_counters else ''}"
                        f")"
                    ),
                    events=[GameEvent(
                        event_type=EventType.DIES,
                        source_card=perm.card_name,
                        source_player=controller,
                        details=(
                            f"{perm.card_name} dies (toughness {effective_t} <= 0)"
                        ),
                    )],
                ))

            # 704.5g — Creature with lethal damage marked on it
            # (We'd need damage tracking for this — noted for future)

        # 704.5j — Legendary rule: if a player controls 2+ legends
        # with the same name, they choose one and put the rest into graveyard
        _check_legend_rule(player.name, player.permanents, card_data, results)

        # 704.5d — Token in a zone other than battlefield ceases to exist
        # (Can't check this without zone tracking — noted)

    return results


def _check_legend_rule(
    player_name: str,
    permanents: list[PermanentOnBoard],
    card_data: dict[str, Card],
    results: list[SBAResult],
) -> None:
    """704.5j — Check for duplicate legendary permanents."""
    legend_names: dict[str, list[PermanentOnBoard]] = {}
    for perm in permanents:
        card = card_data.get(perm.card_name)
        if card and "Legendary" in card.type_line:
            legend_names.setdefault(card.name, []).append(perm)

    for name, perms in legend_names.items():
        if len(perms) > 1:
            results.append(SBAResult(
                rule="704.5j",
                description=(
                    f"{player_name} controls {len(perms)} copies of "
                    f"legendary permanent '{name}'. They must choose one "
                    f"to keep; the rest are put into the graveyard."
                ),
            ))


def _is_creature(card: Card) -> bool:
    """Check if a card is a creature from its type line."""
    return "Creature" in card.type_line


def _get_base_pt(card: Card) -> tuple[int | None, int | None]:
    """Extract base power/toughness as integers, handling */*, X, etc."""
    try:
        power = int(card.power) if card.power and card.power != "*" else None
        toughness = int(card.toughness) if card.toughness and card.toughness != "*" else None
        return power, toughness
    except (ValueError, TypeError):
        return None, None
