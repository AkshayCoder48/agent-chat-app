"""Custom tools CRUD endpoints.

A custom tool is a user-defined function the agent can call. Two flavours:

  * ``http_webhook`` — POST the tool args as JSON to a URL, return the
    response body as the tool result.
  * ``python_snippet`` — run a Python source snippet in the sandbox; the
    snippet receives the args as kwargs and ``return``s a value.

At chat time, :mod:`app.agents.custom_tools_loader` reads active tools and
registers them on the agent via ``@agent.tool``.
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, get_db_session
from app.db.models.user_settings import CustomTool

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/custom-tools", tags=["custom-tools"])


class CustomToolCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=128, pattern=r"^[a-z_][a-z0-9_]*$")
    description: str = Field(..., min_length=1)
    parameters_schema: dict = Field(default_factory=dict)
    impl_kind: str = "http_webhook"
    http_url: str | None = None
    http_headers: dict[str, str] = Field(default_factory=dict)
    python_source: str | None = None
    is_active: bool = True


class CustomToolUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    parameters_schema: dict | None = None
    impl_kind: str | None = None
    http_url: str | None = None
    http_headers: dict[str, str] | None = None
    python_source: str | None = None
    is_active: bool | None = None


class CustomToolOut(BaseModel):
    id: UUID
    name: str
    description: str
    parameters_schema: dict
    impl_kind: str
    http_url: str | None
    http_headers: dict[str, str]
    python_source: str | None
    is_active: bool


def _to_out(row: CustomTool) -> CustomToolOut:
    return CustomToolOut(
        id=row.id,
        name=row.name,
        description=row.description,
        parameters_schema=dict(row.parameters_schema or {}),
        impl_kind=row.impl_kind,
        http_url=row.http_url,
        http_headers=dict(row.http_headers or {}),
        python_source=row.python_source,
        is_active=row.is_active,
    )


@router.get("", response_model=list[CustomToolOut])
async def list_custom_tools(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db_session),
    active_only: bool = False,
) -> Any:
    stmt = select(CustomTool).where(CustomTool.user_id == current_user.id)
    if active_only:
        stmt = stmt.where(CustomTool.is_active.is_(True))
    stmt = stmt.order_by(CustomTool.created_at.desc())
    result = await db.execute(stmt)
    return [_to_out(r) for r in result.scalars().all()]


@router.post("", response_model=CustomToolOut, status_code=201)
async def create_custom_tool(
    payload: CustomToolCreate,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db_session),
) -> Any:
    if payload.impl_kind not in {"http_webhook", "python_snippet"}:
        raise HTTPException(400, "impl_kind must be one of: http_webhook, python_snippet")
    if payload.impl_kind == "http_webhook" and not payload.http_url:
        raise HTTPException(400, "http_webhook impl requires http_url")
    if payload.impl_kind == "python_snippet" and not payload.python_source:
        raise HTTPException(400, "python_snippet impl requires python_source")

    # Uniqueness check (the DB also enforces it).
    existing = await db.execute(
        select(CustomTool).where(
            CustomTool.user_id == current_user.id, CustomTool.name == payload.name
        )
    )
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(409, f"A tool named {payload.name!r} already exists")

    row = CustomTool(
        user_id=current_user.id,
        name=payload.name,
        description=payload.description,
        parameters_schema=payload.parameters_schema,
        impl_kind=payload.impl_kind,
        http_url=payload.http_url,
        http_headers=payload.http_headers,
        python_source=payload.python_source,
        is_active=payload.is_active,
    )
    db.add(row)
    await db.flush()
    return _to_out(row)


@router.put("/{tool_id}", response_model=CustomToolOut)
async def update_custom_tool(
    tool_id: UUID,
    payload: CustomToolUpdate,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db_session),
) -> Any:
    stmt = select(CustomTool).where(
        CustomTool.id == tool_id, CustomTool.user_id == current_user.id
    )
    row = (await db.execute(stmt)).scalar_one_or_none()
    if row is None:
        raise HTTPException(404, "Custom tool not found")

    for field in (
        "name", "description", "parameters_schema", "impl_kind",
        "http_url", "http_headers", "python_source", "is_active",
    ):
        v = getattr(payload, field)
        if v is not None:
            setattr(row, field, v)
    await db.flush()
    return _to_out(row)


@router.delete("/{tool_id}", status_code=204)
async def delete_custom_tool(
    tool_id: UUID,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db_session),
) -> None:
    stmt = delete(CustomTool).where(
        CustomTool.id == tool_id, CustomTool.user_id == current_user.id
    )
    await db.execute(stmt)


# ------------------------------------------------------------------ catalog
# A tiny built-in catalog of "starter" tools the user can install with one
# click. Each entry mirrors the schema of :class:`CustomToolCreate` so the
# frontend can POST it straight to ``/custom-tools``.

_BUILTIN_CATALOG: list[dict[str, Any]] = [
    {
        "name": "get_weather",
        "description": "Get the current weather for a city. Free OpenWeather-like API.",
        "parameters_schema": {
            "type": "object",
            "properties": {"city": {"type": "string"}},
            "required": ["city"],
        },
        "impl_kind": "http_webhook",
        "http_url": "https://wttr.in/{city}?format=3",
        "http_headers": {},
        "python_source": None,
    },
    {
        "name": "random_joke",
        "description": "Return a random short joke from the official Joke API.",
        "parameters_schema": {"type": "object", "properties": {}},
        "impl_kind": "http_webhook",
        "http_url": "https://official-joke-api.appspot.com/random_joke",
        "http_headers": {},
        "python_source": None,
    },
    {
        "name": "word_count",
        "description": "Count words in the given text using a Python snippet.",
        "parameters_schema": {
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        },
        "impl_kind": "python_snippet",
        "http_url": None,
        "http_headers": {},
        "python_source": "return {'count': len(text.split())}",
    },
]


@router.get("/catalog", response_model=list[dict[str, Any]])
async def list_catalog(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db_session),
) -> Any:
    """Return the built-in custom-tool catalog (with installation state).

    Each entry is the tool definition plus an ``installed`` boolean.
    """
    installed_stmt = select(CustomTool.name).where(CustomTool.user_id == current_user.id)
    installed = {(await db.execute(installed_stmt)).scalars().all()}
    return [{**entry, "installed": entry["name"] in installed} for entry in _BUILTIN_CATALOG]


__all__ = ["router"]
