"""Tests for stack ordering and APNAP rules (rules 405, 101.4)."""

from app.services.game_rules.stack import (
    StackItem,
    order_triggers_apnap,
    resolution_order,
    describe_stack,
)


def _trigger(desc: str, controller: str, source: str = "Card") -> StackItem:
    return StackItem(description=desc, controller=controller, source_card=source)


class TestAPNAPOrdering:
    def test_active_player_triggers_on_bottom(self):
        """Active player's triggers go on stack first = resolve last."""
        triggers = [
            _trigger("Alice trigger", "Alice"),
            _trigger("Bob trigger", "Bob"),
        ]
        ordered = order_triggers_apnap(triggers, "Alice", ["Alice", "Bob"])
        # Alice on bottom (index 0), Bob on top (index 1)
        assert ordered[0].controller == "Alice"
        assert ordered[1].controller == "Bob"

    def test_resolution_is_reverse(self):
        """Stack resolves LIFO — top of stack resolves first."""
        triggers = [
            _trigger("Alice trigger", "Alice"),
            _trigger("Bob trigger", "Bob"),
        ]
        ordered = order_triggers_apnap(triggers, "Alice", ["Alice", "Bob"])
        resolved = resolution_order(ordered)
        # Bob resolves first (was on top)
        assert resolved[0].controller == "Bob"
        assert resolved[1].controller == "Alice"

    def test_three_player_apnap(self):
        """Turn order: Alice -> Bob -> Charlie."""
        triggers = [
            _trigger("Charlie trigger", "Charlie"),
            _trigger("Alice trigger", "Alice"),
            _trigger("Bob trigger", "Bob"),
        ]
        ordered = order_triggers_apnap(triggers, "Alice", ["Alice", "Bob", "Charlie"])
        assert ordered[0].controller == "Alice"    # bottom
        assert ordered[1].controller == "Bob"      # middle
        assert ordered[2].controller == "Charlie"  # top

        resolved = resolution_order(ordered)
        assert resolved[0].controller == "Charlie"  # resolves first
        assert resolved[1].controller == "Bob"
        assert resolved[2].controller == "Alice"    # resolves last

    def test_multiple_triggers_same_player(self):
        """Same player's triggers stay grouped together."""
        triggers = [
            _trigger("Alice A", "Alice", "Card A"),
            _trigger("Bob X", "Bob", "Card X"),
            _trigger("Alice B", "Alice", "Card B"),
        ]
        ordered = order_triggers_apnap(triggers, "Alice", ["Alice", "Bob"])
        # Alice's two triggers at bottom, Bob's on top
        assert ordered[0].controller == "Alice"
        assert ordered[1].controller == "Alice"
        assert ordered[2].controller == "Bob"

    def test_active_player_not_in_order_list(self):
        """If active player isn't in the explicit order, they get inserted first."""
        triggers = [
            _trigger("Alice", "Alice"),
            _trigger("Bob", "Bob"),
        ]
        ordered = order_triggers_apnap(triggers, "Alice", ["Bob", "Alice"])
        assert ordered[0].controller == "Alice"  # active player first

    def test_empty_triggers(self):
        assert order_triggers_apnap([], "Alice", ["Alice", "Bob"]) == []

    def test_single_trigger(self):
        triggers = [_trigger("Solo", "Alice")]
        ordered = order_triggers_apnap(triggers, "Alice", ["Alice"])
        assert len(ordered) == 1
        assert ordered[0].controller == "Alice"

    def test_no_player_order_inferred(self):
        """When no player order is given, infer from controllers."""
        triggers = [
            _trigger("Alice", "Alice"),
            _trigger("Bob", "Bob"),
        ]
        ordered = order_triggers_apnap(triggers, "Alice", [])
        assert ordered[0].controller == "Alice"


class TestDescribeStack:
    def test_describes_in_resolution_order(self):
        stack = [
            _trigger("draws a card", "Alice", "Rhystic Study"),
            _trigger("deals 2 damage", "Bob", "Impact Tremors"),
        ]
        lines = describe_stack(stack)
        assert len(lines) == 2
        # Top of stack (last index) resolves first
        assert "Impact Tremors" in lines[0]
        assert "Rhystic Study" in lines[1]

    def test_empty_stack(self):
        assert describe_stack([]) == []
