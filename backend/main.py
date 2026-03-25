"""FastAPI app: ArcGIS-backed explorer agent with SSE chat and optional static UI."""

from __future__ import annotations

import json
import logging
import os
import traceback
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic_ai import Agent, AgentRunResultEvent
from pydantic_ai.messages import (
    FunctionToolCallEvent,
    FunctionToolResultEvent,
    PartDeltaEvent,
    PartStartEvent,
    RetryPromptPart,
    TextPart,
    TextPartDelta,
    ThinkingPart,
    ThinkingPartDelta,
    ToolReturnPart,
)

from agent import build_agent, dynamic_instructions
from arcgis_catalog_indexer import ArcGISCatalogStore
from message_bridge import chat_to_model_messages, split_last_user
from models import ChatRequest
from tools.arcgis import ExplorerDeps

_root = Path(__file__).resolve().parent.parent
load_dotenv(_root / ".env")
load_dotenv(Path(__file__).resolve().parent / ".env")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434/v1")
os.environ.setdefault("OLLAMA_BASE_URL", OLLAMA_BASE_URL)

ARCGIS_CATALOG_URL = os.getenv(
    "ARCGIS_CATALOG_URL",
    "https://sampleserver6.arcgisonline.com/arcgis/rest/services",
)
# If "false", skip HTTP crawl on startup (use POST /api/catalog/reindex or scripts/reindex_arcgis_rest_catalog.py).
CATALOG_INDEX_ON_STARTUP = os.getenv("CATALOG_INDEX_ON_STARTUP", "true").lower() in ("1", "true", "yes")
FRONTEND_DIST = Path(__file__).resolve().parent.parent / "frontend" / "dist"

httpx_client: httpx.AsyncClient | None = None
catalog_store: ArcGISCatalogStore | None = None
_agent_cache: tuple[str, Agent[ExplorerDeps, str]] | None = None


def get_agent() -> Agent[ExplorerDeps, str]:
    """Build (or rebuild) the agent when OLLAMA_MODEL_SPEC changes."""
    global _agent_cache
    spec = os.getenv("OLLAMA_MODEL_SPEC", "ollama:llama3.2:3b")
    if _agent_cache is None or _agent_cache[0] != spec:
        logger.info("Using Ollama model: %s", spec)
        _agent_cache = (spec, build_agent(spec))
    return _agent_cache[1]


def _sse(obj: dict[str, Any]) -> str:
    return f"data: {json.dumps(obj, default=str, ensure_ascii=False)}\n\n"


def _serialize_tool_args(args: Any) -> Any:
    if isinstance(args, dict):
        return args
    if isinstance(args, str):
        try:
            return json.loads(args)
        except json.JSONDecodeError:
            return args
    return args


def _error_details_to_jsonable(obj: Any) -> Any:
    if isinstance(obj, list):
        out: list[Any] = []
        for item in obj:
            if isinstance(item, dict):
                out.append(item)
            elif hasattr(item, "__dict__"):
                out.append({k: v for k, v in vars(item).items() if not k.startswith("_")})
            else:
                out.append(str(item))
        return out
    return obj


def _tool_result_payload(tr: Any) -> Any:
    if isinstance(tr, RetryPromptPart):
        return _error_details_to_jsonable(tr.content) if isinstance(tr.content, list) else tr.content
    content = getattr(tr, "content", tr)
    if isinstance(content, (dict, list, str, int, float, bool)) or content is None:
        return content
    return str(content)


def _looks_like_arg_validation_errors(payload: Any) -> bool:
    if not isinstance(payload, list) or not payload:
        return False
    first = payload[0]
    return isinstance(first, dict) and "type" in first and "loc" in first and "msg" in first


def _debug_tool_result_text(result: Any) -> str | None:
    """Crude debug blob for the assistant stream (not end-user UX)."""
    if isinstance(result, RetryPromptPart):
        name = result.tool_name or "?"
        body = json.dumps(_tool_result_payload(result), indent=2, default=str)
        return f"\n[DEBUG] tool_args_validation_failed tool={name} id={result.tool_call_id}\n{body}\n"
    if isinstance(result, ToolReturnPart):
        if result.outcome != "success":
            body = json.dumps(_tool_result_payload(result), indent=2, default=str)
            return (
                f"\n[DEBUG] tool_outcome={result.outcome} tool={result.tool_name} "
                f"id={result.tool_call_id}\n{body}\n"
            )
        payload = _tool_result_payload(result)
        if _looks_like_arg_validation_errors(payload):
            body = json.dumps(payload, indent=2, default=str)
            return f"\n[DEBUG] tool_return_validation_errors tool={result.tool_name}\n{body}\n"
    return None


def _log_tool_result_summary(tool_name: str, payload: Any) -> None:
    """Compact server log line for debugging agent tool steps (avoid dumping full row payloads)."""
    if _looks_like_arg_validation_errors(payload):
        logger.warning("chat step tool_result name=%s validation_errors=%s", tool_name, payload)
        return
    if isinstance(payload, dict):
        row_count = payload.get("row_count")
        err = payload.get("arcgis_error")
        extra = f" row_count={row_count}" if row_count is not None else ""
        if err is not None:
            extra += f" arcgis_error={err!r}"
        if payload.get("exceededTransferLimit"):
            extra += " exceededTransferLimit=True"
        logger.info("chat step tool_result name=%s%s", tool_name, extra)
    else:
        logger.info("chat step tool_result name=%s (non-dict payload)", tool_name)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global httpx_client, catalog_store
    httpx_client = httpx.AsyncClient(headers={"User-Agent": "offline-ai-explorer/0.1"})
    catalog_store = ArcGISCatalogStore(ARCGIS_CATALOG_URL)
    if CATALOG_INDEX_ON_STARTUP:
        await catalog_store.refresh(httpx_client)
        logger.info(
            "ArcGIS catalog indexed once at startup: %s services",
            len(catalog_store.index.services),
        )
    else:
        logger.info(
            "ArcGIS catalog startup crawl skipped (CATALOG_INDEX_ON_STARTUP=false); "
            "run scripts/reindex_arcgis_rest_catalog.py or POST /api/catalog/reindex",
        )
    get_agent()
    yield
    if httpx_client:
        await httpx_client.aclose()
        httpx_client = None


app = FastAPI(title="Offline AI Data Explorer", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("CORS_ORIGINS", "http://127.0.0.1:5173,http://localhost:5173").split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/catalog")
async def get_catalog() -> dict[str, Any]:
    if not catalog_store:
        raise HTTPException(503, "Catalog not ready")
    return json.loads(catalog_store.index.model_dump_json())


@app.post("/api/catalog/reindex")
async def post_catalog_reindex(
    x_catalog_reindex_token: str | None = Header(default=None, alias="X-Catalog-Reindex-Token"),
) -> dict[str, Any]:
    """Re-crawl ArcGIS REST catalog (on-demand; same crawler as startup). Optional shared secret."""
    if not httpx_client or not catalog_store:
        raise HTTPException(503, "Server not ready")
    expected = os.getenv("CATALOG_REINDEX_TOKEN")
    if expected and x_catalog_reindex_token != expected:
        raise HTTPException(401, "Invalid or missing X-Catalog-Reindex-Token")
    await catalog_store.refresh(httpx_client)
    return {
        "ok": True,
        "services": len(catalog_store.index.services),
        "updated_at": catalog_store.index.updated_at,
        "error": catalog_store.index.error,
    }


async def _stream_chat(body: ChatRequest) -> AsyncIterator[str]:
    if not httpx_client or not catalog_store:
        yield _sse({"type": "error", "message": "Server not ready"})
        return
    try:
        prior, user_text = split_last_user(body.messages)
    except ValueError as e:
        yield _sse({"type": "error", "message": str(e)})
        return

    history = chat_to_model_messages(prior)
    deps = ExplorerDeps(
        catalog_root=ARCGIS_CATALOG_URL,
        client=httpx_client,
        catalog=catalog_store,
    )
    instructions = dynamic_instructions(catalog_store.prompt_summary())
    preview = user_text.strip().replace("\n", " ")[:120]
    logger.info("chat run start user_preview=%r", preview)

    try:
        async for event in get_agent().run_stream_events(
            user_text,
            message_history=history,
            deps=deps,
            instructions=instructions,
        ):
            # PartStartEvent carries the first chunk of a text part (and often the *entire* final
            # assistant message after tool calls when the provider does not emit further deltas).
            if isinstance(event, PartStartEvent) and isinstance(event.part, TextPart):
                if event.part.content:
                    yield _sse({"type": "text_delta", "text": event.part.content})
            elif isinstance(event, PartStartEvent) and isinstance(event.part, ThinkingPart):
                # Ollama / LFM2 often stream chain-of-thought in `reasoning`, mapped to ThinkingPart;
                # we forward it as text so the UI is not stuck with a stray visible `content` token (e.g. "A").
                if event.part.content:
                    yield _sse({"type": "text_delta", "text": event.part.content})
            elif isinstance(event, PartDeltaEvent) and isinstance(event.delta, TextPartDelta):
                yield _sse({"type": "text_delta", "text": event.delta.content_delta})
            elif isinstance(event, PartDeltaEvent) and isinstance(event.delta, ThinkingPartDelta):
                d = event.delta.content_delta
                if d:
                    yield _sse({"type": "text_delta", "text": d})
            elif isinstance(event, FunctionToolCallEvent):
                part = event.part
                args = _serialize_tool_args(part.args)
                logger.info("chat step tool_call name=%s args=%s", part.tool_name, args)
                yield _sse(
                    {
                        "type": "tool_call",
                        "tool_call_id": part.tool_call_id,
                        "tool_name": part.tool_name,
                        "args": args,
                    },
                )
            elif isinstance(event, FunctionToolResultEvent):
                tr = event.result
                payload = _tool_result_payload(tr)
                dbg = _debug_tool_result_text(tr)
                if dbg:
                    yield _sse({"type": "text_delta", "text": dbg})
                _log_tool_result_summary(getattr(tr, "tool_name", None) or "?", payload)
                yield _sse(
                    {
                        "type": "tool_result",
                        "tool_call_id": tr.tool_call_id,
                        "tool_name": getattr(tr, "tool_name", None) or "",
                        "result": payload,
                    },
                )
            elif isinstance(event, AgentRunResultEvent):
                yield _sse({"type": "done"})
    except Exception as exc:  # noqa: BLE001
        logger.exception("Chat stream failed")
        yield _sse(
            {
                "type": "error",
                "message": str(exc),
                "traceback": traceback.format_exc(),
            },
        )


@app.post("/api/chat")
async def chat(body: ChatRequest) -> StreamingResponse:
    return StreamingResponse(
        _stream_chat(body),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


if FRONTEND_DIST.is_dir():
    from fastapi.staticfiles import StaticFiles

    app.mount("/", StaticFiles(directory=FRONTEND_DIST, html=True), name="ui")
