import os
import stat
import tempfile

from suveryn_api_gateway.main import private_tmp


def test_private_tmp_redirects_temporary_files(tmp_path, monkeypatch):
    monkeypatch.setenv("SUVERYN_WORK_DIR", str(tmp_path / "work"))
    saved_env, saved_tempdir = os.environ.get("TMPDIR"), tempfile.tempdir
    try:
        d = private_tmp()
        assert stat.S_IMODE(d.stat().st_mode) == 0o700
        with tempfile.SpooledTemporaryFile(max_size=1) as f:  # what Starlette uses for uploads
            f.write(b"%PDF- confidential")
            f.rollover()
            assert os.path.realpath(f"/proc/self/fd/{f.fileno()}").startswith(str(d)) or tempfile.gettempdir() == str(d)
    finally:
        tempfile.tempdir = saved_tempdir
        if saved_env is None:
            os.environ.pop("TMPDIR", None)
        else:
            os.environ["TMPDIR"] = saved_env
