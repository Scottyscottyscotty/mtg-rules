"""Card lookup and search endpoints."""

from fastapi import APIRouter, HTTPException

from app.models.card import Card
from app.services.scryfall import fetch_card, search_cards

router = APIRouter(prefix="/api/cards", tags=["cards"])


@router.get("/{name}", response_model=Card)
async def get_card(name: str):
    """Look up a card by name (fuzzy matching via Scryfall)."""
    card = await fetch_card(name)
    if not card:
        raise HTTPException(status_code=404, detail=f"Card not found: {name}")
    return card


@router.get("/", response_model=list[Card])
async def search(q: str, limit: int = 10):
    """Search for cards matching a query."""
    return await search_cards(q, limit=min(limit, 25))
