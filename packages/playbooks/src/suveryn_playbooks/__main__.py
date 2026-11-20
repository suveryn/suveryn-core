"""``python -m suveryn_playbooks <packs directory>``: check that a directory of packs loads beside the
official playbooks and case types, and say what it holds (``packs.py``). Exit code 1 names the file and the problem."""
import sys

from . import CASE_TYPES, PLAYBOOKS
from .packs import main

sys.exit(main(sys.argv[1:], PLAYBOOKS, CASE_TYPES))
