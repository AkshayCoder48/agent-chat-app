"""MCP (Model Context Protocol) server CRUD endpoints.

Stored configs are loaded at chat time by :mod:`app.agents.mcp_loader`,
which spins up a pydantic-ai toolset per active server so the agent can
call the server's tools.
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
from app.db.models.user_settings import MCPServer

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/mcp-servers", tags=["mcp-servers"])


class MCPServerCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    transport: str = Field(..., description="stdio | sse | streamable_http")
    command: str | None = None
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    url: str | None = None
    headers: dict[str, str] = Field(default_factory=dict)
    is_active: bool = True


class MCPServerUpdate(BaseModel):
    name: str | None = None
    transport: str | None = None
    command: str | None = None
    args: list[str] | None = None
    env: dict[str, str] | None = None
    url: str | None = None
    headers: dict[str, str] | None = None
    is_active: bool | None = None


class MCPServerOut(BaseModel):
    id: UUID
    name: str
    transport: str
    command: str | None
    args: list[str]
    env: dict[str, str]
    url: str | None
    headers: dict[str, str]
    is_active: bool


def _to_out(row: MCPServer) -> MCPServerOut:
    return MCPServerOut(
        id=row.id,
        name=row.name,
        transport=row.transport,
        command=row.command,
        args=list(row.args or []),
        env=dict(row.env or {}),
        url=row.url,
        headers=dict(row.headers or {}),
        is_active=row.is_active,
    )


@router.get("", response_model=list[MCPServerOut])
async def list_mcp_servers(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db_session),
    active_only: bool = False,
) -> Any:
    """List the user's MCP server configurations."""
    stmt = select(MCPServer).where(MCPServer.user_id == current_user.id)
    if active_only:
        stmt = stmt.where(MCPServer.is_active.is_(True))
    stmt = stmt.order_by(MCPServer.created_at.desc())
    result = await db.execute(stmt)
    return [_to_out(r) for r in result.scalars().all()]


@router.post("", response_model=MCPServerOut, status_code=201)
async def create_mcp_server(
    payload: MCPServerCreate,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db_session),
) -> Any:
    """Add a new MCP server configuration."""
    if payload.transport not in {"stdio", "sse", "streamable_http"}:
        raise HTTPException(400, "transport must be one of: stdio, sse, streamable_http")
    if payload.transport == "stdio" and not payload.command:
        raise HTTPException(400, "stdio transport requires a command")
    if payload.transport in {"sse", "streamable_http"} and not payload.url:
        raise HTTPException(400, f"{payload.transport} transport requires a url")

    row = MCPServer(
        user_id=current_user.id,
        name=payload.name,
        transport=payload.transport,
        command=payload.command,
        args=payload.args,
        env=payload.env,
        url=payload.url,
        headers=payload.headers,
        is_active=payload.is_active,
    )
    db.add(row)
    await db.flush()
    return _to_out(row)


@router.put("/{server_id}", response_model=MCPServerOut)
async def update_mcp_server(
    server_id: UUID,
    payload: MCPServerUpdate,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db_session),
) -> Any:
    stmt = select(MCPServer).where(
        MCPServer.id == server_id, MCPServer.user_id == current_user.id
    )
    row = (await db.execute(stmt)).scalar_one_or_none()
    if row is None:
        raise HTTPException(404, "MCP server not found")

    for field in ("name", "transport", "command", "url", "is_active"):
        v = getattr(payload, field)
        if v is not None:
            setattr(row, field, v)
    if payload.args is not None:
        row.args = payload.args
    if payload.env is not None:
        row.env = payload.env
    if payload.headers is not None:
        row.headers = payload.headers
    await db.flush()
    return _to_out(row)


@router.delete("/{server_id}", status_code=204)
async def delete_mcp_server(
    server_id: UUID,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db_session),
) -> None:
    stmt = delete(MCPServer).where(
        MCPServer.id == server_id, MCPServer.user_id == current_user.id
    )
    await db.execute(stmt)


__all__ = ["router"]
