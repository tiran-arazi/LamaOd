from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from main import _looks_like_tnufa_data_request
from mocks import tnufa_mock
from tools.tnufa import (
    TnufaDeps,
    TnufaQueryResult,
    TnufaSchemaResult,
    get_tnufa_schema,
    query_tnufa_city,
    query_tnufa_events,
)

MOCK_CITY_ROW_COUNT = 25

SERIOUS_INJURIES_CITIES = {
    "אשקלון",
    "הרצליה",
    "חדרה",
    "חולון",
    "חיפה",
    "ירושלים",
    "לוד",
    "נהריה",
    "נתניה",
    "פתח תקווה",
    "תל אביב - יפו",
}


def test_tnufa_route_positive_cases() -> None:
    assert _looks_like_tnufa_data_request("כמה פצועים יש בתל אביב")
    assert _looks_like_tnufa_data_request("injuries by city for Haifa")
    assert _looks_like_tnufa_data_request("how many wounded in Jerusalem?")
    assert _looks_like_tnufa_data_request("tnufa data for cities")


def test_tnufa_route_negative_cases() -> None:
    assert not _looks_like_tnufa_data_request("hello there")
    assert not _looks_like_tnufa_data_request("show me tesla stock prices")
    assert not _looks_like_tnufa_data_request("explain injuries in medicine generally")


def test_mock_query_like_support_city_variants() -> None:
    out = tnufa_mock.query(
        where="City LIKE 'תל אביב%'",
        out_fields="City,MinorInjuries",
        order_by_fields=None,
        limit=10,
    )
    assert len(out["rows"]) == 1
    assert out["rows"][0]["City"] == "תל אביב - יפו"
    assert out["rows"][0]["MinorInjuries"] == 40


def test_mock_query_and_or_support() -> None:
    out = tnufa_mock.query(
        where="SevereInjuries > 0 AND MinorInjuries >= 13 OR City = 'ירושלים'",
        out_fields="City,SevereInjuries,MinorInjuries",
        order_by_fields="MinorInjuries DESC",
        limit=20,
    )
    cities = [r["City"] for r in out["rows"]]
    assert "תל אביב - יפו" in cities
    assert "אשדוד" in cities
    assert "ירושלים" in cities


def test_mock_query_invalid_where_returns_no_rows() -> None:
    out = tnufa_mock.query(
        where="this is not sql",
        out_fields="*",
        order_by_fields=None,
        limit=20,
    )
    assert out["rows"] == []


def test_mock_all_cities_by_city_listing() -> None:
    """Simulates 'injuries by city' / all rows with a high limit."""
    out = tnufa_mock.query(
        where="1=1",
        out_fields="*",
        order_by_fields=None,
        limit=500,
    )
    assert len(out["rows"]) == MOCK_CITY_ROW_COUNT
    cities = {r["City"] for r in out["rows"]}
    assert len(cities) == MOCK_CITY_ROW_COUNT
    assert "מודיעין-מכבים-רעות" in cities


def test_mock_haifa_moderate_injuries() -> None:
    """User-style: how many moderate injuries in Haifa → City = חיפה."""
    out = tnufa_mock.query(
        where="City = 'חיפה'",
        out_fields="City,ModerateInjuries,SeriousInjuries,MinorInjuries",
        order_by_fields=None,
        limit=10,
    )
    assert len(out["rows"]) == 1
    row = out["rows"][0]
    assert row["City"] == "חיפה"
    assert row["ModerateInjuries"] == 3
    assert row["SeriousInjuries"] == 1
    assert row["MinorInjuries"] == 24


def test_mock_beer_sheva_row() -> None:
    out = tnufa_mock.query(
        where="City = 'באר שבע'",
        out_fields="*",
        order_by_fields=None,
        limit=5,
    )
    assert len(out["rows"]) == 1
    assert out["rows"][0]["ModerateInjuries"] == 2
    assert out["rows"][0]["SeriousInjuries"] == 0
    assert out["rows"][0]["MinorInjuries"] == 18


def test_mock_jerusalem_severity_breakdown() -> None:
    out = tnufa_mock.query(
        where="City = 'ירושלים'",
        out_fields="City,ModerateInjuries,SeriousInjuries,SevereInjuries,MinorInjuries",
        order_by_fields=None,
        limit=5,
    )
    row = out["rows"][0]
    assert row["ModerateInjuries"] == 4
    assert row["SeriousInjuries"] == 3
    assert row["SevereInjuries"] == 1
    assert row["MinorInjuries"] == 35


def test_mock_top_cities_by_moderate_injuries() -> None:
    out = tnufa_mock.query(
        where="1=1",
        out_fields="City,ModerateInjuries",
        order_by_fields="ModerateInjuries DESC",
        limit=3,
    )
    assert [r["City"] for r in out["rows"]] == ["תל אביב - יפו", "ירושלים", "אשקלון"]
    assert [r["ModerateInjuries"] for r in out["rows"]] == [5, 4, 4]


def test_mock_top_city_by_minor_injuries() -> None:
    out = tnufa_mock.query(
        where="1=1",
        out_fields="City,MinorInjuries",
        order_by_fields="MinorInjuries DESC",
        limit=1,
    )
    assert out["rows"][0]["City"] == "תל אביב - יפו"
    assert out["rows"][0]["MinorInjuries"] == 40


def test_mock_cities_with_serious_injuries() -> None:
    out = tnufa_mock.query(
        where="SeriousInjuries > 0",
        out_fields="City,SeriousInjuries",
        order_by_fields=None,
        limit=100,
    )
    assert len(out["rows"]) == len(SERIOUS_INJURIES_CITIES)
    assert {r["City"] for r in out["rows"]} == SERIOUS_INJURIES_CITIES
    assert all(r["SeriousInjuries"] > 0 for r in out["rows"])


def test_mock_cities_with_severe_injuries() -> None:
    out = tnufa_mock.query(
        where="SevereInjuries > 0",
        out_fields="City,SevereInjuries",
        order_by_fields="SevereInjuries DESC",
        limit=20,
    )
    cities = [r["City"] for r in out["rows"]]
    assert cities == ["אור עקיבא", "תל אביב - יפו", "ירושלים", "אשדוד", "רמת גן", "חדרה", "רמלה"]


def test_mock_moderate_injuries_tie_filter() -> None:
    out = tnufa_mock.query(
        where="ModerateInjuries = 4",
        out_fields="City,ModerateInjuries",
        order_by_fields="City ASC",
        limit=10,
    )
    assert {r["City"] for r in out["rows"]} == {"אשקלון", "ירושלים"}


def test_mock_rishon_lezion() -> None:
    out = tnufa_mock.query(
        where="City = 'ראשון לציון'",
        out_fields="City,ModerateInjuries,MinorInjuries",
        order_by_fields=None,
        limit=5,
    )
    assert out["rows"][0]["ModerateInjuries"] == 1
    assert out["rows"][0]["MinorInjuries"] == 22


def test_mock_nazareth() -> None:
    out = tnufa_mock.query(
        where="City = 'נצרת'",
        out_fields="City,ModerateInjuries,MinorInjuries",
        order_by_fields=None,
        limit=5,
    )
    assert out["rows"][0]["ModerateInjuries"] == 2
    assert out["rows"][0]["MinorInjuries"] == 15


def test_mock_unknown_city_returns_empty() -> None:
    out = tnufa_mock.query(
        where="City = 'עיר שלא קיימת'",
        out_fields="*",
        order_by_fields=None,
        limit=10,
    )
    assert out["rows"] == []


def _tnufa_ctx(service_url: str | None = None) -> SimpleNamespace:
    return SimpleNamespace(deps=TnufaDeps(client=MagicMock(), service_url=service_url))


@pytest.mark.asyncio
async def test_query_tnufa_events_uses_mock_when_no_service_url() -> None:
    ctx = _tnufa_ctx(service_url=None)
    result = await query_tnufa_events(
        ctx,
        where="City = 'נהריה'",
        out_fields="City,ModerateInjuries",
        orderByFields=None,
        limit=10,
    )
    assert isinstance(result, TnufaQueryResult)
    assert result.source == "mock"
    assert result.row_count == 1
    assert result.rows[0].City == "נהריה"
    assert result.rows[0].ModerateInjuries == 3
    assert result.rows[0].TotalInjuries is None


@pytest.mark.asyncio
async def test_query_tnufa_events_normalizes_tel_aviv_short_name() -> None:
    ctx = _tnufa_ctx(service_url=None)
    result = await query_tnufa_events(
        ctx,
        where="City = 'תל אביב'",
        out_fields="City,ModerateInjuries,SeriousInjuries,SevereInjuries,MinorInjuries",
        orderByFields=None,
        limit=10,
    )
    assert result.row_count == 1
    row = result.rows[0]
    assert row.City == "תל אביב - יפו"
    assert row.ModerateInjuries == 5
    assert row.SeriousInjuries == 2
    assert row.SevereInjuries == 1
    assert row.MinorInjuries == 40
    assert row.TotalInjuries == 48


@pytest.mark.asyncio
async def test_query_tnufa_events_total_injuries_requires_full_fields() -> None:
    ctx = _tnufa_ctx(service_url=None)
    result = await query_tnufa_events(
        ctx,
        where="City = 'ירושלים'",
        out_fields="*",
        orderByFields=None,
        limit=10,
    )
    assert result.row_count == 1
    row = result.rows[0]
    assert row.City == "ירושלים"
    assert row.TotalInjuries == 43


@pytest.mark.asyncio
async def test_query_tnufa_events_normalizes_english_tel_aviv() -> None:
    ctx = _tnufa_ctx(service_url=None)
    result = await query_tnufa_events(
        ctx,
        where="City = 'tel aviv'",
        out_fields="City,MinorInjuries",
        orderByFields=None,
        limit=10,
    )
    assert result.row_count == 1
    assert result.rows[0].City == "תל אביב - יפו"
    assert result.rows[0].MinorInjuries == 40


@pytest.mark.asyncio
async def test_query_tnufa_city_in_english_total() -> None:
    ctx = _tnufa_ctx(service_url=None)
    result = await query_tnufa_city(ctx, city="tel aviv", metric="total")
    assert result.row_count == 1
    row = result.rows[0]
    assert row.City == "תל אביב - יפו"
    assert row.TotalInjuries == 48


@pytest.mark.asyncio
async def test_query_tnufa_city_metric_minor() -> None:
    ctx = _tnufa_ctx(service_url=None)
    result = await query_tnufa_city(ctx, city="tel aviv", metric="minor")
    assert result.row_count == 1
    row = result.rows[0]
    assert row.City == "תל אביב - יפו"
    assert row.MinorInjuries == 40
    assert row.TotalInjuries is None


@pytest.mark.asyncio
async def test_query_tnufa_city_noisy_mixed_language_city_value() -> None:
    ctx = _tnufa_ctx(service_url=None)
    result = await query_tnufa_city(ctx, city="tel Aviv / נהתל", metric="total")
    assert result.row_count == 1
    row = result.rows[0]
    assert row.City == "תל אביב - יפו"
    assert row.TotalInjuries == 48


@pytest.mark.asyncio
async def test_query_tnufa_city_json_array_city_value() -> None:
    ctx = _tnufa_ctx(service_url=None)
    result = await query_tnufa_city(ctx, city='["חיפה"]', metric="total")
    assert result.row_count == 1
    row = result.rows[0]
    assert row.City == "חיפה"
    assert row.TotalInjuries == 28


@pytest.mark.asyncio
async def test_query_tnufa_city_invalid_argument_format_warning() -> None:
    ctx = _tnufa_ctx(service_url=None)
    result = await query_tnufa_city(ctx, city="[]", metric="total")
    assert result.row_count == 0
    assert result.source == "validation"
    assert result.warning is not None
    assert "Invalid city argument format" in result.warning


@pytest.mark.asyncio
async def test_query_tnufa_city_unknown_city_warning() -> None:
    ctx = _tnufa_ctx(service_url=None)
    result = await query_tnufa_city(ctx, city="atlantis", metric="total")
    assert result.row_count == 0
    assert result.warning is not None
    assert "No rows matched city" in result.warning


@pytest.mark.asyncio
async def test_query_tnufa_city_mixed_or_unsupported_script_warning() -> None:
    ctx = _tnufa_ctx(service_url=None)
    result = await query_tnufa_city(ctx, city="وלلל", metric="total")
    assert result.row_count == 0
    assert result.source == "validation"
    assert result.warning is not None
    assert "Unsupported or malformed city value" in result.warning


@pytest.mark.asyncio
async def test_get_tnufa_schema_mock_matches_fixture_field_names() -> None:
    ctx = _tnufa_ctx(service_url=None)
    schema = await get_tnufa_schema(ctx)
    assert isinstance(schema, TnufaSchemaResult)
    names = [f.name for f in schema.fields]
    assert names == [
        "City",
        "ModerateInjuries",
        "SeriousInjuries",
        "SevereInjuries",
        "MinorInjuries",
    ]

