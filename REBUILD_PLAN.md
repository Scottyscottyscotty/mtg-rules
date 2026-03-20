# MTG Rules App — Rebuild Plan

## Architecture: Before vs After

### Before (Current)
```
5 routers → 5 independent services → duplicate Scryfall calls + 2 Claude calls
```

### After (Rebuild)
```
5 routers → CardRegistry (shared cache) → AnalysisPipeline (1 Claude call) → game_rules (deterministic)
```

## Changes

### 1. CardRegistry — shared card data layer
**File:** `app/services/card_registry.py`

- In-memory LRU cache (dict) + existing disk cache as L2
- Single `get_card()` and `get_cards()` interface
- All services use this instead of calling `fetch_card()` directly
- Batch fetch with concurrency for board/combat requests
- Pre-warm cache from board state before analysis begins

**Why:** Currently board_analyzer, combat_simulator, chat, and interaction_resolver
all independently call scryfall.fetch_card(). Same card fetched 3 times in one
session hits disk 3 times. Memory cache eliminates this.

### 2. Eliminate Phase 2 Claude call — template the summary
**File:** `app/services/summary_renderer.py`

- Takes the computed cascade, SBAs, triggers, stack order, did_not_trigger
- Generates both `summary` (technical) and `plain_english` (casual) deterministically
- Template-based: "Okay, so here's what happens..." followed by each step
- Saves ~3 seconds per board analysis request (eliminates one Claude API call)

**Why:** Phase 2 currently asks Claude to reformat data that's already fully computed.
Claude isn't reasoning in Phase 2 — it's just writing prose from a bullet list.
A template does this in <1ms instead of ~3 seconds.

### 3. Unified analysis pipeline — merge interaction_resolver into board_analyzer
**File:** `app/services/analyzer.py` (replaces both board_analyzer.py and interaction_resolver.py)

- Single entry point: `analyze(cards, event?, board?)`
- If board state provided → full board analysis (triggers, SBAs, cascade)
- If just cards provided → interaction analysis (same Claude call, simpler prompt)
- Same Claude prompt structure for both, just different context
- Deterministic post-processing always runs (layers, APNAP, SBAs)

**Why:** interaction_resolver uses fragile regex patterns that miss edge cases.
board_analyzer uses Claude which is accurate but slow. By unifying them,
interactions get the same quality as board analysis. The regex approach is deleted.

### 4. Feed rules engine context to Claude
**File:** Modified `app/services/analyzer.py`

- Before calling Claude, look up relevant rules sections based on:
  - Event type → rule sections (e.g., ETB → 603, combat → 506-510)
  - Card keywords → keyword rules (e.g., deathtouch → 702.2)
  - Board state → applicable SBA rules (704)
- Include rule text in Claude's prompt as authoritative context
- Ask Claude to cite rule numbers in trigger explanations

**Why:** Currently board_analyzer ignores the rules engine entirely. Chat uses it
for context retrieval. By feeding rules to the board analyzer's Claude call,
we get more accurate trigger identification AND rule citations in output.

### 5. Deterministic summary renderer
**File:** `app/services/summary_renderer.py`

Template structure:
```
plain_english:
  "Okay, so here's what happens..."
  For each cascade step:
    - "{card} enters the battlefield / dies / etc."
    - "This triggers {trigger_card}'s ability: {trigger_text}"
  "State-based actions check:"
    - "{creature} has {toughness} toughness and dies (rule 704.5f)"
  "Stack resolves (APNAP order):"
    - "1. {top of stack} resolves first..."
  "What does NOT trigger:"
    - "{card} didn't trigger because {reason}"
```

**Why:** Deterministic, consistent, instant. No API call needed.

### 6. Updated file structure

```
app/
  services/
    card_registry.py      # NEW: shared card cache (memory + disk)
    analyzer.py           # NEW: unified analysis (replaces board_analyzer + interaction_resolver)
    summary_renderer.py   # NEW: deterministic prose generation
    combat_simulator.py   # KEEP: deterministic combat (already good)
    chat.py               # MODIFY: use card_registry, feed rules context
    scryfall.py           # MODIFY: becomes thin HTTP layer, no caching logic
    rules_engine.py       # KEEP: add method to get rules by event type
    game_rules/           # KEEP: deterministic rules engine (already good)
      __init__.py
      state_based_actions.py
      layers.py
      stack.py
      combat.py
  models/
    card.py               # KEEP
    board.py              # KEEP
    rules.py              # KEEP
  routers/
    cards.py              # MODIFY: use card_registry
    rules.py              # KEEP
    interactions.py       # MODIFY: use unified analyzer
    board.py              # MODIFY: use unified analyzer
    chat.py               # KEEP
```

**Deleted files:**
- `app/services/board_analyzer.py` (replaced by analyzer.py)
- `app/services/interaction_resolver.py` (replaced by analyzer.py)

### 7. Performance impact

| Metric | Before | After |
|--------|--------|-------|
| Board analysis latency | ~8.5s (2 Claude calls) | ~5s (1 Claude call) |
| Interaction analysis quality | Regex (fragile) | Claude (accurate) |
| Interaction analysis latency | ~100ms | ~3s (tradeoff: accuracy) |
| Card fetch (repeated card) | Disk read | Memory read |
| Card fetch (same session) | Disk read per service | Single memory read |

### 8. Implementation order

1. CardRegistry (unblocks everything else)
2. Summary renderer (eliminates Phase 2 Claude call)
3. Unified analyzer (biggest architectural change)
4. Rules engine integration (feeds context to Claude)
5. Update routers to use new services
6. Update tests
7. Delete old files
