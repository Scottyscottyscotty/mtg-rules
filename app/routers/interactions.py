"""Interaction analysis endpoints."""

from fastapi import APIRouter, HTTPException

from app.models.card import InteractionQuery, InteractionResult
from app.services.analyzer import analyze_interaction
from app.services.card_registry import card_registry

router = APIRouter(prefix="/api/interactions", tags=["interactions"])


@router.post("/analyze", response_model=InteractionResult)
async def analyze(query: InteractionQuery):
    """Analyze how 2+ cards interact with each other.

    Provide card names and optionally a format to check legality.
    Returns stack analysis, layer interactions, replacement effects,
    keyword combos, and relevant rulings.
    """
    if len(query.card_names) < 2:
        raise HTTPException(
            status_code=400,
            detail="Provide at least 2 card names to analyze interactions.",
        )
    if len(query.card_names) > 6:
        raise HTTPException(
            status_code=400,
            detail="Maximum 6 cards per interaction query.",
        )

    card_data = await card_registry.get_cards(query.card_names)

    cards = []
    for name in query.card_names:
        card = card_data.get(name)
        if not card:
            raise HTTPException(status_code=404, detail=f"Card not found: {name}")
        cards.append(card)

    result = await analyze_interaction(cards)

    # Filter by format if specified
    if query.format and query.format != "all":
        for card in result.cards:
            status = card.legalities.get(query.format, "unknown")
            if status != "legal":
                result.summary = (
                    f"Warning: {card.name} is '{status}' in {query.format}.\n\n"
                    + result.summary
                )

    return result
