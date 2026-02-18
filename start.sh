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
    for subdir in loras vae checkpoints clip controlnet upscale_models unet; do
        if [ -d "$RUNPOD_VOLUME_PATH/ComfyUI/models/$subdir" ]; then
            # Map clip to text_encoders for ComfyUI
            if [ "$subdir" = "clip" ]; then
                ln -sf "$RUNPOD_VOLUME_PATH/ComfyUI/models/$subdir" /comfyui/models/text_encoders
                echo "  ✅ Linked $subdir -> text_encoders: $RUNPOD_VOLUME_PATH/ComfyUI/models/$subdir"
            elif [ "$subdir" = "checkpoints" ]; then
                ln -sf "$RUNPOD_VOLUME_PATH/ComfyUI/models/$subdir" /comfyui/models/diffusion_models
                echo "  ✅ Linked $subdir -> diffusion_models: $RUNPOD_VOLUME_PATH/ComfyUI/models/$subdir"
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
