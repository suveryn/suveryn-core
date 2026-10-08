"""Private, self-deleting scratch space for intermediate document files.

OCRmyPDF and its Tesseract/Ghostscript subprocesses write work files to the system temp
directory, which is /tmp by default. A searchable copy of a deed is the full confidential
document, so while a document is processed both Python's ``tempfile`` and the ``TMPDIR`` that
subprocesses inherit point at a fresh 0700 directory that is removed afterwards, on success
and on error.
"""

import os
import shutil
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path


@contextmanager
def private_workdir(base: Path) -> Iterator[Path]:
    """Yield a fresh 0700 directory under ``base`` with TMPDIR/tempfile pointed at it; delete it afterwards.

    Process-wide side effect: while the block runs, every temp file in this process (and in
    subprocesses started from it) lands in this directory. Don't run two of these at once in
    one process.
    """
    base.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(base, 0o700)
    path = Path(tempfile.mkdtemp(prefix="doc-", dir=base))  # mkdtemp creates it 0700
    saved_env, saved_tempdir = os.environ.get("TMPDIR"), tempfile.tempdir
    os.environ["TMPDIR"] = str(path)
    tempfile.tempdir = str(path)
    try:
        yield path
    finally:
        tempfile.tempdir = saved_tempdir
        if saved_env is None:
            os.environ.pop("TMPDIR", None)
        else:
            os.environ["TMPDIR"] = saved_env
        shutil.rmtree(path, ignore_errors=True)
