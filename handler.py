import runpod
import requests
import json
import time
import os
import base64

# Путь к ComfyUI
COMFYUI_DIR = "/workspace/ComfyUI"
COMFYUI_PORT = 8188
COMFYUI_URL = f"http://127.0.0.1:{COMFYUI_PORT}"

# Стандартный путь к Network Volume в RunPod
# RunPod автоматически монтирует Network Volume в /runpod-volume
# Если Network Volume содержит папку models, она будет доступна по пути /runpod-volume/models
RUNPOD_VOLUME_PATH = os.environ.get("RUNPOD_VOLUME_PATH", "/runpod-volume")
COMFYUI_MODELS_PATH = os.path.join(COMFYUI_DIR, "models")

# Удалены функции list_directory_recursive и check_network_volume_contents
# Больше не нужны, так как путь к моделям известен

def find_network_volume():
    """Находит путь к Network Volume с моделями (известный путь)"""
    print("\n" + "="*60)
    print("🔍 Поиск Network Volume с моделями")
    print("="*60)
    
    # Известный путь к моделям
    models_path = os.path.join(RUNPOD_VOLUME_PATH, "ComfyUI", "models")
    
    if os.path.exists(models_path):
        print(f"✅ Найдена папка models: {models_path}")
        
        # Быстрая проверка наличия типичных папок
        try:
            subdirs = [d for d in os.listdir(models_path) if os.path.isdir(os.path.join(models_path, d))]
            model_subdirs = [d for d in subdirs if d in ["vae", "loras", "clip", "unet", "gguf", "checkpoints", "diffusion_models"]]
            if model_subdirs:
                print(f"   Подпапки с моделями: {', '.join(model_subdirs[:10])}")
            return models_path
        except Exception as e:
            print(f"   ⚠️ Ошибка проверки: {e}")
            return models_path  # Все равно возвращаем путь
    
    # Fallback: проверяем альтернативные пути
    alternative_paths = [
        os.path.join(RUNPOD_VOLUME_PATH, "models"),
        RUNPOD_VOLUME_PATH,
    ]
    
    for alt_path in alternative_paths:
        if os.path.exists(alt_path):
            try:
                subdirs = [d for d in os.listdir(alt_path) if os.path.isdir(os.path.join(alt_path, d))]
                if any(d in ["vae", "loras", "clip", "unet", "gguf"] for d in subdirs):
                    print(f"✅ Найдена папка models (альтернативный путь): {alt_path}")
                    return alt_path
            except:
                continue
    
    print(f"⚠️ Папка models не найдена")
    print(f"   Проверенные пути: {models_path}, {alternative_paths}")
    return None

def setup_models_symlink(network_models_path):
    """
    Создает символические ссылки от Network Volume к ComfyUI models
    Также создает extra_model_paths.yaml для ComfyUI, если нужно
    """
    if not network_models_path:
        return False
    
    comfyui_models = os.path.join(COMFYUI_DIR, "models")
    
    # Вариант 1: Создаем символические ссылки на подпапки (более безопасно)
    # Это позволяет сохранить локальную папку models и добавить Network Volume как дополнительный путь
    try:
        # Создаем папку models если её нет
        os.makedirs(comfyui_models, exist_ok=True)
        
        # Создаем ссылки на подпапки из Network Volume
        linked_count = 0
        for subdir in ["vae", "loras", "clip", "unet", "gguf", "checkpoints", "diffusion_models", "text_encoders"]:
            network_subdir = os.path.join(network_models_path, subdir)
            comfyui_subdir = os.path.join(comfyui_models, subdir)
            
            if os.path.exists(network_subdir):
                # Если подпапка уже существует, проверяем что это не ссылка
                if os.path.exists(comfyui_subdir):
                    if os.path.islink(comfyui_subdir):
                        # Удаляем старую ссылку
                        os.unlink(comfyui_subdir)
                    else:
                        # Локальная папка существует - не трогаем
                        print(f"⚠️ Папка {comfyui_subdir} уже существует локально, пропускаю")
                        continue
                
                # Создаем символическую ссылку
                os.symlink(network_subdir, comfyui_subdir)
                print(f"✅ Создана ссылка: {comfyui_subdir} -> {network_subdir}")
                linked_count += 1
        
        if linked_count > 0:
            print(f"✅ Создано {linked_count} символических ссылок на подпапки models")
            return True
        else:
            print(f"⚠️ Не найдено подпапок для создания ссылок в {network_models_path}")
    except Exception as e:
        print(f"⚠️ Ошибка создания ссылок на подпапки: {e}")
    
    # Вариант 2: Создаем extra_model_paths.yaml для ComfyUI
    # Правильный формат для ComfyUI: каждая секция должна иметь base_path и пути к папкам
    try:
        extra_model_paths_file = os.path.join(COMFYUI_DIR, "extra_model_paths.yaml")
        if not os.path.exists(extra_model_paths_file):
            import yaml
            # Правильный формат для ComfyUI extra_model_paths.yaml
            extra_paths_config = {
                "a": {  # Имя секции (может быть любым, обычно 'a')
                    "base_path": str(network_models_path),
                    "checkpoints": "checkpoints",
                    "vae": "vae",
                    "loras": "loras",
                    "upscale_models": "upscale_models",
                    "controlnet": "controlnet",
                    "clip": "clip",
                    "unet": "unet",
                    "gguf": "gguf",
                    "text_encoders": "text_encoders",
                    "diffusion_models": "diffusion_models"
                }
            }
            
            with open(extra_model_paths_file, 'w') as f:
                yaml.dump(extra_paths_config, f, default_flow_style=False, sort_keys=False)
            print(f"✅ Создан extra_model_paths.yaml: {extra_model_paths_file}")
            print(f"   Указывает на Network Volume: {network_models_path}")
            return True
    except ImportError:
        print("⚠️ PyYAML не установлен, не могу создать extra_model_paths.yaml")
    except Exception as e:
        print(f"⚠️ Ошибка создания extra_model_paths.yaml: {e}")
        import traceback
        traceback.print_exc()
    
    return False

# Функции start_comfyui, wait_for_comfyui, cleanup_comfyui удалены
# ComfyUI теперь запускается через start.sh скрипт (как в comfuiStory)

def queue_prompt(prompt):
    """Отправляет промпт в очередь ComfyUI"""
    p = {"prompt": prompt}
    data = json.dumps(p).encode('utf-8')
    
    # Логируем, что отправляем (первые 2000 символов)
    prompt_str = json.dumps(prompt, indent=2)
    print(f"📤 Отправляю в ComfyUI /prompt (первые 2000 символов):")
    print(prompt_str[:2000])
    
    # Проверяем наличие узла RandomSeed в отправляемом workflow
    if isinstance(prompt, dict):
        seed_node_found = False
        for node_id, node_data in prompt.items():
            if isinstance(node_data, dict) and node_data.get("class_type") == "RandomSeed":
                seed_node_found = True
                print(f"✅ Узел RandomSeed найден в отправляемом workflow: {node_id}")
                break
        if not seed_node_found:
            print("⚠️ Узел RandomSeed НЕ найден в отправляемом workflow!")
            # Выводим все class_type для отладки
            all_types = {k: v.get("class_type") for k, v in prompt.items() if isinstance(v, dict)}
            print(f"   Все class_type в workflow: {list(all_types.values())[:20]}")
    
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
        # Ищем узел "RandomSeed" (стандартный узел ComfyUI)
        found_id, node_data = find_node_by_type(workflow, "RandomSeed")
        if found_id and "inputs" in workflow[found_id]:
            # RandomSeed использует параметры seed и noise_seed
            if "seed" in workflow[found_id]["inputs"]:
                workflow[found_id]["inputs"]["seed"] = seed_value
            if "noise_seed" in workflow[found_id]["inputs"]:
                workflow[found_id]["inputs"]["noise_seed"] = seed_value
            print(f"✅ Seed обновлен в узле 'RandomSeed' (ID: {found_id}): {seed_value}")
        else:
            # Ищем узел с seed в inputs (для обратной совместимости)
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
        # Ищем узел "RandomSeed" (стандартный узел ComfyUI)
        seed_updated = False
        for node in nodes:
            if node.get("type") == "RandomSeed":
                if "inputs" in node:
                    if "seed" in node["inputs"]:
                        node["inputs"]["seed"] = seed_value
                    if "noise_seed" in node["inputs"]:
                        node["inputs"]["noise_seed"] = seed_value
                    print(f"✅ Seed обновлен в узле 'RandomSeed' (ID: {node.get('id')}): {seed_value}")
                    seed_updated = True
                    break
        
        # Если не нашли RandomSeed, ищем узел с seed в inputs
        if not seed_updated:
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

# Функция cleanup_comfyui удалена
# ComfyUI остается запущенным для следующих запросов (как в comfuiStory)

def check_comfyui_server():
    """Проверяет доступность ComfyUI сервера (как в comfuiStory)"""
    try:
        response = requests.get(f"{COMFYUI_URL}/system_stats", timeout=5)
        return response.status_code == 200
    except Exception:
        return False

def check_custom_nodes():
    """Проверяет, какие custom nodes загружены в ComfyUI через object_info"""
    try:
        response = requests.get(f"{COMFYUI_URL}/object_info", timeout=10)
        if response.status_code == 200:
            object_info = response.json()
            
            # Логируем структуру object_info для отладки
            print(f"📊 Структура object_info: {type(object_info)}")
            if isinstance(object_info, dict):
                print(f"   Ключи верхнего уровня (первые 20): {list(object_info.keys())[:20]}")
            
            # Ищем Seed Generator в object_info
            # object_info может быть словарем, где ключи - это class_type узлов
            all_node_types = []
            if isinstance(object_info, dict):
                # Проверяем, является ли это плоским словарем с class_type как ключами
                # или вложенной структурой
                for key, value in object_info.items():
                    if isinstance(value, dict):
                        # Если значение - словарь, это может быть информация об узле
                        all_node_types.append(key)
                    elif isinstance(value, list):
                        # Если значение - список, это может быть список узлов
                        all_node_types.append(key)
            
            # Проверяем наличие Seed Generator
            if "Seed Generator" in all_node_types:
                print(f"✅ Custom node 'Seed Generator' найден в object_info")
                return True
            else:
                print(f"⚠️ Custom node 'Seed Generator' НЕ найден в object_info")
                print(f"   Всего типов узлов: {len(all_node_types)}")
                print(f"   Доступные типы узлов (первые 50): {all_node_types[:50]}")
                # Ищем похожие названия
                similar = [t for t in all_node_types if "seed" in t.lower() or "generator" in t.lower()]
                if similar:
                    print(f"   Похожие узлы: {similar}")
                # Выводим полный список для отладки (первые 100)
                print(f"   Полный список узлов (первые 100): {all_node_types[:100]}")
                return False
        else:
            print(f"⚠️ object_info вернул статус {response.status_code}")
            return False
    except Exception as e:
        print(f"⚠️ Ошибка проверки custom nodes: {e}")
        import traceback
        traceback.print_exc()
        return False

def check_custom_nodes():
    """Проверяет, какие custom nodes загружены в ComfyUI"""
    try:
        response = requests.get(f"{COMFYUI_URL}/object_info", timeout=10)
        if response.status_code == 200:
            object_info = response.json()
            # Ищем Seed Generator в object_info
            all_node_types = []
            for category, nodes in object_info.items():
                if isinstance(nodes, dict) and "input" in nodes:
                    all_node_types.append(category)
            
            # Проверяем наличие Seed Generator
            if "Seed Generator" in all_node_types:
                print(f"✅ Custom node 'Seed Generator' найден в object_info")
                return True
            else:
                print(f"⚠️ Custom node 'Seed Generator' НЕ найден в object_info")
                print(f"   Доступные типы узлов (первые 30): {all_node_types[:30]}")
                return False
        return False
    except Exception as e:
        print(f"⚠️ Ошибка проверки custom nodes: {e}")
        return False

def handler(job):
    """
    Handler для RunPod Serverless
    Принимает запрос с workflow и параметрами
    
    ComfyUI должен быть уже запущен через start.sh скрипт
    (как в comfuiStory подходе)
    """
    try:
        # Проверяем, что ComfyUI доступен (как в comfuiStory)
        if not check_comfyui_server():
            return {
                "error": "ComfyUI сервер недоступен. Убедитесь, что ComfyUI запущен."
            }
        
        print("✅ ComfyUI сервер доступен")
        
        # Проверяем, что custom nodes загружены
        print("🔍 Проверяю наличие custom nodes через object_info...")
        check_custom_nodes()
        
        # Получаем данные из запроса
        print(f"📥 Получен job: {json.dumps(job, indent=2)[:500]}")
        input_data = job.get("input", {})
        print(f"📥 input_data: {json.dumps(input_data, indent=2)[:500]}")
        
        workflow_type = input_data.get("workflow", "photo")  # photo, video, voice
        workflow_params = input_data.get("params", {})
        
        print(f"📋 Тип workflow: {workflow_type}")
        print(f"📋 Получены параметры: {list(workflow_params.keys())}")
        print(f"📋 Значения параметров: {workflow_params}")
        
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
        
        # Проверяем, что все узлы присутствуют в workflow
        if isinstance(workflow_to_send, dict):
            if "nodes" in workflow_to_send:
                # Формат с nodes - проверяем наличие всех узлов
                node_ids_in_workflow = {str(node.get("id")) for node in workflow_to_send.get("nodes", [])}
                print(f"📋 Workflow содержит {len(workflow_to_send.get('nodes', []))} узлов")
                
                # Проверяем наличие узла Seed Generator
                seed_gen_nodes = [node for node in workflow_to_send.get("nodes", []) if node.get("type") == "Seed Generator"]
                if seed_gen_nodes:
                    print(f"✅ Найден узел Seed Generator в формате nodes: {[n.get('id') for n in seed_gen_nodes]}")
                else:
                    print("⚠️ Узел Seed Generator не найден в workflow (формат nodes)")
            else:
                # Плоский формат - проверяем наличие всех узлов
                node_ids_in_workflow = set(workflow_to_send.keys())
                print(f"📋 Workflow содержит {len(workflow_to_send)} узлов")
                
                # Проверяем наличие узла Seed Generator
                seed_gen_nodes = [k for k, v in workflow_to_send.items() if isinstance(v, dict) and v.get("class_type") == "Seed Generator"]
                if seed_gen_nodes:
                    print(f"✅ Найден узел Seed Generator: {seed_gen_nodes}")
                    # Проверяем содержимое узла
                    for node_id in seed_gen_nodes:
                        node_data = workflow_to_send[node_id]
                        print(f"   Узел {node_id}: class_type={node_data.get('class_type')}, inputs={node_data.get('inputs', {})}")
                else:
                    print("⚠️ Узел Seed Generator не найден в workflow (плоский формат)")
                    # Выводим все class_type для отладки
                    all_class_types = {k: v.get("class_type") for k, v in workflow_to_send.items() if isinstance(v, dict)}
                    print(f"   Все class_type в workflow: {all_class_types}")
        
        # Логируем первые 1000 символов workflow для отладки
        workflow_str = json.dumps(workflow_to_send)
        print(f"📋 Workflow для отправки (первые 1000 символов): {workflow_str[:1000]}")
        
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
                return {
                    "error": "Не удалось отправить промпт в очередь",
                    "details": error_details,
                    "comfyui_error": error_info,
                    "node_errors": node_errors
                }
            
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
                    
                    # ComfyUI остается запущенным для следующих запросов
                    # (как в comfuiStory подходе)
                    
                    print("✅ Генерация завершена успешно")
                    
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
                    
                    return {
                        "status": "failed",
                        "error": error_msg
                    }
            
            time.sleep(1)
        
        # Таймаут
        print("⏱️ Превышено время ожидания генерации")
        
        return {
            "status": "timeout",
            "error": "Превышено время ожидания генерации"
        }
        
    except Exception as e:
        # Обрабатываем ошибки без завершения ComfyUI
        error_type = type(e).__name__
        error_msg = str(e)
        print(f"❌ Критическая ошибка в handler: {error_type}: {error_msg}")
        
        return {
            "error": error_msg,
            "type": error_type,
            "status": "error"
        }

# Запускаем RunPod serverless
# RunPod requires runpod.serverless.start() to be called
if __name__ == "__main__":
    runpod.serverless.start({"handler": handler})
