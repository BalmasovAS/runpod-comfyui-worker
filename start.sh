#!/bin/bash
# Скрипт для запуска ComfyUI в фоне и handler (как в comfuiStory)

set -e

echo "🚀 Запускаю ComfyUI в фоне..."

# Находим Network Volume и настраиваем модели
python3 -c "
import os
import sys
sys.path.insert(0, '/workspace')

# Импортируем функции из handler
from handler import find_network_volume, setup_models_symlink

# Находим Network Volume
network_models_path = find_network_volume()

# Настраиваем символические ссылки
if network_models_path:
    setup_models_symlink(network_models_path)
    print('✅ Модели подключены из Network Volume')
else:
    print('⚠️ Network Volume не найден, используем локальные модели')
"

# Запускаем ComfyUI в фоне
cd /workspace/ComfyUI
python3 main.py --listen 127.0.0.1 --port 8188 --enable-cors-header "*" > /tmp/comfyui.log 2>&1 &
COMFYUI_PID=$!

echo "✅ ComfyUI запущен (PID: $COMFYUI_PID)"

# Ждем пока ComfyUI запустится (как в comfuiStory - check_server с 500 попыток по 50ms)
echo "⏳ Ожидание запуска ComfyUI..."
for i in {1..500}; do
    if curl -s http://127.0.0.1:8188/system_stats > /dev/null 2>&1; then
        echo "✅ ComfyUI API доступен!"
        break
    fi
    if [ $i -eq 500 ]; then
        echo "❌ ComfyUI не запустился за 500 попыток"
        echo "Последние строки логов ComfyUI:"
        tail -50 /tmp/comfyui.log
        exit 1
    fi
    sleep 0.05  # 50ms как в comfuiStory (COMFY_API_AVAILABLE_INTERVAL_MS)
done

# Даем время на сканирование моделей
echo "⏳ Ожидание сканирования моделей (60 секунд)..."
sleep 60

# Запускаем handler (он заменит текущий процесс через exec)
echo "🚀 Запускаю RunPod handler..."
cd /workspace
exec python3 handler.py
