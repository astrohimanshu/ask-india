# Ollama with the production model baked in, so a scale-from-zero replica never downloads.
# Build: docker build -t ghcr.io/astrohimanshu/ask-india-ollama:dev infra/azure/ollama
FROM ollama/ollama:0.32.15
ARG MODEL=qwen2.5-coder:3b
ENV OLLAMA_MODELS=/models OLLAMA_HOST=0.0.0.0:11434 OLLAMA_KEEP_ALIVE=30m OLLAMA_NUM_PARALLEL=1
RUN mkdir -p /models && (ollama serve >/tmp/serve.log 2>&1 & sleep 5 && ollama pull "$MODEL" && pkill ollama) && ls /models/manifests/registry.ollama.ai/library
EXPOSE 11434
