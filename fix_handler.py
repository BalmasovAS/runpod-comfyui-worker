#!/usr/bin/env python3
# Исправляем handler.py - заменяем Seed Generator на KSamplerAdvanced

with open('handler.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Простая замена текста функции apply_photo_params_to_nodes
old_apply_photo = '''    # Обновляем seed (если нужно)
    if "seed" in params:
        seed_value = int(params["seed"])
        # Ищем узел "Seed Generator" (из KJNodes)
        seed_updated = False
        for node in nodes:
            if node.get("type") == "Seed Generator":
                if "inputs" in node and "seed" in node["inputs"]:
                    node["inputs"]["seed"] = seed_value
                    print(f"✅ Seed обновлен в узле 'Seed Generator' (ID: {node.get('id')}): {seed_value}")
                    seed_updated = True
                    break
        
        # Если не нашли Seed Generator, ищем узел с seed в inputs
        if not seed_updated:
            for node in nodes:
                if "inputs" in node and "seed" in node["inputs"]:
                    node["inputs"]["seed"] = seed_value
                    print(f"✅ Seed обновлен в узле '{node.get('id')}': {seed_value}")
                    break'''

new_apply_photo = '''    # Обновляем seed (если нужно)
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
        
        # Если не нашли KSamplerAdvanced, ищем узел с seed в inputs
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
                        break'''

if old_apply_photo in content:
    content = content.replace(old_apply_photo, new_apply_photo)
    print("✅ Функция apply_photo_params_to_nodes исправлена")
else:
    print("❌ Не найдена функция apply_photo_params_to_nodes")

# Сохраняем результат
with open('handler.py', 'w', encoding='utf-8') as f:
    f.write(content)

print("✅ handler.py исправлен успешно")
