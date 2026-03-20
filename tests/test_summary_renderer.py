"""Tests for deterministic summary renderer."""

from app.models.board import (
    CascadeStep,
    DidNotTrigger,
    EventType,
    GameEvent,
)
from app.services.game_rules.layers import Layer, LayerEffect
from app.services.game_rules.state_based_actions import SBAResult
from app.services.summary_renderer import render_summary


def _event(etype=EventType.ENTERS_BATTLEFIELD, source=None, details=""):
    return GameEvent(event_type=etype, source_card=source, details=details)


class TestRenderSummary:
    def test_returns_two_strings(self):
        summary, plain = render_summary(
            event=_event(),
            cascade=[],
            stack_order=[],
            sba_results=[],
            triggers=[],
            did_not_trigger=[],
            layer_effects=[],
            warnings=[],
        )
        assert isinstance(summary, str)
        assert isinstance(plain, str)

    def test_plain_english_starts_with_okay(self):
        _, plain = render_summary(
            event=_event(),
            cascade=[],
            stack_order=[],
            sba_results=[],
            triggers=[],
            did_not_trigger=[],
            layer_effects=[],
            warnings=[],
        )
        assert plain.startswith("Okay, so here's what happens...")

    def test_technical_includes_event(self):
        summary, _ = render_summary(
            event=_event(details="Grizzly Bears ETB"),
            cascade=[],
            stack_order=[],
            sba_results=[],
            triggers=[],
            did_not_trigger=[],
            layer_effects=[],
            warnings=[],
        )
        assert "Grizzly Bears ETB" in summary

    def test_sba_results_included(self):
        sba = SBAResult(
            rule="704.5f",
            description="Llanowar Elves dies (toughness 0)",
        )
        summary, plain = render_summary(
            event=_event(),
            cascade=[],
            stack_order=[],
            sba_results=[sba],
            triggers=[],
            did_not_trigger=[],
            layer_effects=[],
            warnings=[],
        )
        assert "704.5f" in summary
        assert "Llanowar Elves" in summary
        assert "Llanowar Elves" in plain

    def test_triggers_included(self):
        trigger = {
            "permanent_name": "Blood Artist",
            "controller": "Alice",
            "trigger_text": "Whenever a creature dies",
            "trigger_condition": "creature died",
            "resulting_effects": "target player loses 1 life",
        }
        summary, plain = render_summary(
            event=_event(),
            cascade=[],
            stack_order=[],
            sba_results=[],
            triggers=[trigger],
            did_not_trigger=[],
            layer_effects=[],
            warnings=[],
        )
        assert "Blood Artist" in summary
        assert "Blood Artist" in plain
        assert "Whenever a creature dies" in summary

    def test_did_not_trigger_in_technical_not_plain(self):
        """did_not_trigger appears in technical summary but NOT in plain English
        (the UI renders it as a separate section)."""
        dnt = DidNotTrigger(
            permanent_name="Soul Warden",
            controller="Bob",
            reason="dying is not entering the battlefield",
        )
        summary, plain = render_summary(
            event=_event(),
            cascade=[],
            stack_order=[],
            sba_results=[],
            triggers=[],
            did_not_trigger=[dnt],
            layer_effects=[],
            warnings=[],
        )
        assert "Soul Warden" in summary
        # Plain English should NOT include did_not_trigger (UI handles it)
        assert "Soul Warden" not in plain

    def test_layer_effects_included(self):
        effect = LayerEffect(
            source_card="Massacre Wurm",
            controller="Alice",
            effect_text="Other creatures get -2/-2",
            layer=Layer.PT_MODIFICATION,
        )
        summary, plain = render_summary(
            event=_event(),
            cascade=[],
            stack_order=[],
            sba_results=[],
            triggers=[],
            did_not_trigger=[],
            layer_effects=[effect],
            warnings=[],
        )
        assert "Massacre Wurm" in summary
        assert "Massacre Wurm" in plain
        assert "Layer 7c" in summary

    def test_stack_order_included(self):
        stack = [
            "1. Blood Artist's trigger (Alice): target player loses 1 life",
            "2. Soul Warden's trigger (Bob): gain 1 life",
        ]
        summary, _ = render_summary(
            event=_event(),
            cascade=[],
            stack_order=stack,
            sba_results=[],
            triggers=[],
            did_not_trigger=[],
            layer_effects=[],
            warnings=[],
        )
        assert "Blood Artist" in summary
        assert "Soul Warden" in summary

    def test_warnings_included(self):
        summary, plain = render_summary(
            event=_event(),
            cascade=[],
            stack_order=[],
            sba_results=[],
            triggers=[],
            did_not_trigger=[],
            layer_effects=[],
            warnings=["Card 'Foo' not found on Scryfall"],
        )
        assert "Foo" in summary
        assert "Foo" in plain
