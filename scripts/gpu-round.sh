#!/usr/bin/env bash
# The GPU round: the tests that need a real card and the real model, on a rented GPU machine (a RunPod pod,
# Ubuntu 22.04 or 24.04 with the CUDA toolkit, root, /workspace on the volume). From a clone of this repository:
#
#   bash scripts/gpu-round.sh                 # llama.cpp at the appliance's pin
#   COMPARE=b12111 bash scripts/gpu-round.sh  # and again with a newer llama.cpp, the answers and the reads only
#   LLAMA_TAG=b12111 bash scripts/gpu-round.sh  # only that llama.cpp; the summary keeps earlier runs' results
#
# What it runs, in order, with llama-server holding the model on the same card as the appliance does:
#   1. test_e2e.py on the GPU (Docling and bge-m3 next to the model: does it all fit?);
#   2. test_answers_e2e.py (the answers held to their citations, the trap deed's questions);
#   3. test_playbook_reads_e2e.py (deed intake read by the model).
# It ends with a summary to paste back: the card, the versions, the peak memory, pass or fail per run. The reports
# hold per check whether it held, never document or answer text. Only the fictional trap deed is read.
# Safe to run again: the downloads, the build and the database are kept in $WORK and reused.
set -euo pipefail

CORE="$(cd "$(dirname "$0")/.." && pwd)"
WORK="${WORK:-/workspace/gpu-round}"
LLAMA_TAG="${LLAMA_TAG:-b11223}"            # suveryn-appliance provision/versions.json
COMPARE="${COMPARE:-}"                      # another llama.cpp tag to compare, or empty
UV_VERSION=0.13.7
UV_SHA256=c5221ff41b7892bfc223543883600125f6a47fe845093e0f5bdff4f359196d83
declare -A LLAMA_COMMIT=([b11223]=4da6337767f973e2b4d0797e5b323d77d8565e4a [b12111]=52e53a76df0298d2c316ae7e704eeec03b0bf478)
PORT=8080
DB=postgresql://postgres:postgres@127.0.0.1:5432/suveryn_test

mkdir -p "$WORK/results"
RESULTS="$WORK/results"
exec > >(tee -a "$WORK/round.log") 2>&1
step() { printf '\n== %s  %s\n' "$(date +%H:%M:%S)" "$*"; }
die() { printf '\nSTOPPED: %s\n' "$*"; exit 1; }

export HF_HOME="$WORK/hf" UV_CACHE_DIR="$WORK/uv-cache" UV_PYTHON_INSTALL_DIR="$WORK/python"
export PATH="$WORK/bin:/usr/local/cuda/bin:$PATH" DEBIAN_FRONTEND=noninteractive

step "checks"
command -v nvidia-smi >/dev/null || die "no nvidia-smi: this machine has no GPU driver"
command -v nvcc >/dev/null || die "no nvcc: choose a pod template with the CUDA toolkit (a 'devel' image)"
nvidia-smi --query-gpu=name,driver_version,memory.total --format=csv,noheader
[ "$(df -BG --output=avail "$WORK" | tail -1 | tr -dc 0-9)" -ge 45 ] || die "less than 45 GB free in $WORK"

step "system packages (PostgreSQL 16 with pgvector, OCR, build tools)"
apt-get update -qq
if [ ! -d /usr/lib/postgresql/16 ]; then
  apt-get install -y -qq curl ca-certificates gnupg lsb-release postgresql-common >/dev/null
  /usr/share/postgresql-common/pgdg/apt.postgresql.org.sh -y >/dev/null
  apt-get install -y -qq postgresql-16 postgresql-16-pgvector >/dev/null
fi
apt-get install -y -qq git cmake build-essential libssl-dev ocrmypdf tesseract-ocr-nld tesseract-ocr-fra \
  tesseract-ocr-eng ghostscript poppler-utils >/dev/null

step "uv $UV_VERSION"
if [ "$("$WORK/bin/uv" --version 2>/dev/null | cut -d' ' -f2)" != "$UV_VERSION" ]; then
  curl -fsSL -o "$WORK/uv.tar.gz" "https://github.com/astral-sh/uv/releases/download/$UV_VERSION/uv-x86_64-unknown-linux-gnu.tar.gz"
  echo "$UV_SHA256  $WORK/uv.tar.gz" | sha256sum -c --quiet || die "uv download doesn't match its checksum"
  mkdir -p "$WORK/bin" && tar -xzf "$WORK/uv.tar.gz" -C "$WORK/bin" --strip-components=1
fi

step "suveryn-core $(git -C "$CORE" rev-parse --short HEAD)"
cd "$CORE"
uv python install 3.12
uv sync --all-packages --dev -q

build_llama() {  # a tag: clone at its pinned commit, build llama-server for this card
  local tag="$1" dir="$WORK/llama.cpp-$1"
  [ -n "${LLAMA_COMMIT[$tag]:-}" ] || die "no pinned commit for llama.cpp $tag"
  [ -d "$dir/.git" ] || git -c advice.detachedHead=false clone -q --depth 1 --branch "$tag" https://github.com/ggml-org/llama.cpp "$dir"
  [ "$(git -C "$dir" rev-parse HEAD)" = "${LLAMA_COMMIT[$tag]}" ] || die "llama.cpp $tag isn't at its pinned commit"
  if [ ! -x "$dir/build/bin/llama-server" ]; then
    cmake -S "$dir" -B "$dir/build" -DGGML_CUDA=ON -DGGML_CUDA_NCCL=OFF -DCMAKE_CUDA_ARCHITECTURES=native \
      -DGGML_NATIVE=ON -DLLAMA_CURL=OFF -DCMAKE_BUILD_TYPE=Release >/dev/null
    cmake --build "$dir/build" --target llama-server -j "$(nproc)" >/dev/null
  fi
}
for tag in $LLAMA_TAG $COMPARE; do step "llama.cpp $tag"; build_llama "$tag"; done

manifest() { uv run python -c "import json,sys; m=next(m for m in json.load(open('models/manifest.json'))['models'] if m.get('default') and m['role']=='llm'); print(m[sys.argv[1]])" "$1"; }
MODEL_FILE="$(manifest file)"; MODEL_SHA="$(manifest sha256)"; MODEL_SRC="$(manifest source)"; MODEL_ARGS="$(manifest llama_server_args)"
MODEL="$WORK/models/$MODEL_FILE"
step "model $MODEL_FILE"
mkdir -p "$WORK/models"
if [ ! -f "$MODEL.ok" ]; then
  curl -fL --retry 5 -C - -o "$MODEL" "$MODEL_SRC/resolve/main/$MODEL_FILE"
  echo "$MODEL_SHA  $MODEL" | sha256sum -c --quiet || die "the model doesn't match the manifest's checksum (delete $MODEL and run again)"
  touch "$MODEL.ok"
fi

step "Docling and bge-m3"
SUVERYN_RAG_DEVICE=cuda uv run suveryn-fetch-models

step "database"
pg_ctlcluster 16 main status >/dev/null 2>&1 || pg_ctlcluster 16 main start
su postgres -c "psql -qc \"ALTER USER postgres PASSWORD 'postgres'\""
su postgres -c "psql -tAc \"SELECT 1 FROM pg_database WHERE datname='suveryn_test'\"" | grep -q 1 \
  || su postgres -c "createdb suveryn_test"

LLAMA_PID=""; MEM_PID=""
# Waits for these two only: a bare `wait` also waits for the log's tee (bash 5.1+), which never ends.
stop_all() {
  local pid
  for pid in $LLAMA_PID $MEM_PID; do kill "$pid" 2>/dev/null || true; wait "$pid" 2>/dev/null || true; done
  LLAMA_PID=""; MEM_PID=""
}
trap stop_all EXIT

serve() {  # a tag: llama-server with the manifest's arguments, until /health answers
  local tag="$1"
  eval "set -- $MODEL_ARGS"
  "$WORK/llama.cpp-$tag/build/bin/llama-server" -m "$MODEL" --host 127.0.0.1 --port "$PORT" "$@" \
    > "$RESULTS/llama-server-$tag.log" 2>&1 &
  LLAMA_PID=$!
  for _ in $(seq 600); do
    curl -fs "http://127.0.0.1:$PORT/health" >/dev/null 2>&1 && return 0
    kill -0 "$LLAMA_PID" 2>/dev/null || die "llama-server $tag stopped (see $RESULTS/llama-server-$tag.log)"
    sleep 1
  done
  die "llama-server $tag didn't answer in 10 minutes"
}

export SUVERYN_TEST_DATABASE_URL="$DB" SUVERYN_RAG_DEVICE=cuda SUVERYN_EXTRACT_UNSANDBOXED=1 \
  SUVERYN_LLM_BASE_URL="http://127.0.0.1:$PORT" SUVERYN_LLM_TIMEOUT_S=600
declare -A RC
run_test() {  # a name, a test file, extra environment
  local name="$1" file="$2"; shift 2
  step "$name"
  set +e
  env "$@" uv run pytest "packages/rag/tests/$file" -v -rs -s -p no:cacheprovider \
    --junitxml="$RESULTS/$name.xml" 2>&1 | tee "$RESULTS/$name.log"
  RC[$name]=${PIPESTATUS[0]}
  set -e
}

for tag in $LLAMA_TAG $COMPARE; do
  step "llama-server $tag"
  serve "$tag"
  nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits -lms 500 > "$RESULTS/memory-$tag.csv" &
  MEM_PID=$!
  [ "$tag" = "$LLAMA_TAG" ] && run_test "reader-$tag" test_e2e.py
  run_test "answers-$tag" test_answers_e2e.py SUVERYN_EVAL_REPORT="$RESULTS/answers-$tag.json"
  run_test "reads-$tag" test_playbook_reads_e2e.py SUVERYN_EVAL_REPORT_READS="$RESULTS/reads-$tag.json"
  stop_all
done

step "summary"
{
  echo "GPU round $(date -u +%Y-%m-%dT%H:%MZ)"
  nvidia-smi --query-gpu=name,driver_version,memory.total --format=csv,noheader | sed 's/^/card: /'
  echo "suveryn-core: $(git -C "$CORE" rev-parse --short HEAD) ($(git -C "$CORE" rev-parse --abbrev-ref HEAD))"
  echo "model: $MODEL_FILE"
  for csv in "$RESULTS"/memory-*.csv; do   # this run's and any earlier run's kept in $WORK
    tag="$(basename "$csv" .csv)"; tag="${tag#memory-}"
    echo "llama.cpp $tag (${LLAMA_COMMIT[$tag]:0:7}): peak $(sort -n "$csv" | tail -1) MiB used"
  done
  for xml in "$RESULTS"/*.xml; do
    name="$(basename "$xml" .xml)"
    uv run python - "$xml" "$name" "${RC[$name]:-?}" <<'PY'
import sys, xml.etree.ElementTree as ET
r = ET.parse(sys.argv[1]).getroot()
s = r if r.tag == "testsuite" else r.find("testsuite")
t, f, e, k = (int(s.get(a, 0)) for a in ("tests", "failures", "errors", "skipped"))
print(f"{sys.argv[2]}: {t - f - e - k} passed, {f} failed, {e} errors, {k} skipped (exit {sys.argv[3]})")
PY
  done
  for log in "$RESULTS"/reader-*.log; do
    echo "out of memory in $(basename "$log"): $(grep -ci 'out of memory' "$log" || true)"
  done
  for j in "$RESULTS"/answers-*.json; do
    [ -f "$j" ] && uv run python -c "import json,sys; r=json.load(open(sys.argv[1])); s=sorted(c['seconds'] for c in r['cases'] if 'seconds' in c); print(f\"{sys.argv[1].split('/')[-1]}: {r['passed']}/{r['total']} cases, median {s[len(s)//2] if s else '?'} s per answer\"); [print('  failed:', f) for f in r['failures']]" "$j"
  done
  for j in "$RESULTS"/reads-*.json; do
    [ -f "$j" ] && uv run python -c "import json,sys; r=json.load(open(sys.argv[1])); print(f\"{sys.argv[1].split('/')[-1]}: {r['playbook']}, {r['retries']} retries, failures: {r['failures'] or 'none'}\")" "$j"
  done
} | tee "$RESULTS/summary.txt"
echo
echo "Paste everything between the lines above (from 'GPU round') back into the chat. Reports: $RESULTS"
