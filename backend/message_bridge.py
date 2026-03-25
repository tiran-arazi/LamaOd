"""Convert API chat messages to pydantic-ai ModelMessage history."""

from __future__ import annotations

from typing import Any

from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    ModelResponsePart,
    SystemPromptPart,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)

from models import ChatMessage, ChatMessagePart


def chat_to_model_messages(messages: list[ChatMessage]) -> list[ModelMessage]:
    out: list[ModelMessage] = []
    for msg in messages:
        if msg.role == "system":
            text = msg.content if isinstance(msg.content, str) else ""
            if text.strip():
                out.append(ModelRequest(parts=[SystemPromptPart(content=text)]))
        elif msg.role == "user":
            if isinstance(msg.content, str):
                out.append(ModelRequest(parts=[UserPromptPart(content=msg.content)]))
            elif isinstance(msg.content, list):
                texts = [p.text for p in msg.content if p.type == "text" and p.text]
                joined = "\n".join(texts)
                out.append(ModelRequest(parts=[UserPromptPart(content=joined or "(empty)")]))
        elif msg.role == "tool":
            payloads: list[dict[str, Any]] = []
            if isinstance(msg.content, dict):
                payloads = [msg.content]
            elif isinstance(msg.content, list):
                payloads = [x for x in msg.content if isinstance(x, dict)]
            tr_parts: list[ToolReturnPart] = []
            for d in payloads:
                tid = str(d.get("tool_call_id") or "")
                name = str(d.get("tool_name") or "")
                res = d.get("result")
                tr_parts.append(ToolReturnPart(tool_name=name, content=res, tool_call_id=tid))
            if tr_parts:
                out.append(ModelRequest(parts=tr_parts))
        elif msg.role == "assistant":
            if isinstance(msg.content, str) and msg.content.strip():
                out.append(ModelResponse(parts=[TextPart(content=msg.content)]))
            elif isinstance(msg.content, list):
                parts: list[ModelResponsePart] = []
                for p in msg.content:
                    if not isinstance(p, ChatMessagePart):
                        continue
                    if p.type == "text" and p.text:
                        parts.append(TextPart(content=p.text))
                    elif p.type == "tool-call":
                        parts.append(
                            ToolCallPart(
                                tool_name=p.tool_name or "",
                                args=p.args if p.args is not None else {},
                                tool_call_id=p.tool_call_id or "",
                            ),
                        )
                if parts:
                    out.append(ModelResponse(parts=parts))
    return out


def split_last_user(messages: list[ChatMessage]) -> tuple[list[ChatMessage], str]:
    if not messages:
        raise ValueError("messages empty")
    last = messages[-1]
    if last.role != "user":
        raise ValueError("last message must be user")
    if not isinstance(last.content, str) or not last.content.strip():
        raise ValueError("user message must be non-empty string")
    return messages[:-1], last.content
