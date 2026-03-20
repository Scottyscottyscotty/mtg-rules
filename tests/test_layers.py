"""Tests for the layer system (rule 613)."""

from app.services.game_rules.layers import (
    Layer,
    LayerEffect,
    classify_layer,
    sort_effects_by_layer,
    get_layer_name,
)


class TestLayerClassification:
    def test_copy_effects(self):
        assert classify_layer("becomes a copy of target creature") == Layer.COPY

    def test_control_changing(self):
        assert classify_layer("gain control of target creature") == Layer.CONTROL

    def test_type_changing(self):
        assert classify_layer("is a Swamp in addition to its other types") == Layer.TYPE

    def test_color_changing(self):
        assert classify_layer("is black") == Layer.COLOR

    def test_ability_granting(self):
        assert classify_layer("has flying") == Layer.ABILITY
        assert classify_layer("gains trample until end of turn") == Layer.ABILITY
        assert classify_layer("has hexproof") == Layer.ABILITY
        assert classify_layer("can't be blocked") == Layer.ABILITY

    def test_pt_cda(self):
        assert classify_layer("power and toughness are each equal to the number of cards") == Layer.PT_CDA

    def test_pt_set(self):
        assert classify_layer("base power and toughness are 3/3") == Layer.PT_SET

    def test_pt_modification(self):
        assert classify_layer("gets +2/+2 until end of turn") == Layer.PT_MODIFICATION
        assert classify_layer("gets -2/-2 until end of turn") == Layer.PT_MODIFICATION
        assert classify_layer("other creatures you control get +1/+1") == Layer.PT_MODIFICATION

    def test_pt_counters(self):
        assert classify_layer("put a +1/+1 counter on it") == Layer.PT_COUNTERS
        assert classify_layer("remove a -1/-1 counter") == Layer.PT_COUNTERS

    def test_pt_switch(self):
        assert classify_layer("switch its power and toughness") == Layer.PT_SWITCH
        assert classify_layer("power and toughness are switched") == Layer.PT_SWITCH

    def test_generic_pt_defaults_to_modification(self):
        assert classify_layer("increases power by 2") == Layer.PT_MODIFICATION

    def test_unknown_defaults_to_ability(self):
        assert classify_layer("some random effect text") == Layer.ABILITY


class TestLayerOrdering:
    def test_effects_sorted_by_layer(self):
        effects = [
            LayerEffect("Card A", "Alice", "gets +2/+2", Layer.PT_MODIFICATION, timestamp=0),
            LayerEffect("Card B", "Alice", "is a Swamp", Layer.TYPE, timestamp=0),
            LayerEffect("Card C", "Alice", "gains flying", Layer.ABILITY, timestamp=0),
        ]
        sorted_effects = sort_effects_by_layer(effects)
        assert sorted_effects[0].layer == Layer.TYPE       # Layer 4
        assert sorted_effects[1].layer == Layer.ABILITY     # Layer 6
        assert sorted_effects[2].layer == Layer.PT_MODIFICATION  # Layer 7c

    def test_same_layer_sorted_by_timestamp(self):
        effects = [
            LayerEffect("Newer", "Alice", "gets +1/+1", Layer.PT_MODIFICATION, timestamp=5),
            LayerEffect("Older", "Alice", "gets +2/+2", Layer.PT_MODIFICATION, timestamp=1),
        ]
        sorted_effects = sort_effects_by_layer(effects)
        assert sorted_effects[0].source_card == "Older"   # older first
        assert sorted_effects[1].source_card == "Newer"

    def test_sublayers_ordered_correctly(self):
        """7a < 7b < 7c < 7d < 7e"""
        effects = [
            LayerEffect("Switch", "A", "switch", Layer.PT_SWITCH, 0),
            LayerEffect("CDA", "A", "cda", Layer.PT_CDA, 0),
            LayerEffect("Counter", "A", "counter", Layer.PT_COUNTERS, 0),
            LayerEffect("Set", "A", "set", Layer.PT_SET, 0),
            LayerEffect("Mod", "A", "mod", Layer.PT_MODIFICATION, 0),
        ]
        sorted_effects = sort_effects_by_layer(effects)
        layers = [e.layer for e in sorted_effects]
        assert layers == [
            Layer.PT_CDA,           # 7a
            Layer.PT_SET,           # 7b
            Layer.PT_MODIFICATION,  # 7c
            Layer.PT_COUNTERS,      # 7d
            Layer.PT_SWITCH,        # 7e
        ]

    def test_full_layer_stack(self):
        """All layers in correct order."""
        effects = [
            LayerEffect("E", "A", "ability", Layer.ABILITY, 0),
            LayerEffect("A", "A", "copy", Layer.COPY, 0),
            LayerEffect("G", "A", "mod", Layer.PT_MODIFICATION, 0),
            LayerEffect("C", "A", "text", Layer.TEXT, 0),
            LayerEffect("B", "A", "control", Layer.CONTROL, 0),
            LayerEffect("D", "A", "type", Layer.TYPE, 0),
            LayerEffect("F", "A", "color", Layer.COLOR, 0),
        ]
        sorted_effects = sort_effects_by_layer(effects)
        layers = [e.layer for e in sorted_effects]
        assert layers == [
            Layer.COPY,             # 1
            Layer.CONTROL,          # 2
            Layer.TEXT,             # 3
            Layer.TYPE,             # 4
            Layer.COLOR,            # 5
            Layer.ABILITY,          # 6
            Layer.PT_MODIFICATION,  # 7c
        ]

    def test_empty_list(self):
        assert sort_effects_by_layer([]) == []


class TestLayerNames:
    def test_all_layers_have_names(self):
        for layer in Layer:
            name = get_layer_name(layer)
            assert name
            assert "Layer" in name
