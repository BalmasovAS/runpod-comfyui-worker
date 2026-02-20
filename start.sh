#!/usr/bin/env bash

# Use libtcmalloc for better memory management
TCMALLOC="$(ldconfig -p | grep -Po "libtcmalloc.so.\d" | head -n 1)"
export LD_PRELOAD="${TCMALLOC}"

# Ensure ComfyUI-Manager runs in offline network mode inside the container
comfy-manager-set-mode offline || echo "worker-comfyui - Could not set ComfyUI-Manager network_mode" >&2

# Setup symbolic links to Network Volume (models are mounted at runtime)
echo "worker-comfyui: Setting up model paths..."
RUNPOD_VOLUME_PATH="${RUNPOD_VOLUME_PATH:-/runpod-volume}"

# Create model directories in ComfyUI if they don't exist
mkdir -p /comfyui/models/{loras,vae,diffusion_models,text_encoders,controlnet,upscale_models,unet}

# Remove existing symlinks if they exist (from Dockerfile build)
rm -f /comfyui/models/loras /comfyui/models/vae /comfyui/models/diffusion_models
rm -f /comfyui/models/text_encoders /comfyui/models/controlnet /comfyui/models/upscale_models

# Create symbolic links to Network Volume (only if target exists)
if [ -d "$RUNPOD_VOLUME_PATH/loras" ]; then
    ln -sf "$RUNPOD_VOLUME_PATH/loras" /comfyui/models/loras
    echo "  ✅ Linked loras: $RUNPOD_VOLUME_PATH/loras -> /comfyui/models/loras"
fi

if [ -d "$RUNPOD_VOLUME_PATH/vae" ]; then
    ln -sf "$RUNPOD_VOLUME_PATH/vae" /comfyui/models/vae
    echo "  ✅ Linked vae: $RUNPOD_VOLUME_PATH/vae -> /comfyui/models/vae"
fi

if [ -d "$RUNPOD_VOLUME_PATH/diffusion_models" ]; then
    ln -sf "$RUNPOD_VOLUME_PATH/diffusion_models" /comfyui/models/diffusion_models
    echo "  ✅ Linked diffusion_models: $RUNPOD_VOLUME_PATH/diffusion_models -> /comfyui/models/diffusion_models"
fi

if [ -d "$RUNPOD_VOLUME_PATH/text_encoders" ]; then
    ln -sf "$RUNPOD_VOLUME_PATH/text_encoders" /comfyui/models/text_encoders
    echo "  ✅ Linked text_encoders: $RUNPOD_VOLUME_PATH/text_encoders -> /comfyui/models/text_encoders"
fi

if [ -d "$RUNPOD_VOLUME_PATH/controlnet" ]; then
    ln -sf "$RUNPOD_VOLUME_PATH/controlnet" /comfyui/models/controlnet
    echo "  ✅ Linked controlnet: $RUNPOD_VOLUME_PATH/controlnet -> /comfyui/models/controlnet"
fi

if [ -d "$RUNPOD_VOLUME_PATH/upscale_models" ]; then
    ln -sf "$RUNPOD_VOLUME_PATH/upscale_models" /comfyui/models/upscale_models
    echo "  ✅ Linked upscale_models: $RUNPOD_VOLUME_PATH/upscale_models -> /comfyui/models/upscale_models"
fi

# Check for ComfyUI/models structure on Network Volume
if [ -d "$RUNPOD_VOLUME_PATH/ComfyUI/models" ]; then
    echo "  📁 Found ComfyUI/models structure on Network Volume"
    # Link subdirectories from ComfyUI/models
    for subdir in loras vae checkpoints clip controlnet upscale_models unet diffusion_models; do
        if [ -d "$RUNPOD_VOLUME_PATH/ComfyUI/models/$subdir" ]; then
            # Map clip to text_encoders for ComfyUI
            if [ "$subdir" = "clip" ]; then
                ln -sf "$RUNPOD_VOLUME_PATH/ComfyUI/models/$subdir" /comfyui/models/text_encoders
                echo "  ✅ Linked $subdir -> text_encoders: $RUNPOD_VOLUME_PATH/ComfyUI/models/$subdir"
            elif [ "$subdir" = "checkpoints" ] || [ "$subdir" = "diffusion_models" ]; then
                # Если diffusion_models уже существует, не перезаписываем
                if [ ! -L /comfyui/models/diffusion_models ] || [ "$subdir" = "diffusion_models" ]; then
                    ln -sf "$RUNPOD_VOLUME_PATH/ComfyUI/models/$subdir" /comfyui/models/diffusion_models
                    echo "  ✅ Linked $subdir -> diffusion_models: $RUNPOD_VOLUME_PATH/ComfyUI/models/$subdir"
                fi
            else
                ln -sf "$RUNPOD_VOLUME_PATH/ComfyUI/models/$subdir" /comfyui/models/$subdir
                echo "  ✅ Linked $subdir: $RUNPOD_VOLUME_PATH/ComfyUI/models/$subdir"
            fi
        fi
    done
fi

# List what's available
echo "worker-comfyui: Model directories:"
ls -la /comfyui/models/ | head -20

echo "worker-comfyui: Starting ComfyUI"

# Проверяем наличие установленных custom nodes
echo "worker-comfyui: Checking installed custom nodes..."
if [ -d "/comfyui/custom_nodes/ComfyUI-QwenTTS" ]; then
    echo "  ✅ ComfyUI-QwenTTS найден"
    echo "  📁 Содержимое папки:"
    ls -la /comfyui/custom_nodes/ComfyUI-QwenTTS/ | head -10
    echo "  📄 Python файлы в папке:"
    find /comfyui/custom_nodes/ComfyUI-QwenTTS -name "*.py" | head -5
    if [ -f "/comfyui/custom_nodes/ComfyUI-QwenTTS/requirements.txt" ]; then
        echo "  ✅ requirements.txt найден"
    else
        echo "  ⚠️ requirements.txt НЕ найден"
    fi
else
    echo "  ⚠️ ComfyUI-QwenTTS НЕ найден в /comfyui/custom_nodes/"
    echo "  📁 Доступные custom nodes:"
    ls -la /comfyui/custom_nodes/ | head -10
fi

# Allow operators to tweak verbosity; default is DEBUG.
: "${COMFY_LOG_LEVEL:=DEBUG}"

# Function to wait for ComfyUI to be ready
wait_for_comfyui() {
    local pid=$1
    local max_attempts=120
    local attempt=1
    
    echo "worker-comfyui: Waiting for ComfyUI to be ready..."
    
    while [ $attempt -le $max_attempts ]; do
        # Check if process is still running
        if ! kill -0 $pid 2>/dev/null; then
            echo "worker-comfyui: ❌ ComfyUI process died!"
            return 1
        fi
        
        # Check if ComfyUI HTTP server is ready
        if curl -s http://127.0.0.1:8188/system_stats > /dev/null 2>&1; then
            echo "worker-comfyui: ✅ ComfyUI is ready! (attempt $attempt/$max_attempts)"
            return 0
        fi
        
        if [ $((attempt % 10)) -eq 0 ]; then
            echo "worker-comfyui: ⏳ Still waiting... (attempt $attempt/$max_attempts)"
        fi
        
        sleep 1
        attempt=$((attempt + 1))
    done
    
    echo "worker-comfyui: ❌ ComfyUI did not become ready after $max_attempts attempts"
    return 1
}

# Serve the API and don't shutdown the container
if [ "$SERVE_API_LOCALLY" == "true" ]; then
    python -u /comfyui/main.py --disable-auto-launch --disable-metadata --listen --verbose "${COMFY_LOG_LEVEL}" --log-stdout &
    COMFYUI_PID=$!
    echo "worker-comfyui: ComfyUI started (PID: $COMFYUI_PID)"
    
    # Wait for ComfyUI to be ready
    if ! wait_for_comfyui $COMFYUI_PID; then
        exit 1
    fi
    
    # Проверяем наличие QwenTTS нод после запуска ComfyUI
    echo "worker-comfyui: Checking QwenTTS nodes availability..."
    sleep 5  # Даем время на загрузку нод
    if curl -s http://127.0.0.1:8188/object_info > /tmp/object_info.json 2>/dev/null; then
        if grep -q "AILab_Qwen3TTSVoiceInstruct" /tmp/object_info.json; then
            echo "  ✅ AILab_Qwen3TTSVoiceInstruct найден в object_info"
        else
            echo "  ⚠️ AILab_Qwen3TTSVoiceInstruct НЕ найден в object_info"
            echo "  🔍 Ищем похожие ноды:"
            grep -i "qwen\|tts\|voice" /tmp/object_info.json | head -5 || echo "    Нет похожих нод"
        fi
        if grep -q "AILab_Qwen3TTSVoiceDesign_Advanced" /tmp/object_info.json; then
            echo "  ✅ AILab_Qwen3TTSVoiceDesign_Advanced найден в object_info"
        else
            echo "  ⚠️ AILab_Qwen3TTSVoiceDesign_Advanced НЕ найден в object_info"
        fi
    else
        echo "  ⚠️ Не удалось получить object_info от ComfyUI"
    fi
    
    echo "worker-comfyui: Starting RunPod Handler"
    python -u /handler.py --rp_serve_api --rp_api_host=0.0.0.0
else
    python -u /comfyui/main.py --disable-auto-launch --disable-metadata --listen --verbose "${COMFY_LOG_LEVEL}" --log-stdout &
    COMFYUI_PID=$!
    echo "worker-comfyui: ComfyUI started (PID: $COMFYUI_PID)"
    
    # Wait for ComfyUI to be ready
    if ! wait_for_comfyui $COMFYUI_PID; then
        exit 1
    fi
    
    echo "worker-comfyui: Starting RunPod Handler"
    python -u /handler.py
fi
