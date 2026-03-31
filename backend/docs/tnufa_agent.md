# Tnufa agent (תנופה)

Specialist agent for **injury counts by city**: one row per city with integer fields for moderate, serious, severe, and minor injuries. Data is exposed as an ArcGIS FeatureLayer query; when `TNUFA_SERVICE_URL` is unset, the stack uses the offline fixture `mocks/mockTnufaEvents.json` via `mocks/tnufa_mock.py`.

## When the Tnufa agent runs

The chat pipeline sends a turn to Tnufa when any of the following hold:

1. **Keyword / domain**: Hebrew (`תנופה`, `פצועים`, `נפגעים`, …) or explicit `tnufa`.
2. **English pattern**: injury / casualty / wounded language together with city language or a **data question** (`how many`, `top`, `statistics`, …)—see `_looks_like_tnufa_data_request` in `main.py`.
3. **Router model**: the small router agent returns `route: "tnufa"` for injury-by-city questions that did not match the heuristic first.

Other data questions go to **esri** (catalog GIS) or **unknown_data** when they do not match Tnufa or the catalog.

## Tools (Pydantic AI)

| Tool | Role |
|------|------|
| `get_tnufa_schema` | Field names and types (from the live layer `.../0?f=json` or from the mock JSON `fields`). |
| `query_tnufa_events` | `where`, `out_fields`, `orderByFields`, `limit` → `rows`, `row_count`, and optionally ArcGIS debug metadata when using a real URL. |

Agent instructions live in `agent.py` as `TNUFA_INSTRUCTIONS` (field names, SQL tips, grounding rules).

## Layer fields (exact names)

Use these in `where` and `orderByFields`:

- `City` (string, Hebrew municipal names in the fixture)
- `ModerateInjuries`, `SeriousInjuries`, `SevereInjuries`, `MinorInjuries` (integers)

## Query patterns

- Single city (exact name as in data): `City = 'חיפה'`
- Prefix / variants (e.g. Tel Aviv vs. `תל אביב - יפו`): `City LIKE 'תל אביב%'`
- All cities (subject to `limit`): `where='1=1'`
- Rankings: `orderByFields='ModerateInjuries DESC'`, set `limit` for N cities
- Filter non-zero serious injuries: `SeriousInjuries > 0`

Real ArcGIS REST accepts richer SQL; the **mock** supports a small subset (single conditions, `AND` / `OR`, `LIKE` with `%` / `_`). Invalid `where` strings return no rows in mock—do not rely on that matching production ArcGIS behavior byte-for-byte.

## Mock fixture

- **File**: `backend/mocks/mockTnufaEvents.json`
- **Cities**: 25 rows (Hebrew names). Examples: `חיפה`, `תל אביב - יפו`, `ירושלים`, `מודיעין-מכבים-רעות`, `באר שבע`, `נצרת`, … In this fixture, 11 cities have `SeriousInjuries > 0` and 7 have `SevereInjuries > 0` (see tests for exact sets).
- **Implementation**: `mocks/tnufa_mock.py` implements filtering/sorting for local tests without HTTP.

## Tests

From `backend/` (with dev dependencies installed):

```bash
.venv/bin/python -m pytest -q tests/test_tnufa_routing_and_mock.py
```

Routing tests cover when Tnufa is selected; mock tests assert row counts and field values from `mockTnufaEvents.json`.

## Configuration

- `TNUFA_SERVICE_URL`: optional base URL for the real FeatureServer (layer `0` queried). If empty, tools use the mock.
