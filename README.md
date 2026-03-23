# Open WebUI pilot (Mac dev → air-gapped Windows Server 2019)

Python **3.12.x** only (`open-webui` does not support Python 3.13+ yet). The UI and Mermaid/Vega assets ship inside the `open-webui` wheel, so **routine chat + diagrams work without loading JS from a CDN**.

## Quick start (this Mac)

1. Install [Ollama](https://ollama.com) and pull a model, e.g. `ollama pull llama3.2:3b`.
2. From this folder:

```bash
/opt/homebrew/bin/python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp env.example .env
./scripts/run-pilot.sh
```

3. Open [http://127.0.0.1:8080](http://127.0.0.1:8080).

## Offline / air-gap behaviour

- **`OFFLINE_MODE=true`** — sets `HF_HUB_OFFLINE=1` and turns off the version update check (see `open_webui/env.py` in the installed package).
- **`ENABLE_VERSION_UPDATE_CHECK=false`** — avoids outbound “is there a new release” calls.
- **Ollama** must already have models on disk (`ollama pull` while online, then copy the Ollama model directory if you clone machines).
- **First-time RAG / embeddings** may still need Hugging Face files downloaded while online; pure chat + Mermaid does not.

### Startup log: `LocalEntryNotFoundError` (Hugging Face)

With **`OFFLINE_MODE=true`** and an empty HF cache, you may see a **retrieval/embedding** error in the log on first boot. Chat and **Mermaid/Vega** still work if the server reaches “Started server process”. To remove the warning: run once with **`OFFLINE_MODE=false`** on a connected machine so default embedding assets can cache, **or** pre-populate the HF cache on the air-gapped box **or** avoid using RAG until models are local.

## Charts and diagrams (Open WebUI–native)

Open WebUI renders **diagrams and data charts from assistant messages** when the model uses the right **markdown fenced blocks**. The renderers ship **inside** the [`open-webui`](https://pypi.org/project/open-webui/) package (under `open_webui/frontend/`); you do **not** install Plotly or a separate “chart package” for this path, and you do **not** need a CDN for Mermaid/Vega on a closed network.

Official product context: [Open WebUI documentation](https://docs.openwebui.com/) (self-hosted / offline-capable UI).

### Diagrams → Mermaid

- Use a code fence with the language tag **`mermaid`** (not `graph`, `flowchart`, or `diagram`).
- Syntax reference: [Mermaid documentation](https://mermaid.js.org/).

### Numeric / data charts → Vega or Vega-Lite

- **Vega-Lite** (recommended for most charts): fence language **`vega-lite`**, body = valid JSON spec.
- **Vega**: fence language **`vega`**.
- Examples: [Vega-Lite gallery](https://vega.github.io/vega-lite/examples/).

### Best practice so models cooperate

1. Append the snippet in [`prompts/system-prompt-charts-and-diagrams.txt`](prompts/system-prompt-charts-and-diagrams.txt) to your **default system prompt** (Admin / workspace settings) or to a **model** system prompt.
2. Smoke-test the UI with a user message that contains only a `mermaid` block (see [docs/CLOSED-NETWORK-USB.md](docs/CLOSED-NETWORK-USB.md) §7).

### Optional: in-browser Python (Pyodide)

For numerical work, Open WebUI can run Python in the browser via **Pyodide** (enable/configure **Code Interpreter** in the Admin UI for your version). Bundled packages are **fixed** in the wheel’s Pyodide lockfile (e.g. **matplotlib** is available; **Plotly** is not bundled there). On a **strict** air gap, avoid `micropip.install` for extra packages. Prefer **Mermaid** or **Vega-Lite** in markdown for portable, offline-friendly charts.

### Moving to a closed network (USB)

See **[docs/CLOSED-NETWORK-USB.md](docs/CLOSED-NETWORK-USB.md)** for the full list of wheels, venv, `data/`, Ollama blobs, and optional Hugging Face cache.

## Windows Server 2019 (no Docker)

1. Install Python **3.12** and Ollama for Windows.
2. Copy this directory (including `.venv` **or** `requirements.txt` + `wheels-offline` from `scripts/vendor-wheels.sh`).
3. If air-gapped: `pip install --no-index --find-links=wheels-offline -r requirements.txt` inside a new venv.
4. Run `scripts\run-pilot.ps1` (or set the same env vars as `env.example` and run `open-webui serve`).

## Layout

| Path | Purpose |
|------|--------|
| `data/` | SQLite DB, uploads (created automatically; gitignored) |
| `requirements.txt` | Pinned deps from the working pilot (`open-webui` 0.8.8) |
| `wheels-offline/` | Optional wheelhouse for air-gap install (`scripts/vendor-wheels.sh`) |
| `docs/CLOSED-NETWORK-USB.md` | What to copy for offline / USB transfer |
| `prompts/system-prompt-charts-and-diagrams.txt` | System prompt addition for Mermaid / Vega-Lite output (model-facing text only) |
| `prompts/snippet-xy-plot-vega-lite.txt` | Example `vega-lite` block for an x–y line plot (copy into chat) |
