# LLM Setup Guide

This pipeline uses a local LLM to extract bond terms from prospectus text (Stage 5b).
The model runs entirely on your machine — no data leaves your environment.

---

## What you need

- [Ollama](https://ollama.com) installed and running
- At least one model pulled (see [Model recommendations](#model-recommendations))
- A `.env` file at the project root with your connection parameters

---

## Step 1 — Install Ollama

If you have not installed Ollama yet:

```bash
# macOS
brew install ollama

# Linux
curl -fsSL https://ollama.com/install.sh | sh

# Windows
# Download the installer from https://ollama.com/download
```

Start the Ollama service (macOS: it starts automatically after install; Linux: `ollama serve`).

Verify it is running:

```bash
curl http://localhost:11434
# → "Ollama is running"
```

---

## Step 2 — Pull a model

Pull the default model used by this pipeline:

```bash
ollama pull qwen3-vl:8b
```

Verify it downloaded:

```bash
ollama list
# NAME              ID            SIZE    MODIFIED
# qwen3-vl:8b       ...           5.2 GB  ...
```

See [Model recommendations](#model-recommendations) for alternatives.

---

## Step 3 — Create your .env file

Copy the example file and edit it:

```bash
cp .env.example .env
```

Open `.env` and set `OLLAMA_MODEL` to match exactly what `ollama list` shows:

```
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=qwen3-vl:8b
```

The `.env` file is git-ignored and never committed. You only need to set variables
that differ from the defaults. For a standard local setup, the two lines above are
the only ones you need.

### All available parameters

| Variable | Default | Description |
|---|---|---|
| `OLLAMA_BASE_URL` | `http://localhost:11434` | URL of the Ollama instance |
| `OLLAMA_MODEL` | `qwen3-vl:8b` | Model tag (must match `ollama list`) |
| `OLLAMA_TIMEOUT` | `600.0` | Per-request timeout in seconds |
| `OLLAMA_NUM_CTX` | `8192` | Context window in tokens |
| `OLLAMA_TEMPERATURE` | `0.0` | Sampling temperature (0 = deterministic) |

---

## Step 4 — Verify the setup

Run the pipeline tests, skipping anything that does not need Ollama:

```bash
.venv/bin/python -m pytest tests/ -v -m "not requires_ollama"
```

To run the full integration test (requires a pulled model and running Ollama):

```bash
.venv/bin/python -m pytest tests/test_stage5b_llm.py -v
```

A successful run looks like:

```
tests/test_stage5b_llm.py::TestOllamaIntegration::test_extract_identifiers_geopark PASSED
```

---

## Model recommendations

| Model | Pull command | VRAM | Notes |
|---|---|---|---|
| `qwen3-vl:8b` | `ollama pull qwen3-vl:8b` | ~5.2 GB | **Default. Vision-language model; handles text and layout equally well.** |
| `qwen2.5:7b` | `ollama pull qwen2.5:7b` | ~4.7 GB | Strong text-only alternative. Slightly faster than qwen3-vl. |
| `qwen2.5:14b` | `ollama pull qwen2.5:14b` | ~9 GB | Noticeably more accurate on complex tables. Recommended if you have the VRAM. |
| `phi3.5:mini` | `ollama pull phi3.5` | ~2.2 GB | Smallest option. Adequate for simple prospectuses; struggles with multi-bond documents. |
| `mistral:7b` | `ollama pull mistral` | ~4.1 GB | Solid alternative to qwen2.5:7b. |
| `llama3.1:8b` | `ollama pull llama3.1` | ~4.7 GB | Good general-purpose option. |

**Key requirements for this pipeline:**
- Minimum 8K context window (all models above satisfy this)
- Reliable JSON output (all models above support Ollama's `format: json` mode)

Set your chosen model in `.env`:

```
OLLAMA_MODEL=qwen2.5:14b
```

---

## Running Ollama on a different machine

If Ollama runs on a remote server or a different port, set `OLLAMA_BASE_URL`:

```
OLLAMA_BASE_URL=http://192.168.1.100:11434
OLLAMA_MODEL=qwen3-vl:8b
```

Standard Ollama has no authentication. If your instance is behind a reverse proxy
with HTTP basic auth, contact the project maintainer — backend-level auth support
can be added to `OllamaBackend` in `pipeline/llm_backend.py`.

---

## Troubleshooting

**`Cannot connect to Ollama at http://localhost:11434. Is it running?`**
- Ollama is not running. Start it: `ollama serve` (Linux) or open the Ollama app (macOS/Windows).

**`Ollama HTTP 404: model 'qwen3-vl:8b' not found`**
- The model has not been pulled. Run `ollama pull qwen3-vl:8b`.
- Or your `OLLAMA_MODEL` in `.env` does not match `ollama list` exactly.

**Extraction is very slow (>2 min per bond)**
- Normal for first run — the model loads into memory on the first request.
- Subsequent calls are faster. If consistently slow, try a smaller model or increase `OLLAMA_TIMEOUT`.

**LLM returns empty fields or wrong values**
- Check `data/output/debug/{fixture}_stage4_tables.txt` — this shows exactly what text the LLM receives. If the table detection failed (low signal text), the LLM has little to work with.
- Try a larger model (`qwen2.5:14b`).
- Increase `OLLAMA_NUM_CTX` if the section text is very long.
