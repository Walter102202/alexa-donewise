"""FastAPI UI host and session orchestration, using MCP for every operation."""

from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import agent, scripted
from .config import USER_TIMEZONES, Settings
from .llm import make_llm, system_prompt
from .session import Session

SIM_ROOT = Path(__file__).resolve().parent.parent


class TurnInput(BaseModel):
    text: str = Field(min_length=1, max_length=10000)


class FaultInput(BaseModel):
    kind: Literal["drop_response_after_write", "ack_without_write"]
    uses: int = Field(default=1, ge=1, le=100)


class ModeInput(BaseModel):
    ui_mode: Literal["voice", "scripted"]
    timezone: Literal[USER_TIMEZONES] | None = None


def build_app(settings: Settings | None = None, *, llm=None) -> FastAPI:
    settings = settings or Settings()
    sessions = {}

    @asynccontextmanager
    async def lifespan(app):
        yield
        for session in sessions.values():
            await session.close()

    app = FastAPI(lifespan=lifespan)
    app.state.sessions = sessions

    @app.middleware("http")
    async def same_origin(request: Request, call_next):
        origin = request.headers.get("origin")
        if origin and urlsplit(origin).netloc != request.headers.get("host"):
            return JSONResponse({"error": "Origin not allowed"}, status_code=403)
        return await call_next(request)

    def get_session(session_id):
        if session_id not in sessions:
            raise HTTPException(404, "Session not found")
        return sessions[session_id]

    def launch(session, action):
        if not session.launch(action):
            raise HTTPException(409, "A turn is already running")
        return {"ok": True}

    @app.get("/")
    async def index():
        return FileResponse(SIM_ROOT / "static" / "index.html")

    async def new_session(ui_mode=None, timezone=None):
        timezone = timezone or settings.user_timezone
        model = llm or make_llm(settings, lambda: system_prompt(timezone))
        session = Session(settings, model, ui_mode, timezone)
        try:
            await session.start()
        except Exception:
            raise HTTPException(
                503, "MCP server unavailable or demo configuration invalid"
            ) from None
        sessions[session.id] = session
        return session.metadata()

    @app.post("/session")
    async def create_session(body: ModeInput | None = None):
        return await new_session(body.ui_mode if body else None, body.timezone if body else None)

    @app.post("/session/{session_id}/mode")
    async def change_mode(session_id: str, body: ModeInput):
        session = get_session(session_id)
        if session.busy:
            raise HTTPException(409, "Wait for the current action before changing mode")
        async with session.lock:
            return await new_session(body.ui_mode, body.timezone or session.timezone)

    @app.get("/session/{session_id}/events")
    async def events(session_id: str, request: Request):
        session = get_session(session_id)
        try:
            after = max(0, int(request.headers.get("last-event-id", "0")))
        except ValueError:
            raise HTTPException(400, "Invalid event cursor") from None
        return StreamingResponse(
            session.stream(after),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.get("/session/{session_id}/state")
    async def state(session_id: str):
        session = get_session(session_id)
        await session.refresh_faults()
        return {
            **session.metadata(),
            "receipts": session.receipts,
            "step": session.step,
            "busy": session.busy,
            "pending_approval": session.pending_approval["request"]
            if session.pending_approval
            else None,
        }

    @app.post("/session/{session_id}/turn")
    async def turn(session_id: str, body: TurnInput):
        session = get_session(session_id)
        if session.ui_mode == "scripted" and not (
            session.pending_approval and agent.is_affirmation(body.text)
        ):
            raise HTTPException(409, "Free input requires a new voice session")
        return launch(session, lambda: agent.turn(session, body.text))

    @app.post("/session/{session_id}/approve")
    async def approve(session_id: str):
        session = get_session(session_id)
        if not session.pending_approval:
            raise HTTPException(409, "No pending approval")
        return launch(session, lambda: agent.turn(session, "Yes, charge it."))

    @app.post("/session/{session_id}/script/next")
    async def next_step(session_id: str):
        session = get_session(session_id)
        if not settings.demo_admin_token:
            raise HTTPException(404, "Demo controls disabled")
        if session.ui_mode != "scripted":
            raise HTTPException(409, "Script controls require a new scripted session")
        if session.step >= 5:
            raise HTTPException(409, "Script complete")
        return launch(session, lambda: scripted.next_step(session))

    @app.get("/session/{session_id}/script")
    async def script_state(session_id: str):
        return {"step": get_session(session_id).step, "total": 5}

    @app.post("/session/{session_id}/faults")
    async def faults(session_id: str, body: FaultInput):
        if not settings.demo_admin_token:
            raise HTTPException(404, "Demo controls disabled")
        session = get_session(session_id)
        if session.ui_mode != "voice":
            raise HTTPException(409, "Scripted sessions arm their own faults")
        if session.busy:
            raise HTTPException(409, "Wait for the current action before arming a fault")
        expected_uses = 1 if body.kind == "drop_response_after_write" else 2
        if body.uses != expected_uses:
            raise HTTPException(400, "Use the fault preset's exact number of uses")
        async with session.lock:
            try:
                await session.arm(body.kind, body.uses)
            except RuntimeError:
                raise HTTPException(400, "Fault could not be armed") from None
        return {"ok": True, "fault_state": session.fault_state}

    app.mount("/static", StaticFiles(directory=SIM_ROOT / "static"), name="static")
    app.mount("/fixtures", StaticFiles(directory=SIM_ROOT / "fixtures"), name="fixtures")
    return app


def main():
    settings = Settings()
    uvicorn.run(build_app(settings), host="127.0.0.1", port=settings.port)


if __name__ == "__main__":
    main()
