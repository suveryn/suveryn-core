# engine

The model client and the shared answer schema.

| Module | Contents |
|---|---|
| `schemas.py` | `ChatRequest`, `ChatResponse`, `Citation`, `SourceRef`, `Calculation`, `StreamStatus`, `StreamDelta`, `StreamError`: the API's request and answer shapes, shared with `chat` and `rag` |
| `llm.py` | `LlamaServerClient`, an async client for llama-server: health, whole answers, streaming. With `user=`, each call's token counts go to its `on_usage` hook |
| `usage.py` | `UsageRecord` (user, kind, model, prompt/completion tokens; never text) and the `UsageRecorder` hook: token usage is captured here, once, for every model call (suveryn-tracker#7); the gateway stores it |
| `config.py` | `LLMSettings` from `SUVERYN_LLM_BASE_URL`, `SUVERYN_LLM_DEFAULT_MODEL`, `SUVERYN_LLM_TIMEOUT_S` |

Key points for reviewers:

- **Every answer has `citations`.** For a grounded answer it holds the passages given to the model (`[n]` → `citations[n-1]`); an empty list means unsourced. See [invariants](../../docs/architecture.md#4-invariants-what-must-stay-true).
- **Requests are bounded:** at most 200 messages of 100,000 characters, `max_tokens` up to 8192, and the last message must be the user's.
- **No model is hard-coded.** The served model is read from llama-server's `/v1/models`. Qwen3.8-27B is the default, and Mistral Small 3.2 24B works unchanged.
- **`cache_prompt` is on.** Follow-up questions on the same document reuse llama-server's cache (about 6× faster in the [benchmark](https://github.com/suveryn/suveryn-docs/blob/main/benchmarks/2026-10-hardware-benchmark.md)). That cache holds personal data; see [where confidential data lives](../../docs/architecture.md#3-where-confidential-data-lives).
- **Nothing is logged** by this package.
