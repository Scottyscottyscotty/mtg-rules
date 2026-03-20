"""Deterministic MTG game rules engine.

Handles the mechanical, non-ambiguous parts of Magic rules that don't
require AI reasoning:

- State-based actions (rule 704): creature with 0 toughness dies, etc.
- Layer system (rule 613): fixed ordering for continuous effects
- Stack / APNAP ordering (rules 405, 101.4): LIFO resolution, active
  player's triggers go on first

The AI (Claude) handles the HARD parts:
- Reading oracle text and determining what triggers
- Understanding card interactions semantically
- Identifying replacement effects from card text

This hybrid approach gives us deterministic correctness for mechanical
rules while leveraging the LLM for the parts that require language
understanding.
"""

from app.services.game_rules.state_based_actions import check_sbas, SBAResult
from app.services.game_rules.layers import sort_effects_by_layer, LayerEffect
from app.services.game_rules.stack import order_triggers_apnap, StackItem
from app.services.game_rules.combat import (
    resolve_combat,
    CombatCreature,
    CombatKeyword,
    BlockAssignment,
    CombatResult,
)

__all__ = [
    "check_sbas",
    "SBAResult",
    "sort_effects_by_layer",
    "LayerEffect",
    "order_triggers_apnap",
    "StackItem",
    "resolve_combat",
    "CombatCreature",
    "CombatKeyword",
    "BlockAssignment",
    "CombatResult",
]
