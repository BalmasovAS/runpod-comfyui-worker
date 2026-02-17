import runpod
import requests
import json
import time
import os
import subprocess
import base64
import threading

# Путь к ComfyUI
COMFYUI_DIR = "/workspace/ComfyUI"
COMFYUI_PORT = 8188
COMFYUI_URL = f"http://127.0.0.1:{COMFYUI_PORT}"

# Стандартный путь к Network Volume в RunPod
# RunPod автоматически монтирует Network Volume в /runpod-volume
# Если Network Volume содержит папку models, она будет доступна по пути /runpod-volume/models
RUNPOD_VOLUME_PATH = os.environ.get("RUNPOD_VOLUME_PATH", "/runpod-volume")
COMFYUI_MODELS_PATH = os.path.join(COMFYUI_DIR, "models")

def list_directory_recursive(path, max_depth=3, current_depth=0, prefix=""):
    """Рекурсивно выводит содержимое директории"""
    if current_depth >= max_depth:
        return
    
    try:
        items = sorted(os.listdir(path))
        for i, item in enumerate(items):
            is_last = i == len(items) - 1
            item_path = os.path.join(path, item)
            
            if os.path.isdir(item_path):
                connector = "└── " if is_last else "├── "
                print(f"{prefix}{connector}📁 {item}/")
                
                next_prefix = prefix + ("    " if is_last else "│   ")
                list_directory_recursive(item_path, max_depth, current_depth + 1, next_prefix)
            else:
                connector = "└── " if is_last else "├── "
                size = os.path.getsize(item_path)
                size_str = f"({size / (1024*1024*1024):.2f} GB)" if size > 1024*1024*1024 else f"({size / (1024*1024):.2f} MB)" if size > 1024*1024 else f"({size / 1024:.2f} KB)"
                print(f"{prefix}{connector}📄 {item} {size_str}")
    except PermissionError:
        print(f"{prefix}⚠️ Нет доступа к {path}")
    except Exception as e:
        print(f"{prefix}❌ Ошибка: {e}")

def check_network_volume_contents(volume_path):
    """Проверяет содержимое Network Volume и выводит детальную информацию"""
    print("\n" + "="*60)
    print("📋 СОДЕРЖИМОЕ NETWORK VOLUME")
    print("="*60)
    print(f"Путь: {volume_path}\n")
    
    try:
        # Выводим структуру директории
        list_directory_recursive(volume_path, max_depth=4)
        
        # Детальная проверка папки models
        models_path = os.path.join(volume_path, "models") if "models" not in os.path.basename(volume_path) else volume_path
        
        if os.path.exists(models_path):
            print(f"\n📊 СТАТИСТИКА ПАПКИ MODELS:")
            print("="*60)
            
            model_types = ["vae", "loras", "clip", "unet", "gguf", "checkpoints"]
            total_files = 0
            total_size = 0
            
            for model_type in model_types:
                type_path = os.path.join(models_path, model_type)
                if os.path.exists(type_path):
                    try:
                        files = [f for f in os.listdir(type_path) if os.path.isfile(os.path.join(type_path, f))]
                        type_size = sum(os.path.getsize(os.path.join(type_path, f)) for f in files)
                        total_files += len(files)
                        total_size += type_size
                        
                        print(f"\n{model_type.upper()}:")
                        print(f"  Файлов: {len(files)}")
                        print(f"  Размер: {type_size / (1024*1024*1024):.2f} GB")
                        if files:
                            print(f"  Примеры:")
                            for f in files[:5]:
                                file_path = os.path.join(type_path, f)
                                file_size = os.path.getsize(file_path)
                                size_str = f"{file_size / (1024*1024*1024):.2f} GB" if file_size > 1024*1024*1024 else f"{file_size / (1024*1024):.2f} MB"
                                print(f"    - {f} ({size_str})")
                            if len(files) > 5:
                                print(f"    ... и еще {len(files) - 5} файлов")
                    except Exception as e:
                        print(f"  ⚠️ Ошибка чтения {model_type}: {e}")
            
            print(f"\n📈 ИТОГО:")
            print(f"  Всего файлов: {total_files}")
            print(f"  Общий размер: {total_size / (1024*1024*1024):.2f} GB")
        
    except Exception as e:
        print(f"❌ Ошибка при проверке содержимого: {e}")
    
    print("="*60 + "\n")

def find_network_volume():
    """Находит путь к Network Volume с моделями (стандартный путь RunPod)"""
    print("\n" + "="*60)
    print("🔍 Поиск Network Volume с моделями")
    print("="*60)
    
    # Стандартный путь RunPod для Network Volume
    volume_path = RUNPOD_VOLUME_PATH
    
    if not os.path.exists(volume_path):
        print(f"⚠️ Network Volume не найден по стандартному пути: {volume_path}")
        print("   Проверьте, что Network Volume подключен к Endpoint")
        return None
    
    print(f"✅ Network Volume найден: {volume_path}")
    
    try:
        items = os.listdir(volume_path)
        print(f"   Содержимое: {', '.join(items)}")
        
        # Ищем папку models в разных местах
        possible_models_paths = [
            os.path.join(volume_path, "models"),  # /runpod-volume/models
            os.path.join(volume_path, "ComfyUI", "models"),  # /runpod-volume/ComfyUI/models
            volume_path,  # Может быть models напрямую в volume_path
        ]
        
        models_path = None
        for possible_path in possible_models_paths:
            if os.path.exists(possible_path):
                # Проверяем, есть ли там структура models (vae, loras, clip и т.д.)
                try:
                    subdirs = [d for d in os.listdir(possible_path) if os.path.isdir(os.path.join(possible_path, d))]
                    # Проверяем наличие типичных папок для моделей
                    if any(d in ["vae", "loras", "clip", "unet", "gguf", "checkpoints", "diffusion_models"] for d in subdirs):
                        models_path = possible_path
                        print(f"✅ Найдена папка models: {models_path}")
                        print(f"   Подпапки: {', '.join(subdirs)}")
                        break
                except Exception as e:
                    continue
        
        if models_path and os.path.exists(models_path):
            # Проверяем наличие нужных моделей
            try:
                vae_path = os.path.join(models_path, "vae")
                loras_path = os.path.join(models_path, "loras")
                
                if os.path.exists(vae_path):
                    vae_files = [f for f in os.listdir(vae_path) if f.endswith('.safetensors')]
                    print(f"   VAE файлов: {len(vae_files)}")
                    if "wan_2.1_vae.safetensors" in vae_files:
                        print(f"   ✅ Найден wan_2.1_vae.safetensors")
                
                if os.path.exists(loras_path):
                    lora_files = [f for f in os.listdir(loras_path) if f.endswith('.safetensors')]
                    print(f"   LoRA файлов: {len(lora_files)}")
                
                # Выводим детальное содержимое
                check_network_volume_contents(volume_path)
                
                return models_path
            except Exception as e:
                print(f"   ⚠️ Ошибка проверки структуры: {e}")
                return models_path  # Все равно возвращаем путь
        else:
            print(f"⚠️ Папка models не найдена в {volume_path}")
            print(f"   Проверенные пути: {possible_models_paths}")
            print(f"   Попробуйте создать папку models в Network Volume со структурой:")
            print(f"   models/")
            print(f"   ├── vae/")
            print(f"   ├── loras/")
            print(f"   ├── clip/")
            print(f"   └── unet/ или gguf/")
            return None
            
    except Exception as e:
        print(f"❌ Ошибка чтения Network Volume: {e}")
        return None

def setup_models_symlink(network_models_path):
    """Создает символические ссылки от Network Volume к ComfyUI models"""
    if not network_models_path:
        return False
    
    comfyui_models = os.path.join(COMFYUI_DIR, "models")
    
    # Если папка models уже существует и не является ссылкой, не трогаем
    if os.path.exists(comfyui_models) and not os.path.islink(comfyui_models):
        print(f"⚠️ Папка {comfyui_models} уже существует, не создаю ссылку")
        # Но проверим, может нужно создать ссылки на подпапки
        try:
            for subdir in ["vae", "loras", "clip", "unet", "gguf"]:
                network_subdir = os.path.join(network_models_path, subdir)
                comfyui_subdir = os.path.join(comfyui_models, subdir)
                
                if os.path.exists(network_subdir) and not os.path.exists(comfyui_subdir):
                    os.makedirs(os.path.dirname(comfyui_subdir), exist_ok=True)
                    os.symlink(network_subdir, comfyui_subdir)
                    print(f"✅ Создана ссылка: {comfyui_subdir} -> {network_subdir}")
        except Exception as e:
            print(f"⚠️ Ошибка создания ссылок на подпапки: {e}")
        return True
    
    # Создаем символическую ссылку на всю папку models
    try:
        if os.path.exists(comfyui_models):
            # Удаляем существующую папку если она пуста
            try:
                if not os.listdir(comfyui_models):
                    os.rmdir(comfyui_models)
                else:
                    print(f"⚠️ Папка {comfyui_models} не пуста, не создаю ссылку")
                    return False
            except:
                pass
        
        os.symlink(network_models_path, comfyui_models)
        print(f"✅ Создана символическая ссылка: {comfyui_models} -> {network_models_path}")
        return True
    except Exception as e:
        print(f"❌ Ошибка создания символической ссылки: {e}")
        return False

def start_comfyui():
    """Запускает ComfyUI в фоновом режиме с логированием"""
    print(f"🚀 Запускаю ComfyUI из {COMFYUI_DIR}...")
    
    # Проверяем, что директория существует
    if not os.path.exists(COMFYUI_DIR):
        print(f"❌ Директория ComfyUI не найдена: {COMFYUI_DIR}")
        return None
    
    if not os.path.exists(os.path.join(COMFYUI_DIR, "main.py")):
        print(f"❌ Файл main.py не найден в {COMFYUI_DIR}")
        return None
    
    os.chdir(COMFYUI_DIR)
    
    # Запускаем с логированием в реальном времени
    process = subprocess.Popen(
        ["python", "main.py", "--listen", "127.0.0.1", "--port", str(COMFYUI_PORT)],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,  # Объединяем stderr в stdout
        universal_newlines=True,
        bufsize=1  # Line buffered
    )
    
    # Запускаем поток для чтения логов
    def log_output():
        try:
            for line in iter(process.stdout.readline, ''):
                if line:
                    print(f"[ComfyUI] {line.rstrip()}")
        except Exception as e:
            print(f"❌ Ошибка чтения логов ComfyUI: {e}")
    
    log_thread = threading.Thread(target=log_output, daemon=True)
    log_thread.start()
    
    # Даем процессу немного времени на запуск
    time.sleep(2)
    
    # Проверяем, что процесс еще работает
    if process.poll() is not None:
        # Процесс уже завершился - значит была ошибка
        print(f"❌ ComfyUI процесс завершился с кодом: {process.returncode}")
        return None
    
    print(f"✅ ComfyUI процесс запущен (PID: {process.pid})")
    return process

def wait_for_comfyui(comfyui_process, max_wait=300):
    """Ждет пока ComfyUI запустится и просканирует модели"""
    print("⏳ Ожидание запуска ComfyUI...")
    print(f"   Проверяю доступность {COMFYUI_URL}/system_stats")
    
    api_available = False
    for i in range(max_wait):
        # Проверяем, что процесс еще работает
        if comfyui_process is None:
            print("❌ ComfyUI процесс не был запущен")
            return False
        
        if comfyui_process.poll() is not None:
            # Процесс завершился - значит была ошибка
            returncode = comfyui_process.returncode
            print(f"❌ ComfyUI процесс завершился с кодом: {returncode}")
            return False
        
        # Пробуем разные endpoints для проверки готовности
        try:
            # Сначала пробуем простой endpoint
            response = requests.get(f"{COMFYUI_URL}/system_stats", timeout=3)
            if response.status_code == 200:
                if not api_available:
                    print("✅ ComfyUI API доступен!")
                    api_available = True
                
                # Проверяем, что сервер действительно работает
                try:
                    # Пробуем получить object_info для проверки полной готовности
                    objects_response = requests.get(f"{COMFYUI_URL}/object_info", timeout=5)
                    if objects_response.status_code == 200:
                        print("✅ ComfyUI полностью готов, жду сканирования моделей...")
                        
                        # КРИТИЧНО: Даем достаточно времени на сканирование моделей с Network Volume
                        # ComfyUI может долго сканировать модели, особенно если их много
                        print("⏳ Ожидание сканирования моделей (60 секунд)...")
                        time.sleep(60)  # Даем время на сканирование
                
                        # Проверяем доступность моделей через object_info
                        object_info = objects_response.json()
                        
                        # Проверяем наличие VAE моделей
                        vae_loader = object_info.get("VAELoader", {})
                        vae_input = vae_loader.get("input", {})
                        vae_names = vae_input.get("vae_name", [])
                        
                        if isinstance(vae_names, list) and len(vae_names) > 0:
                            print(f"✅ Найдено VAE моделей: {len(vae_names)}")
                            if "wan_2.1_vae.safetensors" in vae_names:
                                print("✅ wan_2.1_vae.safetensors найден!")
                            else:
                                print(f"⚠️ wan_2.1_vae.safetensors не найден. Доступные: {vae_names[:5]}")
                        else:
                            print(f"⚠️ VAE модели не найдены или список пуст")
                        
                        # Проверяем наличие LoRA моделей
                        lora_loader = object_info.get("LoraLoader", {})
                        lora_input = lora_loader.get("input", {})
                        lora_names = lora_input.get("lora_name", [])
                        
                        if isinstance(lora_names, list) and len(lora_names) > 0:
                            print(f"✅ Найдено LoRA моделей: {len(lora_names)}")
                        else:
                            print(f"⚠️ LoRA модели не найдены")
                        
                        print("✅ ComfyUI готов к работе")
                        return True
                except Exception as e:
                    print(f"⚠️ object_info недоступен: {e}, но API работает - продолжаем")
                    return True
        except requests.exceptions.ConnectionError:
            # Сервер еще не запустился
            if i % 10 == 0:
                print(f"⏳ Ожидание ComfyUI... ({i}/{max_wait}с) [Процесс работает: PID {comfyui_process.pid}]")
        except requests.exceptions.Timeout:
            # Таймаут - возможно сервер перегружен
            if i % 10 == 0:
                print(f"⏳ Таймаут при подключении к ComfyUI... ({i}/{max_wait}с)")
        except Exception as e:
            if i % 10 == 0:
                print(f"⏳ Ожидание ComfyUI... ({i}/{max_wait}с) [Ошибка: {type(e).__name__}]")
        
        time.sleep(1)
    
    if api_available:
        print("⚠️ ComfyUI API был доступен, но не удалось получить полную информацию")
        return True  # Все равно продолжаем, если API работал
    
    print("❌ ComfyUI не запустился за отведенное время")
    return False

def queue_prompt(prompt):
    """Отправляет промпт в очередь ComfyUI"""
    p = {"prompt": prompt}
    data = json.dumps(p).encode('utf-8')
    response = requests.post(f"{COMFYUI_URL}/prompt", data=data)
    return response.json()

def get_image(filename, subfolder, folder_type):
    """Получает изображение из ComfyUI"""
    data = {"filename": filename, "subfolder": subfolder, "type": folder_type}
    url_values = "&".join([f"{k}={v}" for k, v in data.items()])
    response = requests.get(f"{COMFYUI_URL}/view?{url_values}")
    return response.content

def get_history(prompt_id):
    """Получает историю выполнения промпта"""
    response = requests.get(f"{COMFYUI_URL}/history/{prompt_id}")
    return response.json()

def find_node_by_type(workflow, node_type, title_keyword=None):
    """Находит узел по типу и опционально по ключевому слову в title"""
    for node_id, node_data in workflow.items():
        if isinstance(node_data, dict):
            if node_data.get("class_type") == node_type:
                if title_keyword:
                    title = str(node_data.get("_meta", {}).get("title", ""))
                    if title_keyword.lower() in title.lower():
                        return node_id, node_data
                else:
                    return node_id, node_data
    return None, None

def find_node_by_input(workflow, input_name):
    """Находит узел, который имеет указанный input параметр"""
    for node_id, node_data in workflow.items():
        if isinstance(node_data, dict) and "inputs" in node_data:
            if input_name in node_data["inputs"]:
                return node_id, node_data
    return None, None

def apply_prompt(workflow, prompt_text, is_negative=False):
    """Обновляет промпт в workflow (positive или negative)"""
    # Сначала пробуем стандартные узлы
    node_id = "4" if is_negative else "3"
    if node_id in workflow and "inputs" in workflow[node_id]:
        workflow[node_id]["inputs"]["text"] = prompt_text
        prompt_type = "Negative prompt" if is_negative else "Промпт"
        print(f"✅ {prompt_type} обновлен в узле '{node_id}': {prompt_text[:100]}...")
        return True
    
    # Ищем по типу и title
    keyword = "Negative" if is_negative else "Positive"
    found_id, _ = find_node_by_type(workflow, "CLIPTextEncode", keyword)
    if found_id:
        workflow[found_id]["inputs"]["text"] = prompt_text
        prompt_type = "Negative prompt" if is_negative else "Промпт"
        print(f"✅ {prompt_type} обновлен в узле '{found_id}': {prompt_text[:100]}...")
        return True
    
    print(f"⚠️ Узел для {'negative' if is_negative else 'positive'} prompt не найден")
    return False

def apply_video_params(workflow, params):
    """Применяет параметры для видео: prompt, fps, length"""
    # Обновляем промпт
    if "prompt" in params:
        apply_prompt(workflow, params["prompt"], is_negative=False)
    
    # Обновляем fps (кадры в секунду)
    if "fps" in params:
        fps_value = int(params["fps"])
        # Ищем узел с fps (может быть в разных типах узлов)
        found_id, node_data = find_node_by_input(workflow, "fps")
        if found_id:
            workflow[found_id]["inputs"]["fps"] = fps_value
            print(f"✅ FPS обновлен в узле '{found_id}': {fps_value}")
        else:
            # Пробуем найти по типу узла
            found_id, _ = find_node_by_type(workflow, "EmptyHunyuanLatentVideo")
            if found_id and "inputs" in workflow[found_id]:
                if "fps" in workflow[found_id]["inputs"]:
                    workflow[found_id]["inputs"]["fps"] = fps_value
                    print(f"✅ FPS обновлен в узле '{found_id}': {fps_value}")
                else:
                    print("⚠️ Параметр fps не найден в workflow")
    
    # Обновляем length (длину видео)
    if "length" in params:
        length_value = int(params["length"])
        # Ищем узел с length
        found_id, node_data = find_node_by_input(workflow, "length")
        if found_id:
            workflow[found_id]["inputs"]["length"] = length_value
            print(f"✅ Length обновлен в узле '{found_id}': {length_value}")
        else:
            # Пробуем найти по типу узла
            found_id, _ = find_node_by_type(workflow, "EmptyHunyuanLatentVideo")
            if found_id and "inputs" in workflow[found_id]:
                if "length" in workflow[found_id]["inputs"]:
                    workflow[found_id]["inputs"]["length"] = length_value
                    print(f"✅ Length обновлен в узле '{found_id}': {length_value}")
                else:
                    print("⚠️ Параметр length не найден в workflow")

def apply_voice_params(workflow, params):
    """Применяет параметры для голоса: любые параметры"""
    # Обновляем промпт (если есть)
    if "prompt" in params:
        apply_prompt(workflow, params["prompt"], is_negative=False)
    
    # Применяем все остальные параметры универсально
    for param_key, param_value in params.items():
        if param_key == "prompt":
            continue  # Уже обработали
        
        # Ищем узел с этим параметром
        found_id, node_data = find_node_by_input(workflow, param_key)
        if found_id:
            # Преобразуем значение в нужный тип
            if isinstance(workflow[found_id]["inputs"][param_key], (int, float)):
                try:
                    param_value = int(param_value) if isinstance(workflow[found_id]["inputs"][param_key], int) else float(param_value)
                except (ValueError, TypeError):
                    pass
            workflow[found_id]["inputs"][param_key] = param_value
            print(f"✅ Параметр '{param_key}' обновлен в узле '{found_id}': {param_value}")
        else:
            # Пробуем найти по типу узла и обновить widgets_values
            for node_id, node_data in workflow.items():
                if isinstance(node_data, dict) and "widgets_values" in node_data:
                    print(f"⚠️ Параметр '{param_key}' не найден напрямую, возможно нужен в widgets_values")

def apply_photo_params(workflow, params):
    """Применяет параметры для фото: prompt, negative_prompt, seed и т.д."""
    # Обновляем промпт
    if "prompt" in params:
        apply_prompt(workflow, params["prompt"], is_negative=False)
    
    # Обновляем negative prompt
    if "negative_prompt" in params:
        apply_prompt(workflow, params["negative_prompt"], is_negative=True)
    
    # Обновляем seed
    if "seed" in params:
        seed_value = int(params["seed"])
        found_id, node_data = find_node_by_input(workflow, "seed")
        if found_id:
            workflow[found_id]["inputs"]["seed"] = seed_value
            print(f"✅ Seed обновлен в узле '{found_id}': {seed_value}")
        else:
            # Пробуем найти EmptyHunyuanLatentVideo
            found_id, _ = find_node_by_type(workflow, "EmptyHunyuanLatentVideo")
            if found_id and "inputs" in workflow[found_id]:
                if "seed" in workflow[found_id]["inputs"]:
                    workflow[found_id]["inputs"]["seed"] = seed_value
                    print(f"✅ Seed обновлен в узле '{found_id}': {seed_value}")

def find_node_in_nodes(nodes, node_id=None, node_type=None, title_keyword=None):
    """Находит узел в массиве nodes по ID, типу или title"""
    for node in nodes:
        if node_id and str(node.get("id", "")) == str(node_id):
            return node
        if node_type and node.get("type") == node_type:
            if title_keyword:
                title = str(node.get("title", "") or node.get("properties", {}).get("title", ""))
                if title_keyword.lower() in title.lower():
                    return node
            else:
                return node
    return None

def apply_photo_params_to_nodes(nodes, params):
    """Применяет параметры для фото к формату с nodes"""
    # Обновляем промпт (ищем CLIPTextEncode с title "Positive" или без "Negative")
    if "prompt" in params:
        prompt_text = params["prompt"]
        # Ищем узел CLIPTextEncode для positive prompt
        for node in nodes:
            if node.get("type") == "CLIPTextEncode":
                title = str(node.get("title", "") or node.get("properties", {}).get("title", ""))
                if "Negative" not in title and "negative" not in title.lower():
                    if "widgets_values" in node and len(node["widgets_values"]) > 0:
                        node["widgets_values"][0] = prompt_text
                        print(f"✅ Промпт обновлен в узле '{node.get('id')}': {prompt_text[:100]}...")
                        break
    
    # Обновляем negative prompt
    if "negative_prompt" in params:
        negative_prompt_text = params["negative_prompt"]
        for node in nodes:
            if node.get("type") == "CLIPTextEncode":
                title = str(node.get("title", "") or node.get("properties", {}).get("title", ""))
                if "Negative" in title or "negative" in title.lower():
                    if "widgets_values" in node and len(node["widgets_values"]) > 0:
                        node["widgets_values"][0] = negative_prompt_text
                        print(f"✅ Negative prompt обновлен в узле '{node.get('id')}': {negative_prompt_text[:100]}...")
                        break
    
    # Обновляем seed (если нужно)
    if "seed" in params:
        seed_value = int(params["seed"])
        # Ищем узел с seed в inputs или widgets_values
        for node in nodes:
            if "inputs" in node and "seed" in node["inputs"]:
                node["inputs"]["seed"] = seed_value
                print(f"✅ Seed обновлен в узле '{node.get('id')}': {seed_value}")
                break

def apply_video_params_to_nodes(nodes, params):
    """Применяет параметры для видео к формату с nodes"""
    # Обновляем промпт
    if "prompt" in params:
        prompt_text = params["prompt"]
        for node in nodes:
            if node.get("type") == "CLIPTextEncode":
                title = str(node.get("title", "") or node.get("properties", {}).get("title", ""))
                if "Negative" not in title and "negative" not in title.lower():
                    if "widgets_values" in node and len(node["widgets_values"]) > 0:
                        node["widgets_values"][0] = prompt_text
                        print(f"✅ Промпт обновлен в узле '{node.get('id')}': {prompt_text[:100]}...")
                        break
    
    # Обновляем fps и length (если нужно)
    # Это зависит от структуры конкретного workflow

def apply_voice_params_to_nodes(nodes, params):
    """Применяет параметры для голоса к формату с nodes"""
    # Обновляем промпт (если есть)
    if "prompt" in params:
        prompt_text = params["prompt"]
        for node in nodes:
            if node.get("type") == "CLIPTextEncode" or "text" in str(node.get("type", "")).lower():
                if "widgets_values" in node and len(node["widgets_values"]) > 0:
                    node["widgets_values"][0] = prompt_text
                    print(f"✅ Промпт обновлен в узле '{node.get('id')}': {prompt_text[:100]}...")
                    break
    
    # Обновляем другие параметры универсально
    for param_key, param_value in params.items():
        if param_key == "prompt":
            continue
        # Ищем узлы с этим параметром в inputs или widgets_values
        for node in nodes:
            if "inputs" in node and param_key in node["inputs"]:
                node["inputs"][param_key] = param_value
                print(f"✅ Параметр '{param_key}' обновлен в узле '{node.get('id')}': {param_value}")
                break

def cleanup_comfyui(process, timeout=10):
    """
    Завершает процесс ComfyUI с гарантией
    Сначала пробует terminate(), затем kill() если нужно
    """
    if process is None:
        return
    
    try:
        # Пробуем мягкое завершение
        process.terminate()
        try:
            process.wait(timeout=timeout)
            print(f"✅ ComfyUI процесс завершен (terminate)")
        except subprocess.TimeoutExpired:
            # Если не завершился, принудительно убиваем
            print(f"⚠️ ComfyUI не завершился за {timeout}с, принудительное завершение...")
            process.kill()
            process.wait(timeout=5)
            print(f"✅ ComfyUI процесс завершен (kill)")
    except Exception as e:
        print(f"⚠️ Ошибка при завершении ComfyUI: {e}")
        try:
            # Последняя попытка - kill
            process.kill()
            process.wait(timeout=2)
        except Exception:
            pass

def handler(job):
    """
    Handler для RunPod Serverless
    Принимает запрос с workflow и параметрами
    
    ВАЖНО: Воркер автоматически завершает работу после возврата результата.
    RunPod serverless завершает контейнер после того, как handler вернет ответ.
    
    Процесс ComfyUI завершается во всех случаях:
    - При успешном завершении генерации
    - При ошибке генерации
    - При таймауте
    - При любой другой ошибке
    """
    comfyui_process = None
    try:
        # Шаг 1: Находим Network Volume с моделями
        network_models_path = find_network_volume()
        
        # Шаг 2: Настраиваем символические ссылки
        if network_models_path:
            setup_models_symlink(network_models_path)
        
        # Шаг 3: Запускаем ComfyUI
        comfyui_process = start_comfyui()
        
        if comfyui_process is None:
            return {
                "error": "Не удалось запустить ComfyUI процесс"
            }
        
        # Шаг 4: Ждем пока ComfyUI запустится и просканирует модели
        if not wait_for_comfyui(comfyui_process):
            cleanup_comfyui(comfyui_process)
            return {
                "error": "ComfyUI не запустился за отведенное время"
            }
        
        # Получаем данные из запроса
        input_data = job.get("input", {})
        workflow_type = input_data.get("workflow", "photo")  # photo, video, voice
        workflow_params = input_data.get("params", {})
        
        print(f"📋 Тип workflow: {workflow_type}")
        print(f"📋 Получены параметры: {list(workflow_params.keys())}")
        
        # Загружаем workflow
        workflow_path = f"{COMFYUI_DIR}/workflows/{workflow_type}.json"
        if not os.path.exists(workflow_path):
            return {
                "error": f"Workflow {workflow_type}.json не найден"
            }
        
        with open(workflow_path, 'r', encoding='utf-8') as f:
            workflow_data = json.load(f)
        
        # Определяем формат workflow (с nodes или без)
        # Формат 1: плоский объект {"3": {...}, "4": {...}}
        # Формат 2: с nodes {"nodes": [{...}], ...}
        
        # Для формата с nodes работаем напрямую, не конвертируя
        # Это важно, чтобы сохранить widgets_values и другие поля
        if "nodes" in workflow_data:
            # Работаем напрямую с nodes, обновляя только нужные параметры
            workflow_to_send = json.loads(json.dumps(workflow_data))  # Глубокая копия
            
            # Применяем параметры напрямую к nodes
            if workflow_type == "video":
                apply_video_params_to_nodes(workflow_to_send["nodes"], workflow_params)
            elif workflow_type == "voice":
                apply_voice_params_to_nodes(workflow_to_send["nodes"], workflow_params)
            else:
                apply_photo_params_to_nodes(workflow_to_send["nodes"], workflow_params)
            
            print(f"📤 Отправляю workflow в ComfyUI (узлов: {len(workflow_to_send['nodes'])})")
        else:
            # Плоский формат - работаем напрямую
            workflow_to_send = json.loads(json.dumps(workflow_data))  # Глубокая копия
            
            # Применяем параметры к workflow в зависимости от типа
            if workflow_type == "video":
                apply_video_params(workflow_to_send, workflow_params)
            elif workflow_type == "voice":
                apply_voice_params(workflow_to_send, workflow_params)
            else:
                apply_photo_params(workflow_to_send, workflow_params)
            
            print(f"📤 Отправляю workflow в ComfyUI (узлов: {len(workflow_to_send)})")
        
        # Отправляем промпт в очередь
        print("📤 Отправляю workflow в ComfyUI API...")
        result = queue_prompt(workflow_to_send)
        
        prompt_id = result.get("prompt_id")
        
        if not prompt_id:
            # Проверяем, есть ли ошибки в ответе
            error_info = result.get("error", {})
            node_errors = result.get("node_errors", {})
            
            if error_info or node_errors:
                error_msg = error_info.get("message", "Неизвестная ошибка") if error_info else "Ошибка валидации workflow"
                error_type = error_info.get("type", "") if error_info else ""
                
                error_details = f"Ошибка ComfyUI: {error_msg}"
                if node_errors:
                    error_details += "\n\nОшибки в узлах:"
                    for node_id, node_error in node_errors.items():
                        node_type = node_error.get("class_type", "Unknown")
                        errors = node_error.get("errors", [])
                        for err in errors:
                            err_msg = err.get("message", "Unknown error")
                            err_details = err.get("details", "")
                            error_details += f"\n- Узел {node_id} ({node_type}): {err_msg}"
                            if err_details:
                                error_details += f" ({err_details})"
                
                print(f"❌ Ошибка при отправке промпта: {error_details}")
                cleanup_comfyui(comfyui_process)
                return {
                    "error": "Не удалось отправить промпт в очередь",
                    "details": error_details,
                    "comfyui_error": error_info,
                    "node_errors": node_errors
                }
            
            cleanup_comfyui(comfyui_process)
            return {
                "error": "Не удалось отправить промпт в очередь",
                "details": result
            }
        
        # Ждем завершения генерации
        max_wait = 300  # 5 минут максимум
        start_time = time.time()
        
        while time.time() - start_time < max_wait:
            history = get_history(prompt_id)
            
            if prompt_id in history:
                history_data = history[prompt_id]
                status = history_data.get("status", {})
                
                if status.get("completed"):
                    # Генерация завершена
                    outputs = history_data.get("outputs", {})
                    files = []  # Может содержать изображения, видео или аудио
                    
                    # Собираем все файлы (изображения, видео, аудио)
                    for node_id, node_output in outputs.items():
                        # Изображения
                        if "images" in node_output:
                            for image_info in node_output["images"]:
                                filename = image_info["filename"]
                                subfolder = image_info.get("subfolder", "")
                                folder_type = image_info.get("type", "output")
                                
                                file_data = get_image(filename, subfolder, folder_type)
                                # Конвертируем в base64 для отправки
                                file_base64 = base64.b64encode(file_data).decode('utf-8')
                                files.append({
                                    "filename": filename,
                                    "data": file_base64,
                                    "type": "image"
                                })
                        
                        # Видео
                        if "videos" in node_output:
                            for video_info in node_output["videos"]:
                                filename = video_info["filename"]
                                subfolder = video_info.get("subfolder", "")
                                folder_type = video_info.get("type", "output")
                                
                                # Используем get_image для получения видео (тот же endpoint)
                                file_data = get_image(filename, subfolder, folder_type)
                                file_base64 = base64.b64encode(file_data).decode('utf-8')
                                files.append({
                                    "filename": filename,
                                    "data": file_base64,
                                    "type": "video"
                                })
                        
                        # Аудио
                        if "audio" in node_output:
                            audio_info = node_output["audio"]
                            filename = audio_info["filename"]
                            subfolder = audio_info.get("subfolder", "")
                            folder_type = audio_info.get("type", "output")
                            
                            file_data = get_image(filename, subfolder, folder_type)  # Тот же endpoint
                            file_base64 = base64.b64encode(file_data).decode('utf-8')
                            files.append({
                                "filename": filename,
                                "data": file_base64,
                                "type": "audio"
                            })
                    
                    # Завершаем процесс ComfyUI перед возвратом результата
                    cleanup_comfyui(comfyui_process)
                    
                    print("✅ Генерация завершена успешно, воркер завершает работу")
                    
                    return {
                        "status": "completed",
                        "prompt_id": prompt_id,
                        "files": files,  # Универсальное поле для всех типов файлов
                        "images": files,  # Обратная совместимость
                        "outputs": outputs
                    }
                
                if status.get("failed"):
                    # Генерация провалилась
                    error_msg = status.get("error", "Неизвестная ошибка")
                    print(f"❌ Генерация провалилась: {error_msg}")
                    cleanup_comfyui(comfyui_process)
                    
                    return {
                        "status": "failed",
                        "error": error_msg
                    }
            
            time.sleep(1)
        
        # Таймаут
        print("⏱️ Превышено время ожидания генерации")
        cleanup_comfyui(comfyui_process)
        
        return {
            "status": "timeout",
            "error": "Превышено время ожидания генерации"
        }
        
    except Exception as e:
        # Убеждаемся что процесс завершен при любой ошибке
        error_type = type(e).__name__
        error_msg = str(e)
        print(f"❌ Критическая ошибка в handler: {error_type}: {error_msg}")
        cleanup_comfyui(comfyui_process)
        
        return {
            "error": error_msg,
            "type": error_type,
            "status": "error"
        }

# Запускаем RunPod serverless
# RunPod requires runpod.serverless.start() to be called
if __name__ == "__main__":
    runpod.serverless.start({"handler": handler})
