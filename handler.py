import runpod
import requests
import json
import time
import os
import base64
import sys

# Handler version: 2025-02-17 - Added workflow conversion from nodes to flat format

# Путь к ComfyUI (обновлен для нового Dockerfile)
COMFYUI_DIR = "/comfyui"
COMFYUI_PORT = 8188
COMFYUI_URL = f"http://127.0.0.1:{COMFYUI_PORT}"

# Добавляем ComfyUI в sys.path для импорта кастомных модулей
sys.path.insert(0, COMFYUI_DIR)

# Патч для RES4LYF: добавляем beta57 в стандартные scheduler
try:
    import comfy.samplers
    if "beta57" not in comfy.samplers.SCHEDULER_NAMES:
        comfy.samplers.SCHEDULER_NAMES.append("beta57")
        print("[Handler] ✅ Патч применен: добавлен 'beta57' в SCHEDULER_NAMES")
    else:
        print("[Handler] ✅ Scheduler 'beta57' уже присутствует в SCHEDULER_NAMES")
except Exception as e:
    print(f"[Handler] ⚠️ Не удалось применить патч для beta57: {e}")

# Стандартный путь к Network Volume в RunPod
RUNPOD_VOLUME_PATH = os.environ.get("RUNPOD_VOLUME_PATH", "/runpod-volume")

def convert_nodes_to_flat_format(workflow_with_nodes):
    """
    Конвертирует workflow из формата с nodes в плоский формат для ComfyUI API
    
    Формат с nodes:
    {
      "nodes": [{"id": 1, "type": "...", "inputs": {...}, "outputs": [{"links": [link_id]}]}],
      "links": [link_id] или связи в outputs
    }
    
    Плоский формат:
    {
      "1": {"class_type": "...", "inputs": {"param": [from_node_id, from_slot]}}
    }
    """
    if "nodes" not in workflow_with_nodes:
        # Уже плоский формат
        return workflow_with_nodes
    
    nodes = workflow_with_nodes.get("nodes", [])
    links = workflow_with_nodes.get("links", [])
    
    # Создаем словарь для быстрого доступа к узлам по ID
    nodes_by_id = {node["id"]: node for node in nodes}
    
    # Строим карту связей из массива links
    # Формат links: [link_id, from_node_id, from_slot, to_node_id, to_slot, type]
    connections = {}  # {(to_node_id, to_slot): (from_node_id, from_slot)}
    link_id_to_connection = {}  # {link_id: (from_node_id, from_slot, to_node_id, to_slot)}
    
    # Обрабатываем массив links
    for link in links:
        if isinstance(link, list) and len(link) >= 5:
            # Формат: [link_id, from_node_id, from_slot, to_node_id, to_slot, type]
            link_id = link[0] if len(link) > 0 else None
            from_node_id = link[1] if len(link) > 1 else None
            from_slot = link[2] if len(link) > 2 else 0
            to_node_id = link[3] if len(link) > 3 else None
            to_slot = link[4] if len(link) > 4 else 0
            
            if from_node_id is not None and to_node_id is not None:
                connections[(to_node_id, to_slot)] = (from_node_id, from_slot)
                if link_id is not None:
                    link_id_to_connection[link_id] = (from_node_id, from_slot, to_node_id, to_slot)
                print(f"🔗 Связь: узел {from_node_id}:{from_slot} -> узел {to_node_id}:{to_slot} (link_id: {link_id})")
    
    # Также обрабатываем связи из outputs узлов (для обратной совместимости)
    for node in nodes:
        node_id = node.get("id")
        outputs = node.get("outputs")
        
        # Проверяем, что outputs не None и является списком
        if outputs is None:
            outputs = []
        if not isinstance(outputs, list):
            outputs = []
        
        # Проходим по всем outputs узла
        for output_idx, output in enumerate(outputs):
            if isinstance(output, dict):
                output_links = output.get("links")
                
                # Проверяем, что links не None и является списком
                if output_links is None:
                    output_links = []
                if not isinstance(output_links, list):
                    output_links = []
                
                # links содержит ID связей или прямые ссылки на узлы
                for link in output_links:
                    if isinstance(link, list) and len(link) >= 2:
                        # Прямая ссылка [to_node_id, to_slot]
                        to_node_id = link[0]
                        to_slot = link[1] if len(link) > 1 else 0
                        # Используем только если связь еще не установлена из массива links
                        if (to_node_id, to_slot) not in connections:
                            connections[(to_node_id, to_slot)] = (node_id, output_idx)
    
    # Конвертируем nodes в плоский формат
    flat_workflow = {}
    
    # Узлы, которые нужно пропустить (это не рабочие узлы, а UI элементы)
    # PrimitiveNode НЕ пропускаем, так как он используется для ввода текста в voice workflow
    skip_node_types = ["Note", "MarkdownNote", "Reroute", "ShowText", "ShowImage", "PreviewAny"]
    
    for node in nodes:
        node_id = str(node.get("id"))
        node_id_int = node.get("id")
        node_type = node.get("type", "")
        
        # Пропускаем узлы, которые не являются рабочими (Note, Reroute и т.д.)
        # НО НЕ пропускаем PrimitiveNode, так как он используется для ввода текста
        if node_type in skip_node_types:
            print(f"⏭️ Пропускаю узел {node_id} типа '{node_type}' (это UI элемент, не рабочий узел)")
            continue
        
        # Создаем запись в плоском формате
        flat_node = {
            "class_type": node_type,
            "inputs": {}
        }
        
        # Обрабатываем widgets_values - добавляем в inputs
        if "widgets_values" in node and node["widgets_values"] is not None:
            widgets = node["widgets_values"]
            if not isinstance(widgets, list):
                widgets = []
            # Для LoadImage: widgets_values[0] = filename, widgets_values[1] = subfolder (обычно "image" или "input")
            if node_type == "LoadImage" and len(widgets) >= 1:
                flat_node["inputs"]["image"] = widgets[0]
                if len(widgets) >= 2:
                    flat_node["inputs"]["upload"] = widgets[1]
                else:
                    # Если subfolder не указан, используем "input" по умолчанию (для загруженных изображений)
                    flat_node["inputs"]["upload"] = "input"
            # Для CLIPTextEncode: widgets_values[0] = text
            elif node_type == "CLIPTextEncode" and len(widgets) >= 1:
                flat_node["inputs"]["text"] = widgets[0]
            # Для VAELoader: widgets_values[0] = vae_name
            elif node_type == "VAELoader" and len(widgets) >= 1:
                flat_node["inputs"]["vae_name"] = widgets[0]
            # Для CLIPLoader: widgets_values[0] = clip_name, widgets_values[1] = type, widgets_values[2] = device
            elif node_type == "CLIPLoader" and len(widgets) >= 1:
                flat_node["inputs"]["clip_name"] = widgets[0]
                if len(widgets) >= 2:
                    flat_node["inputs"]["type"] = widgets[1]
                if len(widgets) >= 3:
                    flat_node["inputs"]["device"] = widgets[2]
            # Для UnetLoaderGGUF: widgets_values[0] = unet_name
            elif node_type == "UnetLoaderGGUF" and len(widgets) >= 1:
                flat_node["inputs"]["unet_name"] = widgets[0]
            # Для LoraLoader: widgets_values[0] = lora_name, widgets_values[1] = strength_model, widgets_values[2] = strength_clip
            elif node_type == "LoraLoader" and len(widgets) >= 1:
                flat_node["inputs"]["lora_name"] = widgets[0]
                if len(widgets) >= 2:
                    flat_node["inputs"]["strength_model"] = widgets[1]
                if len(widgets) >= 2:
                    flat_node["inputs"]["strength_clip"] = widgets[2]
            # Для LoraLoaderModelOnly: widgets_values[0] = lora_name, widgets_values[1] = strength_model
            elif node_type == "LoraLoaderModelOnly" and len(widgets) >= 1:
                flat_node["inputs"]["lora_name"] = widgets[0]
                if len(widgets) >= 2:
                    flat_node["inputs"]["strength_model"] = widgets[1]
            # Для EmptyHunyuanLatentVideo: widgets_values[0] = width, widgets_values[1] = height, widgets_values[2] = length, widgets_values[3] = batch_size
            elif node_type == "EmptyHunyuanLatentVideo":
                if len(widgets) >= 1:
                    flat_node["inputs"]["width"] = widgets[0]
                if len(widgets) >= 2:
                    flat_node["inputs"]["height"] = widgets[1]
                if len(widgets) >= 3:
                    flat_node["inputs"]["length"] = widgets[2]
                if len(widgets) >= 4:
                    flat_node["inputs"]["batch_size"] = widgets[3]
            # Для SaveVideo: widgets_values[0] = filename_prefix, widgets_values[1] = codec, widgets_values[2] = format
            elif node_type == "SaveVideo":
                if len(widgets) >= 1:
                    flat_node["inputs"]["filename_prefix"] = widgets[0]
                if len(widgets) >= 2:
                    flat_node["inputs"]["codec"] = widgets[1]
                if len(widgets) >= 3:
                    flat_node["inputs"]["format"] = widgets[2]
            # Для CreateVideo: widgets_values[0] = fps
            elif node_type == "CreateVideo":
                if len(widgets) >= 1:
                    fps_value = widgets[0]
                    # Конвертируем в int если нужно
                    if isinstance(fps_value, str) and fps_value.isdigit():
                        fps_value = int(fps_value)
                    flat_node["inputs"]["fps"] = fps_value
            # Для WanImageToVideo: widgets_values содержат width, height, length, batch_size
            elif node_type == "WanImageToVideo":
                # Порядок: [width, height, length, batch_size]
                if len(widgets) >= 1:
                    flat_node["inputs"]["width"] = widgets[0]
                if len(widgets) >= 2:
                    flat_node["inputs"]["height"] = widgets[1]
                if len(widgets) >= 3:
                    flat_node["inputs"]["length"] = widgets[2]
                if len(widgets) >= 4:
                    flat_node["inputs"]["batch_size"] = widgets[3]
            # Для PrimitiveNode: widgets_values[0] = значение (текст для voice workflow)
            # НЕ создаем узел PrimitiveNode, так как он не установлен в ComfyUI
            # Вместо этого пропускаем его и передадим текст напрямую в целевой узел после конвертации
            elif node_type == "PrimitiveNode":
                if len(widgets) >= 1:
                    # Проверяем тип выхода - если STRING, это текст
                    outputs = node.get("outputs", [])
                    if any(output.get("type") == "STRING" for output in outputs):
                        # Пропускаем создание узла - текст будет передан напрямую в целевой узел
                        print(f"📝 PrimitiveNode {node_id}: пропускаю создание узла, текст '{widgets[0][:50]}...' будет передан напрямую")
                        # Сохраняем текст в node для последующей передачи
                        node["_text_value"] = widgets[0]
                        continue
            # Для AILab_Qwen3TTSVoiceInstruct: widgets_values[0] = character (или gender), [1] = style, [2] = description
            # Согласно документации, может требоваться character вместо gender
            elif node_type == "AILab_Qwen3TTSVoiceInstruct":
                if len(widgets) >= 1:
                    # Пробуем character, если не работает - gender
                    flat_node["inputs"]["character"] = widgets[0]
                if len(widgets) >= 2:
                    flat_node["inputs"]["style"] = widgets[1]
                if len(widgets) >= 3:
                    flat_node["inputs"]["description"] = widgets[2]
            # Для AILab_Qwen3TTSVoiceDesign_Advanced: widgets_values содержат параметры модели
            # Порядок из workflow: [text_placeholder, instruct_placeholder, model_size, device, dtype, language, max_new_tokens, do_sample, temperature, top_p, top_k, repetition_penalty, attention_backend, unload_models, seed]
            # Но text и instruct приходят через inputs (связи), не через widgets_values
            # widgets_values[0] и [1] - это плейсхолдеры, реальные значения приходят через связи
            elif node_type == "AILab_Qwen3TTSVoiceDesign_Advanced":
                # Пропускаем первые два (text и instruct - приходят через связи)
                # Начинаем с индекса 2: model_size, device, dtype, language и т.д.
                if len(widgets) >= 3:
                    flat_node["inputs"]["model_size"] = widgets[2]
                if len(widgets) >= 4:
                    flat_node["inputs"]["device"] = widgets[3]
                if len(widgets) >= 5:
                    flat_node["inputs"]["dtype"] = widgets[4]
                    # precision может быть тем же, что и dtype, или отдельным параметром
                    flat_node["inputs"]["precision"] = widgets[4]
                if len(widgets) >= 6:
                    flat_node["inputs"]["language"] = widgets[5]
                if len(widgets) >= 7:
                    flat_node["inputs"]["max_new_tokens"] = widgets[6]
                if len(widgets) >= 8:
                    flat_node["inputs"]["do_sample"] = widgets[7]
                if len(widgets) >= 9:
                    flat_node["inputs"]["temperature"] = widgets[8]
                if len(widgets) >= 10:
                    flat_node["inputs"]["top_p"] = widgets[9]
                if len(widgets) >= 11:
                    flat_node["inputs"]["top_k"] = widgets[10]
                if len(widgets) >= 12:
                    flat_node["inputs"]["repetition_penalty"] = widgets[11]
                if len(widgets) >= 13:
                    flat_node["inputs"]["attention_backend"] = widgets[12]
                if len(widgets) >= 14:
                    flat_node["inputs"]["unload_models"] = widgets[13]
                if len(widgets) >= 15:
                    # Для voice workflow всегда используем фиксированный seed для стабильного голоса
                    # seed может быть числом или "randomize"
                    seed_value = widgets[14]
                    if isinstance(seed_value, str) and seed_value.lower() == "randomize":
                        # Фиксированный seed для стабильного голоса
                        seed_value = 42
                    flat_node["inputs"]["seed"] = seed_value
            # Для SaveAudio: widgets_values[0] = filename_prefix
            elif node_type == "SaveAudio":
                if len(widgets) >= 1:
                    flat_node["inputs"]["filename_prefix"] = widgets[0]
            # Для KSamplerAdvanced: widgets_values содержат параметры в определенном порядке
            elif node_type == "KSamplerAdvanced":
                # Порядок: [add_noise, seed, randomize, steps, cfg, sampler_name, scheduler, start_at_step, end_at_step, return_with_leftover_noise]
                if len(widgets) >= 1:
                    flat_node["inputs"]["add_noise"] = widgets[0]
                if len(widgets) >= 2:
                    # seed может быть числом или "randomize"
                    seed_value = widgets[1]
                    if isinstance(seed_value, str) and seed_value.lower() == "randomize":
                        # Используем случайное значение или оставляем как есть
                        import random
                        seed_value = random.randint(0, 2**32 - 1)
                    flat_node["inputs"]["noise_seed"] = seed_value
                if len(widgets) >= 4:
                    flat_node["inputs"]["steps"] = widgets[3]
                if len(widgets) >= 5:
                    flat_node["inputs"]["cfg"] = widgets[4]
                if len(widgets) >= 6:
                    flat_node["inputs"]["sampler_name"] = widgets[5]
                if len(widgets) >= 7:
                    flat_node["inputs"]["scheduler"] = widgets[6]
                if len(widgets) >= 8:
                    flat_node["inputs"]["start_at_step"] = widgets[7]
                if len(widgets) >= 9:
                    flat_node["inputs"]["end_at_step"] = widgets[8]
                if len(widgets) >= 10:
                    flat_node["inputs"]["return_with_leftover_noise"] = widgets[9]
            # Для UNETLoader: widgets_values[0] = unet_name, widgets_values[1] = weight_dtype
            elif node_type == "UNETLoader":
                if len(widgets) >= 1:
                    flat_node["inputs"]["unet_name"] = widgets[0]
                if len(widgets) >= 2:
                    flat_node["inputs"]["weight_dtype"] = widgets[1]
            # Для ModelSamplingSD3: widgets_values[0] = shift
            elif node_type == "ModelSamplingSD3":
                if len(widgets) >= 1:
                    flat_node["inputs"]["shift"] = widgets[0]
        
        # Обрабатываем связи из connections
        # Ищем все связи, которые ведут к этому узлу
        # Пропускаем обработку через connections для узлов, которые имеют inputs с полем link
        # (они будут обработаны позже через массив inputs)
        has_inputs_with_links = False
        if "inputs" in node and isinstance(node["inputs"], list):
            for input_item in node["inputs"]:
                if isinstance(input_item, dict) and input_item.get("link") is not None:
                    has_inputs_with_links = True
                    break
        
        for (to_node_id, to_slot), (from_node_id, from_slot) in connections.items():
            if to_node_id == node_id_int:
                # Пропускаем узлы, которые имеют inputs с полем link (они обрабатываются позже)
                if has_inputs_with_links:
                    continue
                
                # Эта связь ведет к текущему узлу
                # Нужно определить имя входа по типу узла и slot
                input_name = None
                
                # Стандартные имена входов для разных типов узлов
                if node_type == "KSamplerAdvanced":
                    if to_slot == 0:
                        input_name = "model"
                    elif to_slot == 1:
                        input_name = "positive"
                    elif to_slot == 2:
                        input_name = "negative"
                    elif to_slot == 3:
                        input_name = "latent_image"
                elif node_type == "VAEDecode":
                    if to_slot == 0:
                        input_name = "samples"
                    elif to_slot == 1:
                        input_name = "vae"
                elif node_type == "CLIPTextEncode":
                    if to_slot == 0:
                        input_name = "clip"
                elif node_type == "LoraLoader":
                    if to_slot == 0:
                        input_name = "model"
                    elif to_slot == 1:
                        input_name = "clip"
                elif node_type == "LoraLoaderModelOnly":
                    if to_slot == 0:
                        input_name = "model"
                elif node_type == "PathchSageAttentionKJ":
                    if to_slot == 0:
                        input_name = "model"
                elif node_type == "WanImageToVideo":
                    # WanImageToVideo имеет входы: positive, negative, vae, clip_vision_output, start_image
                    # Используем имя входа из inputs массива по индексу to_slot
                    input_name = None
                    if "inputs" in node and isinstance(node["inputs"], list) and to_slot < len(node["inputs"]):
                        input_item = node["inputs"][to_slot]
                        if isinstance(input_item, dict):
                            input_name = input_item.get("name")
                    # Fallback на маппинг по слотам, если имя не найдено
                    if not input_name:
                        if to_slot == 0:
                            input_name = "positive"
                        elif to_slot == 1:
                            input_name = "negative"
                        elif to_slot == 2:
                            input_name = "vae"
                        elif to_slot == 3:
                            input_name = "clip_vision_output"
                        elif to_slot == 4:
                            input_name = "start_image"
                elif node_type == "SaveVideo":
                    if to_slot == 0:
                        input_name = "video"
                    elif to_slot == 1:
                        input_name = "filename_prefix"
                    # codec и format обычно задаются через widgets_values
                elif node_type == "AILab_Qwen3TTSVoiceDesign_Advanced":
                    # Входы: text (slot 0), instruct (slot 1)
                    if to_slot == 0:
                        input_name = "text"
                    elif to_slot == 1:
                        input_name = "instruct"
                elif node_type == "SaveAudio":
                    if to_slot == 0:
                        input_name = "audio"
                elif node_type == "PreviewAudio":
                    if to_slot == 0:
                        input_name = "audio"
                
                if input_name:
                    flat_node["inputs"][input_name] = [str(from_node_id), from_slot]
        
        # Обрабатываем inputs узла - ищем связи через поле "link"
        if "inputs" in node and node["inputs"] is not None:
            node_inputs = node["inputs"]
            if isinstance(node_inputs, list):
                # Формат: [{"name": "images", "type": "IMAGE", "link": 182}, ...]
                for input_def in node_inputs:
                    if isinstance(input_def, dict):
                        input_name = input_def.get("name")
                        link_id = input_def.get("link")
                        
                        # Если есть link, находим связь по link_id
                        if link_id is not None and link_id in link_id_to_connection:
                            from_node_id, from_slot, to_node_id, to_slot = link_id_to_connection[link_id]
                            if to_node_id == node_id_int:
                                # Это связь к текущему узлу
                                flat_node["inputs"][input_name] = [str(from_node_id), from_slot]
                                print(f"🔗 Связь через link {link_id}: {input_name} = [{from_node_id}, {from_slot}]")
                        # Если нет link, но есть значение в input_def, копируем его
                        elif "value" in input_def:
                            if input_name not in flat_node["inputs"]:
                                flat_node["inputs"][input_name] = input_def["value"]
                                print(f"📝 Прямое значение для {input_name}: {input_def['value']}")
            elif isinstance(node_inputs, dict):
                # Формат: {"param": value} - прямые значения
                for key, value in node_inputs.items():
                    # Не перезаписываем, если уже установлено из widgets_values или connections
                    if key not in flat_node["inputs"]:
                        flat_node["inputs"][key] = value
        
        # Копируем _meta если есть
        if "_meta" in node:
            flat_node["_meta"] = node["_meta"]
        
        flat_workflow[node_id] = flat_node
    
    print(f"✅ Конвертировано {len(flat_workflow)} узлов из формата с nodes в плоский формат")
    return flat_workflow

def queue_prompt(prompt):
    """Отправляет промпт в очередь ComfyUI"""
    p = {"prompt": prompt}
    data = json.dumps(p).encode('utf-8')
    
    # Логируем, что отправляем (первые 2000 символов)
    prompt_str = json.dumps(prompt, indent=2)
    print(f"📤 Отправляю в ComfyUI /prompt (первые 2000 символов):")
    print(prompt_str[:2000])
    
    # Проверяем наличие узлов KSamplerAdvanced в отправляемом workflow
    if isinstance(prompt, dict):
        ksample_nodes = []
        for node_id, node_data in prompt.items():
            if isinstance(node_data, dict) and node_data.get("class_type") == "KSamplerAdvanced":
                ksample_nodes.append(node_id)
                inputs = node_data.get("inputs", {})
                sampler = inputs.get("sampler_name", "unknown")
                scheduler = inputs.get("scheduler", "unknown")
                seed = inputs.get("noise_seed", "unknown")
                print(f"   Узел {node_id}: sampler={sampler}, scheduler={scheduler}, seed={seed}")
        
        if ksample_nodes:
            print(f"✅ Найдены узлы KSamplerAdvanced: {ksample_nodes}")
        else:
            print("⚠️ Узлы KSamplerAdvanced НЕ найдены в workflow!")
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
        seed_updated = False
        
        # Обновляем noise_seed в KSamplerAdvanced узлах (теперь это прямое значение, не ссылка)
        for node_id, node_data in workflow.items():
            if isinstance(node_data, dict) and node_data.get("class_type") == "KSamplerAdvanced":
                if "inputs" in node_data and "noise_seed" in node_data["inputs"]:
                    workflow[node_id]["inputs"]["noise_seed"] = seed_value
                    print(f"✅ Noise seed обновлен в узле KSamplerAdvanced '{node_id}': {seed_value}")
                    seed_updated = True
        
        if not seed_updated:
            print(f"⚠️ Не удалось найти узел для обновления seed")

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
        seed_updated = False
        
        # Ищем все узлы KSamplerAdvanced и обновляем noise_seed
        for node in nodes:
            if node.get("type") == "KSamplerAdvanced":
                if "inputs" in node and "noise_seed" in node["inputs"]:
                    node["inputs"]["noise_seed"] = seed_value
                    print(f"✅ Seed обновлен в узле KSamplerAdvanced (ID: {node.get('id')}): {seed_value}")
                    seed_updated = True
        
        # Если не нашли KSamplerAdvanced, ищем узел с seed/noise_seed в inputs
        if not seed_updated:
            for node in nodes:
                if "inputs" in node:
                    if "noise_seed" in node["inputs"]:
                        node["inputs"]["noise_seed"] = seed_value
                        print(f"✅ Seed (noise_seed) обновлен в узле '{node.get('id')}': {seed_value}")
                        seed_updated = True
                        break
                    elif "seed" in node["inputs"]:
                        node["inputs"]["seed"] = seed_value
                        print(f"✅ Seed обновлен в узле '{node.get('id')}': {seed_value}")
                        seed_updated = True
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
    # Обновляем текст для озвучки (PrimitiveNode с типом STRING)
    text_to_speak = None
    if "text" in params or "prompt" in params:
        text_to_speak = params.get("text") or params.get("prompt", "")
        for node in nodes:
            # Ищем PrimitiveNode с выходом STRING (это узел для ввода текста)
            if node.get("type") == "PrimitiveNode":
                # Проверяем, что это узел для текста (есть выход STRING)
                outputs = node.get("outputs", [])
                if any(output.get("type") == "STRING" for output in outputs):
                    if "widgets_values" in node and len(node["widgets_values"]) > 0:
                        node["widgets_values"][0] = text_to_speak
                        print(f"✅ Текст для озвучки обновлен в узле '{node.get('id')}': {text_to_speak[:100]}...")
                        break
    
    # Вычисляем max_new_tokens на основе длины текста (если текст есть)
    calculated_tokens = None
    if text_to_speak:
        text_length = len(text_to_speak)
        # Минимум 256 (требование модели), максимум 512 для коротких сообщений
        calculated_tokens = max(256, min(512, int(text_length / 4 * 1.5)))
        print(f"📊 Длина текста: {text_length} символов, вычислен max_new_tokens: {calculated_tokens}")
    
    # Обновляем параметры голоса (gender, style, description) для AILab_Qwen3TTSVoiceInstruct
    if "voice_gender" in params or "voice_style" in params or "voice_description" in params:
        for node in nodes:
            if node.get("type") == "AILab_Qwen3TTSVoiceInstruct":
                widgets = node.get("widgets_values", [])
                if len(widgets) >= 1 and "voice_gender" in params:
                    widgets[0] = params["voice_gender"]
                if len(widgets) >= 2 and "voice_style" in params:
                    widgets[1] = params["voice_style"]
                if len(widgets) >= 3 and "voice_description" in params:
                    widgets[2] = params["voice_description"]
                node["widgets_values"] = widgets
                print(f"✅ Параметры голоса обновлены в узле '{node.get('id')}'")
                break
    
    # Обновляем max_new_tokens и seed для AILab_Qwen3TTSVoiceDesign_Advanced
    if calculated_tokens is not None:
        # Фиксированный seed для стабильного голоса
        fixed_seed = 42  # Всегда один и тот же голос
        for node in nodes:
            if node.get("type") == "AILab_Qwen3TTSVoiceDesign_Advanced":
                widgets = node.get("widgets_values", [])
                # widgets_values[6] = max_new_tokens (индекс 6 согласно порядку в workflow)
                if len(widgets) >= 7:
                    widgets[6] = calculated_tokens
                    node["widgets_values"] = widgets
                    print(f"✅ max_new_tokens обновлен в узле '{node.get('id')}': {calculated_tokens}")
                # widgets_values[14] = seed (индекс 14 согласно порядку в workflow)
                if len(widgets) >= 15:
                    widgets[14] = fixed_seed
                    node["widgets_values"] = widgets
                    print(f"✅ Seed зафиксирован в узле '{node.get('id')}': {fixed_seed}")
                break
    
    # Обновляем другие параметры универсально
    for param_key, param_value in params.items():
        if param_key in ["prompt", "text", "voice_gender", "voice_style", "voice_description"]:
            continue  # Уже обработали
        # Ищем узлы с этим параметром в inputs или widgets_values
        for node in nodes:
            if "inputs" in node and param_key in node["inputs"]:
                node["inputs"][param_key] = param_value
                print(f"✅ Параметр '{param_key}' обновлен в узле '{node.get('id')}': {param_value}")
                break

def check_comfyui_server():
    """Проверяет доступность ComfyUI сервера"""
    try:
        response = requests.get(f"{COMFYUI_URL}/system_stats", timeout=5)
        return response.status_code == 200
    except Exception:
        return False

def check_custom_nodes():
    """Проверяет, какие custom nodes загружены в ComfyUI"""
    try:
        response = requests.get(f"{COMFYUI_URL}/object_info", timeout=10)
        if response.status_code == 200:
            object_info = response.json()
            
            # Логируем структуру object_info
            print(f"📊 Структура object_info: {type(object_info)}")
            if isinstance(object_info, dict):
                all_node_types = list(object_info.keys())
                print(f"   Доступные типы узлов (первые 50): {all_node_types[:50]}")
                
                # Проверяем наличие KSamplerAdvanced
                if "KSamplerAdvanced" in all_node_types:
                    print(f"✅ Узел 'KSamplerAdvanced' найден в object_info")
                    
                    # Проверяем параметры KSamplerAdvanced
                    ksampler_info = object_info.get("KSamplerAdvanced", {})
                    input_info = ksampler_info.get("input", {})
                    
                    # Проверяем доступные sampler_name
                    sampler_required = input_info.get("sampler_name", {})
                    if isinstance(sampler_required, list) and len(sampler_required) > 0:
                        samplers = sampler_required[0].get("list", [])
                        print(f"   Доступные samplers (первые 20): {samplers[:20]}")
                        if "res_2s" in samplers:
                            print(f"   ✅ Sampler 'res_2s' найден!")
                        else:
                            print(f"   ⚠️ Sampler 'res_2s' НЕ найден!")
                    
                    # Проверяем доступные scheduler
                    scheduler_required = input_info.get("scheduler", {})
                    if isinstance(scheduler_required, list) and len(scheduler_required) > 0:
                        schedulers = scheduler_required[0].get("list", [])
                        print(f"   Доступные schedulers (первые 20): {schedulers[:20]}")
                        if "beta57" in schedulers:
                            print(f"   ✅ Scheduler 'beta57' найден!")
                        else:
                            print(f"   ⚠️ Scheduler 'beta57' НЕ найден!")
                    
                    return True
                else:
                    print(f"⚠️ Узел 'KSamplerAdvanced' НЕ найден в object_info")
                    # Ищем похожие названия
                    similar = [t for t in all_node_types if "sampler" in t.lower() or "ksample" in t.lower()]
                    if similar:
                        print(f"   Похожие узлы: {similar}")
                    return False
            return False
        else:
            print(f"⚠️ object_info вернул статус {response.status_code}")
            return False
    except Exception as e:
        print(f"⚠️ Ошибка проверки custom nodes: {e}")
        import traceback
        traceback.print_exc()
        return False

def handler(job):
    """
    Handler для RunPod Serverless
    ComfyUI должен быть уже запущен через start.sh скрипт
    """
    try:
        # Проверяем тип job - может быть строкой JSON
        if isinstance(job, str):
            try:
                job = json.loads(job)
                print("✅ job был строкой, распарсен в dict")
            except json.JSONDecodeError as e:
                print(f"❌ Ошибка парсинга job как JSON строки: {e}")
                return {
                    "error": f"Неверный формат job (ожидается dict или JSON строка): {str(e)}"
                }
        
        if not isinstance(job, dict):
            return {
                "error": f"Неверный тип job: ожидается dict, получен {type(job)}"
            }
        
        # Проверяем, что ComfyUI доступен
        if not check_comfyui_server():
            return {
                "error": "ComfyUI сервер недоступен. Убедитесь, что ComfyUI запущен."
            }
        
        print("✅ ComfyUI сервер доступен")
        
        # Проверяем, что custom nodes загружены
        print("🔍 Проверяю наличие custom nodes через object_info...")
        check_custom_nodes()
        
        # Получаем данные из запроса
        try:
            # Логируем job без изображений (они могут быть очень большими)
            job_for_log = {}
            if isinstance(job, dict):
                job_for_log = job.copy()
                if "input" in job_for_log and isinstance(job_for_log["input"], dict):
                    input_copy = job_for_log["input"].copy()
                    if "images" in input_copy:
                        images_count = len(input_copy["images"]) if isinstance(input_copy["images"], list) else 0
                        input_copy["images"] = f"[{images_count} изображений, скрыто для логов]"
                    job_for_log["input"] = input_copy
            print(f"📥 Получен job: {json.dumps(job_for_log, indent=2)[:1000]}")
        except Exception as e:
            print(f"⚠️ Ошибка логирования job: {e}")
            print(f"📥 Получен job (тип: {type(job)})")
        
        input_data = job.get("input", {})
        
        if not isinstance(input_data, dict):
            return {
                "error": f"Неверный тип input_data: ожидается dict, получен {type(input_data)}"
            }
        
        # Логируем input_data без изображений
        try:
            input_data_for_log = {}
            if isinstance(input_data, dict):
                input_data_for_log = input_data.copy()
                if "images" in input_data_for_log:
                    images_count = len(input_data_for_log["images"]) if isinstance(input_data_for_log["images"], list) else 0
                    input_data_for_log["images"] = f"[{images_count} изображений, скрыто для логов]"
            print(f"📥 input_data: {json.dumps(input_data_for_log, indent=2)[:1000]}")
        except Exception as e:
            print(f"⚠️ Ошибка логирования input_data: {e}")
            print(f"📥 input_data (тип: {type(input_data)})")
        
        workflow_type = input_data.get("workflow", "photo")  # photo, video, voice
        workflow_params = input_data.get("params", {})
        input_images = input_data.get("images", [])  # Массив входных изображений для video workflow
        
        # Инициализируем uploaded_filenames заранее, чтобы она была доступна во всех ветках
        uploaded_filenames = []
        
        if input_images:
            print(f"📸 Получено {len(input_images)} входных изображений для обработки")
        
        print(f"📋 Тип workflow: {workflow_type}")
        print(f"📋 Получены параметры: {list(workflow_params.keys())}")
        print(f"📋 Значения параметров: {workflow_params}")
        
        # Проверяем наличие необходимых узлов для конкретного типа workflow
        print(f"🔍 Проверяю наличие необходимых узлов для {workflow_type} workflow...")
        try:
            response = requests.get(f"{COMFYUI_URL}/object_info", timeout=10)
            if response.status_code == 200:
                object_info = response.json()
                all_node_types = list(object_info.keys())
                
                # Определяем необходимые узлы в зависимости от типа workflow
                required_nodes = []
                
                if workflow_type == "video":
                    required_nodes = ["PathchSageAttentionKJ", "KSamplerAdvanced", "EmptyHunyuanLatentVideo", "WanImageToVideo"]
                elif workflow_type == "voice":
                    required_nodes = ["AILab_Qwen3TTSVoiceInstruct", "AILab_Qwen3TTSVoiceDesign_Advanced", "SaveAudio", "PreviewAudio"]
                    # PrimitiveNode опционален - если его нет, текст передадим напрямую в AILab_Qwen3TTSVoiceDesign_Advanced
                else:  # photo
                    required_nodes = ["PathchSageAttentionKJ", "KSamplerAdvanced", "EmptyHunyuanLatentVideo"]
                
                missing_nodes = []
                for node_type in required_nodes:
                    if node_type not in all_node_types:
                        missing_nodes.append(node_type)
                
                if missing_nodes:
                    print(f"⚠️ Отсутствуют необходимые узлы для {workflow_type} workflow: {missing_nodes}")
                    print(f"   Доступные узлы (первые 100): {all_node_types[:100]}")
                    # Ищем похожие названия для QwenTTS
                    if workflow_type == "voice":
                        qwen_nodes = [t for t in all_node_types if "qwen" in t.lower() or "tts" in t.lower() or "voice" in t.lower()]
                        if qwen_nodes:
                            print(f"   Найдены похожие узлы (QwenTTS): {qwen_nodes}")
                    return {
                        "error": f"Отсутствуют необходимые custom nodes для {workflow_type} workflow: {', '.join(missing_nodes)}. Убедитесь, что все custom nodes установлены и загружены. ComfyUI-QwenTTS должен быть установлен для voice workflow. Пересоберите Docker образ с обновленным Dockerfile."
                    }
                else:
                    print(f"✅ Все необходимые узлы для {workflow_type} workflow найдены: {required_nodes}")
        except Exception as e:
            print(f"⚠️ Ошибка проверки узлов: {e}")
            # Продолжаем выполнение, так как это только предупреждение
        
        # Загружаем workflow
        workflow_path = f"{COMFYUI_DIR}/workflows/{workflow_type}.json"
        if not os.path.exists(workflow_path):
            return {
                "error": f"Workflow {workflow_type}.json не найден"
            }
        
        with open(workflow_path, 'r', encoding='utf-8') as f:
            workflow_data = json.load(f)
        
        # Определяем формат workflow (с nodes или без)
        if "nodes" in workflow_data:
            # Работаем с форматом nodes
            workflow_with_nodes = json.loads(json.dumps(workflow_data))  # Глубокая копия
            
            # Применяем параметры напрямую к nodes
            if workflow_type == "video":
                apply_video_params_to_nodes(workflow_with_nodes["nodes"], workflow_params)
            elif workflow_type == "voice":
                apply_voice_params_to_nodes(workflow_with_nodes["nodes"], workflow_params)
            else:
                apply_photo_params_to_nodes(workflow_with_nodes["nodes"], workflow_params)
            
            # Конвертируем в плоский формат для ComfyUI API
            print(f"🔄 Конвертирую workflow из формата с nodes в плоский формат...")
            workflow_to_send = convert_nodes_to_flat_format(workflow_with_nodes)
            
            # Если PrimitiveNode был пропущен, передаем текст напрямую в узлы, которые на него ссылаются
            if workflow_type == "voice":
                # Собираем текст из всех PrimitiveNode, которые были пропущены
                primitive_texts = {}
                for node in workflow_with_nodes["nodes"]:
                    if node.get("type") == "PrimitiveNode" and "_text_value" in node:
                        node_id = str(node.get("id"))
                        primitive_texts[node_id] = node["_text_value"]
                
                # Если есть текст из workflow_params, используем его
                if "text" in workflow_params:
                    text_to_speak = workflow_params.get("text", "")
                elif primitive_texts:
                    # Используем первый найденный текст из PrimitiveNode
                    text_to_speak = list(primitive_texts.values())[0]
                else:
                    text_to_speak = None
                
                if text_to_speak:
                    # Вычисляем max_new_tokens на основе длины текста
                    # Примерно 1 токен = 4 символа, умножаем на 1.5 для запаса
                    # Минимум 256 (требование модели), максимум 512 для коротких сообщений
                    text_length = len(text_to_speak)
                    calculated_tokens = max(256, min(512, int(text_length / 4 * 1.5)))
                    print(f"📊 Длина текста: {text_length} символов, вычислен max_new_tokens: {calculated_tokens}")
                    
                    # Фиксированный seed для стабильного голоса
                    fixed_seed = 42  # Всегда один и тот же голос
                    
                    # Ищем все узлы AILab_Qwen3TTSVoiceDesign_Advanced и передаем текст напрямую
                    for node_id, node_data in workflow_to_send.items():
                        if isinstance(node_data, dict):
                            class_type = node_data.get("class_type", "")
                            # Для AILab_Qwen3TTSVoiceDesign_Advanced обязательно устанавливаем text из параметров
                            if class_type == "AILab_Qwen3TTSVoiceDesign_Advanced":
                                inputs = node_data.get("inputs", {})
                                # Убеждаемся, что text установлен из параметров, а не из плейсхолдера
                                if "text" in inputs:
                                    # Если text - это ссылка на несуществующий узел, заменяем на прямой текст
                                    text_input = inputs.get("text")
                                    if isinstance(text_input, list) and len(text_input) >= 1:
                                        ref_node_id = str(text_input[0])
                                        if ref_node_id not in workflow_to_send or ref_node_id in primitive_texts:
                                            node_data["inputs"]["text"] = text_to_speak
                                            print(f"✅ Текст передан напрямую в AILab_Qwen3TTSVoiceDesign_Advanced (узел {node_id}): {text_to_speak[:50]}...")
                                    elif isinstance(text_input, str) and len(text_input) > 200:
                                        # Если text слишком длинный (плейсхолдер), заменяем на реальный текст
                                        node_data["inputs"]["text"] = text_to_speak
                                        print(f"✅ Текст заменен в AILab_Qwen3TTSVoiceDesign_Advanced (узел {node_id}): {text_to_speak[:50]}...")
                                else:
                                    # Если text не установлен, устанавливаем из параметров
                                    node_data["inputs"]["text"] = text_to_speak
                                    print(f"✅ Текст установлен в AILab_Qwen3TTSVoiceDesign_Advanced (узел {node_id}): {text_to_speak[:50]}...")
                                
                                # Обновляем max_new_tokens на основе длины текста
                                if "max_new_tokens" in inputs:
                                    node_data["inputs"]["max_new_tokens"] = calculated_tokens
                                    print(f"✅ max_new_tokens обновлен в AILab_Qwen3TTSVoiceDesign_Advanced (узел {node_id}): {calculated_tokens}")
                                
                                # Фиксируем seed для стабильного голоса
                                if "seed" in inputs:
                                    node_data["inputs"]["seed"] = fixed_seed
                                    print(f"✅ Seed зафиксирован в AILab_Qwen3TTSVoiceDesign_Advanced (узел {node_id}): {fixed_seed}")
                            else:
                                # Для других узлов проверяем связи на PrimitiveNode
                                inputs = node_data.get("inputs", {})
                                for input_name, input_value in inputs.items():
                                    if isinstance(input_value, list) and len(input_value) >= 1:
                                        ref_node_id = str(input_value[0])
                                        # Если это ссылка на пропущенный PrimitiveNode, заменяем на прямой текст
                                        if ref_node_id in primitive_texts:
                                            node_data["inputs"][input_name] = primitive_texts[ref_node_id]
                                            print(f"✅ Текст передан напрямую в {class_type} (узел {node_id}, вход {input_name}): {primitive_texts[ref_node_id][:50]}...")
                                        # Также проверяем, если это ссылка на несуществующий узел (PrimitiveNode)
                                        elif ref_node_id not in workflow_to_send and input_name == "text":
                                            node_data["inputs"][input_name] = text_to_speak
                                            print(f"✅ Текст передан напрямую в {class_type} (узел {node_id}): {text_to_speak[:50]}...")
            
            print(f"📤 Отправляю workflow в ComfyUI (узлов: {len(workflow_to_send)})")
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
                node_ids_in_workflow = {str(node.get("id")) for node in workflow_to_send.get("nodes", [])}
                print(f"📋 Workflow содержит {len(workflow_to_send.get('nodes', []))} узлов")
                
                ksample_nodes = [node for node in workflow_to_send.get("nodes", []) if node.get("type") == "KSamplerAdvanced"]
                if ksample_nodes:
                    print(f"✅ Найдены узлы KSamplerAdvanced: {[n.get('id') for n in ksample_nodes]}")
            else:
                node_ids_in_workflow = set(workflow_to_send.keys())
                print(f"📋 Workflow содержит {len(workflow_to_send)} узлов")
                
                ksample_nodes = [k for k, v in workflow_to_send.items() if isinstance(v, dict) and v.get("class_type") == "KSamplerAdvanced"]
                if ksample_nodes:
                    print(f"✅ Найдены узлы KSamplerAdvanced: {ksample_nodes}")
                    first_node_id = ksample_nodes[0]
                    node_data = workflow_to_send[first_node_id]
                    noise_seed = node_data.get('inputs', {}).get('noise_seed', 'not found')
                    print(f"   Узел {first_node_id}: noise_seed={noise_seed}")
        
        # Обрабатываем входные изображения для video workflow
        if workflow_type == "video" and input_images:
            print(f"📸 Обрабатываю {len(input_images)} входных изображений для video workflow...")
            # uploaded_filenames уже инициализирована выше
            
            for idx, image_data in enumerate(input_images):
                image_name = image_data.get("name", f"input_image_{idx}.png")
                image_base64 = image_data.get("image", "")
                
                # Удаляем data URI prefix если есть
                if image_base64.startswith("data:image"):
                    image_base64 = image_base64.split(",")[1]
                
                # Декодируем base64
                try:
                    image_bytes = base64.b64decode(image_base64)
                    print(f"✅ Изображение {idx + 1} декодировано, размер: {len(image_bytes)} байт")
                    
                    # Загружаем изображение в ComfyUI через /upload/image endpoint
                    files = {
                        'image': (image_name, image_bytes, 'image/png')
                    }
                    upload_response = requests.post(f"{COMFYUI_URL}/upload/image", files=files)
                    
                    if upload_response.status_code == 200:
                        try:
                            # Проверяем, что ответ - это JSON
                            content_type = upload_response.headers.get('content-type', '')
                            if 'application/json' in content_type:
                                upload_result = upload_response.json()
                                uploaded_filename = upload_result.get("name", image_name)
                                uploaded_filenames.append(uploaded_filename)
                                print(f"✅ Изображение {idx + 1} загружено: {uploaded_filename}")
                            else:
                                # Если не JSON, пробуем извлечь имя файла из ответа
                                response_text = upload_response.text
                                print(f"⚠️ Ответ от /upload/image не JSON, content-type: {content_type}")
                                print(f"   Ответ (первые 200 символов): {response_text[:200]}")
                                # Используем оригинальное имя
                                uploaded_filenames.append(image_name)
                                print(f"✅ Использую оригинальное имя файла: {image_name}")
                        except json.JSONDecodeError as e:
                            print(f"⚠️ Ошибка парсинга JSON ответа от /upload/image: {e}")
                            print(f"   Ответ (первые 200 символов): {upload_response.text[:200]}")
                            # Используем оригинальное имя
                            uploaded_filenames.append(image_name)
                            print(f"✅ Использую оригинальное имя файла: {image_name}")
                    else:
                        print(f"⚠️ Ошибка загрузки изображения {idx + 1}: {upload_response.status_code}")
                        print(f"   Ответ: {upload_response.text[:200]}")
                        uploaded_filenames.append(image_name)  # Используем оригинальное имя
                except Exception as e:
                    print(f"⚠️ Ошибка обработки изображения {idx + 1}: {e}")
                    uploaded_filenames.append(image_name)
            
        # Определяем формат workflow (с nodes или без)
        if "nodes" in workflow_data:
            # Работаем с форматом nodes
            workflow_with_nodes = json.loads(json.dumps(workflow_data))  # Глубокая копия
            
            # Обновляем LoadImage узлы с загруженными именами файлов ПЕРЕД конвертацией
            if uploaded_filenames:
                print(f"📝 Обновляю LoadImage узлы в nodes формате с именами файлов: {uploaded_filenames}")
                for node in workflow_with_nodes["nodes"]:
                    if node.get("type") == "LoadImage":
                        if node.get("widgets_values") and len(node["widgets_values"]) > 0:
                            node["widgets_values"][0] = uploaded_filenames[0]
                            print(f"✅ LoadImage узел {node.get('id')} обновлен: {uploaded_filenames[0]}")
                        else:
                            # Если widgets_values нет, создаем его
                            node["widgets_values"] = [uploaded_filenames[0], "image"]
                            print(f"✅ LoadImage узел {node.get('id')} обновлен (создан widgets_values): {uploaded_filenames[0]}")
            
            # Применяем параметры напрямую к nodes
            if workflow_type == "video":
                apply_video_params_to_nodes(workflow_with_nodes["nodes"], workflow_params)
            elif workflow_type == "voice":
                apply_voice_params_to_nodes(workflow_with_nodes["nodes"], workflow_params)
            else:
                apply_photo_params_to_nodes(workflow_with_nodes["nodes"], workflow_params)
            
            # Конвертируем в плоский формат для ComfyUI API
            print(f"🔄 Конвертирую workflow из формата с nodes в плоский формат...")
            workflow_to_send = convert_nodes_to_flat_format(workflow_with_nodes)
            
            # Если PrimitiveNode был пропущен, передаем текст напрямую в узлы, которые на него ссылаются
            if workflow_type == "voice":
                # Собираем текст из всех PrimitiveNode, которые были пропущены
                primitive_texts = {}
                for node in workflow_with_nodes["nodes"]:
                    if node.get("type") == "PrimitiveNode" and "_text_value" in node:
                        node_id = str(node.get("id"))
                        primitive_texts[node_id] = node["_text_value"]
                
                # Если есть текст из workflow_params, используем его
                if "text" in workflow_params:
                    text_to_speak = workflow_params.get("text", "")
                elif primitive_texts:
                    # Используем первый найденный текст из PrimitiveNode
                    text_to_speak = list(primitive_texts.values())[0]
                else:
                    text_to_speak = None
                
                if text_to_speak:
                    # Вычисляем max_new_tokens на основе длины текста
                    # Примерно 1 токен = 4 символа, умножаем на 1.5 для запаса
                    # Минимум 256 (требование модели), максимум 512 для коротких сообщений
                    text_length = len(text_to_speak)
                    calculated_tokens = max(256, min(512, int(text_length / 4 * 1.5)))
                    print(f"📊 Длина текста: {text_length} символов, вычислен max_new_tokens: {calculated_tokens}")
                    
                    # Фиксированный seed для стабильного голоса
                    fixed_seed = 42  # Всегда один и тот же голос
                    
                    # Ищем все узлы AILab_Qwen3TTSVoiceDesign_Advanced и передаем текст напрямую
                    for node_id, node_data in workflow_to_send.items():
                        if isinstance(node_data, dict):
                            class_type = node_data.get("class_type", "")
                            # Для AILab_Qwen3TTSVoiceDesign_Advanced обязательно устанавливаем text из параметров
                            if class_type == "AILab_Qwen3TTSVoiceDesign_Advanced":
                                inputs = node_data.get("inputs", {})
                                # Убеждаемся, что text установлен из параметров, а не из плейсхолдера
                                if "text" in inputs:
                                    # Если text - это ссылка на несуществующий узел, заменяем на прямой текст
                                    text_input = inputs.get("text")
                                    if isinstance(text_input, list) and len(text_input) >= 1:
                                        ref_node_id = str(text_input[0])
                                        if ref_node_id not in workflow_to_send or ref_node_id in primitive_texts:
                                            node_data["inputs"]["text"] = text_to_speak
                                            print(f"✅ Текст передан напрямую в AILab_Qwen3TTSVoiceDesign_Advanced (узел {node_id}): {text_to_speak[:50]}...")
                                    elif isinstance(text_input, str) and len(text_input) > 200:
                                        # Если text слишком длинный (плейсхолдер), заменяем на реальный текст
                                        node_data["inputs"]["text"] = text_to_speak
                                        print(f"✅ Текст заменен в AILab_Qwen3TTSVoiceDesign_Advanced (узел {node_id}): {text_to_speak[:50]}...")
                                else:
                                    # Если text не установлен, устанавливаем из параметров
                                    node_data["inputs"]["text"] = text_to_speak
                                    print(f"✅ Текст установлен в AILab_Qwen3TTSVoiceDesign_Advanced (узел {node_id}): {text_to_speak[:50]}...")
                                
                                # Обновляем max_new_tokens на основе длины текста
                                if "max_new_tokens" in inputs:
                                    node_data["inputs"]["max_new_tokens"] = calculated_tokens
                                    print(f"✅ max_new_tokens обновлен в AILab_Qwen3TTSVoiceDesign_Advanced (узел {node_id}): {calculated_tokens}")
                                
                                # Фиксируем seed для стабильного голоса
                                if "seed" in inputs:
                                    node_data["inputs"]["seed"] = fixed_seed
                                    print(f"✅ Seed зафиксирован в AILab_Qwen3TTSVoiceDesign_Advanced (узел {node_id}): {fixed_seed}")
                            else:
                                # Для других узлов проверяем связи на PrimitiveNode
                                inputs = node_data.get("inputs", {})
                                for input_name, input_value in inputs.items():
                                    if isinstance(input_value, list) and len(input_value) >= 1:
                                        ref_node_id = str(input_value[0])
                                        # Если это ссылка на пропущенный PrimitiveNode, заменяем на прямой текст
                                        if ref_node_id in primitive_texts:
                                            node_data["inputs"][input_name] = primitive_texts[ref_node_id]
                                            print(f"✅ Текст передан напрямую в {class_type} (узел {node_id}, вход {input_name}): {primitive_texts[ref_node_id][:50]}...")
                                        # Также проверяем, если это ссылка на несуществующий узел (PrimitiveNode)
                                        elif ref_node_id not in workflow_to_send and input_name == "text":
                                            node_data["inputs"][input_name] = text_to_speak
                                            print(f"✅ Текст передан напрямую в {class_type} (узел {node_id}): {text_to_speak[:50]}...")
            
            print(f"📤 Отправляю workflow в ComfyUI (узлов: {len(workflow_to_send)})")
        else:
            # Плоский формат - работаем напрямую
            workflow_to_send = json.loads(json.dumps(workflow_data))  # Глубокая копия
            
            # Обновляем LoadImage узлы с загруженными именами файлов
            if uploaded_filenames:
                print(f"📝 Обновляю LoadImage узлы в плоском формате с именами файлов: {uploaded_filenames}")
                for node_id, node_data in workflow_to_send.items():
                    if isinstance(node_data, dict) and node_data.get("class_type") == "LoadImage":
                        if "widgets_values" in node_data and len(node_data["widgets_values"]) > 0:
                            node_data["widgets_values"][0] = uploaded_filenames[0]
                            print(f"✅ LoadImage узел {node_id} обновлен: {uploaded_filenames[0]}")
                        else:
                            # Если widgets_values нет, создаем его
                            node_data["widgets_values"] = [uploaded_filenames[0], "image"]
                            print(f"✅ LoadImage узел {node_id} обновлен (создан widgets_values): {uploaded_filenames[0]}")
            
            # Применяем параметры к workflow в зависимости от типа
            if workflow_type == "video":
                apply_video_params(workflow_to_send, workflow_params)
            elif workflow_type == "voice":
                apply_voice_params(workflow_to_send, workflow_params)
            else:
                apply_photo_params(workflow_to_send, workflow_params)
            
            print(f"📤 Отправляю workflow в ComfyUI (узлов: {len(workflow_to_send)})")
        
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
        max_wait = 900  # 15 минут максимум (для больших моделей с компиляцией)
        start_time = time.time()
        
        while time.time() - start_time < max_wait:
            history = get_history(prompt_id)
            
            if prompt_id in history:
                history_data = history[prompt_id]
                status = history_data.get("status", {})
                
                if status.get("completed"):
                    # Генерация завершена
                    outputs = history_data.get("outputs", {})
                    print(f"📊 Получены outputs от ComfyUI, количество узлов: {len(outputs)}")
                    print(f"📊 Ключи outputs: {list(outputs.keys())}")
                    
                    files = []
                    
                    # Собираем все файлы (изображения, видео, аудио)
                    for node_id, node_output in outputs.items():
                        print(f"🔍 Обрабатываю узел {node_id}, ключи: {list(node_output.keys())}")
                        
                        # Изображения (могут быть видео, если есть поле animated или расширение .mp4/.webm)
                        if "images" in node_output:
                            print(f"  📸 Найдены изображения в узле {node_id}: {len(node_output['images'])} шт.")
                            # Проверяем, есть ли поле animated (указывает на видео)
                            is_animated = node_output.get("animated", False)
                            
                            for image_info in node_output["images"]:
                                filename = image_info["filename"]
                                subfolder = image_info.get("subfolder", "")
                                folder_type = image_info.get("type", "output")
                                
                                # Определяем тип файла по расширению или полю animated
                                file_type = "image"
                                if is_animated or filename.lower().endswith(('.mp4', '.webm', '.mov', '.avi', '.mkv')):
                                    file_type = "video"
                                    print(f"    🎬 Определено как видео (animated={is_animated}, расширение={filename.split('.')[-1]})")
                                
                                print(f"    📥 Загружаю файл: {filename} (subfolder: {subfolder}, type: {folder_type}, file_type: {file_type})")
                                file_data = get_image(filename, subfolder, folder_type)
                                file_base64 = base64.b64encode(file_data).decode('utf-8')
                                files.append({
                                    "filename": filename,
                                    "data": file_base64,
                                    "type": file_type
                                })
                                print(f"    ✅ Файл добавлен как {file_type}, размер base64: {len(file_base64)} символов")
                        
                        # Видео
                        if "videos" in node_output:
                            print(f"  🎬 Найдены видео в узле {node_id}: {len(node_output['videos'])} шт.")
                            for video_info in node_output["videos"]:
                                filename = video_info["filename"]
                                subfolder = video_info.get("subfolder", "")
                                folder_type = video_info.get("type", "output")
                                
                                print(f"    📥 Загружаю видео: {filename} (subfolder: {subfolder}, type: {folder_type})")
                                file_data = get_image(filename, subfolder, folder_type)
                                file_base64 = base64.b64encode(file_data).decode('utf-8')
                                files.append({
                                    "filename": filename,
                                    "data": file_base64,
                                    "type": "video"
                                })
                                print(f"    ✅ Видео добавлено, размер base64: {len(file_base64)} символов")
                        
                        # Аудио
                        if "audio" in node_output:
                            print(f"  🎵 Найдено аудио в узле {node_id}")
                            audio_info = node_output["audio"]
                            
                            # audio может быть списком или словарем
                            if isinstance(audio_info, list):
                                # Если это список, берем первый элемент
                                if len(audio_info) > 0:
                                    audio_info = audio_info[0]
                                else:
                                    print(f"    ⚠️ Список audio пуст, пропускаю")
                                    continue
                            
                            # Проверяем, что audio_info - словарь
                            if not isinstance(audio_info, dict):
                                print(f"    ⚠️ audio_info не является словарем: {type(audio_info)}, пропускаю")
                                continue
                            
                            filename = audio_info.get("filename") or audio_info.get("name")
                            if not filename:
                                print(f"    ⚠️ Не удалось найти filename в audio_info: {audio_info}")
                                continue
                            
                            subfolder = audio_info.get("subfolder", "")
                            folder_type = audio_info.get("type", "output")
                            
                            print(f"    📥 Загружаю аудио: {filename} (subfolder: {subfolder}, type: {folder_type})")
                            file_data = get_image(filename, subfolder, folder_type)
                            file_base64 = base64.b64encode(file_data).decode('utf-8')
                            files.append({
                                "filename": filename,
                                "data": file_base64,
                                "type": "audio"
                            })
                            print(f"    ✅ Аудио добавлено, размер base64: {len(file_base64)} символов")
                    
                    print(f"✅ Генерация завершена успешно, собрано файлов: {len(files)}")
                    if files:
                        for idx, file_info in enumerate(files):
                            print(f"  Файл {idx + 1}: {file_info['filename']}, тип: {file_info['type']}, размер base64: {len(file_info['data'])} символов")
                    else:
                        print("⚠️ ВНИМАНИЕ: Файлы не найдены в outputs!")
                        print(f"📋 Полный outputs для отладки: {json.dumps(outputs, indent=2)[:2000]}")
                    
                    return {
                        "status": "completed",
                        "prompt_id": prompt_id,
                        "files": files,
                        "images": files,  # Для обратной совместимости
                        "outputs": outputs
                    }
                
                if status.get("failed"):
                    # Генерация провалилась
                    error_msg = status.get("error", "Неизвестная ошибка")
                    print(f"❌ Генерация провалилась: {error_msg}")
                    
                    # Выводим детали ошибки
                    if "node_errors" in history_data:
                        print(f"📋 Ошибки в узлах: {history_data['node_errors']}")
                    
                    return {
                        "status": "failed",
                        "error": error_msg,
                        "details": history_data
                    }
            else:
                # Prompt ID не найден в истории - возможно, еще не начал выполняться
                # Проверяем через /queue
                try:
                    queue_response = requests.get(f"{COMFYUI_URL}/queue")
                    if queue_response.status_code == 200:
                        queue_data = queue_response.json()
                        running = queue_data.get("queue_running", [])
                        pending = queue_data.get("queue_pending", [])
                        
                        # Ищем наш prompt_id в очереди
                        found_in_running = any(item[1] == prompt_id for item in running)
                        found_in_pending = any(item[1] == prompt_id for item in pending)
                        
                        if found_in_running:
                            print(f"🔄 Задача выполняется (в queue_running)")
                        elif found_in_pending:
                            print(f"⏳ Задача в очереди (в queue_pending)")
                        else:
                            print(f"⚠️ Prompt ID {prompt_id} не найден в очереди")
                except Exception as e:
                    print(f"⚠️ Не удалось проверить очередь: {e}")
            
            time.sleep(2)  # Увеличено до 2 секунд, чтобы не перегружать API
        
        # Таймаут
        elapsed_minutes = int((time.time() - start_time) / 60)
        print(f"⏱️ Превышено время ожидания генерации ({elapsed_minutes} минут)")
        
        # Пытаемся получить последний статус перед таймаутом
        try:
            history = get_history(prompt_id)
            if prompt_id in history:
                history_data = history[prompt_id]
                status = history_data.get("status", {})
                print(f"📊 Последний статус: {status}")
        except Exception as e:
            print(f"⚠️ Не удалось получить последний статус: {e}")
        
        return {
            "status": "timeout",
            "error": f"Превышено время ожидания генерации ({elapsed_minutes} минут)",
            "elapsed_seconds": int(time.time() - start_time)
        }
        
    except Exception as e:
        error_type = type(e).__name__
        error_msg = str(e)
        print(f"❌ Критическая ошибка в handler: {error_type}: {error_msg}")
        
        return {
            "error": error_msg,
            "type": error_type,
            "status": "error"
        }

# Запускаем RunPod serverless
if __name__ == "__main__":
    runpod.serverless.start({"handler": handler})
