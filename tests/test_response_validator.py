"""Tests for the deterministic response validation layer."""

from app.models.card import Card
from app.services.response_validator import (
    has_triggered_ability,
    has_replacement_effect,
    validate_phase1,
)


def _card(name: str, oracle_text: str = "", **kw) -> Card:
    return Card(name=name, type_line="Creature", oracle_text=oracle_text, **kw)


# ---------------------------------------------------------------------------
# Oracle text pattern detection
# ---------------------------------------------------------------------------

class TestHasTriggeredAbility:
    def test_when_clause(self):
        assert has_triggered_ability("When this creature enters the battlefield, draw a card.")

    def test_whenever_clause(self):
        assert has_triggered_ability("Whenever a creature dies, you gain 1 life.")

    def test_at_beginning(self):
        assert has_triggered_ability("At the beginning of your upkeep, draw a card.")

    def test_at_end(self):
        assert has_triggered_ability("At end of combat, exile this creature.")

    def test_no_trigger(self):
        assert not has_triggered_ability("Flying")

    def test_replacement_only(self):
        assert not has_triggered_ability(
            "If a source you control would deal damage, it deals triple that damage instead."
        )

    def test_static_ability(self):
        assert not has_triggered_ability("Other creatures you control get +1/+1.")

    def test_empty(self):
        assert not has_triggered_ability("")
        assert not has_triggered_ability(None)

    def test_mixed_trigger_and_replacement(self):
        # Card has both — should detect the trigger
        assert has_triggered_ability(
            "When this enters the battlefield, draw a card. "
            "If damage would be dealt to this, prevent it instead."
        )


class TestHasReplacementEffect:
    def test_instead(self):
        assert has_replacement_effect(
            "If a source you control would deal damage, it deals triple that damage instead."
        )

    def test_if_would(self):
        assert has_replacement_effect(
            "If you would draw a card, draw two cards instead."
        )

    def test_no_replacement(self):
        assert not has_replacement_effect("Whenever a creature dies, you gain 1 life.")

    def test_empty(self):
        assert not has_replacement_effect("")
        assert not has_replacement_effect(None)


# ---------------------------------------------------------------------------
# Full validation
# ---------------------------------------------------------------------------

class TestValidatePhase1:
    def _run(self, phase1, cards, board_names=None):
        card_data = {c.name: c for c in cards}
        if board_names is None:
            board_names = set(card_data.keys())
        return validate_phase1(phase1, card_data, board_names)

    def test_removes_non_trigger_from_did_not_trigger(self):
        """City on Fire has no triggered ability — should be removed from did_not_trigger."""
        cards = [
            _card("City on Fire", "Convoke\nIf a source you control would deal damage "
                   "to a permanent or player, it deals triple that damage instead."),
        ]
        phase1 = {
            "triggers": [],
            "replacement_effects": [
                {"permanent_name": "City on Fire", "controller": "Alice",
                 "replacement_text": "triple damage", "what_it_replaces": "damage",
                 "what_happens_instead": "triple"}
            ],
            "continuous_effects": [],
            "did_not_trigger": [
                {"permanent_name": "City on Fire", "controller": "Alice",
                 "reason": "City on Fire has no triggered abilities."}
            ],
            "warnings": [],
        }
        result = self._run(phase1, cards)
        assert len(result["did_not_trigger"]) == 0

    def test_keeps_valid_did_not_trigger(self):
        """Soul Warden has a triggered ability — should stay in did_not_trigger."""
        cards = [
            _card("Soul Warden",
                   "Whenever another creature enters the battlefield, you gain 1 life."),
        ]
        phase1 = {
            "triggers": [],
            "replacement_effects": [],
            "continuous_effects": [],
            "did_not_trigger": [
                {"permanent_name": "Soul Warden", "controller": "Bob",
                 "reason": "No creature entered the battlefield this event."}
            ],
            "warnings": [],
        }
        result = self._run(phase1, cards)
        assert len(result["did_not_trigger"]) == 1

    def test_removes_contradiction_trigger_and_did_not_trigger(self):
        """Card can't be in both triggers and did_not_trigger."""
        cards = [
            _card("Blood Artist",
                   "Whenever a creature dies, target player loses 1 life "
                   "and you gain 1 life."),
        ]
        phase1 = {
            "triggers": [
                {"permanent_name": "Blood Artist", "controller": "Alice",
                 "trigger_text": "Whenever a creature dies",
                 "resulting_effects": "target player loses 1 life"}
            ],
            "replacement_effects": [],
            "continuous_effects": [],
            "did_not_trigger": [
                {"permanent_name": "Blood Artist", "controller": "Alice",
                 "reason": "contradicting itself"}
            ],
            "warnings": [],
        }
        result = self._run(phase1, cards)
        # Should keep in triggers, remove from did_not_trigger
        assert len(result["triggers"]) == 1
        assert len(result["did_not_trigger"]) == 0

    def test_reclassifies_trigger_to_replacement(self):
        """If Claude calls a replacement effect a 'trigger', reclassify it."""
        cards = [
            _card("Twinflame Tyrant",
                   "Flying\nIf a source you control would deal noncombat damage "
                   "to an opponent or a permanent an opponent controls, it deals "
                   "double that damage instead."),
        ]
        phase1 = {
            "triggers": [
                {"permanent_name": "Twinflame Tyrant", "controller": "Alice",
                 "trigger_text": "damage doubling",
                 "trigger_condition": "combat damage",
                 "resulting_effects": "double damage"}
            ],
            "replacement_effects": [],
            "continuous_effects": [],
            "did_not_trigger": [],
            "warnings": [],
        }
        result = self._run(phase1, cards)
        # Should be moved from triggers to replacement_effects
        assert len(result["triggers"]) == 0
        assert len(result["replacement_effects"]) == 1
        assert result["replacement_effects"][0]["permanent_name"] == "Twinflame Tyrant"

    def test_removes_phantom_cards(self):
        """Cards not on the board should be removed from all sections."""
        cards = [
            _card("Grizzly Bears", ""),
        ]
        phase1 = {
            "triggers": [
                {"permanent_name": "Phantom Card", "controller": "Alice",
                 "trigger_text": "fake trigger",
                 "resulting_effects": "fake effect"}
            ],
            "replacement_effects": [],
            "continuous_effects": [],
            "did_not_trigger": [],
            "warnings": [],
        }
        result = self._run(phase1, cards, board_names={"Grizzly Bears"})
        assert len(result["triggers"]) == 0

    def test_complex_scenario_massacre_wurm(self):
        """Massacre Wurm: continuous effect (not trigger for ETB in this test),
        Blood Artist: trigger, City on Fire: replacement effect only."""
        cards = [
            _card("Massacre Wurm",
                   "When Massacre Wurm enters the battlefield, creatures your "
                   "opponents control get -2/-2 until end of turn.\n"
                   "Whenever a creature an opponent controls dies, that player "
                   "loses 2 life."),
            _card("Blood Artist",
                   "Whenever a creature dies, target player loses 1 life "
                   "and you gain 1 life."),
            _card("City on Fire",
                   "Convoke\nIf a source you control would deal damage "
                   "to a permanent or player, it deals triple that damage instead."),
        ]
        phase1 = {
            "triggers": [
                {"permanent_name": "Blood Artist", "controller": "Alice",
                 "trigger_text": "Whenever a creature dies",
                 "resulting_effects": "target player loses 1 life"},
                {"permanent_name": "Massacre Wurm", "controller": "Alice",
                 "trigger_text": "Whenever a creature an opponent controls dies",
                 "resulting_effects": "that player loses 2 life"},
            ],
            "replacement_effects": [
                {"permanent_name": "City on Fire", "controller": "Alice",
                 "replacement_text": "triple damage",
                 "what_it_replaces": "damage",
                 "what_happens_instead": "triple damage"},
            ],
            "continuous_effects": [
                {"permanent_name": "Massacre Wurm", "controller": "Alice",
                 "effect_text": "creatures opponents control get -2/-2",
                 "pt_modification": [-2, -2],
                 "affects": "creatures opponents control"},
            ],
            "did_not_trigger": [
                {"permanent_name": "City on Fire", "controller": "Alice",
                 "reason": "No triggered abilities."},
            ],
            "warnings": [],
        }
        result = self._run(phase1, cards)
        # City on Fire should be removed from did_not_trigger
        assert len(result["did_not_trigger"]) == 0
        # Both real triggers stay
        assert len(result["triggers"]) == 2
        # City on Fire stays in replacement_effects
        assert len(result["replacement_effects"]) == 1

    def test_card_with_both_trigger_and_replacement(self):
        """Cards with both trigger and replacement text: trigger claim is valid."""
        cards = [
            _card("Complex Card",
                   "When this enters the battlefield, draw a card.\n"
                   "If damage would be dealt to this creature, prevent it instead."),
        ]
        phase1 = {
            "triggers": [
                {"permanent_name": "Complex Card", "controller": "Alice",
                 "trigger_text": "When this enters the battlefield",
                 "resulting_effects": "draw a card"}
            ],
            "replacement_effects": [
                {"permanent_name": "Complex Card", "controller": "Alice",
                 "replacement_text": "prevent damage",
                 "what_it_replaces": "damage",
                 "what_happens_instead": "prevented"},
            ],
            "continuous_effects": [],
            "did_not_trigger": [],
            "warnings": [],
        }
        result = self._run(phase1, cards)
        # Trigger is valid (has When clause) — should stay
        assert len(result["triggers"]) == 1
        assert len(result["replacement_effects"]) == 1

    def test_preserves_existing_warnings(self):
        """Validation should add to warnings, not replace them."""
        cards = [
            _card("Twinflame Tyrant",
                   "Flying\nIf a source you control would deal noncombat damage, "
                   "it deals double that damage instead."),
        ]
        phase1 = {
            "triggers": [
                {"permanent_name": "Twinflame Tyrant", "controller": "Alice",
                 "trigger_text": "double damage",
                 "trigger_condition": "damage",
                 "resulting_effects": "double"}
            ],
            "replacement_effects": [],
            "continuous_effects": [],
            "did_not_trigger": [],
            "warnings": ["Existing warning from Claude"],
        }
        result = self._run(phase1, cards)
        assert "Existing warning from Claude" in result["warnings"]
        # Should also have a reclassification warning
        assert any("reclassified" in w for w in result["warnings"])
