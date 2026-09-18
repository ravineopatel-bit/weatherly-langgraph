"""Web interface for the existing Python LangGraph agent."""
import base64
import logging
import os
import secrets
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from langchain_core.messages import HumanMessage
from pydantic import BaseModel, Field

from weather_agent import build_agent

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")
app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")
SESSION_TTL = 3600
sessions = {}
store_lock = threading.Lock()
capacity = threading.BoundedSemaphore(4)
agent = None
agent_lock = threading.Lock()


@dataclass
class ChatSession:
    messages: list = field(default_factory=list)
    touched: float = field(default_factory=time.monotonic)
    last_request: float = 0
    turns: int = 0
    lock: threading.Lock = field(default_factory=threading.Lock)


@app.middleware("http")
async def protect(request: Request, call_next):
    password = os.getenv("APP_PASSWORD", "")
    if request.url.path != "/healthz":
        if os.getenv("RENDER") and not password:
            return JSONResponse({"detail": "Set APP_PASSWORD in the hosting environment."}, status_code=503)
        if password:
            try:
                scheme, encoded = request.headers.get("authorization", "").split(" ", 1)
                username, supplied = base64.b64decode(encoded, validate=True).decode().split(":", 1)
                valid = scheme.lower() == "basic" and secrets.compare_digest(username, "weather") and secrets.compare_digest(supplied.encode(), password.encode())
            except (ValueError, UnicodeError):
                valid = False
            if not valid:
                return Response(status_code=401, headers={"WWW-Authenticate": 'Basic realm="Weather agent"'})
        if request.method == "POST":
            origin = request.headers.get("origin")
            if origin and urlsplit(origin).netloc != request.headers.get("host"):
                return JSONResponse({"detail": "Request origin is not allowed."}, status_code=403)
            if request.headers.get("sec-fetch-site") == "cross-site":
                return JSONResponse({"detail": "Cross-site request is not allowed."}, status_code=403)
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "same-origin"
    response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
    response.headers["Cache-Control"] = "no-store"
    return response


def get_session(request, response):
    now = time.monotonic()
    with store_lock:
        expired = [key for key, value in sessions.items() if now - value.touched > SESSION_TTL and not value.lock.locked()]
        for key in expired:
            del sessions[key]
        key = request.cookies.get("weather_session")
        if key not in sessions:
            if len(sessions) >= 200:
                raise HTTPException(503, "The weather agent is busy. Please try again later.")
            key = secrets.token_urlsafe(32)
            sessions[key] = ChatSession()
        session = sessions[key]
        session.touched = now
    response.set_cookie("weather_session", key, httponly=True, samesite="strict",
                        secure=bool(os.getenv("RENDER")) or request.url.scheme == "https", max_age=SESSION_TTL)
    return session


@app.get("/")
def index():
    return FileResponse(ROOT / "static" / "index.html")


@app.get("/healthz")
def health():
    return {"status": "ok"}


@app.get("/api/session")
def session_status(request: Request, response: Response):
    session = get_session(request, response)
    return {"configured": bool(os.getenv("OPENAI_API_KEY")), "turns": session.turns}


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)


@app.post("/api/chat")
def chat(body: ChatRequest, request: Request, response: Response):
    global agent
    question = body.message.strip()
    if not question:
        raise HTTPException(422, "Enter a weather question.")
    session = get_session(request, response)
    if not session.lock.acquire(blocking=False):
        raise HTTPException(429, "Wait for your current answer before sending another question.")
    acquired = False
    try:
        if time.monotonic() - session.last_request < 3:
            raise HTTPException(429, "Please wait a few seconds before trying again.")
        if session.turns >= 20:
            raise HTTPException(409, "Start a new chat to continue after 20 questions.")
        if not os.getenv("OPENAI_API_KEY"):
            raise HTTPException(503, "Add OPENAI_API_KEY to the server environment, then restart the app.")
        acquired = capacity.acquire(blocking=False)
        if not acquired:
            raise HTTPException(503, "The weather agent is busy. Please try again shortly.")
        session.last_request = time.monotonic()
        with agent_lock:
            if agent is None:
                agent = build_agent()
        result = agent.invoke({"messages": [*session.messages, HumanMessage(content=question)]},
                              config={"recursion_limit": 16})
        content = result["messages"][-1].content
        if isinstance(content, list):
            content = "\n".join(part.get("text", "") for part in content if isinstance(part, dict))
        session.messages = result["messages"]
        session.turns += 1
        session.touched = time.monotonic()
        return {"answer": content or "No answer returned. Please try again."}
    except HTTPException:
        raise
    except Exception as exc:
        logging.warning("Weather request failed: %s", type(exc).__name__)
        raise HTTPException(502, "Could not get an answer. Please try again. If this continues, check the server API key, model access and quota.") from None
    finally:
        if acquired:
            capacity.release()
        session.lock.release()


@app.post("/api/reset")
def reset(request: Request, response: Response):
    session = get_session(request, response)
    if not session.lock.acquire(blocking=False):
        raise HTTPException(409, "Wait for the current answer before starting a new chat.")
    try:
        session.messages = []
        session.turns = 0
        return {"status": "ok"}
    finally:
        session.lock.release()
