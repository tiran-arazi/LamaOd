"""Test CatalogRAG + rag_registry for Tnufa-shaped queries.

Requires Ollama with ``OLLAMA_EMBED_MODEL`` pulled (default: nomic-embed-text).
Tests skip if embeddings are unavailable.
"""

from __future__ import annotations

import sys
from pathlib import Path

import httpx
import pytest
import pytest_asyncio

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config  # noqa: E402
from catalog_rag import CatalogRAG  # noqa: E402
from rag_registry import register_rag_layers  # noqa: E402

POSITIVE_QUERIES = [
    "how many injuries in tel aviv",
    "כמה פצועים יש בחיפה",
    "wounded people by city",
    "show me casualty statistics",
    "injury data for jerusalem",
    "נפגעים לפי עיר",
]

NEGATIVE_QUERIES = [
    "show me earthquake data",
    "what layers are available",
    "hello how are you",
]

POSITIVE_THRESHOLD = 0.55
NEGATIVE_THRESHOLD = 0.55


async def _build_rag(client: httpx.AsyncClient) -> CatalogRAG:
    rag = CatalogRAG(config.OLLAMA_BASE_URL, config.OLLAMA_EMBED_MODEL)
    register_rag_layers(rag)
    await rag.embed(client)
    return rag


@pytest_asyncio.fixture
async def rag():
    async with httpx.AsyncClient() as client:
        r = await _build_rag(client)
        if not r.ready:
            pytest.skip(
                f"Embedding model '{config.OLLAMA_EMBED_MODEL}' not available "
                f"at {config.OLLAMA_BASE_URL}"
            )
        yield r, client


@pytest.mark.asyncio
@pytest.mark.parametrize("query", POSITIVE_QUERIES)
async def test_tnufa_positive_match(rag, query: str) -> None:
    r, client = rag
    matches = await r.search(query, client, top_k=1)
    assert matches, f"No matches returned for: {query!r}"
    best = matches[0]
    assert best.chunk.route_label == "tnufa"
    assert best.score >= POSITIVE_THRESHOLD, (
        f"Score {best.score:.3f} below {POSITIVE_THRESHOLD} for: {query!r}"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("query", NEGATIVE_QUERIES)
async def test_tnufa_negative_match(rag, query: str) -> None:
    r, client = rag
    matches = await r.search(query, client, top_k=1)
    if not matches:
        return
    best = matches[0]
    assert best.score < NEGATIVE_THRESHOLD, (
        f"Score {best.score:.3f} unexpectedly high for negative query: {query!r}"
    )
