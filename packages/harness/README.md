# harness

Everything between a question and the model, and between the model and the person: what the model is
given, how it is called, and how its answer is checked before anyone sees it. Storage, rights and
screens are not here; they are the gateway's and the UI's. **Start with
[docs/harness.md](../../docs/harness.md)**, which follows one question through these modules.

| Module | Contents |
|---|---|
| `service.py` | `ChatService`: `answer()` (whole answer) and `answer_stream()` (`Status` events for each pipeline step, `Sources`, `Delta` events, then one `Done`). The pipeline: passages, prompt, model, checks |
| `grounding.py` | The grounded prompt (`GROUNDED_INSTRUCTIONS`, the numbered excerpts, the reminders before the question) and citation-marker parsing |
| `guard.py` | Document text is data, never instructions: chat-template control tokens made inert (`neutralise`), text addressed to an AI detected (`instruction_like`, suveryn-tracker#21) |
| `calc.py` | Server-side arithmetic: replaces `[[calc: …]]` markers with exact results and checks their figures (see [Calculations](#calculations)) |
| `support.py` | Each citation checked against its own passage: the figures, dates, years and names of the claim before a marker must be in the passage it cites (`citation_issues`, suveryn-tracker#11). By rule, without another model call |
| `facts.py` | A playbook's facts: asks for the playbook's table (once more, stricter, when it isn't one) and reads each fact with its passages and the same checks (`read_playbook`, `read_facts`) |
| `llm.py` | `LlamaServerClient`, an async client for llama-server: health, whole answers, streaming, stopping (closing the stream closes the connection, so llama-server stops). Every message is sent `neutralise`d. With `user=`, each call's token counts go to its `on_usage` hook |
| `schemas.py` | `ChatRequest`, `ChatResponse`, `Citation`, `SourceRef`, `Calculation`, `CitationIssue` and the stream events: the API's request and answer shapes, shared with `rag` and the gateway |
| `usage.py` | `UsageRecord` (user, kind, model, prompt/completion tokens; never text) and the `UsageRecorder` hook: token usage is captured here, once, for every model call (suveryn-tracker#7); the gateway stores it |
| `audit.py` | Audit events (ids, pages and kinds; never text), such as passages that address an AI |
| `config.py` | `LLMSettings` from `SUVERYN_LLM_BASE_URL`, `SUVERYN_LLM_DEFAULT_MODEL`, `SUVERYN_LLM_TIMEOUT_S` |

Key points for reviewers:

- **Every answer has `citations`.** For a grounded answer it holds the passages given to the model (`[n]` → `citations[n-1]`); an empty list means unsourced. See [invariants](../../docs/architecture.md#4-invariants-what-must-stay-true).
- **Requests are bounded:** at most 200 messages of 100,000 characters, `max_tokens` up to 8192, and the last message must be the user's.
- **No model is hard-coded.** The served model is read from llama-server's `/v1/models`. Qwen3.8-27B is the default, and Mistral Small 3.2 24B works unchanged.
- **`cache_prompt` is on.** Follow-up questions on the same document reuse llama-server's cache (about 6× faster in the [benchmark](https://github.com/suveryn/suveryn-docs/blob/main/benchmarks/2026-10-hardware-benchmark.md)). That cache holds personal data; see [where confidential data lives](../../docs/architecture.md#3-where-confidential-data-lives).
- **No document text is logged** by this package; audit events carry ids, pages and kinds.
- **A change in a prompt is a change in behaviour.** Prompt texts carry the reason they are worded as they are (a model and a test that showed it); keep that when changing them, and run the end-to-end answer tests (`packages/rag/tests/test_answers_e2e.py`) against the models in use.

## How a grounded answer is made

1. The gateway passes the request's `document_ids` to the service.
2. The service gets the passages to answer from, searching for the last question together with the user's question before it (`search_text`: a follow-up such as "bereken die" names nothing to search for on its own) ([`Rag.passages`](../rag/src/suveryn_rag/pipeline.py) in `packages/rag`: retrieval is outside the harness, behind the `Retriever` interface):
   - **small documents** (together at most ~48,000 characters, about 15–20 pages, and 99 passages): *all* their passages, in reading order, so a general question ("what is this document about?") sees the whole text;
   - **larger documents:** their passages that best match the last question, as many as fit the same budget (at least 6), in reading order: every passage is ranked by the hybrid search in `packages/rag` (`Store.best_chunks`). A 58-page deed gets about two thirds of its text this way instead of 6 passages.

   The excerpts are headed by which of the two it is, so the model knows whether "not in the excerpts" means "not in the document" or only "not in the passages selected".
3. The model gets:
   - instructions: answer only from the excerpts; cite every statement, name, number and date as `[n]`; copy figures exactly; never do arithmetic, but write a calculation as `[[calc: …]]` (see below); say so if the answer isn't there;
   - the earlier turns;
   - the numbered excerpts;
   - the question, last, so llama-server can reuse its prompt cache.
4. The answer comes back with `citations` = those passages in the same order. **Marker `[n]` refers to `citations[n-1]`**: the positional contract the chat UI relies on. Passages the answer doesn't cite are still listed; clients show only the cited ones.

Without `document_ids`, `citations` is empty and the answer must be shown as unverified.

## Not here yet

- **Conversation state:** the client sends the earlier turns with every request (the chat UI: the last 40 messages, completed answers only; `lib/history.ts`). Saving conversations is the gateway's job, not this package's.
- **Checking meaning:** citations are checked for their facts (`support.py`), not for what the claim says about them (see [known limitations](../../docs/architecture.md#6-known-limitations)).
- **Summaries made at upload:** a short summary per document, queued with ingestion, so that general questions about documents too large to give whole can still be answered.

## Calculations

Language models make arithmetic mistakes, so the model never calculates. When a total, difference, ratio, share or average is asked for, also when the documents don't describe how to calculate it, it writes `[[calc: 6.507,11 + 6.417,42]]`, with the figures copied exactly from the excerpts. `calc.py` then:

1. computes it exactly (`Decimal`, a small parser, never `eval`), with + - * /, brackets and signs;
2. keeps the figures' number style (`6.507,11`, `6,507.11`, `6 507,11`) and refuses, rather than guesses, when a figure is ambiguous (`1.250 + 3.000` could mean either) or the figures mix styles (`1.5 + 2,25`). Sums keep the decimals of the most precise figure; products keep their exact decimals (up to 6); divisions, and anything after one, are rounded half up to at least 2. A share as a percentage is written `a / (a + b) * 100`;
3. replaces the marker with `6.507,11 + 6.417,42 = 12.924,53`, also while streaming (a marker split across chunks is held back until it is complete);
4. checks every figure, as a whole number, against the passages the answer cites, and lists any it can't find. Before that check, figures the cited passages don't hold are looked up in the other passages the model was given; the system adds markers for the fewest passages that hold them after the result (`… = 12.924,53 [3]`), so every figure can be checked at its source even when the model cited nothing (rarer since earlier answers reach the model with their markers as [*], and the last words before the question ask for citations). The streamed text gets these markers with the final `done` answer. A figure in none of the passages gets no marker and is listed. The factor `100` of a percentage is not a figure from a document and isn't checked.

The response's `calculations` list holds each one (`expression`, `result`, `figures_not_in_sources`, `error`). The chat UI shows a note under the answer: *Calculated by sūveryn, not read from the documents*, with a warning if a figure isn't in the sources or the calculation couldn't be done.

**Figures the model writes itself.** The model can still put a figure in its text without a calculation (seen with Qwen: a partial sum worked out in passing). `unverified_figures` lists every figure in the answer text that is in none of the passages given, is no calculation's result, and wasn't in the user's own questions. Values are compared, so `410.000` matches `410.000,00`. Figures with a grouping or decimal separator, and plain numbers of five digits or more, are checked; plain numbers up to four digits (plot 1, page 57, 2026) and dates are not. The chat UI underlines them and asks the reader to check them.
