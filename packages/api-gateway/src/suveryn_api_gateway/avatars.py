"""Avatars: a person's picture, or their initials (docs/design/avatars.md).

A user uploads a headshot; the browser lets them crop it to a square without distorting it and
sends that square. The gateway trusts nothing about the bytes: it opens them with Pillow (a
bounded decoder: three formats, a pixel cap), applies the camera's orientation, centre-crops to
a square if the browser didn't, resizes to ``SIZE`` pixels and re-encodes as WebP. What is stored
is always that small, normalised image, never the upload. The picture is served to every
signed-in user (colleagues see each other) with an ETag so browsers cache it.

Who may change what: a person changes or removes their own picture; an administrator may remove
anyone's (a picture that shouldn't be there), never set one. The picture is personal data: kept
until the person removes it, an administrator removes it, or the account's data is deleted
(the data lifecycle, suveryn-tracker#31).

Review notes:
- The upload is read into memory and bounded by ``MAX_UPLOAD_BYTES`` (the middleware checks the
  Content-Length first, like documents); ``Image.MAX_IMAGE_PIXELS`` bounds the decode.
- Nothing from the upload survives re-encoding: no metadata, no colour profile, no animation.
"""

from __future__ import annotations

import hashlib
import io
import logging
from datetime import datetime

from PIL import Image, ImageOps, UnidentifiedImageError

from .db import PgStore

log = logging.getLogger("suveryn.gateway")

SIZE = 256                       # pixels, square: the largest the UI draws is 96 CSS px (2x = 192)
MAX_UPLOAD_BYTES = 2 * 1024 * 1024
MAX_PIXELS = 24_000_000          # a 6000 x 4000 photo; the decoder refuses more (decompression bombs)
FORMATS = ("PNG", "JPEG", "WEBP")
CONTENT_TYPE = "image/webp"

SCHEMA = """
CREATE TABLE IF NOT EXISTS user_avatars (
    sub text PRIMARY KEY,
    image bytea NOT NULL,
    etag text NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT now()
);
"""


class NotAnImage(ValueError):
    """The upload isn't a PNG, JPEG or WebP picture the appliance can read."""


def normalise(upload: bytes) -> bytes:
    """The stored picture for an upload: oriented, square, ``SIZE`` pixels, WebP. Raises ``NotAnImage``."""
    if len(upload) > MAX_UPLOAD_BYTES:
        raise NotAnImage("too large")
    Image.MAX_IMAGE_PIXELS = MAX_PIXELS
    try:
        with Image.open(io.BytesIO(upload)) as img:
            if img.format not in FORMATS:
                raise NotAnImage(f"not a {', '.join(FORMATS)} picture")
            img = ImageOps.exif_transpose(img) or img
            img = img.convert("RGB")
            side = min(img.size)
            left, top = (img.width - side) // 2, (img.height - side) // 2
            img = img.crop((left, top, left + side, top + side)).resize((SIZE, SIZE), Image.LANCZOS)
            out = io.BytesIO()
            img.save(out, format="WEBP", quality=85, method=4)
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError, ValueError) as e:
        raise NotAnImage(type(e).__name__) from e
    return out.getvalue()


def etag_of(image: bytes) -> str:
    return hashlib.sha256(image).hexdigest()[:16]


class AvatarStore(PgStore):
    """Avatars in PostgreSQL; creates its table on connect."""

    schema = SCHEMA

    def set(self, sub: str, upload: bytes) -> str:
        """Store the normalised picture for ``sub``; returns its ETag. Raises ``NotAnImage``."""
        image = normalise(upload)
        etag = etag_of(image)
        self._execute("INSERT INTO user_avatars (sub, image, etag, updated_at) VALUES (%s, %s, %s, now())"
                      " ON CONFLICT (sub) DO UPDATE SET image = EXCLUDED.image, etag = EXCLUDED.etag, updated_at = now()",
                      (sub, image, etag))
        return etag

    def get(self, sub: str) -> tuple[bytes, str] | None:
        r = self._execute("SELECT image, etag FROM user_avatars WHERE sub = %s", (sub,)).fetchone()
        return (bytes(r[0]), r[1]) if r else None

    def etag(self, sub: str) -> str | None:
        r = self._execute("SELECT etag FROM user_avatars WHERE sub = %s", (sub,)).fetchone()
        return r[0] if r else None

    def etags(self, subs: list[str]) -> dict[str, str]:
        """The ETags of those of ``subs`` that have a picture."""
        if not subs:
            return {}
        rows = self._execute("SELECT sub, etag FROM user_avatars WHERE sub = ANY(%s)", (subs,)).fetchall()
        return {r[0]: r[1] for r in rows}

    def remove(self, sub: str) -> bool:
        return self._execute("DELETE FROM user_avatars WHERE sub = %s", (sub,)).rowcount > 0

    def updated_at(self, sub: str) -> datetime | None:
        r = self._execute("SELECT updated_at FROM user_avatars WHERE sub = %s", (sub,)).fetchone()
        return r[0] if r else None
