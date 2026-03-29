"""Integration test: verify the agent can handle 'give me 10 earthquakes'.

Runs against the real Ollama model + live ArcGIS sample server.
Requires Ollama running locally and network access.

Usage:
    cd backend
    .venv/bin/python -m pytest tests/test_earthquake_query.py -v

    Live row logs: enabled via ../pytest.ini (log_cli). For full stdout capture use -s.
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

import httpx
import pytest
import pytest_asyncio

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config
from agent import build_agent, dynamic_instructions
from arcgis_catalog_indexer import ArcGISCatalogStore
from tools.arcgis import ExplorerDeps

def _configure_test_logging() -> None:
    """Ensure INFO logs reach handlers (pytest may load before basicConfig otherwise)."""
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    if not root.handlers:
        logging.basicConfig(
            level=logging.INFO,
            format="%(levelname)-8s [%(name)s] %(message)s",
            force=True,
        )
    logging.getLogger(__name__).setLevel(logging.INFO)
    # Catalog crawl floods live logs; row samples are the interesting part.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


_configure_test_logging()
logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 3


@pytest_asyncio.fixture
async def deps():
    """Build ExplorerDeps with a live catalog index."""
    client = httpx.AsyncClient(
        headers={"User-Agent": "test-agent/0.1"},
        verify=config.HTTPX_VERIFY,
    )
    store = ArcGISCatalogStore(config.ARCGIS_CATALOG_URL)
    await store.refresh(client)
    assert not store.index.error, f"Catalog crawl failed: {store.index.error}"
    assert len(store.index.services) > 0, "No services discovered"
    yield ExplorerDeps(
        catalog_root=config.ARCGIS_CATALOG_URL,
        client=client,
        catalog=store,
    )
    await client.aclose()


def _dump_message_history(messages) -> list[dict]:
    """Walk the full message history and extract all tool interactions."""
    from pydantic_ai.messages import (
        ModelRequest,
        ModelResponse,
        RetryPromptPart,
        ToolCallPart,
        ToolReturnPart,
    )

    events = []
    for msg in messages:
        if isinstance(msg, ModelResponse):
            for part in msg.parts:
                if isinstance(part, ToolCallPart):
                    args = part.args
                    if isinstance(args, str):
                        try:
                            args = json.loads(args)
                        except json.JSONDecodeError:
                            pass
                    events.append({
                        "type": "tool_call",
                        "tool_name": part.tool_name,
                        "args": args,
                        "tool_call_id": part.tool_call_id,
                    })
        elif isinstance(msg, ModelRequest):
            for part in msg.parts:
                if isinstance(part, ToolReturnPart):
                    raw = part.content
                    if hasattr(raw, "model_dump") and callable(raw.model_dump):
                        content_dict = raw.model_dump()
                    elif isinstance(raw, dict):
                        content_dict = raw
                    else:
                        content_dict = dict(raw) if hasattr(raw, "keys") else {"_raw": raw}
                    events.append({
                        "type": "tool_return",
                        "tool_name": part.tool_name,
                        "tool_call_id": part.tool_call_id,
                        "content": content_dict,
                    })
                elif isinstance(part, RetryPromptPart):
                    events.append({
                        "type": "retry_prompt",
                        "tool_name": part.tool_name,
                        "tool_call_id": part.tool_call_id,
                        "content": str(part.content),
                    })
    return events


def _log_events(events: list[dict]) -> None:
    logger.info("--- Tool interaction log ---")
    for i, ev in enumerate(events):
        if ev["type"] == "tool_call":
            args_str = json.dumps(ev["args"], default=str) if isinstance(ev["args"], dict) else str(ev["args"])
            logger.info("  [%d] CALL %s(%s)", i, ev["tool_name"], args_str)
        elif ev["type"] == "tool_return":
            content = ev["content"]
            if isinstance(content, dict):
                summary = {k: v for k, v in content.items() if k != "rows"}
                if "rows" in content:
                    summary["rows"] = f"[{len(content['rows'])} items]"
                logger.info("  [%d] RETURN %s -> %s", i, ev["tool_name"], json.dumps(summary, default=str))
            else:
                logger.info("  [%d] RETURN %s -> %s", i, ev["tool_name"], str(content)[:200])
        elif ev["type"] == "retry_prompt":
            logger.info("  [%d] RETRY %s -> %s", i, ev["tool_name"], str(ev["content"])[:200])


def _find_successful_query(events: list[dict]) -> dict | None:
    """Find a query_layer return that has rows > 0."""
    for ev in events:
        if ev["type"] != "tool_return" or ev["tool_name"] != "query_layer":
            continue
        content = ev.get("content")
        if isinstance(content, dict) and content.get("row_count", 0) > 0:
            return ev
    return None


def _log_query_layer_results(content: dict, *, sample_rows: int = 5) -> None:
    """Log structured summary and a sample of rows from a successful query_layer return.

    Uses logging (visible with pytest ``log_cli`` / ``pytest.ini``) and ``print`` to
    stderr so rows still appear with ``pytest -s`` even if log capture differs.
    """
    rows = content.get("rows") or []
    lines: list[str] = []
    lines.append("--- query_layer results ---")
    lines.append(
        f"  service_path={content.get('service_path')!r} layer_id={content.get('layer_id')} "
        f"row_count={content.get('row_count')} exceededTransferLimit={content.get('exceededTransferLimit')}"
    )
    for line in lines:
        logger.info("%s", line)
    print("\n".join(lines), file=sys.stderr, flush=True)

    if content.get("arcgis_error"):
        err = json.dumps(content["arcgis_error"], default=str)
        logger.warning("  arcgis_error=%s", err)
        print(f"  arcgis_error={err}", file=sys.stderr, flush=True)

    if rows:
        n = min(sample_rows, len(rows))
        logger.info("  sample rows (first %d of %d):", n, len(rows))
        print(f"  sample rows (first {n} of {len(rows)}):", file=sys.stderr, flush=True)
        for i, row in enumerate(rows[:n]):
            row_json = json.dumps(row, default=str, ensure_ascii=False, indent=2)
            logger.info("    [%d] %s", i, row_json.replace("\n", " "))
            print(f"    [{i}] {row_json}", file=sys.stderr, flush=True)
    else:
        logger.info("  rows: (empty list)")
        print("  rows: (empty list)", file=sys.stderr, flush=True)

    req = content.get("arcgis_request")
    if isinstance(req, dict):
        req_line = f"  arcgis_request: method={req.get('method')} url={req.get('url')}"
        logger.info("%s", req_line)
        print(req_line, file=sys.stderr, flush=True)


@pytest.mark.asyncio
async def test_earthquake_query(deps: ExplorerDeps):
    """The agent should answer 'give me 10 earthquakes' by calling query_layer
    and returning actual data.  Allows up to MAX_ATTEMPTS because small models
    are non-deterministic."""
    agent = build_agent(config.OLLAMA_MODEL_SPEC)
    instructions = dynamic_instructions(deps.catalog.prompt_summary())
    user_prompt = "give me 10 earthquakes"

    logger.info("=== Starting earthquake query test (max %d attempts) ===", MAX_ATTEMPTS)
    logger.info("Model: %s", config.OLLAMA_MODEL_SPEC)
    logger.info("Catalog summary (first 500 chars):\n%s", deps.catalog.prompt_summary()[:500])

    last_events: list[dict] = []
    for attempt in range(1, MAX_ATTEMPTS + 1):
        logger.info("--- Attempt %d/%d ---", attempt, MAX_ATTEMPTS)

        result = await agent.run(
            user_prompt,
            deps=deps,
            instructions=instructions,
        )

        messages = result.all_messages()
        last_events = _dump_message_history(messages)
        _log_events(last_events)

        logger.info("Final answer (first 300 chars): %s", result.output[:300] if result.output else "(empty)")

        successful_query = _find_successful_query(last_events)
        if successful_query is not None:
            content = successful_query["content"]
            assert isinstance(content, dict)
            row_count = content["row_count"]
            _log_query_layer_results(content)
            logger.info(
                "=== PASS on attempt %d: query_layer returned %d rows; assistant output length=%d chars ===",
                attempt,
                row_count,
                len(result.output or ""),
            )
            return

    snippet = json.dumps(last_events, indent=2, default=str)[:4000]
    logger.error(
        "=== FAIL after %d attempts; last events (truncated) ===\n%s",
        MAX_ATTEMPTS,
        snippet,
    )
    pytest.fail(
        f"Agent failed to produce a successful query_layer call in {MAX_ATTEMPTS} attempts.\n"
        f"Last attempt events:\n{json.dumps(last_events, indent=2, default=str)[:2000]}"
    )
