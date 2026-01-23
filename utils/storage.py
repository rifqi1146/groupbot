import json
import os

def load_json_file(path: str, default):
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default

def save_json_file(path: str, data):
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)

GROUP_FILE = "data/groups.json"

def load_groups():
    if not os.path.exists(GROUP_FILE):
        return {}
    with open(GROUP_FILE, "r") as f:
        return json.load(f)

def save_groups(data):
    os.makedirs(os.path.dirname(GROUP_FILE), exist_ok=True)
    with open(GROUP_FILE, "w") as f:
        json.dump(data, f, indent=2)