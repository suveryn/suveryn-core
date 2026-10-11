"""Document text is data, never instructions (suveryn-tracker#21).

Uploaded documents reach the model as quoted excerpts. Two things could make such text act as more
than data, and this module handles both:

- **Chat-template control tokens.** llama-server renders the conversation with the model's chat
  template and then tokenises it *with special tokens recognised*. A PDF containing ``<|im_start|>``
  (Qwen), ``[INST]`` or ``[SYSTEM_PROMPT]`` (Mistral) would otherwise become a real turn boundary,
  letting the document speak as "system". ``neutralise`` breaks every such sequence with a zero-width
  space, so it is tokenised as ordinary text; what a reader sees is unchanged.
- **Text addressed to an AI.** "Ignore all previous instructions", "negeer de bovenstaande
  instructies", "tu es maintenant…", role headers ("### System:"), and the like. They can't be
  removed reliably, so they are *detected* (``instruction_like``): the model is told excerpts are
  data, the answer says a passage contained such text, and the gateway logs it (kinds and places
  only, never the text). Detection is a signal for the reader, not a guarantee.

Nothing here changes stored documents or cited passages; it applies to the prompt and to warnings.
"""

import re

ZWSP = "\u200b"

# Turn and role markers of the chat templates sūveryn's models use (Qwen: ChatML; Mistral: [INST],
# [SYSTEM_PROMPT]) and of other common templates, plus reasoning tags.
CONTROL = re.compile(
    r"<\|[a-z_]{2,30}\|>|\[/?(?:INST|SYSTEM_PROMPT|AVAILABLE_TOOLS|TOOL_CALLS|TOOL_RESULTS)\]|</?s>|<</?SYS>>"
    r"|<(?:start|end)_of_turn>|</?think>",
    re.IGNORECASE)

# Text addressed to an AI, in English, Dutch and French. Each pattern has a short kind for logs.
INSTRUCTION_LIKE: list[tuple[str, re.Pattern]] = [(kind, re.compile(p, re.IGNORECASE)) for kind, p in [
    ("ignore-instructions",
     (r"\b(?:ignore|disregard|forget)\b.{0,40}\b(?:previous|prior|above|earlier|all|your|these)\b.{0,30}\b(?:instructions?|rules|prompts?|directions)"
     r"|\b(?:negeer|vergeet)\b.{0,40}\b(?:vorige|eerdere|bovenstaande|alle|je|uw|deze)\b.{0,30}\b(?:instructies?|regels|opdrachten?)"
     r"|\b(?:ignorez|ignore|oubliez)\b.{0,40}\b(?:précédentes?|precedentes?|toutes|vos|ces)\b.{0,30}\b(?:instructions?|règles|consignes)")),
    ("role-change",
     (r"\byou are now\b|\bfrom now on,? you\b|\bact as (?:an? )?(?:ai|assistant|chatbot|language model)\b"
     r"|\bje bent nu\b|\bu bent nu\b|\bvanaf nu ben (?:je|u)\b|\btu es (?:maintenant|désormais)\b|\bvous êtes (?:maintenant|désormais)\b")),
    ("addressed-to-ai",
     (r"\b(?:as an? |dear |attention,? |note to (?:the )?)(?:ai|llm|assistant|chatbot|language model)\b"
     r"|\b(?:system prompt|systeemprompt|prompt système|invite système)\b"
     r"|\b(?:aan de|à l'|to the) (?:ai|ia|assistent|assistant)\b")),
    ("role-header", r"(?m)^\s*(?:#{1,6}\s*)?(?:system|assistant|systeem|système)\s*:"),
    ("control-token", CONTROL.pattern),
]]


def neutralise(text: str) -> str:
    """``text`` with every chat-template control sequence broken by a zero-width space."""
    return CONTROL.sub(lambda m: m.group(0)[0] + ZWSP + m.group(0)[1:], text)


def instruction_like(text: str) -> list[str]:
    """The kinds of AI-addressed text found in ``text`` (e.g. ``["ignore-instructions"]``), in order."""
    return [kind for kind, pattern in INSTRUCTION_LIKE if pattern.search(text)]
