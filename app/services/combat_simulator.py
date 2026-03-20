"""Combat simulation service.

Bridges the API models (CombatSimRequest) to the deterministic
combat engine (game_rules.combat). Fetches card data from Scryfall
to get accurate P/T and keywords.
"""

import asyncio

from app.models.board import (
    CombatSimRequest,
    CombatSimResult,
    CombatDamageEvent,
)
from app.models.card import Card
from app.services.game_rules.combat import (
    BlockAssignment,
    CombatCreature,
    CombatKeyword,
    KEYWORD_MAP,
    check_blocking_legality,
    check_menace,
    resolve_combat,
)
from app.services.scryfall import fetch_card


async def simulate_combat(request: CombatSimRequest) -> CombatSimResult:
    """Simulate combat damage for the given attacker/blocker assignments."""
    # Collect all unique card names
    card_names = set()
    for assignment in request.assignments:
        card_names.add(assignment.attacker.card_name)
        for blocker in assignment.blockers:
            card_names.add(blocker.card_name)

    # Fetch card data concurrently
    card_data = await _fetch_cards(card_names)

    # Build combat creatures
    warnings: list[str] = []
    assignments: list[BlockAssignment] = []

    for req_assignment in request.assignments:
        attacker = _build_creature(
            req_assignment.attacker.card_name,
            req_assignment.attacker.controller,
            req_assignment.attacker.power,
            req_assignment.attacker.toughness,
            card_data,
            warnings,
        )
        if attacker is None:
            continue

        blockers: list[CombatCreature] = []
        for blocker_input in req_assignment.blockers:
            blocker = _build_creature(
                blocker_input.card_name,
                blocker_input.controller,
                blocker_input.power,
                blocker_input.toughness,
                card_data,
                warnings,
            )
            if blocker is None:
                continue

            # Check blocking legality
            block_warnings = check_blocking_legality(attacker, blocker)
            warnings.extend(block_warnings)
            blockers.append(blocker)

        assignment = BlockAssignment(
            attacker=attacker,
            blockers=blockers,
            unblocked=len(blockers) == 0,
        )

        # Check menace
        menace_warnings = check_menace(assignment)
        warnings.extend(menace_warnings)

        assignments.append(assignment)

    # Resolve combat
    result = resolve_combat(assignments, request.defending_player)
    result.warnings.extend(warnings)

    # Convert to API response
    return CombatSimResult(
        first_strike_damage=[
            CombatDamageEvent(
                source=e.source, target=e.target,
                amount=e.amount, keywords=e.keywords,
            )
            for e in result.first_strike_damage
        ],
        normal_damage=[
            CombatDamageEvent(
                source=e.source, target=e.target,
                amount=e.amount, keywords=e.keywords,
            )
            for e in result.normal_damage
        ],
        creatures_that_die=result.creatures_that_die,
        player_damage=result.player_damage,
        life_gained=result.life_gained,
        warnings=result.warnings,
        notes=result.notes,
    )


def _build_creature(
    card_name: str,
    controller: str,
    override_power: int | None,
    override_toughness: int | None,
    card_data: dict[str, Card],
    warnings: list[str],
) -> CombatCreature | None:
    """Build a CombatCreature from card data + optional overrides."""
    card = card_data.get(card_name)

    # Use overrides if provided, otherwise get from card data
    power = override_power
    toughness = override_toughness

    if card:
        if power is None:
            try:
                power = int(card.power) if card.power else None
            except ValueError:
                pass
        if toughness is None:
            try:
                toughness = int(card.toughness) if card.toughness else None
            except ValueError:
                pass

    if power is None or toughness is None:
        warnings.append(
            f"Could not determine P/T for '{card_name}'. "
            f"Please provide power and toughness manually."
        )
        return None

    # Extract keywords
    keywords: set[CombatKeyword] = set()
    if card and card.keywords:
        for kw in card.keywords:
            mapped = KEYWORD_MAP.get(kw.lower())
            if mapped:
                keywords.add(mapped)

    return CombatCreature(
        name=card_name,
        controller=controller,
        power=power,
        toughness=toughness,
        keywords=keywords,
    )


async def _fetch_cards(card_names: set[str]) -> dict[str, Card]:
    """Fetch card data for all cards concurrently."""
    async def _fetch_one(name: str) -> tuple[str, Card | None]:
        card = await fetch_card(name)
        return name, card

    results = await asyncio.gather(
        *[_fetch_one(name) for name in card_names]
    )
    return {name: card for name, card in results if card}
