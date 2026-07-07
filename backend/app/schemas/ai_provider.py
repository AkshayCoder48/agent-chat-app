"""Pydantic schemas for the AIProvider model."""

from __future__ import annotations

import uuid
from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field, HttpUrl


class AIProviderBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    base_url: str = Field(..., min_length=1, max_length=512)
    models: list[str] = Field(default_factory=list)
    is_active: bool = True


class AIProviderCreate(AIProviderBase):
    # Optional — local providers like Ollama don't need one.
    api_key: str | None = None


class AIProviderUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=128)
    base_url: str | None = Field(None, min_length=1, max_length=512)
    api_key: str | None = None
    models: list[str] | None = None
    is_active: bool | None = None


class AIProviderRead(AIProviderBase):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    user_id: uuid.UUID
    # Never expose the encrypted api_key. has_api_key tells the UI whether
    # one is configured without leaking it.
    has_api_key: bool = False
    created_at: datetime
    updated_at: datetime


class AIProviderList(BaseModel):
    items: list[AIProviderRead]
    total: int


class AIProviderTestResult(BaseModel):
    ok: bool
    status_code: int | None = None
    detail: str | None = None
    sample_response: str | None = None
