# engine

The model client and the shared answer schema.

| Module | Contents |
|---|---|
| `schemas.py` | `ChatRequest`, `ChatResponse`, `Citation`, `SourceRef`: the API's answer shape, shared with `rag` |
| `llm.py` | `LlamaServerClient`, an async client for llama-server: health, whole answers, streaming |
| `config.py` | `LLMSettings` from `SUVERYN_LLM_BASE_URL`, `SUVERYN_LLM_DEFAULT_MODEL`, `SUVERYN_LLM_TIMEOUT_S` |

Key points for reviewers:

- **Every answer has `citations`.** Until slice 3 connects retrieval to chat, the list is empty, which means unsourced. See `docs/architecture.md` §4.
- **No model is hard-coded.** The served model is read from llama-server's `/v1/models`. Qwen3.8-27B is the default, and Mistral Small 3.2 24B works unchanged.
- **`cache_prompt` is on.** Follow-up questions on the same document reuse llama-server's cache (about 6× faster in the benchmark). That cache holds personal data; see `docs/architecture.md` §3.
- **Nothing is logged** by this package.
