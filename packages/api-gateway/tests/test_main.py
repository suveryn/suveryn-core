import os
import stat
import tempfile

from suveryn_api_gateway.main import private_tmp


def test_private_tmp_redirects_temporary_files(tmp_path, monkeypatch):
    monkeypatch.setenv("SUVERYN_WORK_DIR", str(tmp_path / "work"))
    saved_env, saved_tempdir = os.environ.get("TMPDIR"), tempfile.tempdir
    try:
        stale = tmp_path / "work" / "tmp" / "999999999"  # a folder left by a process that no longer runs
        stale.mkdir(parents=True)
        d = private_tmp()
        assert stat.S_IMODE(d.stat().st_mode) == 0o700 and d.name == str(os.getpid())
        assert tempfile.gettempdir() == str(d) and os.environ["TMPDIR"] == str(d)
        assert not stale.exists()
        assert private_tmp() == d  # idempotent
        with tempfile.SpooledTemporaryFile(max_size=1) as f:  # what Starlette uses for uploads
            f.write(b"%PDF- confidential")
            f.rollover()
            assert [p for p in d.iterdir()] == [] or all(str(p).startswith(str(d)) for p in d.iterdir())
    finally:
        tempfile.tempdir = saved_tempdir
        if saved_env is None:
            os.environ.pop("TMPDIR", None)
        else:
            os.environ["TMPDIR"] = saved_env


def test_suveryns_informational_lines_reach_stderr_once(monkeypatch, capsys):
    """Pod check of eb35c55: nothing configured the suveryn.* loggers, so informational lines were dropped."""
    import logging

    from suveryn_api_gateway.main import configure_logging

    logger = logging.getLogger("suveryn")
    saved = (list(logger.handlers), logger.level, logger.propagate)
    try:
        monkeypatch.setenv("SUVERYN_LOG_LEVEL", "info")
        assert configure_logging() is not None
        assert configure_logging() is None  # idempotent: no second handler
        logging.getLogger("suveryn.rag").info("document database reachable again")
        logging.getLogger("suveryn.gateway").debug("not at INFO")
        err = capsys.readouterr().err
        assert err.count("INFO suveryn.rag: document database reachable again") == 1
        assert "not at INFO" not in err
    finally:
        logger.handlers[:], logger.level, logger.propagate = saved[0], saved[1], saved[2]


def test_an_unknown_log_level_is_info(monkeypatch):
    import logging

    from suveryn_api_gateway.main import configure_logging

    logger = logging.getLogger("suveryn")
    saved = (list(logger.handlers), logger.level, logger.propagate)
    try:
        monkeypatch.setenv("SUVERYN_LOG_LEVEL", "chatty")
        configure_logging()
        assert logger.level == logging.INFO
    finally:
        logger.handlers[:], logger.level, logger.propagate = saved[0], saved[1], saved[2]
