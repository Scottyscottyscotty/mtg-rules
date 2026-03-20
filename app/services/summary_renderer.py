"""Deterministic summary renderer — replaces Phase 2 Claude call.

Takes computed cascade, SBAs, triggers, stack order, and did_not_trigger
data and generates both technical and plain-English summaries using
templates. No API call needed — runs in <1ms.
"""

from app.models.board import (
    BoardAnalysisResult,
    CascadeStep,
    DidNotTrigger,
    GameEvent,
)
from app.services.game_rules.layers import LayerEffect, get_layer_name
from app.services.game_rules.state_based_actions import SBAResult


def render_summary(
    event: GameEvent,
    cascade: list[CascadeStep],
    stack_order: list[str],
    sba_results: list[SBAResult],
    triggers: list[dict],
    did_not_trigger: list[DidNotTrigger],
    layer_effects: list[LayerEffect],
    warnings: list[str],
) -> tuple[str, str]:
    """Generate technical summary and plain-English explanation.

    Returns:
        (summary, plain_english) tuple of strings.
    """
    summary = _render_technical(
        event, cascade, stack_order, sba_results,
        triggers, did_not_trigger, layer_effects, warnings,
    )
    plain = _render_plain_english(
        event, cascade, stack_order, sba_results,
        triggers, did_not_trigger, layer_effects, warnings,
    )
    return summary, plain


def _render_technical(
    event: GameEvent,
    cascade: list[CascadeStep],
    stack_order: list[str],
    sba_results: list[SBAResult],
    triggers: list[dict],
    did_not_trigger: list[DidNotTrigger],
    layer_effects: list[LayerEffect],
    warnings: list[str],
) -> str:
    """Technical step-by-step summary."""
    parts: list[str] = []

    # Event
    parts.append(f"Event: {_describe_event_short(event)}")
    parts.append("")

    # Layer effects
    if layer_effects:
        parts.append("Continuous effects (layer order):")
        for effect in layer_effects:
            layer_name = get_layer_name(effect.layer)
            parts.append(f"  - {effect.source_card}: {effect.effect_text} [{layer_name}]")
        parts.append("")

    # SBAs
    if sba_results:
        parts.append("State-based actions:")
        for sba in sba_results:
            parts.append(f"  - [{sba.rule}] {sba.description}")
        parts.append("")

    # Triggers
    if triggers:
        parts.append("Triggers identified:")
        for t in triggers:
            card = t.get("permanent_name", "Unknown")
            controller = t.get("controller", "Unknown")
            text = t.get("trigger_text", "")
            effect = t.get("resulting_effects", "")
            parts.append(f"  - {card} ({controller}): \"{text}\" -> {effect}")
        parts.append("")

    # Stack
    if stack_order:
        parts.append("Stack resolution order (APNAP):")
        for line in stack_order:
            parts.append(f"  {line}")
        parts.append("")

    # Did not trigger
    if did_not_trigger:
        parts.append("Did NOT trigger:")
        for item in did_not_trigger:
            parts.append(f"  - {item.permanent_name} ({item.controller}): {item.reason}")
        parts.append("")

    # Warnings
    if warnings:
        parts.append("Warnings:")
        for w in warnings:
            parts.append(f"  - {w}")

    return "\n".join(parts).strip()


def _render_plain_english(
    event: GameEvent,
    cascade: list[CascadeStep],
    stack_order: list[str],
    sba_results: list[SBAResult],
    triggers: list[dict],
    did_not_trigger: list[DidNotTrigger],
    layer_effects: list[LayerEffect],
    warnings: list[str],
) -> str:
    """Casual, friendly plain-English explanation."""
    parts: list[str] = []

    parts.append("Okay, so here's what happens...")
    parts.append("")

    # Describe the event
    parts.append(f"**{_describe_event_plain(event)}**")
    parts.append("")

    # Layer effects
    if layer_effects:
        for effect in layer_effects:
            parts.append(
                f"- {effect.source_card}'s continuous effect is active: "
                f"\"{effect.effect_text}\""
            )
        parts.append("")

    # SBAs
    if sba_results:
        parts.append("**State-based actions check:**")
        for sba in sba_results:
            parts.append(f"- {_humanize_sba(sba)}")
        parts.append("")

    # Triggers
    if triggers:
        parts.append("**This triggers the following:**")
        for t in triggers:
            card = t.get("permanent_name", "Unknown")
            trigger_text = t.get("trigger_text", "")
            effect = t.get("resulting_effects", "")
            condition = t.get("trigger_condition", "")
            parts.append(
                f"- {card}'s ability triggers: \"{trigger_text}\" — "
                f"because {condition}. When it resolves: {effect}"
            )
        parts.append("")

    # Stack
    if stack_order:
        parts.append("**Stack resolves (APNAP order):**")
        for line in stack_order:
            parts.append(f"- {line}")
        parts.append("")

    # NOTE: did_not_trigger is intentionally omitted here — the UI renders
    # it as a separate dedicated section. Including it here would duplicate.

    # Warnings
    if warnings:
        parts.append("**Heads up:**")
        for w in warnings:
            parts.append(f"- {w}")

    return "\n".join(parts).strip()


def _describe_event_short(event: GameEvent) -> str:
    """Short event description for technical summary."""
    parts = [event.event_type.value]
    if event.source_card:
        parts.append(f"(source: {event.source_card})")
    if event.target_card:
        parts.append(f"(target: {event.target_card})")
    if event.details:
        parts.append(f"— {event.details}")
    return " ".join(parts)


def _describe_event_plain(event: GameEvent) -> str:
    """Plain English event description."""
    etype = event.event_type.value.replace("_", " ")
    if event.source_card and event.target_card:
        return f"{event.source_card} — {etype} targeting {event.target_card}"
    if event.source_card:
        return f"{event.source_card} — {etype}"
    if event.details:
        return event.details
    return etype.capitalize()


def _humanize_sba(sba: SBAResult) -> str:
    """Make SBA descriptions more conversational."""
    desc = sba.description
    # Already pretty readable from the SBA engine, just add rule ref
    if sba.rule not in desc:
        desc = f"{desc} (rule {sba.rule})"
    return desc
