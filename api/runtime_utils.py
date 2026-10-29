from __future__ import annotations

import os
from datetime import datetime
from datetime import timezone
from pathlib import Path
from typing import Any

from fastapi.encoders import jsonable_encoder
from google.adk.sessions import BaseSessionService
from google.adk.sessions import DatabaseSessionService


DEFAULT_DB_SCHEMA = "adk_store"
DEFAULT_SQLITE_PATH = Path(__file__).resolve().parent / ".adk" / "session.db"
DEFAULT_DATABASE_URL_ENVS = (
    "ADK_WORKBENCH_DATABASE_URL",
    "ADK_DEMO_DATABASE_URL",
    "DATABASE_URL",
)
DEFAULT_DB_SCHEMA_ENVS = (
    "ADK_WORKBENCH_DB_SCHEMA",
    "ADK_DEMO_DB_SCHEMA",
)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def iso_from_timestamp(timestamp: float | None) -> str | None:
    if not timestamp:
        return None
    return datetime.fromtimestamp(timestamp, timezone.utc).isoformat()


def normalize_postgres_url(db_url: str) -> str:
    if db_url.startswith("postgresql://"):
        return db_url.replace("postgresql://", "postgresql+asyncpg://", 1)
    if db_url.startswith("postgres://"):
        return db_url.replace("postgres://", "postgresql+asyncpg://", 1)
    return db_url


def _first_env_value(names: tuple[str, ...]) -> str | None:
    for name in names:
        value = os.getenv(name)
        if value:
            return value
    return None


def build_session_service(
    *,
    database_url_envs: tuple[str, ...] = DEFAULT_DATABASE_URL_ENVS,
    schema_envs: tuple[str, ...] = DEFAULT_DB_SCHEMA_ENVS,
    sqlite_path: Path = DEFAULT_SQLITE_PATH,
    default_db_schema: str = DEFAULT_DB_SCHEMA,
) -> BaseSessionService:
    sqlite_path.parent.mkdir(parents=True, exist_ok=True)
    default_db_url = f"sqlite+aiosqlite:///{sqlite_path}"
    db_url = _first_env_value(database_url_envs) or default_db_url
    db_schema = _first_env_value(schema_envs) or default_db_schema
    db_url = normalize_postgres_url(db_url)

    kwargs: dict[str, Any] = {}
    if db_url.startswith("postgresql+asyncpg://") and db_schema:
        kwargs["connect_args"] = {"server_settings": {"search_path": db_schema}}
    return DatabaseSessionService(db_url=db_url, **kwargs)


def content_text(event: Any) -> str | None:
    if not event.content or not event.content.parts:
        return None
    text_parts = [part.text for part in event.content.parts if part.text]
    return "".join(text_parts) if text_parts else None


def event_to_record(event: Any) -> dict[str, Any]:
    node_path = event.node_info.path if event.node_info else ""
    actions = getattr(event, "actions", None)
    record: dict[str, Any] = {
        "id": event.id,
        "timestamp": iso_from_timestamp(event.timestamp),
        "author": event.author,
        "node_path": node_path,
        "error_code": getattr(event, "error_code", None),
        "error_message": getattr(event, "error_message", None),
        "message": content_text(event),
        "output": getattr(event, "output", None),
        "state_delta": dict(getattr(actions, "state_delta", {}) or {}),
        "long_running_tool_ids": list(
            getattr(event, "long_running_tool_ids", None) or []
        ),
        "function_call": None,
        "function_response": None,
    }
    if event.content and event.content.parts:
        for part in event.content.parts:
            if part.function_call:
                record["function_call"] = {
                    "id": part.function_call.id,
                    "name": part.function_call.name,
                    "args": jsonable_encoder(part.function_call.args),
                }
            if part.function_response:
                record["function_response"] = {
                    "id": part.function_response.id,
                    "name": part.function_response.name,
                    "response": jsonable_encoder(part.function_response.response),
                }
    return jsonable_encoder(record)


def is_mapping(value: Any) -> bool:
    return isinstance(value, dict)
