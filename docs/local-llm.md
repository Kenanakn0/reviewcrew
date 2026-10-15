# Running ReviewCrew with a local model (Ollama)

ReviewCrew talks to any OpenAI-compatible endpoint, so it can run entirely on your own
machine for free with [Ollama](https://ollama.com). `.env.example` is set up for this.

## 1. Install Ollama and pull a model

Windows: `winget install Ollama.Ollama` (or the installer from ollama.com). macOS/Linux: see
ollama.com/download. Then:

```bash
ollama pull qwen2.5-coder:7b
```

`qwen2.5-coder:7b` (about 4.7 GB) is a good default for a desktop. Larger models such as
`qwen2.5-coder:14b` review better if your hardware allows.

## 2. Give the model enough context

Ollama's default context window is only 4k tokens on machines with less than 24 GB of VRAM.
A review prompt (instructions + diff chunk + answer) needs more, and a prompt that does not
fit is cut off silently, which produces poor reviews. Use at least 16k:

- **Windows:** in the Ollama app's settings set *Context length* to 16k, or run
  `setx OLLAMA_CONTEXT_LENGTH 16384` and restart Ollama (quit it from the tray first).
- **macOS/Linux:** `OLLAMA_CONTEXT_LENGTH=16384 ollama serve`

Keep `DIFF_MAX_TOKENS_PER_CHUNK` (4000 in `.env.example`) well below the context length.

## 3. Configure ReviewCrew

These are the defaults in `.env.example`:

```dotenv
LLM_PROVIDER=openai_compat
LLM_MODEL=qwen2.5-coder:7b
OPENAI_COMPAT_BASE_URL=http://localhost:11434/v1
OPENAI_COMPAT_BASE_URL_DOCKER=http://host.docker.internal:11434/v1
LLM_MAX_CONCURRENCY=1
LLM_TIMEOUT_SECONDS=600
DIFF_MAX_TOKENS_PER_CHUNK=4000
```

`OPENAI_COMPAT_BASE_URL` is used when you run `uv run reviewcrew-worker` on the host;
`docker compose` uses `OPENAI_COMPAT_BASE_URL_DOCKER`, because inside a container
`localhost` is the container itself. No Anthropic key is needed.

Check that the endpoint answers:

```bash
curl http://localhost:11434/v1/models
```

If the containers cannot reach Ollama (connection refused in the worker log), make Ollama
listen on all interfaces with `OLLAMA_HOST=0.0.0.0:11434` and restart it. That also exposes
it to your local network, so keep your firewall in place.

## 4. What to expect

- **Speed:** a 7B model on a laptop CPU can take a minute or more per agent call; with a
  GPU it is much faster. `LLM_MAX_CONCURRENCY=1` avoids overloading the machine. Raise it
  if Ollama is configured to serve requests in parallel (`OLLAMA_NUM_PARALLEL`).
- **Quality:** small models miss more issues and report more false positives than large
  hosted models. Measure it on your hardware with `uv run python -m eval.run`; the report
  states which model produced the numbers.
- **Formatting:** ReviewCrew sends the JSON schema with every request (Ollama enforces it)
  and still tolerates the usual small-model slips: JSON wrapped in Markdown fences or prose,
  severity in the wrong case, omitted optional fields. A single malformed finding is
  dropped instead of discarding the whole answer; an unusable answer is retried once and,
  if it fails again, reported in the review summary while the other agents' findings are
  still posted.
