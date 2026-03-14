"""MTG Rules App — FastAPI application."""

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.routers import board, cards, chat, interactions, rules
from app.services.rules_engine import rules_engine


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Load comprehensive rules on startup."""
    await rules_engine.load()
    yield


app = FastAPI(
    title="MTG Rules Engine",
    description="Magic: The Gathering rules lookup and interaction analyzer",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(cards.router)
app.include_router(rules.router)
app.include_router(interactions.router)
app.include_router(board.router)
app.include_router(chat.router)
app.mount("/static", StaticFiles(directory="static"), name="static")

templates = Jinja2Templates(directory="templates")


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse(request, "index.html")
