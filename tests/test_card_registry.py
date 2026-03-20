"""Tests for CardRegistry — shared card data layer."""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from app.models.card import Card
from app.services.card_registry import CardRegistry


def _card(name: str, **kw) -> Card:
    return Card(name=name, type_line="Creature", **kw)


class TestMemoryCache:
    def test_put_and_get(self):
        reg = CardRegistry(max_size=10)
        card = _card("Lightning Bolt")
        reg.warm("Lightning Bolt", card)
        assert reg._get("Lightning Bolt") is card

    def test_case_insensitive(self):
        reg = CardRegistry(max_size=10)
        card = _card("Lightning Bolt")
        reg.warm("Lightning Bolt", card)
        assert reg._get("lightning bolt") is card
        assert reg._get("LIGHTNING BOLT") is card

    def test_lru_eviction(self):
        reg = CardRegistry(max_size=3)
        reg.warm("A", _card("A"))
        reg.warm("B", _card("B"))
        reg.warm("C", _card("C"))
        reg.warm("D", _card("D"))  # evicts A
        assert reg._get("a") is None
        assert reg._get("b") is not None
        assert reg._get("d") is not None

    def test_access_refreshes_lru(self):
        reg = CardRegistry(max_size=3)
        reg.warm("A", _card("A"))
        reg.warm("B", _card("B"))
        reg.warm("C", _card("C"))
        # Access A to refresh it
        reg._get("A")
        reg.warm("D", _card("D"))  # evicts B (oldest untouched)
        assert reg._get("a") is not None  # A was refreshed
        assert reg._get("b") is None      # B was evicted

    def test_size_property(self):
        reg = CardRegistry(max_size=10)
        assert reg.size == 0
        reg.warm("A", _card("A"))
        assert reg.size == 1

    def test_clear(self):
        reg = CardRegistry(max_size=10)
        reg.warm("A", _card("A"))
        reg.clear()
        assert reg.size == 0
        assert reg._get("A") is None


class TestAsyncFetch:
    @pytest.mark.asyncio
    async def test_get_card_from_cache(self):
        reg = CardRegistry(max_size=10)
        card = _card("Grizzly Bears")
        reg.warm("Grizzly Bears", card)
        result = await reg.get_card("Grizzly Bears")
        assert result is card

    @pytest.mark.asyncio
    async def test_get_card_fetches_on_miss(self):
        reg = CardRegistry(max_size=10)
        card = _card("Grizzly Bears")
        with patch("app.services.card_registry.scryfall") as mock_scryfall:
            mock_scryfall.fetch_card = AsyncMock(return_value=card)
            result = await reg.get_card("Grizzly Bears")
            assert result.name == "Grizzly Bears"
            mock_scryfall.fetch_card.assert_called_once_with("Grizzly Bears")
            # Should be cached now
            assert reg._get("Grizzly Bears") is card

    @pytest.mark.asyncio
    async def test_get_card_returns_none_on_miss(self):
        reg = CardRegistry(max_size=10)
        with patch("app.services.card_registry.scryfall") as mock_scryfall:
            mock_scryfall.fetch_card = AsyncMock(return_value=None)
            result = await reg.get_card("Nonexistent Card")
            assert result is None

    @pytest.mark.asyncio
    async def test_get_cards_batch(self):
        reg = CardRegistry(max_size=10)
        cards = {
            "A": _card("A"),
            "B": _card("B"),
        }
        with patch("app.services.card_registry.scryfall") as mock_scryfall:
            mock_scryfall.fetch_card = AsyncMock(side_effect=lambda n: cards.get(n))
            result = await reg.get_cards(["A", "B"])
            assert "A" in result
            assert "B" in result
            assert len(result) == 2

    @pytest.mark.asyncio
    async def test_get_cards_partial_cache(self):
        reg = CardRegistry(max_size=10)
        card_a = _card("A")
        reg.warm("A", card_a)  # A is cached
        card_b = _card("B")
        with patch("app.services.card_registry.scryfall") as mock_scryfall:
            mock_scryfall.fetch_card = AsyncMock(return_value=card_b)
            result = await reg.get_cards(["A", "B"])
            assert result["A"] is card_a
            assert result["B"].name == "B"
            # Only B should have been fetched
            mock_scryfall.fetch_card.assert_called_once()
