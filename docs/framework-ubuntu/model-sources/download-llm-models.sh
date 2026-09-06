#!/bin/bash
set -e
cd /storage/models/llm
echo "=== Qwen2.5-Coder-32B start $(date) ==="
wget -c -q --show-progress 'https://huggingface.co/bartowski/Qwen2.5-Coder-32B-Instruct-GGUF/resolve/main/Qwen2.5-Coder-32B-Instruct-Q4_K_M.gguf' -O Qwen2.5-Coder-32B-Instruct-Q4_K_M.gguf.partial && mv Qwen2.5-Coder-32B-Instruct-Q4_K_M.gguf.partial Qwen2.5-Coder-32B-Instruct-Q4_K_M.gguf
echo "=== Qwen2.5-Coder-32B done $(date) ==="
echo "=== DeepSeek-R1-Distill-Qwen-32B start $(date) ==="
wget -c -q --show-progress 'https://huggingface.co/bartowski/DeepSeek-R1-Distill-Qwen-32B-GGUF/resolve/main/DeepSeek-R1-Distill-Qwen-32B-Q4_K_M.gguf' -O DeepSeek-R1-Distill-Qwen-32B-Q4_K_M.gguf.partial && mv DeepSeek-R1-Distill-Qwen-32B-Q4_K_M.gguf.partial DeepSeek-R1-Distill-Qwen-32B-Q4_K_M.gguf
echo "=== DeepSeek-R1-Distill-Qwen-32B done $(date) ==="
echo "=== Llama-3.3-70B start $(date) ==="
wget -c -q --show-progress 'https://huggingface.co/bartowski/Llama-3.3-70B-Instruct-GGUF/resolve/main/Llama-3.3-70B-Instruct-Q4_K_M.gguf' -O Llama-3.3-70B-Instruct-Q4_K_M.gguf.partial && mv Llama-3.3-70B-Instruct-Q4_K_M.gguf.partial Llama-3.3-70B-Instruct-Q4_K_M.gguf
echo "=== Llama-3.3-70B done $(date) ==="
echo ALL_DOWNLOADS_COMPLETE
