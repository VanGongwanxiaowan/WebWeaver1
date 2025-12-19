"""FastAPI app with SSE streaming and replay endpoints."""

from __future__ import annotations

import json
from collections.abc import Generator
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from webweaver.config import load_settings
from webweaver.events import RunEvent
from webweaver.logging import configure_logging, get_logger
from webweaver.orchestrator.runner import run_research_stream, replay_run


class RunRequest(BaseModel):
    """Run request."""

    query: str


def create_app() -> FastAPI:
    """Create FastAPI app."""

    settings = load_settings()
    configure_logging(settings.log_level)
    logger = get_logger(__name__)

    app = FastAPI(title="WebWeaver", version="0.1.0")

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/runs/stream")
    def runs_stream(req: RunRequest) -> StreamingResponse:
        logger.info("API run requested", extra={"query_len": len(req.query)})

        def gen() -> Generator[bytes, None, None]:
            for ev in run_research_stream(query=req.query, settings=settings):
                payload = json.dumps(ev.model_dump(mode="json"), ensure_ascii=False)
                yield f"data: {payload}\n\n".encode("utf-8")

        return StreamingResponse(gen(), media_type="text/event-stream")

    @app.get("/runs/{run_id}/replay")
    def runs_replay(run_id: str) -> StreamingResponse:
        logger.info("API replay requested", extra={"run_id": run_id})

        def gen() -> Generator[bytes, None, None]:
            for ev in replay_run(run_id=run_id, artifacts_dir=settings.artifacts_dir):
                payload = json.dumps(ev.model_dump(mode="json"), ensure_ascii=False)
                yield f"data: {payload}\n\n".encode("utf-8")

        return StreamingResponse(gen(), media_type="text/event-stream")

    @app.get("/runs/{run_id}/events")
    def runs_events(run_id: str) -> list[RunEvent]:
        logger.info("API events requested", extra={"run_id": run_id})
        events = list(replay_run(run_id=run_id, artifacts_dir=settings.artifacts_dir))
        if not events:
            raise HTTPException(status_code=404, detail="run not found")
        return events

    return app
