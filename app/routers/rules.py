"""Rules lookup and search endpoints."""

from fastapi import APIRouter, HTTPException

from app.models.rules import Rule, RuleSection
from app.services.rules_engine import rules_engine

router = APIRouter(prefix="/api/rules", tags=["rules"])


@router.get("/section/{number}", response_model=RuleSection)
async def get_section(number: str):
    """Get a rules section by number (e.g. '613' for layers)."""
    section = rules_engine.get_section(number)
    if not section:
        raise HTTPException(status_code=404, detail=f"Section not found: {number}")
    return section


@router.get("/rule/{number}", response_model=Rule)
async def get_rule(number: str):
    """Get a specific rule by number (e.g. '613.1')."""
    rule = rules_engine.get_rule(number)
    if not rule:
        raise HTTPException(status_code=404, detail=f"Rule not found: {number}")
    return rule


@router.get("/search", response_model=list[Rule])
async def search_rules(q: str, limit: int = 20):
    """Search rules text for a keyword or phrase."""
    return rules_engine.search_rules(q, limit=min(limit, 50))
