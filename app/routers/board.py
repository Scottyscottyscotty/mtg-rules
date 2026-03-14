"""Board state analysis endpoints."""

from fastapi import APIRouter, HTTPException

from app.models.board import BoardAnalysisRequest, BoardAnalysisResult
from app.services.board_analyzer import analyze_board_event

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
