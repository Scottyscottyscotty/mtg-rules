"""MTG Comprehensive Rules engine.

Downloads and parses the official comprehensive rules from Wizards of the Coast,
providing structured access to rule sections and keyword lookups.
"""

import re
from pathlib import Path

import httpx

from app.models.rules import KeywordAbility, Rule, RuleSection

RULES_TXT_URL = "https://media.wizards.com/2024/downloads/MagicCompRules_20241101.txt"
RULES_CACHE = Path("cache/comprehensive_rules.txt")

# Key rule sections for interaction resolution
STACK_RULES = "405"
PRIORITY_RULES = "117"
LAYER_RULES = "613"
REPLACEMENT_RULES = "614"
TRIGGERED_ABILITIES_RULES = "603"
STATE_BASED_RULES = "704"
KEYWORD_ABILITIES_RULES = "702"
CASTING_RULES = "601"


class RulesEngine:
    def __init__(self) -> None:
        self.sections: dict[str, RuleSection] = {}
        self.rules: dict[str, Rule] = {}
        self.keywords: dict[str, KeywordAbility] = {}
        self._loaded = False

    async def load(self) -> None:
        """Download and parse the comprehensive rules."""
        if self._loaded:
            return

        text = await self._get_rules_text()
        self._parse_rules(text)
        self._loaded = True

    async def _get_rules_text(self) -> str:
        RULES_CACHE.parent.mkdir(exist_ok=True)
        if RULES_CACHE.exists():
            return RULES_CACHE.read_text(encoding="utf-8", errors="replace")

        async with httpx.AsyncClient() as client:
            resp = await client.get(RULES_TXT_URL, timeout=30.0, follow_redirects=True)
            if resp.status_code == 200:
                text = resp.text
                RULES_CACHE.write_text(text, encoding="utf-8")
                return text
        return ""

    def _parse_rules(self, text: str) -> None:
        """Parse rules text into structured sections and rules."""
        # Match rule numbers like "100.1" or "702.3a"
        rule_pattern = re.compile(r"^(\d{3}\.\d+[a-z]?)\.\s+(.+)", re.MULTILINE)
        # Match section headers like "100. General"
        section_pattern = re.compile(r"^(\d{3})\.\s+(.+)", re.MULTILINE)

        current_section = None
        for line in text.split("\n"):
            line = line.strip()
            if not line:
                continue

            sec_match = section_pattern.match(line)
            if sec_match:
                num, title = sec_match.group(1), sec_match.group(2)
                # Only treat as section header if title doesn't look like a rule body
                if not re.match(r"\d", title) and len(title) < 100:
                    section = RuleSection(number=num, title=title)
                    self.sections[num] = section
                    current_section = section

            rule_match = rule_pattern.match(line)
            if rule_match:
                num, text_content = rule_match.group(1), rule_match.group(2)
                rule = Rule(number=num, text=text_content)
                self.rules[num] = rule
                if current_section:
                    current_section.rules.append(rule)

        self._extract_keywords()

    def _extract_keywords(self) -> None:
        """Extract keyword abilities from section 702."""
        for num, rule in self.rules.items():
            if num.startswith("702.") and re.match(r"702\.\d+$", num):
                # These are keyword headers like "702.2. Deathtouch"
                name = rule.text.strip()
                self.keywords[name.lower()] = KeywordAbility(
                    name=name,
                    rule_number=num,
                    description=rule.text,
                )

    def get_rule(self, number: str) -> Rule | None:
        return self.rules.get(number)

    def get_section(self, number: str) -> RuleSection | None:
        return self.sections.get(number)

    def search_rules(self, query: str, limit: int = 20) -> list[Rule]:
        """Search rules by text content."""
        query_lower = query.lower()
        results = []
        for rule in self.rules.values():
            if query_lower in rule.text.lower():
                results.append(rule)
                if len(results) >= limit:
                    break
        return results

    def get_stack_rules(self) -> list[Rule]:
        section = self.sections.get(STACK_RULES)
        return section.rules if section else []

    def get_layer_rules(self) -> list[Rule]:
        section = self.sections.get(LAYER_RULES)
        return section.rules if section else []

    def get_priority_rules(self) -> list[Rule]:
        section = self.sections.get(PRIORITY_RULES)
        return section.rules if section else []

    def get_replacement_effect_rules(self) -> list[Rule]:
        section = self.sections.get(REPLACEMENT_RULES)
        return section.rules if section else []

    def get_state_based_action_rules(self) -> list[Rule]:
        section = self.sections.get(STATE_BASED_RULES)
        return section.rules if section else []


# Singleton
rules_engine = RulesEngine()
