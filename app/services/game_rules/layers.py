"""Layer system for continuous effects (rule 613).

Continuous effects are applied in a strict layer order. Within each layer,
effects apply in timestamp order (oldest first). This is entirely
deterministic — no AI reasoning needed.

Layers:
  1  — Copy effects
  2  — Control-changing effects
  3  — Text-changing effects
  4  — Type-changing effects
  5  — Color-changing effects
  6  — Ability-adding/removing effects
  7  — Power/toughness-changing effects
    7a — Characteristic-defining abilities (e.g., Tarmogoyf)
    7b — Set P/T to specific value (e.g., "becomes a 3/3")
    7c — Modifications from static abilities (e.g., "-2/-2 to creatures")
    7d — Counters (+1/+1, -1/-1)
    7e — Switching power and toughness

Within a layer, if effects have dependencies (one effect depends on
another), they apply in dependency order (rule 613.8). Otherwise,
timestamp order.
"""

from dataclasses import dataclass
from enum import IntEnum


class Layer(IntEnum):
    """The seven layers (plus sublayers) for continuous effects."""
    COPY = 1
    CONTROL = 2
    TEXT = 3
    TYPE = 4
    COLOR = 5
    ABILITY = 6
    PT_CDA = 70        # 7a — characteristic-defining abilities
    PT_SET = 71        # 7b — set to specific value
    PT_MODIFICATION = 72  # 7c — +N/+N, -N/-N from static abilities
    PT_COUNTERS = 73   # 7d — counters
    PT_SWITCH = 74     # 7e — switch P/T


# Keywords/patterns that hint at which layer an effect applies in.
# Claude identifies the effects; this module just orders them.
LAYER_KEYWORDS = {
    Layer.COPY: ["copy", "becomes a copy"],
    Layer.CONTROL: ["gain control", "control of", "gains control"],
    Layer.TEXT: ["change the text", "replacing"],
    Layer.TYPE: [
        "is a", "becomes a", "in addition to its other types",
        "loses all creature types", "is an",
    ],
    Layer.COLOR: [
        "is white", "is blue", "is black", "is red", "is green",
        "loses all colors", "is colorless",
    ],
    Layer.ABILITY: [
        "gains", "has", "loses all abilities", "can't be blocked",
        "has flying", "gains trample", "has hexproof", "has deathtouch",
    ],
    Layer.PT_CDA: ["power and toughness are each equal to"],
    Layer.PT_SET: ["base power and toughness", "becomes a 0/0", "becomes a"],
    Layer.PT_MODIFICATION: [
        "gets +", "gets -", "+1/+1", "-1/-1", "+2/+2", "-2/-2",
        "other creatures you control get",
    ],
    Layer.PT_COUNTERS: ["+1/+1 counter", "-1/-1 counter"],
    Layer.PT_SWITCH: ["switch", "power and toughness are switched"],
}


@dataclass
class LayerEffect:
    """A continuous effect tagged with its layer and source info."""
    source_card: str
    controller: str
    effect_text: str
    layer: Layer
    timestamp: int = 0  # older = lower number = applies first


def classify_layer(effect_text: str) -> Layer:
    """Determine which layer an effect applies in based on its text.

    This uses keyword matching as a heuristic. Claude identifies the
    actual effects; this just categorizes them for ordering.
    """
    text_lower = effect_text.lower()

    # Check from most specific (sublayers) to least specific
    # Order matters: check 7a-7e before layer 4's "becomes a"
    for layer in [
        Layer.PT_CDA, Layer.PT_SWITCH, Layer.PT_COUNTERS,
        Layer.PT_MODIFICATION, Layer.PT_SET,
        Layer.COPY, Layer.CONTROL, Layer.TEXT,
        Layer.TYPE, Layer.COLOR, Layer.ABILITY,
    ]:
        for keyword in LAYER_KEYWORDS[layer]:
            if keyword in text_lower:
                return layer

    # Default: if it mentions P/T at all, it's probably 7c
    if any(c in text_lower for c in ["/+", "/-", "power", "toughness"]):
        return Layer.PT_MODIFICATION

    # Can't determine — default to ability layer (most common)
    return Layer.ABILITY


def sort_effects_by_layer(effects: list[LayerEffect]) -> list[LayerEffect]:
    """Sort continuous effects by layer order, then timestamp within each layer.

    This is the core of the layer system: effects in lower layers apply
    first, and within a layer, older effects (lower timestamp) apply first.
    """
    return sorted(effects, key=lambda e: (e.layer.value, e.timestamp))


def get_layer_name(layer: Layer) -> str:
    """Human-readable name for a layer, for display purposes."""
    names = {
        Layer.COPY: "Layer 1 (Copy effects)",
        Layer.CONTROL: "Layer 2 (Control-changing)",
        Layer.TEXT: "Layer 3 (Text-changing)",
        Layer.TYPE: "Layer 4 (Type-changing)",
        Layer.COLOR: "Layer 5 (Color-changing)",
        Layer.ABILITY: "Layer 6 (Ability adding/removing)",
        Layer.PT_CDA: "Layer 7a (P/T characteristic-defining abilities)",
        Layer.PT_SET: "Layer 7b (Setting P/T to specific values)",
        Layer.PT_MODIFICATION: "Layer 7c (P/T modifications from effects)",
        Layer.PT_COUNTERS: "Layer 7d (P/T from counters)",
        Layer.PT_SWITCH: "Layer 7e (Switching P/T)",
    }
    return names.get(layer, f"Layer {layer.value}")
