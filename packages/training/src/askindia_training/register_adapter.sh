#!/usr/bin/env bash
# Register a PEFT LoRA adapter with the local Ollama as a model named ${2:-askindia-lora}, on top of
# the same base the agent uses in development. Usage: register_adapter.sh <adapter dir> [name]
set -euo pipefail
ADAPTER=$(readlink -f "$1"); NAME="${2:-askindia-lora}"
test -f "$ADAPTER/adapter_model.safetensors" || { echo "no adapter at $ADAPTER"; exit 1; }
TMP=$(mktemp -d)
cat > "$TMP/Modelfile" <<MODELFILE
FROM qwen2.5-coder:7b
ADAPTER $ADAPTER
PARAMETER temperature 0
MODELFILE
ollama create "$NAME" -f "$TMP/Modelfile"
ollama show "$NAME" | head -20
rm -rf "$TMP"
