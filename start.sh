#!/usr/bin/env bash

# Use libtcmalloc for better memory management
TCMALLOC="$(ldconfig -p | grep -Po "libtcmalloc.so.\d" | head -n 1)"
export LD_PRELOAD="${TCMALLOC}"

# Ensure ComfyUI-Manager runs in offline network mode inside the container
comfy-manager-set-mode offline || echo "worker-comfyui - Could not set ComfyUI-Manager network_mode" >&2

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
