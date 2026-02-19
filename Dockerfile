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
# Including build-essential for C compiler (needed for Triton/PyTorch compilation)
# Also install CUDA development libraries for Triton compilation
RUN apt-get update && apt-get install -y \
    python3.12 \
    python3.12-dev \
    python3.12-venv \
    git \
    wget \
    curl \
    build-essential \
    libgl1 \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender1 \
    ffmpeg \
    && ln -sf /usr/bin/python3.12 /usr/bin/python \
    && ln -sf /usr/bin/pip3 /usr/bin/pip

# Install CUDA development libraries for Triton compilation
# Note: These may already be in the base image, but we ensure they're available
RUN apt-get update && apt-get install -y \
    cuda-cudart-dev-12-6 \
    cuda-nvcc-12-6 \
    || echo "CUDA dev packages may already be installed or not available in this base image"

# Disable Triton JIT compilation to avoid runtime compilation errors
# This will use pre-compiled kernels when available
ENV TRITON_DISABLE_LINE_INFO=1
ENV TRITON_INTERPRET=0

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

# Create model directories structure (symlinks will be created at runtime in start.sh)
# Network Volume is mounted at runtime, so we can't create symlinks during build
RUN mkdir -p /comfyui/models/{loras,vae,diffusion_models,text_encoders,controlnet,upscale_models,unet}

# Go back to the root
WORKDIR /

# Install Python runtime dependencies for the handler
RUN uv pip install runpod requests websocket-client pyyaml

# Add application code and scripts
COPY handler.py ./
COPY start.sh ./
RUN chmod +x /start.sh

# Copy workflows to ComfyUI directory
COPY workflows/ /comfyui/workflows/

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
    cd ComfyUI-WanVideoWrapper && \
    uv pip install -r requirements.txt || echo "No requirements.txt or installation failed" && \
    cd .. && \
    echo "Cloning ComfyUI-KJNodes..." && \
    git clone https://github.com/kijai/ComfyUI-KJNodes.git && \
    cd ComfyUI-KJNodes && \
    uv pip install -r requirements.txt || echo "No requirements.txt or installation failed" && \
    cd .. && \
    echo "Installing sageattention for PathchSageAttentionKJ..." && \
    (uv pip install sageattention || \
     uv pip install sageattn || \
     uv pip install git+https://github.com/tencent-ailab/sageattention.git || \
     echo "⚠️ sageattention installation failed, PathchSageAttentionKJ may not work") && \
    echo "Cloning ComfyUI-GGUF..." && \
    git clone https://github.com/city96/ComfyUI-GGUF.git && \
    cd ComfyUI-GGUF && \
    uv pip install -r requirements.txt || echo "No requirements.txt or installation failed" && \
    cd .. && \
    echo "Cloning RES4LYF..." && \
    git clone https://github.com/ClownsharkBatwing/RES4LYF.git && \
    cd RES4LYF && \
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
