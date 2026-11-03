"""``python -m suveryn_playbooks <packs directory>``: check that a directory of packs loads beside the
official playbooks, and say what it holds (``packs.py``). Exit code 1 names the file and the problem."""
import sys

from . import PLAYBOOKS
from .packs import main

sys.exit(main(sys.argv[1:], PLAYBOOKS))
