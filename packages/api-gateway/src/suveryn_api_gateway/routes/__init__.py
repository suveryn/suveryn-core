"""The gateway's routes, one module per area; ``app.py`` builds the app and includes them.

Every module here takes what it needs from ``request.app.state`` (set in ``app.create_app``), so a
route has no closure over the app: the modules are importable on their own and testable through
the app. Shared helpers (who the caller is, which scope a request works in, the 503s for a store
that isn't there) are in ``common.py``.
"""

from . import (  # noqa: F401 - the modules app.py includes
    avatars,
    backups,
    cases,
    chat,
    conversations,
    documents,
    health,
    playbooks,
    signin,
    status,
    usage,
    users,
)
