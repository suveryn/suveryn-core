"""suveryn-tracker#15: uploaded PDFs are read in a separate process without the gateway's secrets.

The reader here is ``fake_reader.py`` (the real reader loop with a fake extraction), so no models
are needed; test_e2e.py runs the real one on the GPU machine.
"""

import sys
from pathlib import Path

import pytest

pytest.importorskip("docling_core")

from suveryn_rag.config import RagSettings
from suveryn_rag.isolation import ExtractionFailed, IsolatedExtractor, child_env

FAKE = [sys.executable, "-I", str(Path(__file__).with_name("fake_reader.py"))]


@pytest.fixture
def reader(tmp_path):
    r = IsolatedExtractor(RagSettings(work_dir=tmp_path), command=FAKE, timeout_s=3)
    yield r
    r.close()


def test_a_document_comes_back_as_validated_json(reader):
    from docling_core.types.doc import DoclingDocument

    ex = reader.extract(Path("deed.pdf"))
    assert isinstance(ex.document, DoclingDocument) and ex.document.texts[0].text == "Een akte."
    assert (ex.pages, ex.ocr_pages, ex.page_texts) == (1, 0, ["Een akte."])


def test_the_reader_gets_no_secrets(reader, monkeypatch):
    env = {"SUVERYN_DATABASE_URL": "postgresql://u:pw@db/x", "SUVERYN_OIDC_CLIENT_SECRET": "x",
           "SUVERYN_OIDC_ISSUER": "http://kc", "PGPASSWORD": "x", "HF_TOKEN": "x", "RUNPOD_API_KEY": "x",
           "MY_SECRET_FILE": "x", "SSH_AUTH_SOCK": "/s", "PATH": "/usr/bin", "HF_HOME": "/models",
           "SUVERYN_OCR_JOBS": "8", "CUDA_VISIBLE_DEVICES": "0", "TMPDIR": "/w"}
    assert set(child_env(env)) == {"PATH", "HF_HOME", "SUVERYN_OCR_JOBS", "CUDA_VISIBLE_DEVICES"}
    # Nothing that points into the gateway's private temporary folder: torch sets its cache there.
    gateway_tmp = {"TMPDIR": "/srv/work/tmp/4242", "TORCHINDUCTOR_CACHE_DIR": "/srv/work/tmp/4242/torchinductor_suveryn",
                   "TRITON_CACHE_DIR": "/srv/work/tmp/4242/triton", "HF_HOME": "/models", "PATH": "/usr/bin"}
    assert child_env(gateway_tmp) == {"HF_HOME": "/models", "PATH": "/usr/bin"}
    # ...and the process really starts with that environment
    monkeypatch.setenv("SUVERYN_DATABASE_URL", "postgresql://u:pw@db/x")
    monkeypatch.setenv("SUVERYN_OIDC_CLIENT_SECRET", "x")
    reader.close()
    with pytest.raises(ExtractionFailed) as e:
        reader.extract(Path("env.pdf"))
    assert "SUVERYN_DATABASE_URL" not in str(e.value) and "SUVERYN_OIDC_CLIENT_SECRET" not in str(e.value)
    assert "PATH" in str(e.value)


def test_a_crash_fails_only_that_document(reader):
    with pytest.raises(ExtractionFailed, match="stopped"):
        reader.extract(Path("crash.pdf"))
    assert reader.extract(Path("next.pdf")).pages == 1  # a fresh reader for the next one


def test_a_hang_is_killed_after_the_time_limit(reader):
    with pytest.raises(ExtractionFailed, match="longer than"):
        reader.extract(Path("hang.pdf"))
    assert reader.extract(Path("next.pdf")).pages == 1


def test_garbage_from_the_reader_is_refused_and_the_reader_replaced(reader):
    with pytest.raises(ExtractionFailed, match="unreadable"):
        reader.extract(Path("garbage.pdf"))
    assert reader.extract(Path("next.pdf")).pages == 1


def test_a_reading_error_is_reported_and_the_reader_carries_on(reader):
    with pytest.raises(ExtractionFailed, match="ValueError: no pages"):
        reader.extract(Path("fails.pdf"))
    assert reader.extract(Path("next.pdf")).pages == 1


def test_a_reader_that_cant_start_fails_at_start_up(tmp_path):
    with pytest.raises(ExtractionFailed, match="didn't start: ModuleNotFoundError"):
        IsolatedExtractor(RagSettings(work_dir=tmp_path), command=[*FAKE, "broken"])


def test_isolation_is_on_by_default_and_the_wrapper_prefixes_the_command(tmp_path, monkeypatch):
    monkeypatch.delenv("SUVERYN_EXTRACT_ISOLATION", raising=False)
    assert RagSettings.from_env().isolate_extraction
    monkeypatch.setenv("SUVERYN_EXTRACT_ISOLATION", "off")
    assert not RagSettings.from_env().isolate_extraction
    monkeypatch.setattr(IsolatedExtractor, "_start", lambda self: None)
    r = IsolatedExtractor(RagSettings(work_dir=tmp_path, extract_wrapper="systemd-run --user --scope"))
    assert r._command[:3] == ["systemd-run", "--user", "--scope"]
    assert r._command[4:7] == ["-I", "-m", "suveryn_rag.isolation"]
    assert "database_url" not in r._command[-1]


# ---------------------------------------------------------------- a reader running as another user
# suveryn-tracker#15 (appliance): the sandboxed reader can't enter the gateway's 0700 work folder, so
# uploads wait in a provisioned inbox (group = the reader's, 2750) and the reader has its own folder.

def test_uploads_go_to_the_inbox_group_readable(tmp_path):
    import io
    import stat

    from suveryn_rag.service import DocumentService, UploadRejected

    inbox = tmp_path / "inbox"
    inbox.mkdir(mode=0o750)
    docs = DocumentService(RagSettings(work_dir=tmp_path / "work", extract_inbox=inbox))
    job = docs.accept_upload(io.BytesIO(b"%PDF-1.7 test"), "akte.pdf", "user-a")
    [f] = inbox.glob("*.pdf")
    assert f.stem == job.id and stat.S_IMODE(f.stat().st_mode) == 0o640  # the reader's group may read it
    assert not (tmp_path / "work" / "uploads").exists()
    (inbox / "keep.txt").write_text("not ours")
    docs.stop()  # removes waiting uploads, never the provisioned folder or other files
    assert inbox.is_dir() and not list(inbox.glob("*.pdf")) and (inbox / "keep.txt").exists()

    inbox.chmod(0o755)  # world-readable: refused rather than exposing uploads to every user
    with pytest.raises(UploadRejected, match="readable by other users"):
        docs.accept_upload(io.BytesIO(b"%PDF-1.7"), "b.pdf", "user-a")
    with pytest.raises(UploadRejected, match="doesn't exist"):
        DocumentService(RagSettings(work_dir=tmp_path / "w", extract_inbox=tmp_path / "missing")).accept_upload(
            io.BytesIO(b"%PDF-1.7"), "c.pdf", "user-a")


def test_without_an_inbox_uploads_stay_private(tmp_path):
    import io
    import stat

    from suveryn_rag.service import DocumentService

    DocumentService(RagSettings(work_dir=tmp_path)).accept_upload(io.BytesIO(b"%PDF-1.7"), "a.pdf", "user-a")
    [f] = (tmp_path / "uploads").glob("*.pdf")
    assert stat.S_IMODE(f.stat().st_mode) == 0o600 and stat.S_IMODE(f.parent.stat().st_mode) == 0o700


def test_the_reader_works_in_its_own_folder(tmp_path, monkeypatch):
    import json
    import os
    import tempfile

    from suveryn_rag.isolation import own_workspace

    monkeypatch.setattr(IsolatedExtractor, "_start", lambda self: None)
    r = IsolatedExtractor(RagSettings(work_dir=tmp_path / "gateway", extract_work_dir=tmp_path / "reader"))
    assert json.loads(r._command[-1])["work_dir"] == str(tmp_path / "reader")

    reader = tmp_path / "reader"
    (reader / "doc-left-by-a-killed-reader").mkdir(parents=True)
    monkeypatch.setenv("TMPDIR", str(tmp_path / "gateway-private-tmp"))
    monkeypatch.setattr(tempfile, "tempdir", None)
    own_workspace(reader)
    assert os.environ["TMPDIR"] == str(reader) and tempfile.gettempdir() == str(reader)
    assert not list(reader.glob("doc-*")) and (reader.stat().st_mode & 0o777) == 0o700
