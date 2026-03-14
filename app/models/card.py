from pydantic import BaseModel


class Card(BaseModel):
    name: str
    mana_cost: str | None = None
    type_line: str
    oracle_text: str | None = None
    power: str | None = None
    toughness: str | None = None
    colors: list[str] = []
    keywords: list[str] = []
    legalities: dict[str, str] = {}
    image_uri: str | None = None
    scryfall_uri: str | None = None
    rulings: list[str] = []


class StackItem(BaseModel):
    """An item on the MTG stack (spell or ability)."""
    source_card: str
    description: str
    controller: str = "Player 1"
    is_ability: bool = False
    targets: list[str] = []


class InteractionQuery(BaseModel):
    card_names: list[str]
    format: str = "all"


class InteractionResult(BaseModel):
    cards: list[Card]
    rulings: list[str]
    stack_notes: list[str]
    layer_notes: list[str]
    replacement_notes: list[str]
    summary: str
