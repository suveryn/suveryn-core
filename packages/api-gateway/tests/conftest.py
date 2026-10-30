"""What every gateway test shares."""

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def not_an_appliance(monkeypatch, tmp_path):
    """The tests run as on a development machine, wherever they run: the gateway refuses uploads while an
    appliance's data partition is short (routes/status.py ``disk_low``), and a test machine with a fuller disk,
    or with a /var/lib/suveryn of its own, must not change what the tests see. A test that wants the data
    partition sets ``status.DATA_PATH`` itself."""
    import suveryn_api_gateway.routes.status as status

    monkeypatch.setattr(status, "DATA_PATH", Path(tmp_path) / "no-data-partition")
