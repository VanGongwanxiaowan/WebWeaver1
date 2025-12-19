"""Uvicorn server launcher.

Console scripts must point to a callable, not an ASGI app object.
"""

from __future__ import annotations

from typing import Annotated

import uvicorn

import typer


def main(
    host: Annotated[str, typer.Option("0.0.0.0", help="Bind host")] = "0.0.0.0",
    port: Annotated[int, typer.Option(8000, help="Bind port")] = 8000,
    reload: Annotated[bool, typer.Option(False, help="Enable auto-reload (dev)")] = False,
) -> None:
    """Start the WebWeaver API server."""

    uvicorn.run(
        "webweaver.api.main:app",
        host=host,
        port=port,
        reload=reload,
        log_level="info",
    )


if __name__ == "__main__":
    typer.run(main)
