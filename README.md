# ComfyUI Wan Video - RunPod Serverless

Современный Dockerfile для ComfyUI с Wan Video support, построенный по стандартам из [comfuiStory](https://github.com/xHaileab/comfuiStory) и [qwen_img_8step](https://github.com/ZeroClue/qwen_img_8step).

## Особенности

- ✅ **comfy-cli** — современный способ установки ComfyUI
- ✅ **uv** — быстрый установщик пакетов (в 10-100 раз быстрее pip)
- ✅ **comfy-node-install** — установка custom nodes через registry.comfy.org
- ✅ **Symbolic links** — модели из Network Volume доступны как локальные
- ✅ **libtcmalloc** — улучшенное управление памятью
- ✅ **ComfyUI-Manager offline mode** — отсутствие интернет-зависимостей
- ✅ **RES4LYF** — кастомные sampler `res_2s` и scheduler `beta57` для Wan Video

## Сборка Docker образа

```bash
# Базовая сборка (custom nodes устанавливаются автоматически)
docker build -t your-registry/comfyui-wan:latest .

# Сборка с кастомной версией ComfyUI
docker build --build-arg COMFYUI_VERSION=v0.2.3 -t your-registry/comfyui-wan:latest .
```

## Развертывание на RunPod

1. Отправьте образ в реестр:
```bash
docker push your-registry/comfyui-wan:latest
```

2. Создайте новый Serverless endpoint на RunPod:
   - Выберите ваш Docker образ
   - Укажите Network Volume с моделями
   - Настройте минимальное/максимальное количество реплик

## Структура моделей на Network Volume

Модели должны находиться в следующих подпапках Network Volume:
```
/runpod-volume/
├── diffusion_models/    # UNET модели
├── loras/              # LoRA модели
├── vae/                # VAE модели
├── text_encoders/      # CLIP модели
├── controlnet/         # ControlNet модели
└── upscale_models/     # Модели апскейлинга
```

## API запросы

### Фото генерация
```json
{
  "workflow": "photo",
  "params": {
    "prompt": "A beautiful landscape",
    "negative_prompt": "blur, low quality",
    "seed": 12345
  }
}
```

### Видео генерация
```json
{
  "workflow": "video",
  "params": {
    "prompt": "A woman walking in the park",
    "fps": 24,
    "length": 64
  }
}
```

### Голос (TTS)
```json
{
  "workflow": "voice",
  "params": {
    "prompt": "Hello, this is a test",
    "speaker": "female"
  }
}
```

## Установленные Custom Nodes

- `ComfyUI-WanVideoWrapper` — Wan Video поддержка
- `ComfyUI-KJNodes` — Дополнительные узлы от KJ
- `city96/ComfyUI-GGUF` — GGUF модели
- `RES4LYF` — Кастомные sampler/scheduler (res_2s, beta57)

## Переменные окружения

- `COMFY_LOG_LEVEL` — уровень логирования (по умолчанию: DEBUG)
- `SERVE_API_LOCALLY` — если true, запускает локальный API (по умолчанию: false)

## Troubleshooting

### Ошибка: Node 'Unet Loader (GGUF)' not found
Решение: Custom node `city96/ComfyUI-GGUF` устанавливается автоматически. Проверьте логи сборки.

### Ошибка: Value not in list (sampler_name: 'res_2s')
Решение: Custom node `RES4LYF` устанавливается автоматически. Проверьте логи сборки.

### Ошибка: Value not in list (scheduler: 'beta57')
Решение: Патч автоматически применяется в `handler.py`. Убедитесь, что RES4LYF установлен и загружен.

## Лицензия

MIT
