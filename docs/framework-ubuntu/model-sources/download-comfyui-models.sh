#!/bin/bash
set -e
echo "=== z_image_turbo_bf16 start $(date) ==="
wget -c -q --show-progress 'https://huggingface.co/Comfy-Org/z_image_turbo/resolve/main/split_files/diffusion_models/z_image_turbo_bf16.safetensors' -O /storage/models/comfyui/diffusion_models/z_image_turbo_bf16.safetensors.partial && mv /storage/models/comfyui/diffusion_models/z_image_turbo_bf16.safetensors.partial /storage/models/comfyui/diffusion_models/z_image_turbo_bf16.safetensors
echo "=== z_image_turbo_bf16 done $(date) ==="
echo "=== qwen_3_4b text encoder start $(date) ==="
wget -c -q --show-progress 'https://huggingface.co/Comfy-Org/z_image_turbo/resolve/main/split_files/text_encoders/qwen_3_4b.safetensors' -O /storage/models/comfyui/text_encoders/qwen_3_4b.safetensors.partial && mv /storage/models/comfyui/text_encoders/qwen_3_4b.safetensors.partial /storage/models/comfyui/text_encoders/qwen_3_4b.safetensors
echo "=== qwen_3_4b done $(date) ==="
echo "=== ae (vae) start $(date) ==="
wget -c -q --show-progress 'https://huggingface.co/Comfy-Org/z_image_turbo/resolve/main/split_files/vae/ae.safetensors' -O /storage/models/comfyui/vae/ae.safetensors.partial && mv /storage/models/comfyui/vae/ae.safetensors.partial /storage/models/comfyui/vae/ae.safetensors
echo "=== ae done $(date) ==="
echo ALL_COMFYUI_DOWNLOADS_COMPLETE
