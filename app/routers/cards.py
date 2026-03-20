"""Card lookup and search endpoints."""

from fastapi import APIRouter, HTTPException

from app.models.card import Card
from app.services.card_registry import card_registry
from app.services.scryfall import autocomplete_card, search_cards

router = APIRouter(prefix="/api/cards", tags=["cards"])


@router.get("/autocomplete", response_model=list[str])
async def autocomplete(q: str):
    """Autocomplete card names using Scryfall. Returns up to 20 suggestions."""
    if len(q) < 2:
        return []
    return await autocomplete_card(q)


@router.get("/search", response_model=list[Card])
async def search(q: str, limit: int = 10):
    """Search for cards matching a query."""
    return await search_cards(q, limit=min(limit, 25))


@router.get("/{name}", response_model=Card)
async def get_card(name: str):
    """Look up a card by name (fuzzy matching via Scryfall)."""
    card = await card_registry.get_card(name)
    if not card:
        raise HTTPException(status_code=404, detail=f"Card not found: {name}")
    return card
