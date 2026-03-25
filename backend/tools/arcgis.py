"""ArcGIS REST tools and visualization hint tool."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Annotated, Any, Literal
from urllib.parse import urlencode

import httpx
from pydantic import Field
from pydantic_ai import RunContext

from arcgis_catalog_indexer import ArcGISCatalogStore

logger = logging.getLogger(__name__)


@dataclass
class ExplorerDeps:
    catalog_root: str
    client: httpx.AsyncClient
    catalog: ArcGISCatalogStore


def _service_suffix(deps: ExplorerDeps, service_path: str) -> str:
    for svc in deps.catalog.index.services:
        if svc.path == service_path:
            return "MapServer" if svc.service_type == "MapServer" else "FeatureServer"
    return "MapServer"


async def _get_json(client: httpx.AsyncClient, url: str) -> dict[str, Any]:
    r = await client.get(url, timeout=120.0)
    r.raise_for_status()
    return r.json()


async def _post_form(client: httpx.AsyncClient, url: str, form: dict[str, str]) -> dict[str, Any]:
    r = await client.post(url, data=form, timeout=120.0)
    r.raise_for_status()
    return r.json()


async def list_services(ctx: RunContext[ExplorerDeps], folder: str | None = None) -> dict[str, Any]:
    """List services and subfolders at a catalog level. Use folder=None for root, or e.g. 'Military' or 'LocalGovernment/Census'."""
    root = ctx.deps.catalog_root.rstrip("/")
    path = folder.strip("/") if folder else ""
    url = f"{root}/{path}?f=json" if path else f"{root}?f=json"
    data = await _get_json(ctx.deps.client, url)
    return {
        "current_path": path or "(root)",
        "folders": list(data.get("folders") or []),
        "services": [
            {"name": s.get("name"), "type": s.get("type")}
            for s in (data.get("services") or [])
            if s.get("name")
        ],
    }


async def list_layers(ctx: RunContext[ExplorerDeps], service_path: str) -> dict[str, Any]:
    """List layers for a MapServer or FeatureServer. service_path is folder-qualified, e.g. 'Census' or 'Military'."""
    root = ctx.deps.catalog_root.rstrip("/")
    suffix = _service_suffix(ctx.deps, service_path)
    url = f"{root}/{service_path}/{suffix}?f=json"
    data = await _get_json(ctx.deps.client, url)
    layers = []
    for layer in data.get("layers") or []:
        if layer.get("id") is None:
            continue
        layers.append(
            {
                "id": layer.get("id"),
                "name": layer.get("name"),
                "geometryType": layer.get("geometryType"),
            },
        )
    return {"service_path": service_path, "service_type": suffix, "layers": layers}


async def get_layer_schema(ctx: RunContext[ExplorerDeps], service_path: str, layer_id: int) -> dict[str, Any]:
    """Return field definitions for a layer (names, types, aliases). Use these names verbatim in `where` and `orderByFields`."""
    root = ctx.deps.catalog_root.rstrip("/")
    suffix = _service_suffix(ctx.deps, service_path)
    url = f"{root}/{service_path}/{suffix}/{layer_id}?f=json"
    data = await _get_json(ctx.deps.client, url)
    fields_out = []
    for fdef in data.get("fields") or []:
        fields_out.append(
            {
                "name": fdef.get("name"),
                "type": fdef.get("type"),
                "alias": fdef.get("alias"),
            },
        )
    return {
        "service_path": service_path,
        "layer_id": layer_id,
        "name": data.get("name"),
        "geometryType": data.get("geometryType"),
        "fields": fields_out,
    }


async def query_layer(
    ctx: RunContext[ExplorerDeps],
    service_path: Annotated[
        str,
        Field(
            description="Folder-qualified service path from the catalog (e.g. Earthquakes_Since1970).",
        ),
    ],
    layer_id: Annotated[
        int,
        Field(
            description="Required integer layer id from list_layers for this service_path (e.g. 0). Do not omit.",
        ),
    ],
    where: Annotated[
        str,
        Field(
            description="SQL WHERE clause for the layer. Use 1=1 to return all rows (subject to limit).",
        ),
    ] = "1=1",
    out_fields: Annotated[str, Field(description="Comma-separated field names or * for all.")] = "*",
    orderByFields: Annotated[
        str | None,
        Field(description="Esri orderByFields, e.g. date_ DESC for newest first. Optional."),
    ] = None,
    limit: Annotated[int, Field(description="Max rows (resultRecordCount), 1–500.")] = 50,
) -> dict[str, Any]:
    """Query features on a layer (POST .../FeatureServer|MapServer/<id>/query, form-encoded).

    Always pass layer_id from list_layers. Use get_layer_schema for valid field names in where/orderByFields.
    """
    root = ctx.deps.catalog_root.rstrip("/")
    suffix = _service_suffix(ctx.deps, service_path)
    query_url = f"{root}/{service_path}/{suffix}/{layer_id}/query"
    w = where.strip() or "1=1"
    form: dict[str, str] = {
        "f": "json",
        "where": w,
        "outFields": out_fields,
        "returnGeometry": "false",
        "resultRecordCount": str(min(max(limit, 1), 500)),
    }
    if orderByFields:
        form["orderByFields"] = orderByFields

    get_url_example = f"{query_url}?{urlencode(form)}"
    logger.info("query_layer ArcGIS POST url=%s form=%s", query_url, form)

    data = await _post_form(ctx.deps.client, query_url, form)
    rows: list[dict[str, Any]] = []
    for feat in data.get("features") or []:
        attrs = feat.get("attributes")
        if isinstance(attrs, dict):
            rows.append(attrs)
    out: dict[str, Any] = {
        "service_path": service_path,
        "layer_id": layer_id,
        "row_count": len(rows),
        "rows": rows,
        "exceededTransferLimit": data.get("exceededTransferLimit", False),
        "arcgis_request": {
            "method": "POST",
            "url": query_url,
            "form_body": dict(form),
            "get_url_example": get_url_example,
            "note": "POST form fields match standard feature-layer query parameters. GET example may exceed URL length limits.",
        },
    }
    if data.get("error"):
        out["arcgis_error"] = data["error"]
    return out


async def suggest_visualization(
    _ctx: RunContext[ExplorerDeps],
    chart_type: Literal["bar", "line", "pie"],
    title: str,
    records: list[dict[str, Any]],
    x_field: str | None = None,
    y_field: str | None = None,
    label_field: str | None = None,
    value_field: str | None = None,
) -> dict[str, Any]:
    """Provide chart metadata and up to 80 data rows for the UI (bar/line: x_field + y_field; pie: label_field + value_field)."""
    slim = records[:80]
    return {
        "chart_type": chart_type,
        "title": title,
        "records": slim,
        "x_field": x_field,
        "y_field": y_field,
        "label_field": label_field,
        "value_field": value_field,
    }
