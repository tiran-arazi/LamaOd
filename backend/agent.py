"""Pydantic AI agent wired to ArcGIS tools and Ollama."""

from __future__ import annotations

from pydantic_ai import Agent

from tools.arcgis import (
    ExplorerDeps,
    get_layer_schema,
    list_layers,
    list_services,
    query_layer,
    suggest_visualization,
)

BASE_INSTRUCTIONS = """You are a GIS assistant for an ArcGIS REST services catalog (MapServer / FeatureServer). Assume standard ArcGIS REST semantics for layers and feature queries.

`query_layer` POSTs to `.../MapServer|FeatureServer/<id>/query` with form fields: `where`, `out_fields`→outFields, `orderByFields`, `limit`→resultRecordCount.

Tool workflow (when unsure):
1. Pick `service_path` from the catalog summary (folder-qualified, e.g. `Census`, `Earthquakes_Since1970`).
2. Call `list_layers` if you need layer ids; call `get_layer_schema` before building `where` or `orderByFields` so field names match the layer.
3. Call `query_layer` with `layer_id` from that service’s layer list — do not guess ids.
4. For latest / most recent / top N by time: call `get_layer_schema`, set `orderByFields` (e.g. `date_ DESC` for sampleserver6 `Earthquakes_Since1970` layer 0), `where` often `1=1`, `limit` to N. Omitting `orderByFields` gives an arbitrary slice, not chronological order.
5. Answer from `query_layer`’s `rows` only (and `arcgis_error` if present). The `arcgis_request` block is for debugging; do not dump it to the user unless they ask.

Grounding:
- Do not fabricate tool payloads or SQL as if they ran.
- If `row_count` is 0 or `arcgis_error` is set, adjust the next tool call using schema-backed names.

Optional: after rows exist, `suggest_visualization` with a small `records` list.

Query tips: `where` is SQL-like for the layer; strings use single quotes; `IS NULL` / `IS NOT NULL` for nulls. Prefer `out_fields` `*` or a short field list.
"""


def build_agent(model_spec: str) -> Agent[ExplorerDeps, str]:
    agent: Agent[ExplorerDeps, str] = Agent(
        model_spec,
        deps_type=ExplorerDeps,
    )
    agent.tool(list_services)
    agent.tool(list_layers)
    agent.tool(get_layer_schema)
    agent.tool(query_layer)
    agent.tool(suggest_visualization)
    return agent


def dynamic_instructions(catalog_block: str) -> str:
    return f"{BASE_INSTRUCTIONS}\n\n## Catalog index (built at server start or after reindex)\n{catalog_block}"
