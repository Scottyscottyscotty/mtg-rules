"""CardRegistry — shared card data layer with memory + disk cache.

All services use this instead of calling scryfall.fetch_card() directly.
Provides:
- L1: In-memory LRU cache (dict with max size)
- L2: Disk cache (existing JSON files)
- L3: Scryfall API (via scryfall module)
- Batch fetch with concurrency for board/combat requests
"""

import asyncio
import logging
from collections import OrderedDict

from app.models.card import Card
from app.services import scryfall

logger = logging.getLogger(__name__)

# Maximum number of cards to keep in memory
MAX_MEMORY_CACHE = 500


class CardRegistry:
    """Shared card cache used by all services."""

    def __init__(self, max_size: int = MAX_MEMORY_CACHE) -> None:
        self._cache: OrderedDict[str, Card] = OrderedDict()
        self._max_size = max_size
        self._in_flight: dict[str, asyncio.Task[Card | None]] = {}

    def _normalize(self, name: str) -> str:
        return name.strip().lower()

    def _put(self, name: str, card: Card) -> None:
        key = self._normalize(name)
        self._cache[key] = card
        self._cache.move_to_end(key)
        if len(self._cache) > self._max_size:
            self._cache.popitem(last=False)

    def _get(self, name: str) -> Card | None:
        key = self._normalize(name)
        card = self._cache.get(key)
        if card is not None:
            self._cache.move_to_end(key)
        return card

    async def get_card(self, name: str) -> Card | None:
        """Get a single card, checking memory cache first."""
        # L1: memory
        card = self._get(name)
        if card is not None:
            return card

        # Deduplicate concurrent requests for the same card
        key = self._normalize(name)
        if key in self._in_flight:
            return await self._in_flight[key]

        task = asyncio.current_task()
        fetch_task = asyncio.ensure_future(self._fetch_and_cache(name))
        self._in_flight[key] = fetch_task
        try:
            return await fetch_task
        finally:
            self._in_flight.pop(key, None)

    async def _fetch_and_cache(self, name: str) -> Card | None:
        """Fetch from disk/API and store in memory cache."""
        # L2+L3: scryfall module handles disk cache + API
        card = await scryfall.fetch_card(name)
        if card is not None:
            self._put(name, card)
            # Also cache under the canonical name
            if card.name.lower() != self._normalize(name):
                self._put(card.name, card)
        return card

    async def get_cards(self, names: list[str]) -> dict[str, Card]:
        """Batch fetch multiple cards concurrently.

        Returns a dict mapping requested name -> Card (only found cards).
        """
        results: dict[str, Card] = {}
        to_fetch: list[str] = []

        # Check memory cache first
        for name in names:
            card = self._get(name)
            if card is not None:
                results[name] = card
            else:
                to_fetch.append(name)

        if not to_fetch:
            return results

        # Fetch remaining concurrently
        fetch_results = await asyncio.gather(
            *[self.get_card(name) for name in to_fetch]
        )
        for name, card in zip(to_fetch, fetch_results):
            if card is not None:
                results[name] = card

        return results

    def warm(self, name: str, card: Card) -> None:
        """Pre-populate the cache (e.g., from a previous lookup)."""
        self._put(name, card)

    @property
    def size(self) -> int:
        return len(self._cache)

    def clear(self) -> None:
        self._cache.clear()


# Singleton instance used across all services
card_registry = CardRegistry()
