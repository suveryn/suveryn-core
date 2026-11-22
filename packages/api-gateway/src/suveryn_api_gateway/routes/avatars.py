"""Avatars (``avatars.py``, docs/design/avatars.md): a person's picture, served to colleagues, set
and removed by the person, removable by an administrator."""

import logging

from fastapi import APIRouter, Request, Response
from suveryn_harness.messages import Problem
from fastapi.concurrency import run_in_threadpool

from ..avatars import CONTENT_TYPE, MAX_UPLOAD_BYTES, AvatarStore, NotAnImage
from ..description import Answer
from ..problems import refusals
from .common import admin_or_403, owner_of

log = logging.getLogger("suveryn.gateway")
router = APIRouter(tags=["users"])  # the group its operations are in, in the description (description.py)


def avatars_or_503(request: Request) -> AvatarStore:
    db = request.app.state.avatars
    if not db.configured:
        raise Problem("user.pictures_unavailable", "Pictures are not available on this server.")
    store = db.get()
    if store is None:
        raise Problem("user.pictures_unavailable", f"Pictures are not available right now: {db.error}.")
    return store


class Picture(Answer):
    """The caller's picture, by its ETag: what a page puts behind the picture's address so a new one is fetched."""

    avatar: str


BINARY = {"schema": {"type": "string", "format": "binary"}}


@router.get("/v1/users/{sub}/avatar", response_class=Response, responses={
    **refusals(404), 200: {"content": {CONTENT_TYPE: BINARY}, "description": "The picture"}, 304: {"description": "Unchanged"}})
async def get_user_picture(sub: str, request: Request):
    """A colleague's picture (every signed-in user may see it), with an ETag: a browser that has it
    sends ``If-None-Match`` and gets 304. 404 when the person has none (the UI shows initials)."""
    if "/" in sub or len(sub) > 200:
        raise Problem("request.not_found", "No picture.")
    found = await run_in_threadpool(avatars_or_503(request).get, sub)
    if found is None:
        raise Problem("request.not_found", "No picture.")
    image, etag = found
    headers = {"ETag": f'"{etag}"', "Cache-Control": "private, max-age=3600"}
    if request.headers.get("if-none-match", "").strip('"') == etag:
        return Response(status_code=304, headers=headers)
    return Response(content=image, media_type=CONTENT_TYPE, headers=headers)


@router.put("/v1/me/avatar", response_model=Picture, responses=refusals(413, 415), openapi_extra={
    # the image as it is, read from the request itself and re-encoded on the server
    "requestBody": {"required": True, "content": {"application/octet-stream": BINARY}}})
async def set_my_picture(request: Request):
    """Set the caller's picture: the request body is the image (PNG, JPEG or WebP; the UI sends the
    square it cropped). It is re-encoded on the server (``avatars.normalise``); answers ``{"avatar": etag}``."""
    upload = await request.body()
    if len(upload) > MAX_UPLOAD_BYTES:
        raise Problem("user.picture_too_large", "The picture is larger than 2 MB.", max_mb=MAX_UPLOAD_BYTES // (1024 * 1024))
    if not upload:
        raise Problem("request.unsupported", "Send the picture as the request body.")
    try:
        etag = await run_in_threadpool(avatars_or_503(request).set, owner_of(request), upload)
    except NotAnImage as e:
        raise Problem("user.picture_unreadable", "That isn't a picture sūveryn can read: use a PNG, JPEG or WebP file.") from e
    return Picture(avatar=etag)


@router.delete("/v1/me/avatar", status_code=204, responses=refusals())
async def delete_my_picture(request: Request):
    """Remove the caller's picture; their initials are shown again."""
    await run_in_threadpool(avatars_or_503(request).remove, owner_of(request))
    return Response(status_code=204)


@router.delete("/v1/users/{sub}/avatar", status_code=204, responses=refusals())
async def delete_user_picture(sub: str, request: Request):
    """Administrators: remove someone's picture (one that shouldn't be there). Never set one."""
    admin_or_403(request)
    await run_in_threadpool(avatars_or_503(request).remove, sub)
    log.info("avatar removed by an administrator")
    return Response(status_code=204)
