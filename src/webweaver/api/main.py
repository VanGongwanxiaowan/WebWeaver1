"""Uvicorn entrypoint."""

from __future__ import annotations

from webweaver.api.app import create_app

app = create_app()
