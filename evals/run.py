#!/usr/bin/env python3
"""Eval harness for the response validator.

Loads fixture files from evals/fixtures/, runs validate_phase1 on each,
and prints a report showing what was changed and whether expectations matched.

Usage:
    python -m evals.run                    # run all fixtures
    python -m evals.run city_on_fire       # run fixtures matching a pattern
    python -m evals.run --verbose          # show full before/after diffs
"""

import argparse
import copy
import json
import sys
from pathlib import Path

# Add project root to path so we can import app modules
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.models.card import Card  # noqa: E402
from app.services.response_validator import validate_phase1  # noqa: E402

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"

# ANSI colors
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
DIM = "\033[2m"
BOLD = "\033[1m"
RESET = "\033[0m"


def load_fixtures(pattern: str | None = None) -> list[dict]:
    """Load all .json fixture files, optionally filtered by name pattern."""
    fixtures = []
    for path in sorted(FIXTURES_DIR.glob("*.json")):
        if pattern and pattern.lower() not in path.stem.lower():
            continue
        with open(path) as f:
            data = json.load(f)
        data["_file"] = path.name
        fixtures.append(data)
    return fixtures


def build_card_data(raw: dict) -> dict[str, Card]:
    """Convert fixture card_data dicts into Card objects."""
    cards = {}
    for name, fields in raw.items():
        cards[name] = Card(**fields)
    return cards


def board_card_names(fixture: dict) -> set[str]:
    """Extract all card names from the board state."""
    names = set()
    for player in fixture["board"]["players"]:
        for perm in player.get("permanents", []):
            names.add(perm["card_name"])
    return names


def diff_section(label: str, before: list, after: list) -> list[str]:
    """Show what was added/removed in a section."""
    lines = []

    before_names = [e.get("permanent_name", "?") for e in before]
    after_names = [e.get("permanent_name", "?") for e in after]

    removed = [n for n in before_names if n not in after_names]
    added = [n for n in after_names if n not in before_names]

    if removed:
        for n in removed:
            lines.append(f"  {RED}- {label}: {n}{RESET}")
    if added:
        for n in added:
            lines.append(f"  {GREEN}+ {label}: {n}{RESET}")

    return lines


def run_fixture(fixture: dict, verbose: bool = False) -> tuple[bool, list[str]]:
    """Run a single fixture through the validator. Returns (passed, report_lines)."""
    lines = []
    name = fixture.get("name", fixture["_file"])
    lines.append(f"\n{BOLD}{name}{RESET} {DIM}({fixture['_file']}){RESET}")

    card_data = build_card_data(fixture["card_data"])
    names_on_board = board_card_names(fixture)

    # Deep copy so we can compare before/after
    phase1_before = copy.deepcopy(fixture["claude_phase1"])
    phase1 = copy.deepcopy(fixture["claude_phase1"])

    # Run validation
    result = validate_phase1(phase1, card_data, names_on_board)

    # Compute diffs
    changes = []
    for section in ("triggers", "replacement_effects", "continuous_effects", "did_not_trigger"):
        changes.extend(diff_section(section, phase1_before.get(section, []), result.get(section, [])))

    # Check warnings added
    old_warnings = set(phase1_before.get("warnings", []))
    new_warnings = set(result.get("warnings", [])) - old_warnings
    for w in new_warnings:
        changes.append(f"  {YELLOW}⚠ warning added: {w}{RESET}")

    if not changes:
        lines.append(f"  {DIM}No changes made by validator{RESET}")
    else:
        lines.extend(changes)

    # Check against expectations
    expected = fixture.get("expected_after_validation", {})
    passed = True
    checks = []

    def check(label, actual, expected_val):
        nonlocal passed
        ok = actual == expected_val
        if not ok:
            passed = False
        icon = f"{GREEN}✓{RESET}" if ok else f"{RED}✗{RESET}"
        checks.append(f"  {icon} {label}: got {actual}, expected {expected_val}")

    if "triggers_count" in expected:
        check("triggers", len(result.get("triggers", [])), expected["triggers_count"])
    if "did_not_trigger_count" in expected:
        check("did_not_trigger", len(result.get("did_not_trigger", [])), expected["did_not_trigger_count"])
    if "replacement_effects_count" in expected:
        check("replacement_effects", len(result.get("replacement_effects", [])), expected["replacement_effects_count"])
    if "warnings_added" in expected:
        check("warnings_added", len(new_warnings) > 0, expected["warnings_added"])

    lines.extend(checks)

    status = f"{GREEN}PASS{RESET}" if passed else f"{RED}FAIL{RESET}"
    lines[0] = f"{status} {lines[0].lstrip()}"

    if verbose and changes:
        lines.append(f"  {DIM}--- before ---{RESET}")
        lines.append(f"  {DIM}{json.dumps(phase1_before, indent=2)[:500]}{RESET}")
        lines.append(f"  {DIM}--- after ---{RESET}")
        lines.append(f"  {DIM}{json.dumps(result, indent=2)[:500]}{RESET}")

    return passed, lines


def main():
    parser = argparse.ArgumentParser(description="Run response validator evals")
    parser.add_argument("pattern", nargs="?", help="Filter fixtures by name")
    parser.add_argument("--verbose", "-v", action="store_true", help="Show full diffs")
    args = parser.parse_args()

    fixtures = load_fixtures(args.pattern)
    if not fixtures:
        print(f"{RED}No fixtures found{RESET}" + (f" matching '{args.pattern}'" if args.pattern else ""))
        sys.exit(1)

    print(f"\n{BOLD}Response Validator Eval Harness{RESET}")
    print(f"Running {len(fixtures)} fixture(s)...\n")
    print("─" * 60)

    total = 0
    passed = 0
    failed_names = []

    for fixture in fixtures:
        ok, lines = run_fixture(fixture, verbose=args.verbose)
        total += 1
        if ok:
            passed += 1
        else:
            failed_names.append(fixture.get("name", fixture["_file"]))
        for line in lines:
            print(line)

    print("\n" + "─" * 60)
    if passed == total:
        print(f"\n{GREEN}{BOLD}All {total} fixture(s) passed.{RESET}\n")
    else:
        print(f"\n{RED}{BOLD}{total - passed}/{total} fixture(s) failed:{RESET}")
        for name in failed_names:
            print(f"  {RED}• {name}{RESET}")
        print()

    sys.exit(0 if passed == total else 1)


if __name__ == "__main__":
    main()
