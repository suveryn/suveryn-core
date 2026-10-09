# chat

Turns a conversation into an answer: either a plain model answer, or one grounded in the user's documents with numbered citations.

| Module | Contents |
|---|---|
| `service.py` | `ChatService`: `answer()` (whole answer) and `answer_stream()` (`Delta` events, then one `Done`) |
| `grounding.py` | Prompt assembly for grounded answers, and citation-marker parsing |

## How a grounded answer is made

1. The gateway passes the request's `document_ids` to the service.
2. The service gets the passages to answer from (`rag` `Rag.passages`):
   - **small documents** (together at most ~48,000 characters, about 15–20 pages, and 99 passages): *all* their passages, in reading order, so a general question ("what is this document about?") sees the whole text;
   - **larger documents:** the 6 best passages for the last question, from the hybrid search in `packages/rag`.

   The excerpts are headed by which of the two it is, so the model knows whether "not in the excerpts" means "not in the document" or only "not in the passages selected".
3. The model gets:
   - instructions: answer only from the excerpts; cite every statement, name, number and date as `[n]`; copy figures exactly; don't calculate; say so if the answer isn't there;
   - the earlier turns;
   - the numbered excerpts;
   - the question, last, so llama-server can reuse its prompt cache.
4. The answer comes back with `citations` = those passages in the same order. **Marker `[n]` refers to `citations[n-1]`**: the positional contract the chat UI relies on. Passages the answer doesn't cite are still listed; clients show only the cited ones.

Without `document_ids`, `citations` is empty and the answer must be shown as unverified.

## Not here yet

- **Conversation state:** the client sends the earlier turns with every request; nothing about a conversation is stored server-side.
- **Answer checking:** verifying that every name, number and date in the answer appears in a cited passage (design point 5 in `docs/architecture.md`).
- **Summaries queued at upload** (development context §4).
