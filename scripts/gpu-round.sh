#!/usr/bin/env bash
# The GPU round: the tests that need a real card and the real model, on a rented GPU machine (a RunPod pod,
# Ubuntu 22.04 or 24.04 with the CUDA toolkit, root, /workspace on the volume). From a clone of this repository:
#
#   bash scripts/gpu-round.sh                 # llama.cpp at the appliance's pin
#   COMPARE=b12111 bash scripts/gpu-round.sh  # and again with a newer llama.cpp, the answers and the reads only
#   LLAMA_TAG=b11223 bash scripts/gpu-round.sh  # only that llama.cpp; the summary keeps earlier runs' results
#   PACKS=/workspace/suveryn-packs bash scripts/gpu-round.sh  # the packs' playbooks too (a checkout copied in:
#                                             # the repository is private; their runs are in its tests/runs)
#     from a Mac: COPYFILE_DISABLE=1 tar -czf - suveryn-packs | ssh … "tar -xzf - -C /workspace"
#   OWN_RUNS=/workspace/own-runs bash scripts/gpu-round.sh  # run specs on your own files too, kept outside the
#                                             # repositories; a spec with "show_facts": true writes what was read to
#                                             # results/facts/<run>.txt, for you, never to the summary
#   MEANING=1 bash scripts/gpu-round.sh       # also: the model judging the planted-error benchmark's answers, beside
#                                             # the rules (an experiment; MEANING=2: once more with thinking;
#                                             # ONLY_MEANING=1: nothing but that, a few minutes)
#   OWN_QUESTIONS=/workspace/own-questions bash scripts/gpu-round.sh  # questions about your own files (test_answers_e2e.py:
#                                             # <name>.json beside its files); answers in results/answers/, for you
#   PEOPLE="1 2 4 8" bash scripts/gpu-round.sh  # also: that many people at work at the same moment (e2e/tests/
#                                             # test_several_people.py): how long each waits for documents, answers
#                                             # and a playbook, and what fails. PEOPLE_SPEC=<a run spec>: on that
#                                             # run's documents and playbook (your own, say) instead of core's deed
#                                             # intake; ONLY_PEOPLE=1: nothing but that step
#   ONLY_RUNS=1 bash scripts/gpu-round.sh     # only the playbook runs (and PEOPLE, if given); SHOW_FACTS=1: what every
#                                             # run read, the fictional ones too, in results/facts/<run>.txt
#
# What it runs, in order, with llama-server holding the model on the same card as the appliance does:
#   1. test_e2e.py on the GPU (Docling and bge-m3 next to the model: does it all fit?);
#   2. test_answers_e2e.py (the answers held to their citations, the trap deed's questions);
#   3. test_playbook_reads_e2e.py (deed intake read by the model);
#   4. e2e/tests/test_playbook_runs.py (every playbook run start to finish through the gateway's API, with
#      PostgreSQL and Keycloak as the end-to-end stack runs them: the reads, the answers in words, the checks,
#      the checkpoint and the summary). RUNS=0 leaves it out;
#   5. with PEOPLE, on the same stack: several people at the same moment.
# It ends with a summary to paste back: the card, the versions, the peak memory, pass or fail per run. The reports
# hold per check whether it held, never document or answer text. Only the fictional trap deed is read.
# Safe to run again: the downloads, the build and the database are kept in $WORK and reused.
set -euo pipefail

CORE="$(cd "$(dirname "$0")/.." && pwd)"
WORK="${WORK:-/workspace/gpu-round}"
LLAMA_TAG="${LLAMA_TAG:-b12111}"            # suveryn-appliance provision/versions.json
COMPARE="${COMPARE:-}"                      # another llama.cpp tag to compare, or empty
RUNS="${RUNS:-1}"                           # the playbook runs through the gateway (4. above)
PACKS="${PACKS:-}"                          # a suveryn-packs checkout, for its playbooks' runs
OWN_RUNS="${OWN_RUNS:-}"                    # a folder of run specs on your own files (never in a repository)
MEANING="${MEANING:-${ONLY_MEANING:-0}}"                     # 1: the meaning experiment too (harness/tests/meaning_experiment.py); 2: and again with thinking
PEOPLE="${PEOPLE:-}"                        # numbers of people at work at the same moment, as "1 2 4 8"; empty: not run
PEOPLE_SPEC="${PEOPLE_SPEC:-}"              # the run spec they work on; empty: core's deed intake on the trap deed
ONLY_RUNS="${ONLY_RUNS:-0}"                 # 1: only the playbook runs
SHOW_FACTS="${SHOW_FACTS:-0}"               # 1: write what every run read, not only the runs that ask for it
ONLY_PEOPLE="${ONLY_PEOPLE:-0}"             # 1: only the several-people step
OWN_QUESTIONS="${OWN_QUESTIONS:-}"          # a folder of your own files with questions about them (never in a repository)
KC_VERSION=26.8.1                           # suveryn-appliance provision/versions.json
KC_SHA256=4e2740b181faa2ea623a1c2ecf00855935311e546046e2f857615a47ed24cbe8
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
apt-get install -y -qq git cmake build-essential libssl-dev openjdk-21-jre-headless ocrmypdf tesseract-ocr-nld tesseract-ocr-fra \
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
uv sync --all-packages --dev --group e2e -q
if [ "$RUNS" = 1 ] && [ ! -x "$WORK/keycloak-$KC_VERSION/bin/kc.sh" ]; then
  step "Keycloak $KC_VERSION (the playbook runs' sign-in)"
  curl -fsSL -o "$WORK/keycloak.tar.gz" "https://github.com/keycloak/keycloak/releases/download/$KC_VERSION/keycloak-$KC_VERSION.tar.gz"
  echo "$KC_SHA256  $WORK/keycloak.tar.gz" | sha256sum -c --quiet || die "Keycloak download doesn't match its checksum"
  tar -xzf "$WORK/keycloak.tar.gz" -C "$WORK"
fi
[ -z "$PACKS" ] || [ -d "$PACKS/be-notary" ] || die "PACKS=$PACKS isn't a suveryn-packs checkout"

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

playbook_runs() {  # a tag: the end-to-end stack's PostgreSQL, Keycloak and gateway with this model server, no UI
  local tag="$1"
  step "playbook runs-$tag"
  export E2E_SERVICES=local E2E_KEYCLOAK_HOME="$WORK/keycloak-$KC_VERSION" E2E_LLM="http://127.0.0.1:$PORT" E2E_NO_UI=1 \
    E2E_RAG_DEVICE=cuda E2E_PACKS_DIR="$PACKS"
  set +e
  uv run python e2e/stack.py up 2>&1 | grep -v "health:"
  if [ "$ONLY_PEOPLE" != 1 ]; then
    E2E_RUNS_DIR="${PACKS:+$PACKS/tests/runs}:${OWN_RUNS:-}" E2E_RUNS_REPORT="$RESULTS/runs-$tag.json" E2E_RUNS_FACTS="$RESULTS/facts" E2E_RUNS_SHOW_ALL="$SHOW_FACTS" \
      uv run pytest e2e/tests/test_playbook_runs.py -v -rs -s -p no:cacheprovider --junitxml="$RESULTS/runs-$tag.xml" 2>&1 \
      | tee "$RESULTS/runs-$tag.log"
    RC[runs-$tag]=${PIPESTATUS[0]}
  fi
  if [ -n "$PEOPLE" ]; then
    step "several people-$tag: $PEOPLE"
    E2E_PEOPLE="$PEOPLE" E2E_PEOPLE_SPEC="$PEOPLE_SPEC" E2E_PEOPLE_REPORT="$RESULTS/people-$tag.json" \
      uv run pytest e2e/tests/test_several_people.py -v -rs -s -p no:cacheprovider --junitxml="$RESULTS/people-$tag.xml" 2>&1 \
      | tee "$RESULTS/people-$tag.log"
    RC[people-$tag]=${PIPESTATUS[0]}
  fi
  uv run python e2e/stack.py stop gateway; uv run python e2e/stack.py stop keycloak  # PostgreSQL stays for what follows
  set -e
  unset E2E_SERVICES E2E_KEYCLOAK_HOME E2E_LLM E2E_NO_UI E2E_RAG_DEVICE E2E_PACKS_DIR
}

for tag in $LLAMA_TAG $COMPARE; do
  step "llama-server $tag"
  serve "$tag"
  nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits -lms 500 > "$RESULTS/memory-$tag.csv" &
  MEM_PID=$!
  if [ "$tag" = "$LLAMA_TAG" ] && [ "$MEANING" != 0 ]; then
    step "meaning experiment"
    set +e
    : > "$RESULTS/meaning.txt"
    for prompt in ${MEANING_PROMPTS:-same follows kind}; do
      uv run python packages/harness/tests/meaning_experiment.py --url "http://127.0.0.1:$PORT" --prompt "$prompt" \
        --out "$RESULTS/meaning-$prompt.json" | tee -a "$RESULTS/meaning.txt"
    done
    [ "$MEANING" = 2 ] && uv run python packages/harness/tests/meaning_experiment.py --url "http://127.0.0.1:$PORT" \
      --prompt "${MEANING_THINKING_PROMPT:-kind}" --thinking --out "$RESULTS/meaning-thinking.json" | tee -a "$RESULTS/meaning.txt"
    set -e
  fi
  if [ "${ONLY_MEANING:-0}" = 1 ]; then stop_all; continue; fi
  if [ "$ONLY_PEOPLE" = 1 ] || [ "$ONLY_RUNS" = 1 ]; then
    [ "$tag" = "$LLAMA_TAG" ] && playbook_runs "$tag"
    stop_all; continue
  fi
  [ "$tag" = "$LLAMA_TAG" ] && run_test "reader-$tag" test_e2e.py
  rm -rf "$RESULTS/answers"  # your own questions' answers, this round's only
  run_test "answers-$tag" test_answers_e2e.py SUVERYN_EVAL_REPORT="$RESULTS/answers-$tag.json" \
    SUVERYN_EVAL_DIR="${OWN_QUESTIONS:-/nonexistent}" SUVERYN_EVAL_ANSWERS="$RESULTS/answers"
  run_test "reads-$tag" test_playbook_reads_e2e.py SUVERYN_EVAL_REPORT_READS="$RESULTS/reads-$tag.json"
  [ "$tag" = "$LLAMA_TAG" ] && [ "$RUNS" = 1 ] && playbook_runs "$tag"
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
  [ "$MEANING" != 0 ] && [ -f "$RESULTS/meaning.txt" ] && cat "$RESULTS/meaning.txt"
  for xml in "$RESULTS"/*.xml; do
    [ -f "$xml" ] && [ "${ONLY_MEANING:-0}" != 1 ] || continue
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
    [ -f "$log" ] || continue
    echo "out of memory in $(basename "$log"): $(grep -ci 'out of memory' "$log" || true)"
  done
  for j in "$RESULTS"/answers-*.json; do
    [ -f "$j" ] && uv run python -c "import json,sys; r=json.load(open(sys.argv[1])); s=sorted(c['seconds'] for c in r['cases'] if 'seconds' in c); print(f\"{sys.argv[1].split('/')[-1]}: {r['passed']}/{r['total']} cases, median {s[len(s)//2] if s else '?'} s per answer\"); [print('  failed:', f) for f in r['failures']]" "$j"
  done
  for j in "$RESULTS"/runs-*.json; do
    [ -f "$j" ] && uv run python -c "
import json, sys
for name, r in json.load(open(sys.argv[1])).items():
    failed = [k for k, ok in r['checks'].items() if not ok]
    print(f\"{name} ({sys.argv[1].split('/')[-1]}): {len(r['checks']) - len(failed)}/{len(r['checks'])} held, {r['found']} of {r['facts']} facts found, {r['seconds']} s\")
    score = ', '.join(f'{k} {a}/{b}' for k, (a, b) in (r.get('score') or {}).items() if b)
    if score:  # a run without expectations has none
        print('  score: ' + score)
    if r.get('in_part'):
        print('  read in part: ' + ', '.join(r['in_part']))
    [print('  failed:', f) for f in failed]" "$j"
  done
  for j in "$RESULTS"/people-*.json; do
    [ -f "$j" ] && uv run python -c "
import json, sys
r = json.load(open(sys.argv[1]))
print(f\"several people ({sys.argv[1].split('/')[-1]}), {r['playbook']} on {r['spec']}: seconds as median (worst)\")
for l in r['levels']:
    t = lambda k: f\"{l[k]['median']} ({l[k]['worst']})\" if l[k] else '-'
    print(f\"  {l['people']} people: documents read {t('documents')}, first words {t('first_words')}, whole answer {t('answer')}, \"
          f\"playbook {t('playbook')}; told to wait {l['told_to_wait']}, playbook refused as busy {l['runs_refused']}, \"
          f\"failed {len(l['failed'])}, peak {l['peak_mib']} MiB, {l['seconds']} s in all\")
    [print('    failed:', f) for f in l['failed']]" "$j"
  done
  [ -d "$RESULTS/facts" ] && echo "what was read in your own runs: $RESULTS/facts (for you; not to paste)"
  [ -d "$RESULTS/answers" ] && echo "the answers to your own questions: $RESULTS/answers (for you; not to paste)"
  for j in "$RESULTS"/reads-*.json; do
    [ -f "$j" ] && uv run python -c "import json,sys; r=json.load(open(sys.argv[1])); print(f\"{sys.argv[1].split('/')[-1]}: {r['playbook']}, {r['retries']} retries, failures: {r['failures'] or 'none'}\")" "$j"
  done
} | tee "$RESULTS/summary.txt"
echo
echo "Paste everything between the lines above (from 'GPU round') back into the chat. Reports: $RESULTS"
