"""Test ASGI app with real auth router, real PostgreSQL, trusted injected clock."""

import os
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from apps.api.authentication.csrf import configured_origins
from apps.api.authentication.mfa import MfaService
from apps.api.authentication.sessions import SessionService
from apps.api.authentication.storage import PostgresAccessStore
from apps.api.routers.authentication import router


def create_app():
    app = FastAPI()
    app.include_router(router, prefix="/v1/auth")
    store = PostgresAccessStore(
        os.environ["CISSTAT_AUTH_TEST_DSN"],
        schema=os.environ["CISSTAT_AUTH_WIRE_SCHEMA"],
    )

    def clock():
        return datetime.fromisoformat(
            Path(os.environ["CISSTAT_AUTH_WIRE_CLOCK"]).read_text()
        )

    app.state.auth_access_store = store
    app.state.auth_session_service = SessionService(store, clock=clock)
    app.state.auth_mfa_service = MfaService(store, clock=clock)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=sorted(configured_origins()),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    return app
