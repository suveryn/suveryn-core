"""Numbers that carry their own check: a Belgian national register number, an enterprise number, an IBAN.

A typo, or a scan that read an 8 as a 3, makes such a number wrong in a way arithmetic proves: no model is asked,
and nothing is guessed. A playbook names the form a fact must have (``format`` in its manifest); a value read in that
form whose check digits don't match goes under *Check* at the checkpoint (``needs: invalid_number``), never a block.
Plan of 10 November 2026, step 3.1.

- ``national_register``: eleven digits, YYMMDD, a serial of three, two check digits: 97 minus the first nine modulo 97,
  or, for someone born in 2000 or later, of "2" followed by them. A BIS number (month + 20 or + 40) checks the same way.
- ``enterprise``: ten digits (a number of nine, written before 2005 without its leading 0, is read with it), starting
  with 0 or 1; the last two are 97 minus the first eight modulo 97.
- ``person_or_company``: either of the two (a party that is a person or a company).
- ``iban``: ISO 13616: the first four characters moved to the end, letters as numbers (A = 10 … Z = 35), modulo 97 is 1;
  a Belgian IBAN is 16 characters.
"""

from __future__ import annotations

import re

FORMATS = ("national_register", "enterprise", "person_or_company", "iban")

_IBAN = re.compile(r"\b([A-Z]{2}\d{2}(?:[ ]?[A-Z0-9]){10,30})\b")
_LENGTHS = {"BE": 16, "NL": 18, "FR": 27, "LU": 20, "DE": 22}


def valid(form: str, value: str) -> bool | None:
    """Whether the number in ``value`` has the check digits its form says; None when ``value`` holds no number of
    that form at all (nothing to check: the value is shown as read, the passage check still applies)."""
    if form == "iban":
        return _iban(value)
    digits = re.sub(r"\D", "", value)
    if form == "national_register":
        return _national(digits) if len(digits) == 11 else None
    if form == "enterprise":
        return _enterprise(digits) if len(digits) in (9, 10) else None
    if form == "person_or_company":
        if len(digits) == 11:
            return _national(digits)
        return _enterprise(digits) if len(digits) in (9, 10) else None
    raise ValueError(f"unknown number form {form!r}")


def _national(d: str) -> bool:
    check = int(d[9:])
    return 97 - int(d[:9]) % 97 == check or 97 - int("2" + d[:9]) % 97 == check


def _enterprise(d: str) -> bool:
    d = d.zfill(10)
    return d[0] in "01" and 97 - int(d[:8]) % 97 == int(d[8:])


def _iban(value: str) -> bool | None:
    m = _IBAN.search(value.upper())
    if not m:
        return None
    iban = m.group(1).replace(" ", "")
    if iban[:2] in _LENGTHS and len(iban) != _LENGTHS[iban[:2]]:
        return False
    moved = iban[4:] + iban[:4]
    return int("".join(str(int(ch, 36)) for ch in moved)) % 97 == 1
