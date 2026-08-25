#!/usr/bin/env bash
# Start the local Ollama server in a detached tmux session and pull the dev models.
set -euo pipefail
export PATH="$HOME/.local/bin:$PATH"
if ! tmux has-session -t ollama 2>/dev/null; then
  tmux new-session -d -s ollama "OLLAMA_KEEP_ALIVE=30m ollama serve 2>&1 | tee -a ~/ollama.log"
  sleep 3
fi
curl -sf localhost:11434/api/version >/dev/null && echo "ollama up"
ollama pull "${SQL_MODEL_NAME:-qwen2.5-coder:7b}"
ollama pull "${CHAT_MODEL_NAME:-qwen2.5:7b-instruct}"
