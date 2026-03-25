"""ArcGIS REST catalog indexer — crawls .../arcgis/rest/services (MapServer + FeatureServer).

Used to build an in-memory index for the agent prompt. Works with any reachable ArcGIS REST root,
including on a closed network: set ARCGIS_CATALOG_URL to your internal server URL.

Indexing is not “learning”: it is HTTP discovery of the same REST API the tools call later.
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone

import httpx

from models import CatalogIndex, CatalogLayerInfo, CatalogServiceEntry

logger = logging.getLogger(__name__)

MAP_TYPES = frozenset({"MapServer", "FeatureServer"})
MAX_FOLDER_DEPTH = 2


class ArcGISCatalogStore:
    """Holds the latest crawl result; thread-safe refresh for async FastAPI."""

    def __init__(self, catalog_root_url: str) -> None:
        self.catalog_root_url = catalog_root_url.rstrip("/")
        self._lock = asyncio.Lock()
        self._index = CatalogIndex(catalog_url=self.catalog_root_url, services=[], error="not built")

    @property
    def index(self) -> CatalogIndex:
        return self._index

    async def refresh(self, client: httpx.AsyncClient) -> CatalogIndex:
        async with self._lock:
            try:
                services = await _crawl_catalog(client, self.catalog_root_url)
                self._index = CatalogIndex(
                    catalog_url=self.catalog_root_url,
                    services=services,
                    updated_at=datetime.now(timezone.utc).isoformat(),
                    error=None,
                )
            except Exception as exc:  # noqa: BLE001
                logger.exception("ArcGIS catalog crawl failed")
                self._index = CatalogIndex(
                    catalog_url=self.catalog_root_url,
                    services=[],
                    updated_at=datetime.now(timezone.utc).isoformat(),
                    error=str(exc),
                )
        return self._index

    def prompt_summary(self, max_services: int = 40, max_fields_per_layer: int = 12) -> str:
        if self._index.error:
            return f"Catalog unavailable: {self._index.error}"
        lines: list[str] = []
        for svc in self._index.services[:max_services]:
            lines.append(f"Service `{svc.path}` ({svc.service_type})")
            for layer in svc.layers[:8]:
                flds = ", ".join(layer.fields[:max_fields_per_layer])
                geo = layer.geometry_type or "unknown"
                lines.append(f"  Layer {layer.layer_id}: {layer.name} ({geo}) — fields: {flds}")
        if len(self._index.services) > max_services:
            lines.append(f"... and {len(self._index.services) - max_services} more services (use list_services).")
        return "\n".join(lines) if lines else "No map or feature services discovered."


async def _crawl_catalog(client: httpx.AsyncClient, catalog_root: str) -> list[CatalogServiceEntry]:
    found: list[CatalogServiceEntry] = []
    seen: set[tuple[str, str]] = set()
    paths_taken: set[str] = set()
    max_services = int(os.getenv("CATALOG_MAX_SERVICES", "25"))

    async def visit_folder(path_prefix: str, folder_depth: int) -> None:
        if len(found) >= max_services:
            return
        url = f"{catalog_root}/{path_prefix}?f=json" if path_prefix else f"{catalog_root}?f=json"
        data = await _get_json(client, url)
        for svc in data.get("services") or []:
            name = svc.get("name")
            typ = svc.get("type")
            if not name or typ not in MAP_TYPES:
                continue
            full_path = f"{path_prefix}/{name}" if path_prefix else name
            key = (full_path, typ)
            if key in seen:
                continue
            if full_path in paths_taken:
                continue
            seen.add(key)
            entry = await _service_entry(client, catalog_root, full_path, typ)
            if entry:
                found.append(entry)
                paths_taken.add(full_path)
            if len(found) >= max_services:
                return
        if folder_depth >= MAX_FOLDER_DEPTH:
            return
        for folder in data.get("folders") or []:
            if len(found) >= max_services:
                return
            child_prefix = f"{path_prefix}/{folder}" if path_prefix else folder
            await visit_folder(child_prefix, folder_depth + 1)

    await visit_folder("", 0)
    found.sort(key=lambda e: e.path.lower())
    return found


async def _service_entry(
    client: httpx.AsyncClient,
    catalog_root: str,
    path: str,
    service_type: str,
) -> CatalogServiceEntry | None:
    suffix = "MapServer" if service_type == "MapServer" else "FeatureServer"
    meta_url = f"{catalog_root}/{path}/{suffix}?f=json"
    try:
        data = await _get_json(client, meta_url)
    except Exception:
        logger.warning("Skip service %s (%s): metadata fetch failed", path, service_type)
        return None
    layers_raw = data.get("layers") or []
    layers: list[CatalogLayerInfo] = []
    max_field_layers = int(os.getenv("CATALOG_MAX_LAYERS_FIELD_DETAIL", "4"))
    for i, layer in enumerate(layers_raw):
        lid = layer.get("id")
        if lid is None:
            continue
        name = layer.get("name") or f"layer_{lid}"
        geo = layer.get("geometryType")
        fields: list[str] = []
        if i < max_field_layers:
            detail_url = f"{catalog_root}/{path}/{suffix}/{lid}?f=json"
            try:
                detail = await _get_json(client, detail_url)
                for fdef in detail.get("fields") or []:
                    fn = fdef.get("name")
                    if fn:
                        fields.append(fn)
            except Exception:
                fields = []
        layers.append(
            CatalogLayerInfo(layer_id=int(lid), name=str(name), geometry_type=geo, fields=fields),
        )
    return CatalogServiceEntry(path=path, service_type=service_type, layers=layers)


async def _get_json(client: httpx.AsyncClient, url: str) -> dict:
    r = await client.get(url, timeout=120.0)
    r.raise_for_status()
    return r.json()
