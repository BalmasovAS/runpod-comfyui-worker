#!/usr/bin/env bash
# comfy-manager-set-mode: Set the network mode for ComfyUI-Manager.
# Usage: comfy-manager-set-mode <mode>
#   <mode> can be: "offline" or "online"
set -euo pipefail

MODE="${1:-}"

if [[ -z "$MODE" ]]; then
    echo "Usage: comfy-manager-set-mode <offline|online>" >&2
    exit 64 # EX_USAGE
fi

CONFIG_FILE="/comfyui/custom_nodes/ComfyUI-Manager/config.json"

if [[ ! -f "$CONFIG_FILE" ]]; then
    echo "ComfyUI-Manager config file not found at $CONFIG_FILE" >&2
    exit 1
fi

# Use jq if available, otherwise fallback to sed
if command -v jq &> /dev/null; then
    jq --arg mode "$MODE" '.channel_mode = $mode' "$CONFIG_FILE" > "${CONFIG_FILE}.tmp" && \
        mv "${CONFIG_FILE}.tmp" "$CONFIG_FILE"
else
    # Fallback to sed for simple replacement
    if [[ "$MODE" == "offline" ]]; then
        sed -i 's/"channel_mode": "online"/"channel_mode": "offline"/g' "$CONFIG_FILE" || \
        sed -i 's/"channel_mode": "local"/"channel_mode": "offline"/g' "$CONFIG_FILE" || \
        echo '"channel_mode": "offline"' >> "$CONFIG_FILE"
    elif [[ "$MODE" == "online" ]]; then
        sed -i 's/"channel_mode": "offline"/"channel_mode": "online"/g' "$CONFIG_FILE" || \
        sed -i 's/"channel_mode": "local"/"channel_mode": "online"/g" "$CONFIG_FILE" || \
        echo '"channel_mode": "online"' >> "$CONFIG_FILE"
    fi
fi

echo "ComfyUI-Manager channel_mode set to: $MODE"
exit 0
