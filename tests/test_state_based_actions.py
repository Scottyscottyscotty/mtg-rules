"""Tests for deterministic state-based action checks (rule 704)."""

from app.models.board import BoardState, PlayerState, PermanentOnBoard, EventType
from app.models.card import Card
from app.services.game_rules.state_based_actions import check_sbas


def _card(name: str, type_line: str, power: str = None, toughness: str = None, **kw) -> Card:
    return Card(name=name, type_line=type_line, power=power, toughness=toughness, **kw)


def _perm(name: str, owner: str, **kw) -> PermanentOnBoard:
    return PermanentOnBoard(card_name=name, owner=owner, **kw)


def _board(*players) -> BoardState:
    return BoardState(players=list(players))


# --- 704.5a: Player at 0 or less life ---

class TestLifeTotalSBA:
    def test_player_at_zero_life(self):
        board = _board(PlayerState(name="Alice", life=0, permanents=[]))
        sbas = check_sbas(board, {})
        assert any(s.rule == "704.5a" for s in sbas)
        assert "Alice" in sbas[0].description

    def test_player_at_negative_life(self):
        board = _board(PlayerState(name="Bob", life=-5, permanents=[]))
        sbas = check_sbas(board, {})
        assert any(s.rule == "704.5a" for s in sbas)

    def test_player_at_positive_life_no_sba(self):
        board = _board(PlayerState(name="Alice", life=20, permanents=[]))
        sbas = check_sbas(board, {})
        assert not any(s.rule == "704.5a" for s in sbas)

    def test_multiple_players_one_dead(self):
        board = _board(
            PlayerState(name="Alice", life=40, permanents=[]),
            PlayerState(name="Bob", life=0, permanents=[]),
        )
        sbas = check_sbas(board, {})
        life_sbas = [s for s in sbas if s.rule == "704.5a"]
        assert len(life_sbas) == 1
        assert "Bob" in life_sbas[0].description


# --- 704.5f: Creature with toughness 0 or less ---

class TestToughnessSBA:
    def test_creature_with_zero_toughness_dies(self):
        board = _board(
            PlayerState(name="Alice", life=40, permanents=[
                _perm("Grizzly Bears", "Alice"),
            ])
        )
        cards = {"Grizzly Bears": _card("Grizzly Bears", "Creature — Bear", "2", "2")}
        sbas = check_sbas(board, cards, {"Grizzly Bears": (0, -3)})
        death_sbas = [s for s in sbas if s.rule == "704.5f"]
        assert len(death_sbas) == 1
        assert "Grizzly Bears" in death_sbas[0].description

    def test_creature_survives_partial_reduction(self):
        board = _board(
            PlayerState(name="Alice", life=40, permanents=[
                _perm("Grizzly Bears", "Alice"),
            ])
        )
        cards = {"Grizzly Bears": _card("Grizzly Bears", "Creature — Bear", "2", "2")}
        # -1/-1 still leaves toughness at 1
        sbas = check_sbas(board, cards, {"Grizzly Bears": (0, -1)})
        death_sbas = [s for s in sbas if s.rule == "704.5f"]
        assert len(death_sbas) == 0

    def test_non_creature_not_checked(self):
        """Enchantments don't die from toughness reduction."""
        board = _board(
            PlayerState(name="Alice", life=40, permanents=[
                _perm("Rhystic Study", "Alice"),
            ])
        )
        cards = {"Rhystic Study": _card("Rhystic Study", "Enchantment", oracle_text="test")}
        sbas = check_sbas(board, cards, {"Rhystic Study": (0, -5)})
        death_sbas = [s for s in sbas if s.rule == "704.5f"]
        assert len(death_sbas) == 0

    def test_counters_modify_toughness(self):
        """Plus counters should keep creature alive."""
        board = _board(
            PlayerState(name="Alice", life=40, permanents=[
                _perm("Grizzly Bears", "Alice", counters={"+1/+1": 3}),
            ])
        )
        cards = {"Grizzly Bears": _card("Grizzly Bears", "Creature — Bear", "2", "2")}
        # -3 toughness from effect, but +3 from counters = net 0 change
        sbas = check_sbas(board, cards, {"Grizzly Bears": (0, -3)})
        death_sbas = [s for s in sbas if s.rule == "704.5f"]
        assert len(death_sbas) == 0

    def test_minus_counters_kill_creature(self):
        """-1/-1 counters reduce toughness."""
        board = _board(
            PlayerState(name="Alice", life=40, permanents=[
                _perm("Grizzly Bears", "Alice", counters={"-1/-1": 2}),
            ])
        )
        cards = {"Grizzly Bears": _card("Grizzly Bears", "Creature — Bear", "2", "2")}
        sbas = check_sbas(board, cards)
        death_sbas = [s for s in sbas if s.rule == "704.5f"]
        assert len(death_sbas) == 1

    def test_star_toughness_not_checked(self):
        """Cards with * toughness can't be numerically evaluated."""
        board = _board(
            PlayerState(name="Alice", life=40, permanents=[
                _perm("Tarmogoyf", "Alice"),
            ])
        )
        cards = {"Tarmogoyf": _card("Tarmogoyf", "Creature — Lhurgoyf", "*", "1+*")}
        sbas = check_sbas(board, cards)
        death_sbas = [s for s in sbas if s.rule == "704.5f"]
        assert len(death_sbas) == 0

    def test_massacre_wurm_scenario(self):
        """Classic scenario: Massacre Wurm's -2/-2 kills small creatures."""
        board = _board(
            PlayerState(name="Alice", life=40, permanents=[
                _perm("Massacre Wurm", "Alice"),
            ]),
            PlayerState(name="Bob", life=40, permanents=[
                _perm("Llanowar Elves", "Bob"),
                _perm("Birds of Paradise", "Bob"),
                _perm("Grizzly Bears", "Bob"),
            ]),
        )
        cards = {
            "Massacre Wurm": _card("Massacre Wurm", "Creature — Phyrexian Wurm", "6", "5"),
            "Llanowar Elves": _card("Llanowar Elves", "Creature — Elf Druid", "1", "1"),
            "Birds of Paradise": _card("Birds of Paradise", "Creature — Bird", "0", "1"),
            "Grizzly Bears": _card("Grizzly Bears", "Creature — Bear", "2", "2"),
        }
        # Massacre Wurm gives -2/-2 to opponents' creatures
        mods = {
            "Llanowar Elves": (-2, -2),
            "Birds of Paradise": (-2, -2),
            "Grizzly Bears": (-2, -2),
        }
        sbas = check_sbas(board, cards, mods)
        death_sbas = [s for s in sbas if s.rule == "704.5f"]
        dead_names = {s.description for s in death_sbas}
        # All three should die (toughness: -1, -1, 0)
        assert len(death_sbas) == 3
        assert any("Llanowar Elves" in d for d in dead_names)
        assert any("Birds of Paradise" in d for d in dead_names)
        assert any("Grizzly Bears" in d for d in dead_names)


# --- 704.5q: Counter cancellation ---

class TestCounterCancellation:
    def test_plus_minus_counters_cancel(self):
        board = _board(
            PlayerState(name="Alice", life=40, permanents=[
                _perm("Grizzly Bears", "Alice", counters={"+1/+1": 3, "-1/-1": 2}),
            ])
        )
        cards = {"Grizzly Bears": _card("Grizzly Bears", "Creature — Bear", "2", "2")}
        sbas = check_sbas(board, cards)
        cancel_sbas = [s for s in sbas if s.rule == "704.5q"]
        assert len(cancel_sbas) == 1
        assert "2" in cancel_sbas[0].description  # 2 pairs cancel

    def test_no_cancellation_without_both(self):
        board = _board(
            PlayerState(name="Alice", life=40, permanents=[
                _perm("Grizzly Bears", "Alice", counters={"+1/+1": 3}),
            ])
        )
        cards = {"Grizzly Bears": _card("Grizzly Bears", "Creature — Bear", "2", "2")}
        sbas = check_sbas(board, cards)
        cancel_sbas = [s for s in sbas if s.rule == "704.5q"]
        assert len(cancel_sbas) == 0


# --- 704.5j: Legend rule ---

class TestLegendRule:
    def test_duplicate_legends_flagged(self):
        board = _board(
            PlayerState(name="Alice", life=40, permanents=[
                _perm("Sheoldred", "Alice"),
                _perm("Sheoldred", "Alice"),
            ])
        )
        cards = {"Sheoldred": _card("Sheoldred", "Legendary Creature — Phyrexian Praetor", "4", "5")}
        sbas = check_sbas(board, cards)
        legend_sbas = [s for s in sbas if s.rule == "704.5j"]
        assert len(legend_sbas) == 1

    def test_different_legends_ok(self):
        board = _board(
            PlayerState(name="Alice", life=40, permanents=[
                _perm("Sheoldred", "Alice"),
                _perm("Atraxa", "Alice"),
            ])
        )
        cards = {
            "Sheoldred": _card("Sheoldred", "Legendary Creature — Phyrexian Praetor", "4", "5"),
            "Atraxa": _card("Atraxa", "Legendary Creature — Phyrexian Angel", "4", "4"),
        }
        sbas = check_sbas(board, cards)
        legend_sbas = [s for s in sbas if s.rule == "704.5j"]
        assert len(legend_sbas) == 0

    def test_different_players_same_legend_ok(self):
        """Each player can have their own copy of a legend."""
        board = _board(
            PlayerState(name="Alice", life=40, permanents=[
                _perm("Sheoldred", "Alice"),
            ]),
            PlayerState(name="Bob", life=40, permanents=[
                _perm("Sheoldred", "Bob"),
            ]),
        )
        cards = {"Sheoldred": _card("Sheoldred", "Legendary Creature — Phyrexian Praetor", "4", "5")}
        sbas = check_sbas(board, cards)
        legend_sbas = [s for s in sbas if s.rule == "704.5j"]
        assert len(legend_sbas) == 0


# --- Edge cases ---

class TestSBAEdgeCases:
    def test_empty_board(self):
        board = _board()
        sbas = check_sbas(board, {})
        assert sbas == []

    def test_unknown_card_skipped(self):
        """Cards not in card_data are silently skipped."""
        board = _board(
            PlayerState(name="Alice", life=40, permanents=[
                _perm("Unknown Card", "Alice"),
            ])
        )
        sbas = check_sbas(board, {})
        death_sbas = [s for s in sbas if s.rule == "704.5f"]
        assert len(death_sbas) == 0

    def test_multiple_sbas_fire_simultaneously(self):
        """Multiple SBAs should all be detected in one check."""
        board = _board(
            PlayerState(name="Alice", life=0, permanents=[
                _perm("Grizzly Bears", "Alice", counters={"-1/-1": 3}),
            ]),
        )
        cards = {"Grizzly Bears": _card("Grizzly Bears", "Creature — Bear", "2", "2")}
        sbas = check_sbas(board, cards)
        rules = [s.rule for s in sbas]
        assert "704.5a" in rules  # Alice at 0 life
        assert "704.5f" in rules  # Bears at -1 toughness

    def test_controller_vs_owner(self):
        """SBA should reference the controller, not just owner."""
        board = _board(
            PlayerState(name="Alice", life=40, permanents=[
                _perm("Grizzly Bears", "Alice", controller="Bob"),
            ])
        )
        cards = {"Grizzly Bears": _card("Grizzly Bears", "Creature — Bear", "2", "2")}
        sbas = check_sbas(board, cards, {"Grizzly Bears": (0, -3)})
        death_sbas = [s for s in sbas if s.rule == "704.5f"]
        assert len(death_sbas) == 1
        assert "Bob" in death_sbas[0].description  # controller, not owner
