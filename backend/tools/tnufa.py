"""Tnufa (תנופה) events tool — injury statistics by city.

Offline behaviour uses ``mocks.tnufa_mock`` (easy to delete). With
``TNUFA_SERVICE_URL`` set, requests go to the real ArcGIS REST layer.

Agent overview (routing, fields, mock SQL limits, tests): ``docs/tnufa_agent.md``.
"""

from __future__ import annotations

import logging
import json
import re
from dataclasses import dataclass
from typing import Annotated, Any, Literal
from urllib.parse import urlencode

import httpx
from pydantic import BaseModel, ConfigDict, Field, computed_field
from pydantic_ai import RunContext

from mocks import tnufa_mock

logger = logging.getLogger(__name__)

_CITY_EQ_RE = re.compile(r"City\s*=\s*'((?:''|[^'])*)'", re.IGNORECASE)
_CITY_LIKE_RE = re.compile(r"City\s+LIKE\s+'((?:''|[^'])*)'", re.IGNORECASE)
_CITY_SPLIT_RE = re.compile(r"[\/|,;]+")
_NON_ALNUM_SPACE_RE = re.compile(r"[^a-z0-9\u0590-\u05ff\s-]+", re.IGNORECASE)
_HAS_HEBREW_RE = re.compile(r"[\u0590-\u05ff]")
_HAS_LATIN_RE = re.compile(r"[a-zA-Z]")
_HAS_ARABIC_RE = re.compile(r"[\u0600-\u06ff]")
_CITY_EN_TO_HE: dict[str, str] = {
    "tel aviv": "תל אביב - יפו",
    "tel-aviv": "תל אביב - יפו",
    "tel aviv-yafo": "תל אביב - יפו",
    "tel aviv yafo": "תל אביב - יפו",
    "jerusalem": "ירושלים",
    "haifa": "חיפה",
    "beer sheva": "באר שבע",
    "be'er sheva": "באר שבע",
    "beersheba": "באר שבע",
    "nazareth": "נצרת",
}
_CITY_HE_CANONICAL: tuple[str, ...] = (
    "תל אביב - יפו",
    "ירושלים",
    "חיפה",
    "באר שבע",
    "נצרת",
)


@dataclass
class TnufaDeps:
    client: httpx.AsyncClient
    service_url: str | None = None


class TnufaSchemaField(BaseModel):
    name: str | None = None
    type: str | None = None
    alias: str | None = None


class TnufaSchemaResult(BaseModel):
    layer: str
    fields: list[TnufaSchemaField]


class TnufaRow(BaseModel):
    model_config = ConfigDict(extra="allow")

    City: str | None = None
    ModerateInjuries: int | None = None
    SeriousInjuries: int | None = None
    SevereInjuries: int | None = None
    MinorInjuries: int | None = None

    @computed_field
    @property
    def TotalInjuries(self) -> int | None:
        # When the query asked for a subset of fields, totals are unknown.
        if (
            self.ModerateInjuries is None
            or self.SeriousInjuries is None
            or self.SevereInjuries is None
            or self.MinorInjuries is None
        ):
            return None
        return (
            int(self.ModerateInjuries or 0)
            + int(self.SeriousInjuries or 0)
            + int(self.SevereInjuries or 0)
            + int(self.MinorInjuries or 0)
        )


class TnufaQueryResult(BaseModel):
    row_count: int
    rows: list[TnufaRow]
    exceededTransferLimit: bool = False
    source: str | None = None
    arcgis_request: dict[str, Any] | None = None
    arcgis_error: dict[str, Any] | None = None
    warning: str | None = None


async def _post_form(client: httpx.AsyncClient, url: str, form: dict[str, str]) -> dict[str, Any]:
    r = await client.post(url, data=form, timeout=120.0)
    r.raise_for_status()
    return r.json()


def _normalize_city_filter_value(raw_value: str) -> str:
    value = raw_value.replace("''", "'").strip()
    if not value:
        return value

    # Handle model artifacts like JSON-encoded city values: '["חיפה"]' or '"חיפה"'.
    try:
        parsed = json.loads(value)
        if isinstance(parsed, list) and parsed:
            for item in parsed:
                if isinstance(item, str) and item.strip():
                    value = item.strip()
                    break
        elif isinstance(parsed, str) and parsed.strip():
            value = parsed.strip()
    except Exception:  # noqa: BLE001
        pass

    # Trim common bracket/quote wrappers if they survived.
    value = value.strip().strip("[](){}")
    if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
        value = value[1:-1].strip()
    if not value:
        return value

    # Try chunked variants first (the model may emit mixed tokens like "tel Aviv / נהתל").
    chunks = [c.strip() for c in _CITY_SPLIT_RE.split(value) if c.strip()]
    if not chunks:
        chunks = [value]

    def _normalize_token(tok: str) -> str:
        tok = tok.lower()
        tok = _NON_ALNUM_SPACE_RE.sub(" ", tok)
        tok = re.sub(r"\s+", " ", tok).strip()
        return tok

    for chunk in chunks:
        low = _normalize_token(chunk)
        if low in _CITY_EN_TO_HE:
            return _CITY_EN_TO_HE[low]
        if "tel" in low and "aviv" in low:
            return "תל אביב - יפו"
        if "jerusalem" in low:
            return "ירושלים"
        if "haifa" in low:
            return "חיפה"
        if "beer sheva" in low or "be er sheva" in low or "beersheba" in low:
            return "באר שבע"
        if "nazareth" in low:
            return "נצרת"
        if "תל אביב" in chunk:
            return "תל אביב - יפו"
        if chunk == "תל אביב":
            return "תל אביב - יפו"
        if chunk in _CITY_HE_CANONICAL:
            return chunk

    low_full = _normalize_token(value)
    if low_full in _CITY_EN_TO_HE:
        return _CITY_EN_TO_HE[low_full]
    if "tel" in low_full and "aviv" in low_full:
        return "תל אביב - יפו"
    if value == "תל אביב":
        return "תל אביב - יפו"
    return value


def _rewrite_where_for_city_variants(where: str) -> str:
    """Normalize common city variants in equality filters to improve recall."""

    def _replace(match: re.Match[str]) -> str:
        original = match.group(1)
        normalized = _normalize_city_filter_value(original)
        escaped = normalized.replace("'", "''")
        # Tel Aviv often appears as "תל אביב - יפו" in the data.
        if normalized == "תל אביב - יפו":
            return "City LIKE 'תל אביב%'"
        return f"City = '{escaped}'"

    rewritten = _CITY_EQ_RE.sub(_replace, where)

    def _replace_like(match: re.Match[str]) -> str:
        original = match.group(1)
        normalized = _normalize_city_filter_value(original)
        escaped = normalized.replace("'", "''")
        if normalized == "תל אביב - יפו":
            return "City LIKE 'תל אביב%'"
        return f"City LIKE '{escaped}'"

    return _CITY_LIKE_RE.sub(_replace_like, rewritten)


def _city_where(city: str) -> str:
    normalized = _normalize_city_filter_value(city)
    escaped = normalized.replace("'", "''")
    if normalized == "תל אביב - יפו":
        return "City LIKE 'תל אביב%'"
    return f"City = '{escaped}'"


def _is_invalid_city_token(city: str) -> bool:
    """Reject obviously malformed city values before querying."""
    has_he = bool(_HAS_HEBREW_RE.search(city))
    has_lat = bool(_HAS_LATIN_RE.search(city))
    has_ar = bool(_HAS_ARABIC_RE.search(city))
    # Dataset/tooling currently supports Hebrew city names and common English aliases.
    if has_ar:
        return True
    # Mixed-script noise from the model is often not a real city (e.g. "ולlל").
    if has_he and has_lat:
        # Allow known english-style separators only when it still looks like a clean alias.
        # If both scripts are present in one token, prefer asking for clarification.
        return True
    return False


async def get_tnufa_schema(ctx: RunContext[TnufaDeps]) -> TnufaSchemaResult:
    """Return the field definitions for the Tnufa events layer (names, types, aliases)."""
    if ctx.deps.service_url:
        url = f"{ctx.deps.service_url.rstrip('/')}/0?f=json"
        r = await ctx.deps.client.get(url, timeout=120.0)
        r.raise_for_status()
        data = r.json()
        fields = [
            {"name": f.get("name"), "type": f.get("type"), "alias": f.get("alias")}
            for f in data.get("fields", [])
        ]
    else:
        # Mock: see mocks/tnufa_mock.py
        fields = tnufa_mock.schema_fields_raw()
    return TnufaSchemaResult(
        layer="TnufaEvents",
        fields=[TnufaSchemaField.model_validate(f) for f in fields],
    )


async def query_tnufa_events(
    ctx: RunContext[TnufaDeps],
    where: Annotated[
        str,
        Field(description="SQL WHERE clause. Use 1=1 to return all rows (subject to limit)."),
    ] = "1=1",
    out_fields: Annotated[
        str,
        Field(description="Comma-separated field names or * for all."),
    ] = "*",
    orderByFields: Annotated[
        str | None,
        Field(description="Esri orderByFields, e.g. MinorInjuries DESC. Optional."),
    ] = None,
    limit: Annotated[
        int | str | None,
        Field(description="Max rows (resultRecordCount), 1–500."),
    ] = 50,
) -> TnufaQueryResult:
    """Query Tnufa (תנופה) injury events by city.

    Fields: City (string), ModerateInjuries (int), SeriousInjuries (int),
    SevereInjuries (int), MinorInjuries (int).
    """
    limit_int = max(1, min(int(limit or 50), 500))
    w_raw = (where or "").strip() or "1=1"
    w = _rewrite_where_for_city_variants(w_raw)
    if w != w_raw:
        logger.info("query_tnufa_events normalized where from %r to %r", w_raw, w)

    if ctx.deps.service_url:
        query_url = f"{ctx.deps.service_url.rstrip('/')}/0/query"
        form: dict[str, str] = {
            "f": "json",
            "where": w,
            "outFields": out_fields,
            "returnGeometry": "false",
            "resultRecordCount": str(limit_int),
        }
        if orderByFields:
            form["orderByFields"] = orderByFields

        logger.info("query_tnufa_events POST url=%s form=%s", query_url, form)
        data = await _post_form(ctx.deps.client, query_url, form)
        rows: list[dict[str, Any]] = []
        for feat in data.get("features", []):
            attrs = feat.get("attributes")
            if isinstance(attrs, dict):
                rows.append(attrs)
        out = TnufaQueryResult(
            row_count=len(rows),
            rows=[TnufaRow.model_validate(r) for r in rows],
            exceededTransferLimit=bool(data.get("exceededTransferLimit", False)),
            arcgis_request={
                "method": "POST",
                "url": query_url,
                "form_body": dict(form),
                "get_url_example": f"{query_url}?{urlencode(form)}",
            },
        )
        if data.get("error"):
            out.arcgis_error = data["error"]
        return out

    # Mock: see mocks/tnufa_mock.py
    logger.info("query_tnufa_events MOCK where=%r order=%r limit=%s", w, orderByFields, limit_int)
    result = tnufa_mock.query(w, out_fields, orderByFields, limit_int)
    return TnufaQueryResult(
        row_count=len(result["rows"]),
        rows=[TnufaRow.model_validate(r) for r in result["rows"]],
        exceededTransferLimit=False,
        source="mock",
    )


async def query_tnufa_city(
    ctx: RunContext[TnufaDeps],
    city: Annotated[
        str,
        Field(description="City name in English or Hebrew, e.g. tel aviv / תל אביב."),
    ],
    metric: Annotated[
        Literal["total", "moderate", "serious", "severe", "minor", "breakdown"],
        Field(description="Requested metric type for this city."),
    ] = "total",
) -> TnufaQueryResult:
    """Safer typed query for city-based questions (avoids free-form SQL generation)."""
    normalized_city = _normalize_city_filter_value(city)
    where = _city_where(city)
    # If normalization fails and there are no obvious letters, return structured guidance.
    if not normalized_city or not re.search(r"[a-zA-Z\u0590-\u05ff]", normalized_city):
        return TnufaQueryResult(
            row_count=0,
            rows=[],
            exceededTransferLimit=False,
            source="validation",
            warning=(
                "Invalid city argument format. Provide a city name as plain text, "
                "for example: 'חיפה' or 'tel aviv'."
            ),
        )
    if _is_invalid_city_token(normalized_city):
        return TnufaQueryResult(
            row_count=0,
            rows=[],
            exceededTransferLimit=False,
            source="validation",
            warning=(
                "Unsupported or malformed city value. Provide a city name in Hebrew or English, "
                "for example: 'חיפה' or 'tel aviv'."
            ),
        )
    if metric in ("total", "breakdown"):
        out_fields = "*"
    elif metric == "moderate":
        out_fields = "City,ModerateInjuries"
    elif metric == "serious":
        out_fields = "City,SeriousInjuries"
    elif metric == "severe":
        out_fields = "City,SevereInjuries"
    else:
        out_fields = "City,MinorInjuries"
    result = await query_tnufa_events(
        ctx,
        where=where,
        out_fields=out_fields,
        orderByFields=None,
        limit=5,
    )
    if result.row_count == 0:
        result.warning = (
            f"No rows matched city={normalized_city!r}. "
            "Try a canonical city name (for example: תל אביב, חיפה, ירושלים)."
        )
    return result
