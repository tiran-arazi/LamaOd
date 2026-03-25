# Offline AI Data Explorer (MVP)

Local web UI plus a **FastAPI** backend that runs a **Pydantic AI** agent against **Ollama** and an **ArcGIS REST** catalog (MapServer / FeatureServer). The default catalog URL is Esri’s public sample server so you can try the flow without your own GIS; for a closed network, point `ARCGIS_CATALOG_URL` at your internal `.../arcgis/rest/services` root.

## Quick start (development)

1. **Python backend**

   ```bash
   cd backend
   python3 -m venv .venv
   source .venv/bin/activate   # Windows: .venv\Scripts\activate
   pip install -r requirements.txt
   cp ../.env.example ../.env   # optional; defaults match .env.example
   uvicorn main:app --reload --port 8000
   ```

2. **Ollama** with a tool-capable model. `.env.example` uses **`ollama:llama3.2:3b`** so it works after `ollama pull llama3.2:3b`. For **LFM2**, run `ollama pull lfm2` and set `OLLAMA_MODEL_SPEC=ollama:lfm2`.

   **`OLLAMA_BASE_URL` must end with `/v1`** (e.g. `http://127.0.0.1:11434/v1`). The backend uses the OpenAI-compatible API; without `/v1` you get `404 page not found` from Ollama.

   Restart the backend after changing `.env` (or use `--reload`).

3. **Frontend**

   ```bash
   cd frontend
   npm install
   npm run dev
   ```

   Open the Vite URL (usually http://localhost:5173). API calls proxy to port 8000.

## Single-process / offline-style serving (no Node in production)

Build the UI and let FastAPI serve `frontend/dist` from `/`:

```bash
cd frontend && npm run build
cd ../backend && source .venv/bin/activate && uvicorn main:app --host 0.0.0.0 --port 8000
```

Browse to http://127.0.0.1:8000/ — static assets and `/api/*` share one origin (good for air-gapped deploys).

## Moving to a Windows server on a closed network

- Set `ARCGIS_CATALOG_URL` to your portal/server REST root (same shape as the public URL, e.g. `http://your-server/arcgis/rest/services`). **Yes, the same code works on an internal ESRI/ArcGIS Server** as long as this host can reach that URL over HTTP(S) (firewall, DNS, TLS, and any auth are your ops concerns; anonymous REST access is what the sample expects).
- Set `OLLAMA_BASE_URL` to the OpenAI-compatible base, e.g. `http://127.0.0.1:11434/v1`.
- Open the host firewall for the HTTP port you choose for Uvicorn.
- Prefer the **build + single Uvicorn** flow above so the browser does not need access to npm or CDNs (the Vite bundle is self-contained).
- Increase `CATALOG_MAX_SERVICES` / indexing env vars if your catalog is small and you want fuller prompts.

## ArcGIS catalog indexing (once at start, or on demand)

The crawler lives in **`backend/arcgis_catalog_indexer.py`** (`ArcGISCatalogStore`). It does **not** learn weights; it **HTTP-crawls** the REST catalog and builds a text summary for the agent.

- **Default:** one crawl when the API **starts** (`CATALOG_INDEX_ON_STARTUP=true`).
- **No timer:** periodic background refresh was removed; re-run a crawl when you want.
- **CLI (clear name):** `backend/scripts/reindex_arcgis_rest_catalog.py` — same crawl, from the shell (optional `--write-json path.json`).
- **While the server runs:** `POST /api/catalog/reindex` (if `CATALOG_REINDEX_TOKEN` is set in `.env`, send header `X-Catalog-Reindex-Token: <token>`).

## API

- `POST /api/chat` — JSON body `{ "messages": [...] }`, SSE stream (`data: {json}` lines): `text_delta`, `tool_call`, `tool_result`, `done`, `error`.
- `GET /api/catalog` — current indexed catalog JSON.
- `POST /api/catalog/reindex` — re-run the ArcGIS crawl (optional `X-Catalog-Reindex-Token` if `CATALOG_REINDEX_TOKEN` is set).
- `GET /api/health` — liveness.

## Project layout

- `backend/arcgis_catalog_indexer.py` — ArcGIS REST catalog crawl for the agent prompt.
- `backend/scripts/reindex_arcgis_rest_catalog.py` — one-shot crawl from the command line.
- `backend/` — FastAPI, ArcGIS tools, Pydantic AI agent.
- `frontend/` — Vite + React + assistant-ui + Recharts + TanStack Table.
