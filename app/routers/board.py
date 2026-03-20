"""Board state analysis and combat simulation endpoints."""

from fastapi import APIRouter, HTTPException

from app.models.board import (
    BoardAnalysisRequest,
    BoardAnalysisResult,
    CombatSimRequest,
    CombatSimResult,
    CombatDamageEvent,
)
from app.services.board_analyzer import analyze_board_event
from app.services.combat_simulator import simulate_combat

router = APIRouter(prefix="/api/board", tags=["board"])


@router.post("/analyze", response_model=BoardAnalysisResult)
async def analyze(request: BoardAnalysisRequest):
    """Analyze what happens when a game event occurs on a board state.

    Provide the full board state (all players and their permanents) plus
    the event that is happening. Returns the full cascade of triggers,
    replacement effects, stack ordering (APNAP), and a summary.
    """
    if not request.board.players:
        raise HTTPException(
            status_code=400,
            detail="Board must have at least one player.",
        )
    if len(request.board.players) > 6:
        raise HTTPException(
            status_code=400,
            detail="Maximum 6 players supported.",
        )

    result = await analyze_board_event(request)
    return result


@router.post("/combat", response_model=CombatSimResult)
async def combat(request: CombatSimRequest):
    """Simulate combat damage resolution.

    Provide attackers with their ordered blockers. The engine handles:
    first strike/double strike, trample, deathtouch, lifelink, and
    determines which creatures die and how much damage players take.
    """
    if not request.assignments:
        raise HTTPException(
            status_code=400,
            detail="At least one attacker is required.",
        )
    if len(request.assignments) > 20:
        raise HTTPException(
            status_code=400,
            detail="Maximum 20 attackers supported.",
        )

    result = await simulate_combat(request)
    return result
