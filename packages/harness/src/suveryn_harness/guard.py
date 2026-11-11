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

from .language import WORDS, any_of, words

ZWSP = "\u200b"

# Turn and role markers of the chat templates sūveryn's models use (Qwen: ChatML; Mistral: [INST],
# [SYSTEM_PROMPT]) and of other common templates, plus reasoning tags.
CONTROL = re.compile(
    r"<\|[a-z_]{2,30}\|>|\[/?(?:INST|SYSTEM_PROMPT|AVAILABLE_TOOLS|TOOL_CALLS|TOOL_RESULTS)\]|</?s>|<</?SYS>>"
    r"|<(?:start|end)_of_turn>|</?think>",
    re.IGNORECASE)

# Text addressed to an AI, in every language of ``language``: its words are in the languages' files, the shapes here.
_AI = any_of(words("ai_names"))
INSTRUCTION_LIKE: list[tuple[str, re.Pattern]] = [(kind, re.compile(p, re.IGNORECASE)) for kind, p in [
    # "ignore ... previous ... instructions", per language so one language's words aren't mixed with another's
    ("ignore-instructions", "|".join(
        rf"\b{any_of(t['ai_ignore'])}\b.{{0,40}}\b{any_of(t['ai_previous'])}\b.{{0,30}}\b{any_of(t['ai_instructions'])}"
        for t in WORDS.values())),
    ("role-change", r"\b" + any_of(words("ai_role_change"), space=" ") + r"\b"),
    ("addressed-to-ai",
     rf"\b{any_of(words('ai_address'), space=' ')} ?{_AI}\b|\b{any_of(words('ai_system_prompt'), space=' ')}\b"),
    ("role-header", r"(?m)^\s*(?:#{1,6}\s*)?" + any_of(words("ai_role_headers")) + r"\s*:"),
    ("control-token", CONTROL.pattern),
]]


def neutralise(text: str) -> str:
    """``text`` with every chat-template control sequence broken by a zero-width space."""
    return CONTROL.sub(lambda m: m.group(0)[0] + ZWSP + m.group(0)[1:], text)


def instruction_like(text: str) -> list[str]:
    """The kinds of AI-addressed text found in ``text`` (e.g. ``["ignore-instructions"]``), in order."""
    return [kind for kind, pattern in INSTRUCTION_LIKE if pattern.search(text)]
