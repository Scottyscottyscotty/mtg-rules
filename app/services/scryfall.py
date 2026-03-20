"""Scryfall API client for fetching card data and rulings."""

import asyncio
import json
import logging
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

from app.models.card import Card

SCRYFALL_API = "https://api.scryfall.com"
CACHE_DIR = Path("cache")
CACHE_DIR.mkdir(exist_ok=True)

MAX_RETRIES = 3
RETRY_BACKOFF = [0.5, 1.0, 2.0]  # seconds between retries


def _cache_path(card_name: str) -> Path:
    safe = card_name.lower().replace(" ", "_").replace(",", "").replace("'", "")
    return CACHE_DIR / f"{safe}.json"


async def _request_with_retry(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    **kwargs,
) -> httpx.Response | None:
    """Make an HTTP request with retry logic for rate limits and transient errors."""
    for attempt in range(MAX_RETRIES + 1):
        resp = await client.request(method, url, **kwargs)

        if resp.status_code == 200:
            return resp

        # Rate limited — back off and retry
        if resp.status_code == 429:
            if attempt < MAX_RETRIES:
                wait = RETRY_BACKOFF[attempt]
                logger.warning(
                    "Scryfall rate limited (429), retrying in %.1fs (attempt %d/%d)",
                    wait, attempt + 1, MAX_RETRIES,
                )
                await asyncio.sleep(wait)
                continue
            logger.error("Scryfall rate limited after %d retries", MAX_RETRIES)
            return None

        # Server error — retry
        if resp.status_code >= 500:
            if attempt < MAX_RETRIES:
                wait = RETRY_BACKOFF[attempt]
                logger.warning(
                    "Scryfall server error (%d), retrying in %.1fs",
                    resp.status_code, wait,
                )
                await asyncio.sleep(wait)
                continue

        # Client error (404, etc.) — don't retry
        return resp

    return None


async def fetch_card(name: str) -> Card | None:
    """Fetch a card by name from Scryfall, with local file caching."""
    cached = _cache_path(name)
    if cached.exists():
        data = json.loads(cached.read_text())
        return _parse_card(data)

    async with httpx.AsyncClient() as client:
        # Scryfall asks for 50-100ms between requests
        resp = await _request_with_retry(
            client, "GET",
            f"{SCRYFALL_API}/cards/named",
            params={"fuzzy": name},
            timeout=10.0,
        )
        if resp is None or resp.status_code != 200:
            logger.warning(
                "Scryfall lookup failed for '%s': %s",
                name, f"HTTP {resp.status_code}" if resp else "no response",
            )
            return None
        logger.info("Scryfall found card: '%s'", name)
        data = resp.json()
        cached.write_text(json.dumps(data))

        # Fetch rulings
        rulings = await _fetch_rulings(client, data.get("id", ""))
        card = _parse_card(data, rulings)
        # Re-cache with rulings
        data["_rulings"] = rulings
        cached.write_text(json.dumps(data))
        return card


async def _fetch_rulings(client: httpx.AsyncClient, card_id: str) -> list[str]:
    await asyncio.sleep(0.1)  # Rate limiting
    resp = await _request_with_retry(
        client, "GET",
        f"{SCRYFALL_API}/cards/{card_id}/rulings",
        timeout=10.0,
    )
    if resp is None or resp.status_code != 200:
        return []
    data = resp.json()
    return [r["comment"] for r in data.get("data", [])]


async def autocomplete_card(query: str) -> list[str]:
    """Autocomplete card names using Scryfall's autocomplete endpoint."""
    async with httpx.AsyncClient() as client:
        resp = await _request_with_retry(
            client, "GET",
            f"{SCRYFALL_API}/cards/autocomplete",
            params={"q": query},
            timeout=5.0,
        )
        if resp is None or resp.status_code != 200:
            return []
        data = resp.json()
        return data.get("data", [])


async def search_cards(query: str, limit: int = 10) -> list[Card]:
    """Search for cards matching a query string."""
    async with httpx.AsyncClient() as client:
        resp = await _request_with_retry(
            client, "GET",
            f"{SCRYFALL_API}/cards/search",
            params={"q": query, "order": "name"},
            timeout=10.0,
        )
        if resp is None or resp.status_code != 200:
            return []
        data = resp.json()
        cards = []
        for card_data in data.get("data", [])[:limit]:
            cards.append(_parse_card(card_data))
        return cards


def _parse_card(data: dict, rulings: list[str] | None = None) -> Card:
    image_uri = None
    if "image_uris" in data:
        image_uri = data["image_uris"].get("normal")
    elif "card_faces" in data and data["card_faces"]:
        face = data["card_faces"][0]
        if "image_uris" in face:
            image_uri = face["image_uris"].get("normal")

    oracle_text = data.get("oracle_text", "")
    if not oracle_text and "card_faces" in data:
        parts = []
        for face in data.get("card_faces", []):
            parts.append(face.get("oracle_text", ""))
        oracle_text = "\n---\n".join(parts)

    if rulings is None:
        rulings = data.get("_rulings", [])

    return Card(
        name=data.get("name", ""),
        mana_cost=data.get("mana_cost"),
        type_line=data.get("type_line", ""),
        oracle_text=oracle_text,
        power=data.get("power"),
        toughness=data.get("toughness"),
        colors=data.get("colors", []),
        keywords=data.get("keywords", []),
        legalities=data.get("legalities", {}),
        image_uri=image_uri,
        scryfall_uri=data.get("scryfall_uri"),
        rulings=rulings,
    )
