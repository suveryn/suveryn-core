# chat

Turns a conversation into an answer: either a plain model answer, or one grounded in the user's documents with numbered citations.

| Module | Contents |
|---|---|
| `service.py` | `ChatService`: `answer()` (whole answer) and `answer_stream()` (`Status` events for each pipeline step, `Delta` events, then one `Done`) |
| `grounding.py` | Prompt assembly for grounded answers, and citation-marker parsing |
| `calc.py` | Server-side arithmetic: replaces `[[calc: …]]` markers with exact results and checks their figures (see [Calculations](#calculations)) |

## How a grounded answer is made

1. The gateway passes the request's `document_ids` to the service.
2. The service gets the passages to answer from, searching for the last question together with the user's question before it (`search_text`: a follow-up such as "bereken die" names nothing to search for on its own) ([`Rag.passages`](../rag/src/suveryn_rag/pipeline.py) in `packages/rag`):
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

- **Conversation state:** the client sends the earlier turns with every request; nothing about a conversation is stored server-side.
- **Answer checking:** verifying that every name, number and date in the answer appears in a cited passage (see [known limitations](../../docs/architecture.md#6-known-limitations)). Calculations already check their own figures.
- **Summaries made at upload:** a short summary per document, queued with ingestion, so that general questions about documents too large to give whole can still be answered.

## Calculations

Language models make arithmetic mistakes, so the model never calculates. When a total, difference, ratio, share or average is asked for, also when the documents don't describe how to calculate it, it writes `[[calc: 6.507,11 + 6.417,42]]`, with the figures copied exactly from the excerpts. `calc.py` then:

1. computes it exactly (`Decimal`, a small parser, never `eval`), with + - * /, brackets and signs;
2. keeps the figures' number style (`6.507,11`, `6,507.11`, `6 507,11`) and refuses, rather than guesses, when a figure is ambiguous (`1.250 + 3.000` could mean either) or the figures mix styles (`1.5 + 2,25`). Sums keep the decimals of the most precise figure; products keep their exact decimals (up to 6); divisions, and anything after one, are rounded half up to at least 2. A share as a percentage is written `a / (a + b) * 100`;
3. replaces the marker with `6.507,11 + 6.417,42 = 12.924,53`, also while streaming (a marker split across chunks is held back until it is complete);
4. checks every figure, as a whole number, against the passages the answer cites, and lists any it can't find. Before that check, figures the cited passages don't hold are looked up in the other passages the model was given; the system adds markers for the fewest passages that hold them after the result (`… = 12.924,53 [3]`), so every figure can be checked at its source even when the model cited nothing (typical for a follow-up, since earlier answers reach the model without their markers). The streamed text gets these markers with the final `done` answer. A figure in none of the passages gets no marker and is listed. The factor `100` of a percentage is not a figure from a document and isn't checked.

The response's `calculations` list holds each one (`expression`, `result`, `figures_not_in_sources`, `error`). The chat UI shows a note under the answer: *Calculated by sūveryn, not read from the documents*, with a warning if a figure isn't in the sources or the calculation couldn't be done.
