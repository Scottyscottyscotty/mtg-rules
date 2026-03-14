"""Conversational rules chat endpoint."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.services.chat import chat

router = APIRouter(prefix="/api/chat", tags=["chat"])


class ChatMessage(BaseModel):
    role: str  # "user" or "assistant"
    content: str


class ChatRequest(BaseModel):
    question: str
    history: list[ChatMessage] = []


class ChatResponse(BaseModel):
    answer: str


@router.post("/ask", response_model=ChatResponse)
async def ask(request: ChatRequest):
    """Ask a rules question. Supports conversation history for follow-ups.

    Send previous messages in `history` to enable contextual follow-ups
    like "what about in commander?" after asking about a rule.
    """
    if not request.question.strip():
        raise HTTPException(status_code=400, detail="Question cannot be empty.")

    try:
        history = [
            {"role": msg.role, "content": msg.content}
            for msg in request.history
        ]
        answer = await chat(request.question, history=history)
        return ChatResponse(answer=answer)
    except ValueError as e:
        raise HTTPException(status_code=503, detail=str(e))
