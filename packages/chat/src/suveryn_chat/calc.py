"""Exact arithmetic in grounded answers: the model chooses the figures, the server computes.

Language models make arithmetic mistakes, and a wrong total in a notarial answer is worse than
none. So the model never calculates itself: it writes a calculation as a marker,
``[[calc: 6.507,11 + 6.417,42]]``, with every figure copied exactly as the excerpts write it. The
server computes it with ``Decimal`` (no floating-point error) and replaces the marker with
``6.507,11 + 6.417,42 = 12.924,53``, in the number style of the figures. Each figure is checked
against the excerpts; one that doesn't appear there is reported, so the reader knows to check it.

Supported: + - * / (also × and ÷), parentheses and signs. The expression is parsed by a small
recursive-descent parser; nothing is ever passed to ``eval``.

Number styles: "6.507,11" (comma decimal, as in Belgian documents), "6,507.11" (point decimal),
"6 507,11" (space grouping) and plain "6507.11". If the figures don't reveal which separator is
the decimal one (e.g. only "1.250" and "3.000"), the calculation is refused rather than guessed.
"""

import re
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal, DivisionByZero, InvalidOperation

from suveryn_engine import Calculation

CALC = re.compile(r"\[\[\s*calc\s*:\s*(.*?)\s*\]\]", re.DOTALL | re.IGNORECASE)
NUMBER = re.compile(r"\d+(?:[.,   ]\d+)*")
GROUPING_SPACES = "   "
MAX_MARKER = 300  # a "[[" not closed within this many characters is not a calculation


class CalcError(ValueError):
    """The calculation can't be done: syntax, ambiguous number style, or division by zero."""


def _decimal_separator(figures: list[str]) -> str | None:
    """"," or "." as the decimal separator these figures use, or None if they have no decimals at all.

    Raises ``CalcError`` when a figure such as "1.250" could be read either way.
    """
    for f in figures:
        if "." in f and "," in f:
            return "," if f.rfind(",") > f.rfind(".") else "."
    for sep, other in ((",", "."), (".", ",")):
        if any(re.search(rf"\{sep}\d{{1,2}}$", f) or f.count(other) > 1 for f in figures):
            return sep
    if any(re.search(r"[.,]\d{3}$", f) or re.search(r"[.,]\d{4,}$", f) for f in figures):
        raise CalcError("the figures don't show which separator is the decimal one")
    return None


def _to_decimal(figure: str, sep: str | None) -> Decimal:
    s = re.sub(f"[{GROUPING_SPACES}]", "", figure)
    if sep:
        s = s.replace("." if sep == "," else ",", "").replace(sep, ".")
    return Decimal(s)


def _format(value: Decimal, places: int, sep: str | None, grouping: str | None) -> str:
    """The result in the figures' own style: same decimal separator, grouping and number of decimals."""
    value = value.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP) if places else value.to_integral_value(ROUND_HALF_UP)
    sign, digits = ("-" if value < 0 else ""), f"{abs(value):f}"
    whole, _, frac = digits.partition(".")
    if grouping:
        whole = f"{int(whole):,}".replace(",", grouping)
    return sign + whole + ((sep or ".") + frac if frac else "")


class _Parser:
    """expr := term (('+'|'-') term)* ; term := factor (('*'|'/') factor)* ; factor := ('+'|'-') factor | NUMBER | '(' expr ')'."""

    def __init__(self, tokens: list[tuple[str, Decimal | str]]):
        self.tokens, self.i = tokens, 0

    def parse(self) -> Decimal:
        value = self.expr()
        if self.i != len(self.tokens):
            raise CalcError("unexpected text in the calculation")
        return value

    def _peek(self):
        return self.tokens[self.i][1] if self.i < len(self.tokens) else None

    def expr(self) -> Decimal:
        value = self.term()
        while self._peek() in ("+", "-"):
            op = self.tokens[self.i][1]
            self.i += 1
            value = value + self.term() if op == "+" else value - self.term()
        return value

    def term(self) -> Decimal:
        value = self.factor()
        while self._peek() in ("*", "/"):
            op = self.tokens[self.i][1]
            self.i += 1
            right = self.factor()
            if op == "/" and right == 0:
                raise CalcError("division by zero")
            value = value * right if op == "*" else value / right
        return value

    def factor(self) -> Decimal:
        if self.i >= len(self.tokens):
            raise CalcError("the calculation is incomplete")
        kind, tok = self.tokens[self.i]
        self.i += 1
        if kind == "num":
            return tok
        if tok in ("+", "-"):
            value = self.factor()
            return value if tok == "+" else -value
        if tok == "(":
            value = self.expr()
            if self._peek() != ")":
                raise CalcError("a bracket is not closed")
            self.i += 1
            return value
        raise CalcError("unexpected text in the calculation")


def evaluate(expression: str) -> tuple[str, list[str]]:
    """Compute an expression; return the formatted result and the figures it used, as written.

    The result has as many decimals as the most precise figure (at least 2 when dividing),
    rounded half up, and the figures' grouping style.
    """
    expression = expression.replace("×", "*").replace("÷", "/").replace("−", "-")
    expression = re.sub(r"\b(EUR|USD|GBP)\b|[€$£]", " ", expression)  # a currency next to a figure is fine
    figures: list[str] = []
    raw: list[tuple[str, str]] = []
    for m in re.finditer(rf"{NUMBER.pattern}|[-+*/()]|\S", expression):
        tok = m.group(0)
        if NUMBER.fullmatch(tok):
            figures.append(tok.strip())
            raw.append(("num", tok.strip()))
        elif tok in "+-*/()":
            raw.append(("op", tok))
        else:
            raise CalcError(f"unexpected text in the calculation: {tok!r}")
    if not figures:
        raise CalcError("the calculation has no figures")
    sep = _decimal_separator(figures)
    tokens = [(k, _to_decimal(v, sep)) if k == "num" else (k, v) for k, v in raw]
    try:
        value = _Parser(tokens).parse()
    except (InvalidOperation, DivisionByZero) as e:
        raise CalcError("the calculation can't be done") from e
    places = max((len(f.rsplit(sep, 1)[1]) for f in figures if sep and sep in f), default=0)
    if "/" in expression:
        places = max(places, 2)
    thousands = ("." if sep == "," else ",") if sep else None
    grouping = next((g for g in (thousands, *GROUPING_SPACES) if g and any(g in f for f in figures)), None)
    return _format(value, places, sep, grouping), figures


def _normalise(text: str) -> str:
    return re.sub(rf"[{GROUPING_SPACES}]+", " ", text)


@dataclass
class CalcRewriter:
    """Replaces ``[[calc: …]]`` markers in streamed answer text with their computed result.

    ``feed`` returns the text that is safe to show now; text from an unfinished "[[" is held
    back until its "]]" arrives (or ``MAX_MARKER`` characters pass). Call ``flush`` at the end.
    ``source`` is the excerpt text the figures are checked against.
    """

    source: str
    calculations: list[Calculation] = field(default_factory=list)
    _pending: str = ""

    def feed(self, text: str) -> str:
        self._pending += text
        out = []
        while True:
            start = self._pending.find("[[")
            if start == -1:
                keep = 1 if self._pending.endswith("[") else 0  # may become "[["
                out.append(self._pending[:len(self._pending) - keep])
                self._pending = self._pending[len(self._pending) - keep:]
                break
            out.append(self._pending[:start])
            self._pending = self._pending[start:]
            end = self._pending.find("]]")
            if end == -1:
                if len(self._pending) > MAX_MARKER:
                    out.append(self._pending[:2])
                    self._pending = self._pending[2:]
                    continue
                break
            marker, self._pending = self._pending[:end + 2], self._pending[end + 2:]
            out.append(self._replace(marker))
        return "".join(out)

    def flush(self) -> str:
        rest, self._pending = self._pending, ""
        return rest

    def _replace(self, marker: str) -> str:
        m = CALC.fullmatch(marker)
        if not m:
            return marker
        expression = " ".join(m.group(1).split())
        try:
            result, figures = evaluate(expression)
        except CalcError as e:
            self.calculations.append(Calculation(expression=expression, result=None, error=str(e)))
            return f"[calculation not possible: {expression}]"
        source = _normalise(self.source)
        missing = [f for f in dict.fromkeys(figures) if _normalise(f) not in source]
        self.calculations.append(Calculation(expression=expression, result=result, figures_not_in_sources=missing))
        return f"{expression} = {result}"


def rewrite(answer: str, source: str) -> tuple[str, list[Calculation]]:
    """Replace every calculation marker in a complete answer; return the text and the calculations."""
    r = CalcRewriter(source)
    text = r.feed(answer) + r.flush()
    return text, r.calculations
