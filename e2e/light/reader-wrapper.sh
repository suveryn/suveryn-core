#!/bin/sh
# Light mode (e2e/README.md): runs e2e/light/fake_reader.py in place of the real reader. The gateway starts the
# reader as "<wrapper> <python> -I -m suveryn_rag.isolation <options>"; the python and the options are kept.
python="$1"
exec "$python" -I "$(dirname "$0")/fake_reader.py"
