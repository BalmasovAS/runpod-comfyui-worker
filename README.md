# ComfyUI Worker for RunPod Serverless

RunPod Serverless worker для ComfyUI с поддержкой Wan Video V2 и других custom nodes.

## Использование в RunPod

### Подключение GitHub репозитория

1. Загрузите этот репозиторий на GitHub:
   ```bash
   cd runpod-comfyui-worker
   git init
   git add .
   git commit -m "Initial commit"
   git remote add origin https://github.com/YOUR_USERNAME/runpod-comfyui-worker.git
   git push -u origin main
   ```

2. В RunPod Console:
   - Создайте новый Serverless Endpoint
   - Выберите **"Build from GitHub repository"** или **"Repository"**
   - Укажите URL вашего репозитория: `https://github.com/YOUR_USERNAME/runpod-comfyui-worker`
   - Укажите ветку (обычно `main`)
   - RunPod автоматически соберет образ из Dockerfile

3. Настройте Network Volume:
   - Подключите Network Volume к Endpoint
   - Убедитесь, что на Network Volume есть структура:
     ```
     models/
     ├── vae/
     ├── loras/
     ├── clip/
     └── unet/ или gguf/
     ```

## Обновление кода

После изменений в коде:

```bash
git add .
git commit -m "Update handler"
git push
```

RunPod автоматически пересоберет образ при следующем запросе (или можно принудительно пересобрать в настройках Endpoint).

## API Использование

### Синхронный запрос (runsync)

```bash
curl -X POST \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "input": {
      "workflow": "photo",
      "params": {
        "prompt": "beautiful girl",
        "negative_prompt": "low quality",
        "seed": 12345
      }
    }
  }' \
  https://api.runpod.ai/v2/YOUR_ENDPOINT_ID/runsync
```

### Асинхронный запрос (run)

```bash
curl -X POST \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "input": {
      "workflow": "photo",
      "params": {
        "prompt": "beautiful girl"
      }
    }
  }' \
  https://api.runpod.ai/v2/YOUR_ENDPOINT_ID/run
```

Затем проверяйте статус через `/status` endpoint.

## Workflow Types

- `photo` - генерация фото
- `video` - генерация видео
- `voice` - генерация голоса

## Параметры

### Photo workflow
- `prompt` - позитивный промпт
- `negative_prompt` - негативный промпт (опционально)
- `seed` - seed для генерации (опционально)

### Video workflow
- `prompt` - промпт
- `fps` - кадров в секунду (опционально)
- `length` - длина видео (опционально)

### Voice workflow
- `prompt` - текст для генерации голоса
- другие параметры в зависимости от workflow

## Структура репозитория

```
runpod-comfyui-worker/
├── Dockerfile          # Docker образ с ComfyUI и custom nodes
├── handler.py          # RunPod serverless handler
├── workflows/         # ComfyUI workflows (photo, video, voice)
│   ├── photo.json
│   ├── video.json
│   └── voice.json
└── README.md          # Этот файл
```

## Troubleshooting

Если модели не находятся:
1. Проверьте, что Network Volume подключен к Endpoint
2. Проверьте структуру папок на Network Volume
3. Проверьте логи воркера в RunPod Console - там будет диагностика

## Преимущества GitHub репозитория

✅ **Не нужно собирать Docker образ локально** - RunPod соберет автоматически  
✅ **Не нужно пушить в Docker Hub** - просто GitHub  
✅ **Быстрые обновления** - просто `git push`  
✅ **Автоматическая сборка** - RunPod пересоберет образ при изменениях  
✅ **Проще разработка** - изменения видны сразу после push
