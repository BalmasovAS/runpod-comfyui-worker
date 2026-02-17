# Используем базовый образ RunPod с PyTorch
FROM runpod/pytorch:2.4.0-py3.11-cuda12.4.1-devel-ubuntu22.04

# Устанавливаем системные пакеты
RUN apt-get update -y && \
    apt-get install -y git wget ffmpeg libgl1-mesa-glx && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /workspace

# Клонируем ComfyUI
RUN git clone https://github.com/comfyanonymous/ComfyUI.git ComfyUI && \
    cd ComfyUI && \
    pip install -r requirements.txt

# Исправляем совместимость torchvision с PyTorch
RUN pip uninstall -y torchvision && \
    pip install torchvision>=0.20.0 --index-url https://download.pytorch.org/whl/cu128

# Устанавливаем RunPod SDK и PyYAML для extra_model_paths.yaml
RUN pip install runpod requests pyyaml

# Устанавливаем custom nodes
WORKDIR /workspace/ComfyUI/custom_nodes

RUN git clone https://github.com/1038lab/ComfyUI-QwenTTS.git && \
    git clone https://github.com/Comfy-Org/ComfyUI-Manager.git && \
    git clone https://github.com/city96/ComfyUI-GGUF.git && \
    cd ComfyUI-GGUF && \
    pip install -r requirements.txt || echo "No requirements.txt" && \
    cd .. && \
    git clone https://github.com/kijai/ComfyUI-KJNodes.git && \
    cd ComfyUI-KJNodes && \
    pip install -r requirements.txt || echo "No requirements.txt" && \
    cd .. && \
    git clone https://github.com/Kosinkadink/ComfyUI-VideoHelperSuite.git && \
    cd ComfyUI-VideoHelperSuite && \
    pip install -r requirements.txt || echo "No requirements.txt"

# Копируем ваш код
WORKDIR /workspace
COPY handler.py /workspace/handler.py
COPY workflows/ /workspace/ComfyUI/workflows/

# Запускаем RunPod serverless handler
CMD ["python", "/workspace/handler.py"]
