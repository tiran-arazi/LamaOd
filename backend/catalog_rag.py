"""In-memory semantic routing via Ollama embeddings (cosine similarity).

MVP: ``register`` hand-written layer descriptions, then ``embed`` once at startup.
Expansion: add more ``register`` calls in ``rag_registry``, or iterate a
``CatalogIndex`` and ``register(text, route_label, **metadata)`` per layer.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import httpx
import numpy as np

logger = logging.getLogger(__name__)

EMBED_BATCH_SIZE = 32


@dataclass
class LayerChunk:
    text: str
    route_label: str
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass
class LayerMatch:
    chunk: LayerChunk
    score: float


class CatalogRAG:
    """In-memory embedding index for route hints (e.g. tnufa vs fall through)."""

    def __init__(self, ollama_base_url: str, embed_model: str) -> None:
        self._base_url = ollama_base_url.rstrip("/")
        self._model = embed_model
        self._chunks: list[LayerChunk] = []
        self._pending_chunks: list[LayerChunk] = []
        self._embeddings: np.ndarray | None = None
        self._ready = False

    @property
    def ready(self) -> bool:
        return self._ready

    def register(self, text: str, route_label: str, **metadata: str) -> None:
        """Queue a document chunk for the next ``embed()`` call."""
        self._pending_chunks.append(
            LayerChunk(text=text, route_label=route_label, metadata=dict(metadata))
        )

    async def embed(self, client: httpx.AsyncClient) -> None:
        """Embed all registered chunks and mark the index ready (or not on failure)."""
        await self._embed_and_store(list(self._pending_chunks), client)

    async def search(
        self,
        query: str,
        client: httpx.AsyncClient,
        top_k: int = 3,
    ) -> list[LayerMatch]:
        if not self._ready or self._embeddings is None:
            return []
        try:
            q_emb = await self._get_embeddings(
                [query], client, prefix="search_query: "
            )
        except Exception:
            logger.exception("CatalogRAG: query embedding failed")
            return []

        q_vec = q_emb[0]
        dot = self._embeddings @ q_vec
        norms = np.linalg.norm(self._embeddings, axis=1) * np.linalg.norm(q_vec)
        norms = np.where(norms == 0, 1e-10, norms)
        similarities = dot / norms

        top_idx = np.argsort(similarities)[::-1][:top_k]
        return [
            LayerMatch(chunk=self._chunks[i], score=float(similarities[i]))
            for i in top_idx
            if similarities[i] > 0
        ]

    async def _embed_and_store(
        self, chunks: list[LayerChunk], client: httpx.AsyncClient
    ) -> None:
        if not chunks:
            logger.warning("CatalogRAG: nothing to index")
            self._ready = False
            return
        texts = [c.text for c in chunks]
        try:
            self._embeddings = await self._get_embeddings(
                texts, client, prefix="search_document: "
            )
        except Exception:
            logger.exception(
                "CatalogRAG: embedding failed (is '%s' pulled in Ollama?) "
                "— RAG routing disabled, falling back to keyword/LLM router",
                self._model,
            )
            self._ready = False
            return
        self._chunks = chunks
        self._pending_chunks.clear()
        self._ready = True
        logger.info("CatalogRAG: indexed %d chunks (%s)", len(chunks), self._model)

    async def _get_embeddings(
        self,
        texts: list[str],
        client: httpx.AsyncClient,
        *,
        prefix: str = "",
    ) -> np.ndarray:
        url = f"{self._base_url}/embeddings"
        all_embs: list[list[float]] = []
        prefixed = [f"{prefix}{t}" for t in texts] if prefix else texts
        for i in range(0, len(prefixed), EMBED_BATCH_SIZE):
            batch = prefixed[i : i + EMBED_BATCH_SIZE]
            resp = await client.post(
                url,
                json={"model": self._model, "input": batch},
                timeout=120.0,
            )
            resp.raise_for_status()
            data = resp.json()
            sorted_items = sorted(data["data"], key=lambda d: d["index"])
            all_embs.extend(item["embedding"] for item in sorted_items)
        return np.array(all_embs, dtype=np.float32)
