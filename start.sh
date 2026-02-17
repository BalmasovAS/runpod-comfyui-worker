#!/bin/bash
# Скрипт для запуска ComfyUI в фоне и handler (как в comfuiStory)

# Не используем set -e, чтобы видеть все ошибки
set +e

echo "🚀 Запускаю ComfyUI в фоне..."
echo "📁 Текущая директория: $(pwd)"
echo "📁 Проверка /workspace:"
ls -la /workspace/ 2>&1 | head -20

# Находим Network Volume и настраиваем модели
echo "🔍 Настройка Network Volume и моделей..."
python3 -c "
import os
import sys
import traceback

try:
    sys.path.insert(0, '/workspace')
    print('✅ /workspace добавлен в sys.path')
    
    # Проверяем наличие handler.py
    handler_path = '/workspace/handler.py'
    if os.path.exists(handler_path):
        print(f'✅ handler.py найден: {handler_path}')
    else:
        print(f'❌ handler.py не найден: {handler_path}')
        sys.exit(1)
    
    # Импортируем функции из handler
    try:
        from handler import find_network_volume, setup_models_symlink
        print('✅ Функции импортированы из handler')
    except Exception as e:
        print(f'❌ Ошибка импорта из handler: {e}')
        traceback.print_exc()
        sys.exit(1)
    
    # Находим Network Volume
    try:
        network_models_path = find_network_volume()
        print(f'📁 Network Volume результат: {network_models_path}')
    except Exception as e:
        print(f'⚠️ Ошибка поиска Network Volume: {e}')
        traceback.print_exc()
        network_models_path = None
    
    # Настраиваем символические ссылки
    if network_models_path:
        try:
            print(f'🔗 Создаю символические ссылки из {network_models_path}...')
            result = setup_models_symlink(network_models_path)
            if result:
                print('✅ Модели подключены из Network Volume')
            else:
                print('⚠️ Не удалось создать ссылки на модели, но продолжаем...')
                # Не останавливаемся, если ссылки не создались - попробуем extra_model_paths.yaml
        except Exception as e:
            print(f'⚠️ Ошибка создания ссылок: {e}')
            traceback.print_exc()
            print('⚠️ Продолжаем без символических ссылок...')
    else:
        print('⚠️ Network Volume не найден, используем локальные модели')
except Exception as e:
    print(f'❌ Критическая ошибка в Python скрипте: {e}')
    traceback.print_exc()
    sys.exit(1)
" || {
    echo "❌ Ошибка в Python скрипте настройки моделей"
    exit 1
}

# Запускаем ComfyUI в фоне
echo "📁 Переход в /workspace/ComfyUI..."
cd /workspace/ComfyUI || {
    echo "❌ Не удалось перейти в /workspace/ComfyUI"
    exit 1
}

echo "📄 Проверка main.py..."
if [ ! -f "main.py" ]; then
    echo "❌ main.py не найден в /workspace/ComfyUI"
    ls -la /workspace/ComfyUI/ | head -20
    exit 1
fi

echo "🚀 Запускаю процесс ComfyUI в фоне..."
python3 main.py --listen 127.0.0.1 --port 8188 --enable-cors-header "*" > /tmp/comfyui.log 2>&1 &
COMFYUI_PID=$!

echo "✅ Процесс ComfyUI запущен (PID: $COMFYUI_PID)"
sleep 2  # Даем процессу время на запуск

# Проверяем, что процесс еще работает
if ! kill -0 $COMFYUI_PID 2>/dev/null; then
    echo "❌ Процесс ComfyUI завершился сразу после запуска!"
    echo "Последние строки логов:"
    tail -50 /tmp/comfyui.log
    exit 1
fi

# Ждем пока HTTP сервер ComfyUI станет доступен (как в comfuiStory - check_server с 500 попыток по 50ms)
echo "⏳ Ожидание готовности HTTP сервера ComfyUI (загрузка моделей и инициализация)..."
echo "   Проверяю доступность http://127.0.0.1:8188/system_stats..."
for i in {1..500}; do
    if curl -s http://127.0.0.1:8188/system_stats > /dev/null 2>&1; then
        echo "✅ HTTP сервер ComfyUI готов и доступен! (попытка $i/500)"
        break
    fi
    
    # Показываем прогресс каждые 50 попыток
    if [ $((i % 50)) -eq 0 ]; then
        echo "   ⏳ Попытка $i/500... (процесс PID $COMFYUI_PID)"
        # Проверяем, что процесс еще работает
        if ! kill -0 $COMFYUI_PID 2>/dev/null; then
            echo "❌ ComfyUI процесс завершился!"
            echo "Последние строки логов ComfyUI:"
            tail -100 /tmp/comfyui.log
            exit 1
        fi
    fi
    
    if [ $i -eq 500 ]; then
        echo "❌ HTTP сервер ComfyUI не стал доступен за 500 попыток (25 секунд)"
        echo "Проверяю статус процесса..."
        if kill -0 $COMFYUI_PID 2>/dev/null; then
            echo "   ⚠️ Процесс работает, но HTTP сервер недоступен (возможно, долгая загрузка моделей)"
        else
            echo "   ❌ Процесс завершился"
        fi
        echo "Последние строки логов ComfyUI:"
        tail -100 /tmp/comfyui.log
        exit 1
    fi
    sleep 0.05  # 50ms как в comfuiStory (COMFY_API_AVAILABLE_INTERVAL_MS)
done

# Даем время на сканирование моделей и загрузку custom nodes
echo "⏳ Ожидание сканирования моделей и загрузки custom nodes (90 секунд)..."
echo "   Это нужно для загрузки всех custom nodes (KJNodes, Wan Video V2 и т.д.)"
sleep 90

# Запускаем handler (он заменит текущий процесс через exec)
echo "🚀 Запускаю RunPod handler..."
cd /workspace || {
    echo "❌ Не удалось перейти в /workspace"
    exit 1
}

echo "📄 Проверка handler.py..."
if [ ! -f "handler.py" ]; then
    echo "❌ handler.py не найден в /workspace"
    ls -la /workspace/ | head -20
    exit 1
fi

echo "✅ Запускаю handler.py..."
exec python3 handler.py
