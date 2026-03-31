"""Load settings from the process environment (see `.env.example`; use a root `backend/.env` copy)."""

from __future__ import annotations

import os
import ssl
import sys
from pathlib import Path

from dotenv import load_dotenv

_backend = Path(__file__).resolve().parent
_root = _backend.parent
load_dotenv(_root / ".env")
load_dotenv(_backend / ".env")


def _require(name: str) -> str:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        print(
            f"Missing required environment variable {name!r}. "
            "Copy `.env.example` to `.env` at the repo root (and/or `backend/.env`) and set it.",
            file=sys.stderr,
        )
        raise SystemExit(1)
    return raw.strip()


def _optional_str(name: str) -> str | None:
    """Like ``_require`` but returns ``None`` when unset or blank."""
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return None
    return raw.strip()


def _truthy(raw: str) -> bool:
    return raw.lower() in ("1", "true", "yes")


def _httpx_verify() -> bool | ssl.SSLContext:
    """Trust store for httpx (ArcGIS catalog, tools). Default matches urllib/ssl without forcing certifi."""
    raw = os.getenv("HTTPX_SSL_VERIFY", "").strip()
    if raw.lower() in ("0", "false", "no"):
        return False
    if raw:
        pem = Path(raw).expanduser()
        if pem.is_file():
            return ssl.create_default_context(cafile=str(pem))
    return ssl.create_default_context()


HTTPX_VERIFY = _httpx_verify()

OLLAMA_BASE_URL = _require("OLLAMA_BASE_URL")
OLLAMA_MODEL_SPEC = _require("OLLAMA_MODEL_SPEC")

ARCGIS_CATALOG_URL = _require("ARCGIS_CATALOG_URL")

TNUFA_SERVICE_URL = _optional_str("TNUFA_SERVICE_URL")

CATALOG_INDEX_ON_STARTUP = _truthy(_require("CATALOG_INDEX_ON_STARTUP"))
CATALOG_MAX_SERVICES = int(_require("CATALOG_MAX_SERVICES"))
CATALOG_MAX_LAYERS_FIELD_DETAIL = int(_require("CATALOG_MAX_LAYERS_FIELD_DETAIL"))

_cors_raw = _require("CORS_ORIGINS")
CORS_ORIGINS = [o.strip() for o in _cors_raw.split(",") if o.strip()]
if not CORS_ORIGINS:
    print("CORS_ORIGINS must list at least one origin (comma-separated).", file=sys.stderr)
    raise SystemExit(1)
