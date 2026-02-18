# Build argument for base image selection
ARG BASE_IMAGE=nvidia/cuda:12.6.3-cudnn-runtime-ubuntu24.04

# Stage 1: Base image with common dependencies
FROM ${BASE_IMAGE} AS base

# Build arguments for this stage with sensible defaults for standalone builds
ARG COMFYUI_VERSION=latest
ARG CUDA_VERSION_FOR_COMFY
ARG ENABLE_PYTORCH_UPGRADE=false
ARG PYTORCH_INDEX_URL

# Prevents prompts from packages asking for user input during installation
ENV DEBIAN_FRONTEND=noninteractive

# Prefer binary wheels over source distributions for faster pip installations
ENV PIP_PREFER_BINARY=1

# Ensures output from python is printed immediately to the terminal without buffering
ENV PYTHONUNBUFFERED=1

# Speed up some cmake builds
ENV CMAKE_BUILD_PARALLEL_LEVEL=8

# Install Python, git and other necessary tools
RUN apt-get update && apt-get install -y \
    python3.12 \
    python3.12-venv \
    git \
    wget \
    libgl1 \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender1 \
    ffmpeg \
    && ln -sf /usr/bin/python3.12 /usr/bin/python \
    && ln -sf /usr/bin/pip3 /usr/bin/pip

# Clean up to reduce image size
RUN apt-get autoremove -y && apt-get clean -y && rm -rf /var/lib/apt/lists/*

# Install uv (latest) using official installer and create isolated venv
RUN wget -qO- https://astral.sh/uv/install.sh | sh \
    && ln -s /root/.local/bin/uv /usr/local/bin/uv \
    && ln -s /root/.local/bin/uvx /usr/local/bin/uvx \
    && uv venv /opt/venv

# Use the virtual environment for all subsequent commands
ENV PATH="/opt/venv/bin:${PATH}"

# Install comfy-cli + dependencies needed by it to install ComfyUI
RUN uv pip install comfy-cli pip setuptools wheel

# Install ComfyUI
RUN if [ -n "${CUDA_VERSION_FOR_COMFY}" ]; then \
    /usr/bin/yes | comfy --workspace /comfyui install --version "${COMFYUI_VERSION}" --cuda-version "${CUDA_VERSION_FOR_COMFY}" --nvidia; \
    else \
    /usr/bin/yes | comfy --workspace /comfyui install --version "${COMFYUI_VERSION}" --nvidia; \
    fi

# Upgrade PyTorch if needed (for newer CUDA versions)
RUN if [ "$ENABLE_PYTORCH_UPGRADE" = "true" ]; then \
    uv pip install --force-reinstall torch torchvision torchaudio --index-url ${PYTORCH_INDEX_URL}; \
    fi

# Change working directory to ComfyUI
WORKDIR /comfyui

# Support for the network volume
COPY extra_model_paths.yaml ./

# --- SYMLINK IMPLEMENTATION START ---
# Create symbolic links to the Network Volume mount point (/runpod-volume)
# This fools ComfyUI into thinking the models are local.
RUN mkdir -p /runpod-volume/loras /runpod-volume/vae /runpod-volume/diffusion_models /runpod-volume/text_encoders /runpod-volume/controlnet /runpod-volume/upscale_models

# LoRAs
RUN ln -s /runpod-volume/loras /comfyui/models/loras

# VAEs
RUN ln -s /runpod-volume/vae /comfyui/models/vae

# UNETs / Diffusion Models
RUN ln -s /runpod-volume/diffusion_models /comfyui/models/diffusion_models

# CLIP / Text Encoders
RUN ln -s /runpod-volume/text_encoders /comfyui/models/text_encoders

# ControlNet
RUN ln -s /runpod-volume/controlnet /comfyui/models/controlnet

# Upscale Models
RUN ln -s /runpod-volume/upscale_models /comfyui/models/upscale_models
# --- SYMLINK IMPLEMENTATION END ---

# Go back to the root
WORKDIR /

# Install Python runtime dependencies for the handler
RUN uv pip install runpod requests websocket-client pyyaml

# Add application code and scripts
COPY handler.py workflows/ ./
COPY start.sh ./
RUN chmod +x /start.sh

# Copy helper script to switch Manager network mode at container start
COPY scripts/comfy-manager-set-mode.sh /usr/local/bin/comfy-manager-set-mode
RUN chmod +x /usr/local/bin/comfy-manager-set-mode

# Prevent pip from asking for confirmation during uninstall steps in custom nodes
ENV PIP_NO_INPUT=1

# Change working directory to ComfyUI
WORKDIR /comfyui

# Install custom nodes manually (more reliable than comfy-node-install)
# These are the required custom nodes for this project
RUN echo "Installing custom ComfyUI nodes..." && \
    cd /comfyui/custom_nodes && \
    echo "Cloning ComfyUI-WanVideoWrapper..." && \
    git clone https://github.com/kijai/ComfyUI-WanVideoWrapper.git && \
    echo "Cloning ComfyUI-KJNodes..." && \
    git clone https://github.com/kijai/ComfyUI-KJNodes.git && \
    echo "Cloning ComfyUI-GGUF..." && \
    git clone https://github.com/city96/ComfyUI-GGUF.git && \
    echo "Cloning RES4LYF..." && \
    git clone https://github.com/ClownsharkBatwing/RES4LYF.git && \
    echo "Installing GGUF dependencies..." && \
    cd ComfyUI-GGUF && \
    uv pip install -r requirements.txt || echo "No requirements.txt or installation failed" && \
    cd .. && \
    echo "✅ Custom nodes installed successfully"

# Go back to the root
WORKDIR /

# Set the default command to run when starting the container
CMD ["/start.sh"]

# Stage 2: Final image
FROM base AS final

# Models will be downloaded on-demand at runtime to avoid build timeouts
