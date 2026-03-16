"""Stack ordering and APNAP rules (rules 405, 101.4).

The stack is LIFO (last in, first out). When multiple triggered abilities
need to go on the stack simultaneously, APNAP ordering determines the order:

  1. Active player puts their triggers on the stack FIRST (in any order)
  2. Then the next player in turn order
  3. ... and so on

Since they go on in APNAP order but resolve LIFO, the active player's
triggers resolve LAST. This is entirely mechanical — once we know who
controls each trigger, the ordering is deterministic.
"""

from dataclasses import dataclass, field


@dataclass
class StackItem:
    """An item on the stack (triggered ability, spell, etc.)."""
    description: str
    controller: str
    source_card: str
    trigger_text: str = ""
    is_trigger: bool = True  # False for spells/activated abilities


def order_triggers_apnap(
    triggers: list[StackItem],
    active_player: str,
    player_order: list[str],
) -> list[StackItem]:
    """Order simultaneous triggers by APNAP rule (101.4).

    When multiple triggers need to go on the stack at the same time:
    1. Active player's triggers go on first (they choose the order)
    2. Then next player in turn order, etc.

    Since the stack is LIFO, the items put on FIRST resolve LAST.
    This means the active player's triggers resolve last.

    Args:
        triggers: All triggers that fired simultaneously.
        active_player: Name of the active player.
        player_order: Full turn order (starting from active player).

    Returns:
        Triggers ordered for stack placement (first item = bottom of stack,
        last item = top of stack = resolves first).
    """
    if not triggers:
        return []

    if not player_order:
        # If no turn order provided, try to infer from active player
        controllers = list(dict.fromkeys(t.controller for t in triggers))
        if active_player in controllers:
            controllers.remove(active_player)
            controllers.insert(0, active_player)
        player_order = controllers

    # Ensure active player is first in the order
    if player_order and player_order[0] != active_player:
        if active_player in player_order:
            player_order = player_order.copy()
            player_order.remove(active_player)
            player_order.insert(0, active_player)

    # Group triggers by controller
    by_controller: dict[str, list[StackItem]] = {}
    for trigger in triggers:
        by_controller.setdefault(trigger.controller, []).append(trigger)

    # Stack them in APNAP order: active player's triggers go on FIRST
    # (bottom of stack, resolve last), then next player, etc.
    ordered: list[StackItem] = []
    for player in player_order:
        if player in by_controller:
            ordered.extend(by_controller[player])

    # Any controllers not in the turn order go last (shouldn't happen, but safe)
    for controller, items in by_controller.items():
        if controller not in player_order:
            ordered.extend(items)

    return ordered


def resolution_order(stack: list[StackItem]) -> list[StackItem]:
    """Return the stack in resolution order (LIFO — top resolves first).

    The stack list is stored bottom-to-top (first placed = index 0).
    Resolution order is the reverse.
    """
    return list(reversed(stack))


def describe_stack(stack: list[StackItem]) -> list[str]:
    """Human-readable stack description in resolution order."""
    resolving = resolution_order(stack)
    lines = []
    for i, item in enumerate(resolving, 1):
        label = f"{item.source_card}" if item.source_card else "Unknown"
        lines.append(
            f"{i}. {label}'s trigger ({item.controller}): {item.description}"
        )
    return lines
