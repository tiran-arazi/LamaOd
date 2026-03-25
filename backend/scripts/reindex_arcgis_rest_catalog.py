#!/usr/bin/env python3
"""CLI: crawl ArcGIS REST catalog once and print summary (optional JSON snapshot).

Run from repo root or from backend/:

  cd backend && source .venv/bin/activate && python scripts/reindex_arcgis_rest_catalog.py

Uses the same env as the API: ARCGIS_CATALOG_URL, CATALOG_MAX_SERVICES, etc.
Works on a closed network if this machine can reach your internal .../arcgis/rest/services URL.

Does not start the web server; use POST /api/catalog/reindex to refresh while the app runs.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv

_backend = Path(__file__).resolve().parent.parent
_root = _backend.parent
sys.path.insert(0, str(_backend))

load_dotenv(_root / ".env")
load_dotenv(_backend / ".env")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("reindex_arcgis_rest_catalog")

from arcgis_catalog_indexer import ArcGISCatalogStore  # noqa: E402


async def main_async() -> int:
    parser = argparse.ArgumentParser(description="One-shot ArcGIS REST catalog crawl")
    parser.add_argument(
        "--write-json",
        type=Path,
        default=None,
        help="Write full catalog index JSON to this path (for auditing or offline review)",
    )
    args = parser.parse_args()

    url = os.getenv(
        "ARCGIS_CATALOG_URL",
        "https://sampleserver6.arcgisonline.com/arcgis/rest/services",
    )
    store = ArcGISCatalogStore(url)
    async with httpx.AsyncClient(
        headers={"User-Agent": "offline-ai-explorer/reindex-cli/0.1"},
        timeout=120.0,
    ) as client:
        await store.refresh(client)

    idx = store.index
    if idx.error:
        logger.error("Crawl failed: %s", idx.error)
        return 1

    print(f"Catalog URL: {idx.catalog_url}")
    print(f"Services: {len(idx.services)}")
    print(f"Updated at: {idx.updated_at}")
    if args.write_json:
        args.write_json.parent.mkdir(parents=True, exist_ok=True)
        args.write_json.write_text(idx.model_dump_json(indent=2), encoding="utf-8")
        print(f"Wrote {args.write_json}")
    return 0


def main() -> None:
    raise SystemExit(asyncio.run(main_async()))


if __name__ == "__main__":
    main()
