"""Pydantic models for API payloads and ArcGIS helpers."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class ChatMessagePart(BaseModel):
    type: Literal["text", "tool-call", "tool-result"]
    text: str | None = None
    tool_call_id: str | None = None
    tool_name: str | None = None
    args: dict[str, Any] | None = None
    result: Any = None


class ChatMessage(BaseModel):
    role: Literal["user", "assistant", "system", "tool"]
    content: str | list[ChatMessagePart] | dict[str, Any] | list[dict[str, Any]] | None = None


class ChatRequest(BaseModel):
    messages: list[ChatMessage] = Field(default_factory=list)


class CatalogLayerInfo(BaseModel):
    layer_id: int
    name: str
    geometry_type: str | None = None
    fields: list[str] = Field(default_factory=list)


class CatalogServiceEntry(BaseModel):
    path: str
    service_type: str
    layers: list[CatalogLayerInfo] = Field(default_factory=list)


class CatalogIndex(BaseModel):
    catalog_url: str
    services: list[CatalogServiceEntry] = Field(default_factory=list)
    updated_at: str | None = None
    error: str | None = None
