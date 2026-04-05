"""FastAPI app: ArcGIS-backed explorer agent with SSE chat and optional static UI."""

from __future__ import annotations

import json
import logging
import os
import re
import traceback
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator

import httpx
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

import config

from agent import (
    RouteDecision,
    build_conversation_agent,
    build_esri_agent,
    build_router_agent,
    build_tnufa_agent,
    build_unknown_data_agent,
    esri_dynamic_instructions,
)
from arcgis_catalog_indexer import ArcGISCatalogStore
from catalog_rag import CatalogRAG
from message_bridge import chat_to_model_messages, split_last_user
from rag_registry import register_rag_layers
from models import ChatRequest
from tools.arcgis import ExplorerDeps
from tools.tnufa import TnufaDeps

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

FRONTEND_DIST = Path(__file__).resolve().parent.parent / "frontend" / "dist"

httpx_client: httpx.AsyncClient | None = None
catalog_store: ArcGISCatalogStore | None = None
catalog_rag: CatalogRAG | None = None

RAG_CONFIDENCE_THRESHOLD = 0.55

_router_cache: tuple[str, Agent[None, RouteDecision]] | None = None
_esri_cache: tuple[str, Agent[ExplorerDeps, str]] | None = None
_conversation_cache: tuple[str, Agent[None, str]] | None = None
_tnufa_cache: tuple[str, Agent[TnufaDeps, str]] | None = None
_unknown_data_cache: tuple[str, Agent[None, str]] | None = None


def _current_spec() -> str:
    return config.OLLAMA_MODEL_SPEC


def get_router_agent() -> Agent[None, RouteDecision]:
    global _router_cache
    spec = _current_spec()
    if _router_cache is None or _router_cache[0] != spec:
        logger.info("Building router agent with model: %s", spec)
        _router_cache = (spec, build_router_agent(spec))
    return _router_cache[1]


def get_esri_agent() -> Agent[ExplorerDeps, str]:
    global _esri_cache
    spec = _current_spec()
    if _esri_cache is None or _esri_cache[0] != spec:
        logger.info("Building ESRI agent with model: %s", spec)
        _esri_cache = (spec, build_esri_agent(spec))
    return _esri_cache[1]


def get_conversation_agent() -> Agent[None, str]:
    global _conversation_cache
    spec = _current_spec()
    if _conversation_cache is None or _conversation_cache[0] != spec:
        logger.info("Building conversation agent with model: %s", spec)
        _conversation_cache = (spec, build_conversation_agent(spec))
    return _conversation_cache[1]


def get_tnufa_agent() -> Agent[TnufaDeps, str]:
    global _tnufa_cache
    spec = _current_spec()
    if _tnufa_cache is None or _tnufa_cache[0] != spec:
        logger.info("Building Tnufa agent with model: %s", spec)
        _tnufa_cache = (spec, build_tnufa_agent(spec))
    return _tnufa_cache[1]


def get_unknown_data_agent() -> Agent[None, str]:
    global _unknown_data_cache
    spec = _current_spec()
    if _unknown_data_cache is None or _unknown_data_cache[0] != spec:
        logger.info("Building unknown-data fallback agent with model: %s", spec)
        _unknown_data_cache = (spec, build_unknown_data_agent(spec))
    return _unknown_data_cache[1]


def _sse(obj: dict[str, Any]) -> str:
    return f"data: {json.dumps(obj, default=str, ensure_ascii=False)}\n\n"


def _is_conversation_shortcut(text: str) -> bool:
    """Fast path for obvious small-talk/greeting messages."""
    normalized = re.sub(r"\s+", " ", text.strip().lower())
    if not normalized:
        return True

    # If any GIS-ish token appears, do not shortcut.
    gis_tokens = (
        "arcgis",
        "mapserver",
        "featureserver",
        "layer",
        "service",
        "query",
        "geometry",
        "feature",
        "where ",
        "out_fields",
        "orderbyfields",
        "earthquake",
        "catalog",
        "gis",
        "tnufa",
        "תנופה",
        "פצועים",
        "נפגעים",
        "פגיעות",
        "injuries",
        "casualt",
    )
    if any(token in normalized for token in gis_tokens):
        return False

    casual_patterns = (
        r"^(hi|hey|hello|yo)\b",
        r"\bhow are you\b",
        r"^(thanks|thank you|thx)\b",
        r"^(good morning|good afternoon|good evening)\b",
        r"^(what can you do|who are you)\??$",
    )
    if any(re.search(pattern, normalized) for pattern in casual_patterns):
        return True

    # Keep ambiguous short prompts on the router path.
    return False


_TNUFA_CITY_NAMES_HE = (
    "בענה", "אור עקיבא", "חיפה", "תל אביב", "באר שבע", "ירושלים",
    "ראשון לציון", "פתח תקווה", "אשדוד", "נתניה", "חולון", "בני ברק",
    "רמת גן", "רחובות", "אשקלון", "הרצליה", "כפר סבא", "חדרה",
    "רעננה", "מודיעין", "נהריה", "בית שמש", "לוד", "רמלה", "נצרת",
)
_TNUFA_CITY_NAMES_EN = (
    "tel aviv", "jerusalem", "haifa", "beer sheva", "be'er sheva",
    "beersheba", "rishon lezion", "petah tikva", "ashdod", "netanya",
    "holon", "bnei brak", "ramat gan", "rehovot", "ashkelon", "herzliya",
    "kfar saba", "hadera", "raanana", "modiin", "nahariya", "beit shemesh",
    "lod", "ramla", "nazareth", "or akiva", "baana",
)


def _looks_like_tnufa_data_request(text: str) -> bool:
    """Heuristic route to Tnufa without relying on the router model."""
    raw = text.strip()
    if not raw:
        return False
    low = re.sub(r"\s+", " ", raw.lower())

    hebrew_injury = ("פצועים", "פצוע", "נפגעים", "נפגע", "פגיעות", "תנופה")
    if any(h in raw for h in hebrew_injury):
        return True

    if "tnufa" in low:
        return True

    injury_en = ("injuries", "injury", "injured", "casualt", "wounded")
    place_en = ("city", "cities", "by city", "per city", "town", "municipal")
    data_en = ("how many", "count", "counts", "number of", "statistics", "stats", "top")
    data_he = ("כמה", "מספר", "סטטיסטיקה", "נתונים", "סך", "סה\"כ")

    has_injury = any(k in low for k in injury_en)
    has_place = any(k in low for k in place_en)
    asks_for_data = any(k in low for k in data_en) or any(k in raw for k in data_he)
    has_known_city = (
        any(c in raw for c in _TNUFA_CITY_NAMES_HE)
        or any(c in low for c in _TNUFA_CITY_NAMES_EN)
    )

    if has_injury and (has_place or has_known_city):
        return True

    if has_injury and asks_for_data:
        if re.search(r"\bhow\s+(many|much)\b", low):
            return True
        if re.search(r"\b(injur\w+|casualt\w+|wounded)\b.*\b(in|at|near|for|from)\s+", low):
            return True

    return False


def _router_fallback_route(text: str) -> str:
    """When the LLM router cannot produce valid structured output, use cheap heuristics."""
    if _looks_like_tnufa_data_request(text):
        return "tnufa"
    low = re.sub(r"\s+", " ", text.strip().lower())
    esri_hints = (
        "earthquake", "magnitude", "mapserver", "featureserver",
        "layer", "arcgis", "catalog", "geometry", "spatial", "census",
    )
    if any(h in low for h in esri_hints):
        return "esri"
    return "unknown_data"


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
    global httpx_client, catalog_store, catalog_rag
    httpx_client = httpx.AsyncClient(
        headers={"User-Agent": "offline-ai-explorer/0.1"},
        verify=config.HTTPX_VERIFY,
    )
    catalog_store = ArcGISCatalogStore(config.ARCGIS_CATALOG_URL)
    if config.CATALOG_INDEX_ON_STARTUP:
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

    catalog_rag = CatalogRAG(config.OLLAMA_BASE_URL, config.OLLAMA_EMBED_MODEL)
    register_rag_layers(catalog_rag)
    await catalog_rag.embed(httpx_client)
    if catalog_rag.ready:
        logger.info("CatalogRAG ready (model=%s)", config.OLLAMA_EMBED_MODEL)
    else:
        logger.warning(
            "CatalogRAG not available — using keyword/LLM routing only. "
            "Pull '%s' in Ollama to enable semantic routing.",
            config.OLLAMA_EMBED_MODEL,
        )

    get_router_agent()
    get_esri_agent()
    get_conversation_agent()
    get_tnufa_agent()
    get_unknown_data_agent()
    yield
    if httpx_client:
        await httpx_client.aclose()
        httpx_client = None


app = FastAPI(title="Offline AI Data Explorer", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS,
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
    preview = user_text.strip().replace("\n", " ")[:120]
    logger.info("chat run start user_preview=%r", preview)

    # --- Route: RAG (semantic) → conversation shortcut → Tnufa keywords → model router ---
    rag_route: str | None = None
    if catalog_rag and catalog_rag.ready:
        try:
            matches = await catalog_rag.search(user_text, httpx_client, top_k=1)
            if matches and matches[0].score >= RAG_CONFIDENCE_THRESHOLD:
                rag_route = matches[0].chunk.route_label
                logger.info(
                    "RAG route=%s score=%.3f", rag_route, matches[0].score
                )
        except Exception:  # noqa: BLE001
            logger.warning("RAG search failed, continuing with fallback routing")

    if rag_route:
        route = rag_route
    elif _is_conversation_shortcut(user_text):
        route = "conversation"
    elif _looks_like_tnufa_data_request(user_text):
        route = "tnufa"
    else:
        try:
            route_result = await get_router_agent().run(user_text)
            route = route_result.output.route
        except Exception as exc:  # noqa: BLE001
            logger.warning("Router agent failed (%s), using heuristic fallback", exc)
            route = _router_fallback_route(user_text)
    logger.info("chat route=%s", route)

    # --- Select agent and prepare run kwargs ---
    if route == "unknown_data":
        agent = get_unknown_data_agent()
        run_kwargs: dict[str, Any] = dict(message_history=history)
    elif route == "tnufa":
        agent = get_tnufa_agent()
        run_kwargs = dict(
            message_history=history,
            deps=TnufaDeps(
                client=httpx_client,
                service_url=config.TNUFA_SERVICE_URL,
            ),
        )
    elif route == "esri":
        agent = get_esri_agent()
        run_kwargs = dict(
            message_history=history,
            deps=ExplorerDeps(
                catalog_root=config.ARCGIS_CATALOG_URL,
                client=httpx_client,
                catalog=catalog_store,
            ),
            instructions=esri_dynamic_instructions(catalog_store.prompt_summary()),
        )
    else:
        agent = get_conversation_agent()
        run_kwargs = dict(message_history=history)

    try:
        async for event in agent.run_stream_events(user_text, **run_kwargs):
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
