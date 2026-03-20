"""Deterministic combat damage simulator (rules 506-511, 120).

Given attackers and blockers with their stats (P/T, keywords), calculates
exactly what happens in combat: damage assignment, deaths, life changes.

Handles:
- First strike / double strike ordering (rule 702.7)
- Trample (rule 702.19): excess damage to defending player
- Deathtouch (rule 702.2): 1 damage is lethal for assignment
- Lifelink (rule 702.15): damage dealt = life gained
- Menace (rule 702.110): must be blocked by 2+ creatures
- Flying / Reach (rules 702.9, 702.17): blocking restrictions
- Indestructible (rule 702.12): damage doesn't destroy
- Multiple blockers: damage assignment order (rule 510.1c)
"""

from dataclasses import dataclass, field
from enum import Enum


class CombatKeyword(str, Enum):
    FIRST_STRIKE = "first_strike"
    DOUBLE_STRIKE = "double_strike"
    TRAMPLE = "trample"
    DEATHTOUCH = "deathtouch"
    LIFELINK = "lifelink"
    FLYING = "flying"
    REACH = "reach"
    MENACE = "menace"
    INDESTRUCTIBLE = "indestructible"
    VIGILANCE = "vigilance"


# Map Scryfall keyword names to our enum
KEYWORD_MAP = {
    "first strike": CombatKeyword.FIRST_STRIKE,
    "double strike": CombatKeyword.DOUBLE_STRIKE,
    "trample": CombatKeyword.TRAMPLE,
    "deathtouch": CombatKeyword.DEATHTOUCH,
    "lifelink": CombatKeyword.LIFELINK,
    "flying": CombatKeyword.FLYING,
    "reach": CombatKeyword.REACH,
    "menace": CombatKeyword.MENACE,
    "indestructible": CombatKeyword.INDESTRUCTIBLE,
    "vigilance": CombatKeyword.VIGILANCE,
}


@dataclass
class CombatCreature:
    """A creature participating in combat."""
    name: str
    controller: str
    power: int
    toughness: int
    keywords: set[CombatKeyword] = field(default_factory=set)
    damage_marked: int = 0
    took_deathtouch: bool = False  # any source with deathtouch dealt damage

    def has(self, kw: CombatKeyword) -> bool:
        return kw in self.keywords

    @property
    def lethal_damage(self) -> int:
        """How much damage is lethal to this creature."""
        return self.toughness - self.damage_marked

    @property
    def is_dead(self) -> bool:
        if self.has(CombatKeyword.INDESTRUCTIBLE):
            return False
        # Deathtouch: any amount of damage is lethal (rule 704.5h)
        if self.took_deathtouch and self.damage_marked > 0:
            return True
        return self.damage_marked >= self.toughness

    def deals_first_strike_damage(self) -> bool:
        return self.has(CombatKeyword.FIRST_STRIKE) or self.has(CombatKeyword.DOUBLE_STRIKE)

    def deals_normal_damage(self) -> bool:
        return not self.has(CombatKeyword.FIRST_STRIKE) or self.has(CombatKeyword.DOUBLE_STRIKE)


@dataclass
class BlockAssignment:
    """An attacker and its ordered blockers."""
    attacker: CombatCreature
    blockers: list[CombatCreature] = field(default_factory=list)
    # True if this attacker is unblocked
    unblocked: bool = True


@dataclass
class DamageEvent:
    """A single damage event."""
    source: str
    target: str  # creature name or "Player: <name>"
    amount: int
    is_combat: bool = True
    keywords: list[str] = field(default_factory=list)


@dataclass
class CombatResult:
    """Full result of combat damage resolution."""
    first_strike_damage: list[DamageEvent] = field(default_factory=list)
    normal_damage: list[DamageEvent] = field(default_factory=list)
    creatures_that_die: list[str] = field(default_factory=list)
    player_damage: dict[str, int] = field(default_factory=dict)
    life_gained: dict[str, int] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def resolve_combat(
    assignments: list[BlockAssignment],
    defending_player: str,
) -> CombatResult:
    """Resolve combat damage for all attackers and blockers.

    Args:
        assignments: Each attacker with its ordered blockers (or unblocked).
        defending_player: Name of the defending player (takes unblocked damage).

    Returns:
        Full combat result with damage events, deaths, life changes.
    """
    result = CombatResult()

    # Determine if there's a first strike step
    has_first_strike = any(
        a.attacker.deals_first_strike_damage() or
        any(b.deals_first_strike_damage() for b in a.blockers)
        for a in assignments
    )

    # --- First Strike Damage Step ---
    if has_first_strike:
        result.notes.append("First strike damage step:")
        for assignment in assignments:
            _resolve_damage_step(
                assignment, defending_player, result,
                first_strike=True,
            )
        # Remove dead creatures before normal damage
        # (they don't deal normal damage if killed by first strike)
        _check_deaths_after_step(assignments, result)

    # --- Normal Combat Damage Step ---
    result.notes.append("Normal combat damage step:")
    for assignment in assignments:
        _resolve_damage_step(
            assignment, defending_player, result,
            first_strike=False,
        )
    _check_deaths_after_step(assignments, result)

    # Calculate net player damage and lifelink gains
    for events in [result.first_strike_damage, result.normal_damage]:
        for event in events:
            if event.target.startswith("Player: "):
                player = event.target[len("Player: "):]
                result.player_damage[player] = result.player_damage.get(player, 0) + event.amount

            if "lifelink" in event.keywords:
                # Find source creature's controller
                source_controller = _find_controller(event.source, assignments)
                if source_controller:
                    result.life_gained[source_controller] = (
                        result.life_gained.get(source_controller, 0) + event.amount
                    )

    return result


def check_blocking_legality(
    attacker: CombatCreature,
    blocker: CombatCreature,
) -> list[str]:
    """Check if a block is legal and return any warnings."""
    warnings = []

    # Flying: can only be blocked by creatures with flying or reach
    if attacker.has(CombatKeyword.FLYING):
        if not blocker.has(CombatKeyword.FLYING) and not blocker.has(CombatKeyword.REACH):
            warnings.append(
                f"{blocker.name} cannot block {attacker.name} — "
                f"{attacker.name} has flying and {blocker.name} has "
                f"neither flying nor reach."
            )

    return warnings


def check_menace(assignment: BlockAssignment) -> list[str]:
    """Check menace blocking requirement."""
    warnings = []
    if assignment.attacker.has(CombatKeyword.MENACE):
        if 0 < len(assignment.blockers) < 2:
            warnings.append(
                f"{assignment.attacker.name} has menace — it must be "
                f"blocked by 2 or more creatures, not {len(assignment.blockers)}."
            )
    return warnings


def _resolve_damage_step(
    assignment: BlockAssignment,
    defending_player: str,
    result: CombatResult,
    first_strike: bool,
) -> None:
    """Resolve one damage step (first strike or normal) for one attacker."""
    attacker = assignment.attacker
    damage_list = result.first_strike_damage if first_strike else result.normal_damage

    # Check if this creature participates in this step
    if first_strike and not attacker.deals_first_strike_damage():
        attacker_deals = False
    elif not first_strike and not attacker.deals_normal_damage():
        attacker_deals = False
    else:
        attacker_deals = not attacker.is_dead  # dead creatures don't deal damage

    if assignment.unblocked:
        # Unblocked: damage goes to defending player
        if attacker_deals and attacker.power > 0:
            kws = _damage_keywords(attacker)
            damage_list.append(DamageEvent(
                source=attacker.name,
                target=f"Player: {defending_player}",
                amount=attacker.power,
                keywords=kws,
            ))
            result.notes.append(
                f"  {attacker.name} ({attacker.power} power) hits "
                f"{defending_player} for {attacker.power} damage"
                f"{' (lifelink)' if attacker.has(CombatKeyword.LIFELINK) else ''}"
            )
    else:
        # Blocked: attacker assigns damage to blockers in order
        if attacker_deals and attacker.power > 0:
            remaining_power = attacker.power
            has_deathtouch = attacker.has(CombatKeyword.DEATHTOUCH)
            has_trample = attacker.has(CombatKeyword.TRAMPLE)
            kws = _damage_keywords(attacker)

            for blocker in assignment.blockers:
                if remaining_power <= 0:
                    break
                if blocker.is_dead:
                    continue

                # With deathtouch, 1 damage is lethal
                lethal = 1 if has_deathtouch else blocker.lethal_damage
                assigned = min(remaining_power, lethal)

                blocker.damage_marked += assigned
                if has_deathtouch:
                    blocker.took_deathtouch = True
                remaining_power -= assigned

                damage_list.append(DamageEvent(
                    source=attacker.name,
                    target=blocker.name,
                    amount=assigned,
                    keywords=kws,
                ))
                result.notes.append(
                    f"  {attacker.name} assigns {assigned} damage to {blocker.name}"
                    f"{' (deathtouch — 1 is lethal)' if has_deathtouch else ''}"
                )

            # Trample: remaining damage goes to defending player
            if has_trample and remaining_power > 0:
                damage_list.append(DamageEvent(
                    source=attacker.name,
                    target=f"Player: {defending_player}",
                    amount=remaining_power,
                    keywords=kws,
                ))
                result.notes.append(
                    f"  {attacker.name} tramples {remaining_power} damage "
                    f"through to {defending_player}"
                )

        # Blockers deal damage back to attacker.
        # Track which blockers are dealing damage in THIS step so we
        # count their damage as simultaneous (they deal even if they'd
        # die from attacker's damage this step). But creatures killed
        # in a PREVIOUS step (e.g., first strike) are already dead.
        for blocker in assignment.blockers:
            # Skip creatures that died in a previous damage step
            # (they were already added to creatures_that_die)
            if blocker.name in result.creatures_that_die:
                continue

            blocker_deals = False
            if first_strike and blocker.deals_first_strike_damage():
                blocker_deals = True
            elif not first_strike and blocker.deals_normal_damage():
                blocker_deals = True

            if blocker_deals and blocker.power > 0:
                attacker.damage_marked += blocker.power
                kws = _damage_keywords(blocker)
                damage_list.append(DamageEvent(
                    source=blocker.name,
                    target=attacker.name,
                    amount=blocker.power,
                    keywords=kws,
                ))
                result.notes.append(
                    f"  {blocker.name} deals {blocker.power} damage to {attacker.name}"
                )


def _check_deaths_after_step(
    assignments: list[BlockAssignment],
    result: CombatResult,
) -> None:
    """Check for creature deaths after a damage step (SBA 704.5f/g)."""
    for assignment in assignments:
        if assignment.attacker.is_dead and assignment.attacker.name not in result.creatures_that_die:
            result.creatures_that_die.append(assignment.attacker.name)
            result.notes.append(f"  * {assignment.attacker.name} dies (lethal damage)")
        for blocker in assignment.blockers:
            if blocker.is_dead and blocker.name not in result.creatures_that_die:
                result.creatures_that_die.append(blocker.name)
                result.notes.append(f"  * {blocker.name} dies (lethal damage)")


def _damage_keywords(creature: CombatCreature) -> list[str]:
    """Get relevant damage keywords for a creature."""
    kws = []
    if creature.has(CombatKeyword.LIFELINK):
        kws.append("lifelink")
    if creature.has(CombatKeyword.DEATHTOUCH):
        kws.append("deathtouch")
    return kws


def _find_controller(creature_name: str, assignments: list[BlockAssignment]) -> str | None:
    """Find which player controls a creature."""
    for assignment in assignments:
        if assignment.attacker.name == creature_name:
            return assignment.attacker.controller
        for blocker in assignment.blockers:
            if blocker.name == creature_name:
                return blocker.controller
    return None
