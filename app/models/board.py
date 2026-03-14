"""Board state models for multiplayer MTG interaction tracking.

Models the full game state: multiple players, each with permanents on the
battlefield. Permanents have continuous effects, triggered abilities, and
replacement effects that are always "listening" for game events.

When an action occurs (cast a spell, draw a card, creature ETB, etc.),
the engine checks every permanent on the board for triggers and replacements,
then resolves the resulting cascade.
"""

from enum import Enum
from pydantic import BaseModel, Field


class Zone(str, Enum):
    BATTLEFIELD = "battlefield"
    STACK = "stack"
    GRAVEYARD = "graveyard"
    HAND = "hand"
    EXILE = "exile"
    COMMAND = "command"


class EventType(str, Enum):
    """Game events that can trigger abilities or be replaced."""
    # Spells
    CAST_SPELL = "cast_spell"
    SPELL_RESOLVES = "spell_resolves"
    SPELL_COUNTERED = "spell_countered"

    # Permanents
    ENTERS_BATTLEFIELD = "enters_battlefield"
    LEAVES_BATTLEFIELD = "leaves_battlefield"
    DIES = "dies"

    # Combat
    ATTACKS = "attacks"
    BLOCKS = "blocks"
    COMBAT_DAMAGE = "combat_damage"

    # Cards
    DRAW_CARD = "draw_card"
    DISCARD = "discard"
    MILL = "mill"

    # Life / Damage
    GAIN_LIFE = "gain_life"
    LOSE_LIFE = "lose_life"
    DAMAGE_DEALT = "damage_dealt"

    # Counters
    COUNTER_PLACED = "counter_placed"
    COUNTER_REMOVED = "counter_removed"

    # Abilities
    ACTIVATE_ABILITY = "activate_ability"
    TRIGGERED_ABILITY = "triggered_ability"

    # Tokens
    CREATE_TOKEN = "create_token"

    # Phases
    UPKEEP = "upkeep"
    DRAW_STEP = "draw_step"
    END_STEP = "end_step"


class PermanentOnBoard(BaseModel):
    """A permanent on a player's battlefield."""
    card_name: str
    owner: str
    controller: str | None = None  # defaults to owner
    tapped: bool = False
    counters: dict[str, int] = {}
    attached_to: str | None = None
    is_token: bool = False
    notes: str | None = None  # free-text for special state

    def effective_controller(self) -> str:
        return self.controller or self.owner


class PlayerState(BaseModel):
    """A player's board presence."""
    name: str
    life: int = 40  # commander default
    permanents: list[PermanentOnBoard] = []
    hand_size: int = 0
    commander_tax: int = 0


class GameEvent(BaseModel):
    """A single game event that occurred or is proposed."""
    event_type: EventType
    source_card: str | None = None
    source_player: str | None = None
    target_card: str | None = None
    target_player: str | None = None
    details: str = ""
    amount: int | None = None  # for damage, life, counters, etc.


class DetectedTrigger(BaseModel):
    """A triggered ability that fires in response to an event."""
    permanent_name: str
    controller: str
    trigger_text: str
    caused_by: GameEvent
    resulting_events: list[GameEvent] = []
    rule_reference: str | None = None


class ReplacementEffect(BaseModel):
    """A replacement effect that modifies an event before it happens."""
    permanent_name: str
    controller: str
    replacement_text: str
    original_event: GameEvent
    modified_event: GameEvent | None = None
    rule_reference: str | None = None


class CascadeStep(BaseModel):
    """One step in a cascade of triggers and effects."""
    step_number: int
    event: GameEvent
    triggers_fired: list[DetectedTrigger] = []
    replacements_applied: list[ReplacementEffect] = []
    notes: list[str] = []


class BoardState(BaseModel):
    """The full board state for a multiplayer game."""
    players: list[PlayerState] = []
    active_player: str | None = None
    turn_number: int = 1
    phase: str = "main_1"


class BoardAnalysisRequest(BaseModel):
    """Request to analyze what happens when an event occurs on a board."""
    board: BoardState
    event: GameEvent


class BoardAnalysisResult(BaseModel):
    """Full cascade analysis of an event on a board state."""
    original_event: GameEvent
    cascade: list[CascadeStep] = []
    stack_order: list[str] = []
    warnings: list[str] = []
    summary: str = ""
    plain_english: str = ""
