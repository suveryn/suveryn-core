"""Audit events: what happened, never what a document says (suveryn-tracker#21, development context §5.4).

The playbook audit log (§6) doesn't exist yet. Until it does, security-relevant events go to their own
logger, ``suveryn.audit``, one JSON object per line, so the appliance can route, keep and rotate them
separately from the application log (and the future audit log can take them over unchanged).

Only identifiers, page numbers, counts and kinds are written: never document text, questions or
answers, which are personal data (§4). ``user`` is the Keycloak id, as stored with documents.
"""

import json
import logging
from datetime import UTC, datetime

log = logging.getLogger("suveryn.audit")


def audit(event: str, **fields) -> None:
    """Write one audit event, e.g. ``audit("instruction_like_document", user=..., document=..., pages=[3])``."""
    log.warning(json.dumps({"at": datetime.now(UTC).isoformat(timespec="seconds"), "event": event, **fields},
                           ensure_ascii=False, sort_keys=True, default=str))
