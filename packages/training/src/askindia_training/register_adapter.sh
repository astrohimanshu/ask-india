#!/usr/bin/env bash
# Register a PEFT LoRA adapter with the local Ollama as ${2:-askindia-lora}, on top of the same
# base the agent uses in development. Ollama serves GGUF bases, so the adapter is converted with
# llama.cpp's converter first (needs the base model's safetensors in the Hugging Face cache).
# Usage: register_adapter.sh <adapter dir> [name]
set -euo pipefail
export PATH="$HOME/.local/bin:$PATH"
ADAPTER=$(readlink -f "$1"); NAME="${2:-askindia-lora}"
test -f "$ADAPTER/adapter_model.safetensors" || { echo "no adapter at $ADAPTER"; exit 1; }
LLAMA_CPP="${LLAMA_CPP:-$HOME/tools/llama.cpp}"
[ -d "$LLAMA_CPP" ] || git clone -q --depth 1 https://github.com/ggml-org/llama.cpp "$LLAMA_CPP"
BASE=$(ls -d "$HOME"/.cache/huggingface/hub/models--Qwen--Qwen2.5-Coder-7B-Instruct/snapshots/*/ | head -1)
GGUF="$ADAPTER/../${NAME}-f16.gguf"
uv run --extra train --with gguf --with sentencepiece python "$LLAMA_CPP/convert_lora_to_gguf.py" \
  --base "$BASE" --outfile "$GGUF" --outtype f16 "$ADAPTER"
printf "FROM qwen2.5-coder:7b\nADAPTER %s\nPARAMETER temperature 0\n" "$(readlink -f "$GGUF")" > "$ADAPTER/../Modelfile"
ollama create "$NAME" -f "$ADAPTER/../Modelfile"
ollama list | grep "$NAME"
