# Avatars: a picture, or initials

Decided and built 18 October 2026. Every person in the office is shown with an avatar: the picture
they uploaded, or their initials when they haven't. It appears next to the signed-in user's name
in the sidebar (where a click opens the dialog to change it), in a case's member list, and in the
office's directory when a colleague is added.

## The shape

The avatar is the brand mark's outer boundary: a rounded square whose corner radius is a quarter
of the side (suveryn-brand `logo/suveryn-icon.svg`: `rx` 5 on 20), with a teal border (`--teal`, at
least 1.5 px, 5% of the side; docs/design/sidebar.md, 13). Initials sit on a light teal wash in Space Grotesk, the first letters
of the first and last word of the display name, upper case, at most two. An administrator (realm
role `suveryn-admin`) wears a small accent-coloured shield over the bottom-right corner, outside
the clipped face so the corner never cuts it. Sizes: 24, 32, 48 and 96 px. The component is
`Avatar` in the UI kit (`packages/chat-ui/src/ui/avatar.tsx`), as every screen's components are.

## Uploading

The dialog ("Your picture") asks for one thing: a headshot, as a PNG, JPEG or WebP file. The
picture is drawn in a frame the shape of the avatar; the person drags it to move it and uses a
zoom slider (1 to 4 times) to get closer. The frame scales the picture by one factor in both
directions ("cover" at zoom 1, so it always fills the frame) and panning is clamped so no edge
ever leaves the frame: the picture can be framed, never stretched. Saving draws the same framing
at 512 x 512 pixels in the browser and sends that PNG; nothing is uploaded that the person hasn't
seen in the frame. "Remove the picture" brings the initials back.

## On the server

The gateway (`avatars.py`) trusts nothing about the bytes. Pillow opens them with a bounded
decoder (three formats; a pixel cap against decompression bombs; at most 2 MB, checked from the
`Content-Length` before the body is read), applies the camera's orientation, centre-crops to a
square if the browser didn't, resizes to 256 pixels and re-encodes as WebP (quality 85, about
10 to 20 KB). What is stored is always that small, normalised image, never the upload: no metadata,
no colour profile, no animation survives. The table is `user_avatars (sub, image, etag, updated_at)`
in the cases' database.

Routes: `PUT /v1/me/avatar` (the image as the body; answers the new ETag), `DELETE /v1/me/avatar`,
`GET /v1/users/{sub}/avatar` (every signed-in user: colleagues see each other; `ETag`, `304` on
`If-None-Match`, `Cache-Control: private, max-age=3600`; 404 without a picture), and
`DELETE /v1/users/{sub}/avatar` for administrators (a picture that shouldn't be there; an
administrator never sets one). `/auth/me`, `/v1/users` and a case's members carry `avatar` (the
ETag, null without one), so the UI keys the picture's URL by it and a new upload shows at once; a
picture that fails to load falls back to initials, never a broken image.

The badge needs to know who administers. The directory asks Keycloak for the holders of the realm
role (`GET /roles/suveryn-admin/users`, cached 30 s). That endpoint needs the `view-realm` right
as well as `view-users` on the `suveryn-directory` client; without it the answer is empty, logged
once, and the badge is simply missing (cosmetic, never an error). The appliance's realm should
grant `view-realm` to the client (suveryn-appliance `keycloak/realm`); the signed-in user's own
badge comes from their token and needs nothing.

## Data lifecycle

A picture is personal data of the person who uploaded it. It is kept until they remove it, an
administrator removes it, or the account's data is deleted; it is never a source for answers and
never leaves the appliance. Deleting follows the [data lifecycle](https://github.com/suveryn/suveryn-docs/blob/main/administration/data-lifecycle.md):
removed from every access path at once; traces in the database's files overwritten over time.
