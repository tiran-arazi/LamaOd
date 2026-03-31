"""Tnufa offline mock — **remove this module** when only the real ArcGIS URL is needed.

All mock-only logic lives here so ``tools/tnufa.py`` stays small.

**To drop mock support later**

1. Delete this file (and optionally ``mockTnufaEvents.json`` in this folder).
2. In ``tools/tnufa.py``: remove ``from mocks import tnufa_mock`` and the ``else`` branches
   that call it; require ``TNUFA_SERVICE_URL`` in config (or raise when unset).
"""

from __future__ import annotations

import json
import operator
import re
from pathlib import Path
from typing import Any

# Fixture next to this module
MOCK_JSON_PATH = Path(__file__).resolve().parent / "mockTnufaEvents.json"

_OPS: dict[str, Any] = {
    "=": operator.eq,
    "!=": operator.ne,
    "<>": operator.ne,
    ">": operator.gt,
    ">=": operator.ge,
    "<": operator.lt,
    "<=": operator.le,
}

_CONDITION_RE = re.compile(
    r"^\s*(\w+)\s*(=|!=|<>|>=|<=|>|<|LIKE)\s*(?:'((?:''|[^'])*)'|(\d+(?:\.\d+)?))\s*$",
    re.IGNORECASE,
)


def _load_fixture() -> dict[str, Any]:
    return json.loads(MOCK_JSON_PATH.read_text(encoding="utf-8"))


def _split_sql(expr: str, keyword: str) -> list[str]:
    """Split by SQL keyword while preserving quoted strings."""
    chunks: list[str] = []
    buf: list[str] = []
    i = 0
    in_quote = False
    n = len(expr)
    key = keyword.lower()
    key_len = len(keyword)

    while i < n:
        ch = expr[i]
        if ch == "'":
            in_quote = not in_quote
            buf.append(ch)
            i += 1
            continue
        if not in_quote and expr[i : i + key_len].lower() == key:
            left_ok = i == 0 or expr[i - 1].isspace()
            right_ok = i + key_len >= n or expr[i + key_len].isspace()
            if left_ok and right_ok:
                part = "".join(buf).strip()
                if part:
                    chunks.append(part)
                buf = []
                i += key_len
                continue
        buf.append(ch)
        i += 1

    tail = "".join(buf).strip()
    if tail:
        chunks.append(tail)
    return chunks


def _like_match(value: Any, pattern: str) -> bool:
    if value is None:
        return False
    escaped = re.escape(pattern).replace("%", ".*").replace("_", ".")
    return re.fullmatch(escaped, str(value), flags=re.IGNORECASE) is not None


def _eval_condition(row: dict[str, Any], cond: str) -> bool:
    m = _CONDITION_RE.match(cond)
    if not m:
        return False
    field, op_str, str_val, num_val = m.groups()
    cell = row.get(field)
    if cell is None:
        return False
    op_up = op_str.upper()
    if str_val is not None:
        target: Any = str_val.replace("''", "'")
    elif num_val is not None:
        target = float(num_val) if "." in num_val else int(num_val)
    else:
        return False
    if op_up == "LIKE":
        return _like_match(cell, str(target))
    return _OPS[op_str](cell, target)


def _matches_where(row: dict[str, Any], where: str) -> bool:
    w = (where or "").strip()
    if not w or w == "1=1":
        return True
    # Support a tiny SQL subset:
    #   cond [AND cond ...] [OR cond [AND cond ...] ...]
    # where each cond is "Field OP value".
    or_groups = _split_sql(w, "OR")
    if not or_groups:
        return False
    for group in or_groups:
        and_conds = _split_sql(group, "AND")
        if and_conds and all(_eval_condition(row, c) for c in and_conds):
            return True
    return False


def _sort_rows(rows: list[dict[str, Any]], order_by: str | None) -> list[dict[str, Any]]:
    if not order_by:
        return rows
    parts = [p.strip() for p in order_by.split(",")]
    for part in reversed(parts):
        tokens = part.split()
        field = tokens[0]
        desc = len(tokens) > 1 and tokens[1].upper() == "DESC"
        rows = sorted(rows, key=lambda r, f=field: (r.get(f) is None, r.get(f)), reverse=desc)
    return rows


def schema_fields_raw() -> list[dict[str, Any]]:
    """Layer ``fields`` array as in the mock JSON."""
    return list(_load_fixture().get("fields", []))


def query(
    where: str,
    out_fields: str,
    order_by_fields: str | None,
    limit: int,
) -> dict[str, Any]:
    """Return filtered rows like a tiny in-process feature query."""
    data = _load_fixture()
    all_names = [f["name"] for f in data.get("fields", [])]
    wanted = set(all_names) if out_fields.strip() == "*" else {f.strip() for f in out_fields.split(",")}

    rows: list[dict[str, Any]] = []
    for feat in data.get("features", []):
        attrs = feat.get("attributes", {})
        if _matches_where(attrs, where):
            rows.append({k: v for k, v in attrs.items() if k in wanted})

    rows = _sort_rows(rows, order_by_fields)
    rows = rows[:limit]
    return {"rows": rows}
