"""CORS and error handling middleware."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware


def add_middleware(app: FastAPI, debug: bool = False) -> None:
    """Add CORS middleware. In debug mode, allow Vite dev server origin."""
    origins = []
    if debug:
        origins = [
            "http://localhost:5173",
            "http://127.0.0.1:5173",
        ]

    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins if origins else ["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
