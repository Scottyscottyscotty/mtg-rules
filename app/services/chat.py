"""Conversational rules chat powered by Claude API.

Flow:
1. User asks a question (e.g., "what does poison do?")
2. We extract card names and rules keywords from the question
3. Fetch relevant rules from the comprehensive rules engine
4. Fetch relevant card data/rulings from Scryfall
5. Send everything to Claude as context with the user's question
6. Return Claude's answer
"""

import os
import re

import anthropic

from app.services.rules_engine import rules_engine
from app.services.scryfall import fetch_card

SYSTEM_PROMPT = """You are an expert Magic: The Gathering rules advisor. You have \
deep knowledge of the comprehensive rules, card interactions, the stack, priority, \
the layer system, replacement effects, state-based actions, and all keyword abilities.

You will be provided with relevant rules text and card rulings as context. Use them \
to give accurate, authoritative answers. Always cite specific rule numbers when relevant \
(e.g., "per rule 704.5j"). If the context doesn't contain enough information to fully \
answer, say so and give your best understanding.

Keep answers clear and concise. Use examples when they help clarify. If a question \
involves a specific interaction, walk through it step by step.

Format rules references in bold when citing them."""

# Keywords that suggest the user is asking about specific rules topics
RULES_TOPIC_KEYWORDS = {
    "stack": ["405"],
    "priority": ["117"],
    "layers": ["613"],
    "layer": ["613"],
    "replacement": ["614"],
    "state-based": ["704"],
    "sba": ["704"],
    "triggered": ["603"],
    "trigger": ["603"],
    "cast": ["601"],
    "casting": ["601"],
    "combat": ["506", "507", "508", "509", "510"],
    "attack": ["508"],
    "block": ["509"],
    "damage": ["120"],
    "trample": ["702.19"],
    "deathtouch": ["702.2"],
    "first strike": ["702.7"],
    "flying": ["702.9"],
    "haste": ["702.10"],
    "hexproof": ["702.11"],
    "indestructible": ["702.12"],
    "lifelink": ["702.15"],
    "reach": ["702.17"],
    "vigilance": ["702.20"],
    "flash": ["702.8"],
    "menace": ["702.110"],
    "ward": ["702.21"],
    "protection": ["702.16"],
    "poison": ["704.5c", "702.69"],
    "infect": ["702.89"],
    "toxic": ["702.164"],
    "legend": ["704.5j"],
    "legendary": ["704.5j"],
    "planeswalker": ["306", "704.5j"],
    "token": ["111"],
    "copy": ["707"],
    "counter": ["701.5"],
    "counters": ["122"],
    "mana": ["106"],
    "color": ["105"],
    "commander": ["903"],
    "mulligan": ["103.5"],
    "companion": ["702.139"],
}


async def chat(
    question: str,
    history: list[dict[str, str]] | None = None,
) -> str:
    """Answer an MTG rules question using retrieved context + Claude."""
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        raise ValueError(
            "ANTHROPIC_API_KEY environment variable is not set. "
            "Set it to use the rules chat feature."
        )

    # Build context from rules + card data
    context = await _build_context(question)

    # Build messages
    messages = []
    if history:
        for msg in history[-10:]:  # Keep last 10 messages for context
            messages.append(msg)
    messages.append({
        "role": "user",
        "content": _format_user_message(question, context),
    })

    client = anthropic.AsyncAnthropic(api_key=api_key)
    response = await client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=1500,
        system=SYSTEM_PROMPT,
        messages=messages,
    )

    return response.content[0].text


async def _build_context(question: str) -> str:
    """Retrieve relevant rules and card data for the question."""
    parts = []

    # 1. Search for relevant rules by topic keywords
    question_lower = question.lower()
    searched_sections = set()
    for keyword, sections in RULES_TOPIC_KEYWORDS.items():
        if keyword in question_lower:
            for section_num in sections:
                if section_num in searched_sections:
                    continue
                searched_sections.add(section_num)
                section = rules_engine.get_section(section_num)
                if section:
                    rules_text = "\n".join(
                        f"  {r.number}. {r.text}"
                        for r in section.rules[:15]
                    )
                    parts.append(
                        f"Rules Section {section.number} — {section.title}:\n{rules_text}"
                    )
                # Also try as a specific rule number
                rule = rules_engine.get_rule(section_num)
                if rule:
                    parts.append(f"Rule {rule.number}: {rule.text}")

    # 2. Full-text search the rules for question keywords
    search_terms = _extract_search_terms(question)
    for term in search_terms[:3]:
        results = rules_engine.search_rules(term, limit=5)
        if results:
            rules_text = "\n".join(
                f"  {r.number}. {r.text}" for r in results
            )
            parts.append(f"Rules matching '{term}':\n{rules_text}")

    # 3. Try to find card names in the question and fetch their data
    card_names = _extract_potential_card_names(question)
    for name in card_names[:3]:
        card = await fetch_card(name)
        if card:
            card_info = f"Card: {card.name}\n"
            card_info += f"  Type: {card.type_line}\n"
            if card.oracle_text:
                card_info += f"  Oracle text: {card.oracle_text}\n"
            if card.keywords:
                card_info += f"  Keywords: {', '.join(card.keywords)}\n"
            if card.rulings:
                card_info += "  Rulings:\n"
                for ruling in card.rulings[:5]:
                    card_info += f"    - {ruling}\n"
            parts.append(card_info)

    return "\n\n".join(parts) if parts else "No specific rules context found."


def _extract_search_terms(question: str) -> list[str]:
    """Extract meaningful search terms from a question."""
    # Remove common stop words
    stop_words = {
        "what", "does", "do", "is", "it", "the", "a", "an", "in", "on",
        "for", "to", "of", "and", "or", "how", "can", "if", "when", "are",
        "that", "this", "with", "from", "my", "i", "me", "you", "again",
        "legal", "work", "works", "happen", "happens", "board", "game",
        "would", "could", "should", "about", "does", "have", "has",
    }
    words = re.findall(r"[a-zA-Z]+", question.lower())
    terms = [w for w in words if w not in stop_words and len(w) > 2]
    return terms


def _extract_potential_card_names(question: str) -> list[str]:
    """Try to extract card names from a question.

    Looks for quoted strings or capitalized multi-word phrases that
    might be card names.
    """
    names = []

    # Quoted strings are most likely card names
    quoted = re.findall(r'"([^"]+)"', question)
    names.extend(quoted)
    quoted_single = re.findall(r"'([^']+)'", question)
    names.extend(quoted_single)

    # Capitalized phrases (2+ words starting with caps) might be card names
    # e.g., "Lightning Bolt", "Rhystic Study"
    cap_phrases = re.findall(r"(?:[A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)", question)
    names.extend(cap_phrases)

    return names


def _format_user_message(question: str, context: str) -> str:
    """Format the user's question with retrieved context."""
    if context and context != "No specific rules context found.":
        return (
            f"Context (retrieved rules and card data):\n"
            f"---\n{context}\n---\n\n"
            f"Question: {question}"
        )
    return question
