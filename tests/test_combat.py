"""Tests for combat damage simulator."""

from app.services.game_rules.combat import (
    BlockAssignment,
    CombatCreature,
    CombatKeyword,
    check_blocking_legality,
    check_menace,
    resolve_combat,
)

K = CombatKeyword


def _creature(name, controller, power, toughness, *keywords):
    return CombatCreature(
        name=name, controller=controller,
        power=power, toughness=toughness,
        keywords=set(keywords),
    )


class TestUnblockedDamage:
    def test_simple_unblocked(self):
        result = resolve_combat(
            [BlockAssignment(
                attacker=_creature("Grizzly Bears", "Alice", 2, 2),
                unblocked=True,
            )],
            defending_player="Bob",
        )
        assert result.player_damage["Bob"] == 2
        assert len(result.creatures_that_die) == 0

    def test_multiple_unblocked(self):
        result = resolve_combat(
            [
                BlockAssignment(
                    attacker=_creature("Bears", "Alice", 2, 2),
                    unblocked=True,
                ),
                BlockAssignment(
                    attacker=_creature("Wurm", "Alice", 6, 6),
                    unblocked=True,
                ),
            ],
            defending_player="Bob",
        )
        assert result.player_damage["Bob"] == 8


class TestBlockedDamage:
    def test_attacker_kills_blocker(self):
        result = resolve_combat(
            [BlockAssignment(
                attacker=_creature("Serra Angel", "Alice", 4, 4),
                blockers=[_creature("Grizzly Bears", "Bob", 2, 2)],
                unblocked=False,
            )],
            defending_player="Bob",
        )
        assert "Grizzly Bears" in result.creatures_that_die
        assert "Serra Angel" not in result.creatures_that_die

    def test_both_die(self):
        result = resolve_combat(
            [BlockAssignment(
                attacker=_creature("Bears A", "Alice", 2, 2),
                blockers=[_creature("Bears B", "Bob", 2, 2)],
                unblocked=False,
            )],
            defending_player="Bob",
        )
        assert "Bears A" in result.creatures_that_die
        assert "Bears B" in result.creatures_that_die

    def test_blocker_survives(self):
        """Wall (0/5) survives, Bears (2/2) survives too (wall has 0 power)."""
        result = resolve_combat(
            [BlockAssignment(
                attacker=_creature("Bears", "Alice", 2, 2),
                blockers=[_creature("Wall", "Bob", 0, 5)],
                unblocked=False,
            )],
            defending_player="Bob",
        )
        assert "Bears" not in result.creatures_that_die  # Wall can't kill it
        assert "Wall" not in result.creatures_that_die   # 2 < 5 toughness

    def test_big_blocker_kills_attacker(self):
        """Wall (3/5) kills Bears (2/2) and survives."""
        result = resolve_combat(
            [BlockAssignment(
                attacker=_creature("Bears", "Alice", 2, 2),
                blockers=[_creature("Wall", "Bob", 3, 5)],
                unblocked=False,
            )],
            defending_player="Bob",
        )
        assert "Bears" in result.creatures_that_die
        assert "Wall" not in result.creatures_that_die


class TestFirstStrike:
    def test_first_strike_kills_before_damage(self):
        """First striker kills blocker before it can deal damage back."""
        result = resolve_combat(
            [BlockAssignment(
                attacker=_creature("Knight", "Alice", 3, 2, K.FIRST_STRIKE),
                blockers=[_creature("Bears", "Bob", 2, 2)],
                unblocked=False,
            )],
            defending_player="Bob",
        )
        assert "Bears" in result.creatures_that_die
        # Knight should survive — Bears died to first strike, never dealt damage
        assert "Knight" not in result.creatures_that_die

    def test_double_strike_deals_twice(self):
        """Double strike deals damage in both first strike and normal steps."""
        result = resolve_combat(
            [BlockAssignment(
                attacker=_creature("DS Creature", "Alice", 3, 3, K.DOUBLE_STRIKE),
                unblocked=True,
            )],
            defending_player="Bob",
        )
        # 3 first strike + 3 normal = 6 total
        assert result.player_damage["Bob"] == 6


class TestTrample:
    def test_trample_excess_to_player(self):
        result = resolve_combat(
            [BlockAssignment(
                attacker=_creature("Wurm", "Alice", 6, 6, K.TRAMPLE),
                blockers=[_creature("Bears", "Bob", 2, 2)],
                unblocked=False,
            )],
            defending_player="Bob",
        )
        assert "Bears" in result.creatures_that_die
        assert result.player_damage["Bob"] == 4  # 6 - 2 toughness = 4 trample

    def test_trample_no_excess(self):
        """If blocker has enough toughness, no trample damage."""
        result = resolve_combat(
            [BlockAssignment(
                attacker=_creature("Bears", "Alice", 2, 2, K.TRAMPLE),
                blockers=[_creature("Wall", "Bob", 0, 5)],
                unblocked=False,
            )],
            defending_player="Bob",
        )
        assert result.player_damage.get("Bob", 0) == 0


class TestDeathtouch:
    def test_deathtouch_only_needs_one(self):
        """Deathtouch assigns only 1 damage per blocker."""
        result = resolve_combat(
            [BlockAssignment(
                attacker=_creature("DT Creature", "Alice", 3, 1, K.DEATHTOUCH),
                blockers=[
                    _creature("Bear A", "Bob", 2, 2),
                    _creature("Bear B", "Bob", 2, 2),
                ],
                unblocked=False,
            )],
            defending_player="Bob",
        )
        # 1 damage to Bear A, 1 to Bear B = both die from deathtouch
        assert "Bear A" in result.creatures_that_die
        assert "Bear B" in result.creatures_that_die

    def test_deathtouch_plus_trample(self):
        """Deathtouch + trample: 1 to blocker, rest tramples through."""
        result = resolve_combat(
            [BlockAssignment(
                attacker=_creature("DT Trampler", "Alice", 6, 6,
                                   K.DEATHTOUCH, K.TRAMPLE),
                blockers=[_creature("Big Wall", "Bob", 0, 10)],
                unblocked=False,
            )],
            defending_player="Bob",
        )
        assert "Big Wall" in result.creatures_that_die
        # 1 damage to wall (lethal with deathtouch), 5 tramples to Bob
        assert result.player_damage["Bob"] == 5


class TestLifelink:
    def test_lifelink_gains_life(self):
        result = resolve_combat(
            [BlockAssignment(
                attacker=_creature("Lifelinker", "Alice", 4, 4, K.LIFELINK),
                unblocked=True,
            )],
            defending_player="Bob",
        )
        assert result.player_damage["Bob"] == 4
        assert result.life_gained["Alice"] == 4

    def test_lifelink_in_combat(self):
        """Lifelink works even when dealing damage to creatures."""
        result = resolve_combat(
            [BlockAssignment(
                attacker=_creature("Lifelinker", "Alice", 4, 4, K.LIFELINK),
                blockers=[_creature("Bears", "Bob", 2, 2)],
                unblocked=False,
            )],
            defending_player="Bob",
        )
        # Dealt 2 to Bears (lethal)
        assert result.life_gained["Alice"] == 2


class TestIndestructible:
    def test_indestructible_survives(self):
        result = resolve_combat(
            [BlockAssignment(
                attacker=_creature("God", "Alice", 5, 5, K.INDESTRUCTIBLE),
                blockers=[_creature("Dragon", "Bob", 10, 10)],
                unblocked=False,
            )],
            defending_player="Bob",
        )
        # God took 10 damage but is indestructible
        assert "God" not in result.creatures_that_die
        assert "Dragon" not in result.creatures_that_die  # 5 < 10


class TestBlockingLegality:
    def test_flying_blocked_by_reach(self):
        attacker = _creature("Flyer", "Alice", 2, 2, K.FLYING)
        blocker = _creature("Spider", "Bob", 1, 3, K.REACH)
        warnings = check_blocking_legality(attacker, blocker)
        assert len(warnings) == 0

    def test_flying_cant_be_blocked_by_ground(self):
        attacker = _creature("Flyer", "Alice", 2, 2, K.FLYING)
        blocker = _creature("Bears", "Bob", 2, 2)
        warnings = check_blocking_legality(attacker, blocker)
        assert len(warnings) == 1
        assert "flying" in warnings[0].lower()

    def test_menace_needs_two_blockers(self):
        assignment = BlockAssignment(
            attacker=_creature("Menace", "Alice", 3, 3, K.MENACE),
            blockers=[_creature("Bears", "Bob", 2, 2)],
            unblocked=False,
        )
        warnings = check_menace(assignment)
        assert len(warnings) == 1
        assert "menace" in warnings[0].lower()

    def test_menace_ok_with_two(self):
        assignment = BlockAssignment(
            attacker=_creature("Menace", "Alice", 3, 3, K.MENACE),
            blockers=[
                _creature("Bear A", "Bob", 2, 2),
                _creature("Bear B", "Bob", 2, 2),
            ],
            unblocked=False,
        )
        warnings = check_menace(assignment)
        assert len(warnings) == 0
