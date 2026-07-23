#!/bin/bash
set -e
echo "=== sd_xl_base_1.0 start $(date) ==="
wget -c -q --show-progress 'https://huggingface.co/stabilityai/stable-diffusion-xl-base-1.0/resolve/main/sd_xl_base_1.0.safetensors' -O /storage/models/comfyui/checkpoints/sd_xl_base_1.0.safetensors.partial && mv /storage/models/comfyui/checkpoints/sd_xl_base_1.0.safetensors.partial /storage/models/comfyui/checkpoints/sd_xl_base_1.0.safetensors
echo "=== sd_xl_base_1.0 done $(date) ==="

echo "=== flux1-schnell-fp8 start $(date) ==="
wget -c -q --show-progress 'https://huggingface.co/Comfy-Org/flux1-schnell/resolve/main/flux1-schnell-fp8.safetensors' -O /storage/models/comfyui/checkpoints/flux1-schnell-fp8.safetensors.partial && mv /storage/models/comfyui/checkpoints/flux1-schnell-fp8.safetensors.partial /storage/models/comfyui/checkpoints/flux1-schnell-fp8.safetensors
echo "=== flux1-schnell-fp8 done $(date) ==="

echo "=== sd15 (v1-5-pruned-emaonly) start $(date) ==="
wget -c -q --show-progress 'https://huggingface.co/stable-diffusion-v1-5/stable-diffusion-v1-5/resolve/main/v1-5-pruned-emaonly.safetensors' -O /storage/models/comfyui/checkpoints/v1-5-pruned-emaonly.safetensors.partial && mv /storage/models/comfyui/checkpoints/v1-5-pruned-emaonly.safetensors.partial /storage/models/comfyui/checkpoints/v1-5-pruned-emaonly.safetensors
echo "=== sd15 done $(date) ==="

echo ALL_EVAL_MODEL_DOWNLOADS_COMPLETE
