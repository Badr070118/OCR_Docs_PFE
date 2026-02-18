#!/usr/bin/env bash
set -euo pipefail

MODEL_PATH="${MODEL_PATH:-models/llama-3.1-8b-instruct-q4_k_m.gguf}"
NGL="${NGL:-35}"
CTX="${CTX:-4096}"
HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-8080}"
LLAMA_CPP_SERVER_BIN="${LLAMA_CPP_SERVER_BIN:-./server}"

echo "Starting llama.cpp server..."
echo "BIN=${LLAMA_CPP_SERVER_BIN}"
echo "MODEL=${MODEL_PATH}"
echo "NGL=${NGL}"
echo "CTX=${CTX}"
echo "HOST=${HOST}"
echo "PORT=${PORT}"

"${LLAMA_CPP_SERVER_BIN}" -m "${MODEL_PATH}" -ngl "${NGL}" -c "${CTX}" --host "${HOST}" --port "${PORT}"
