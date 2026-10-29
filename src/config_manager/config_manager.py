from __future__ import annotations
import json
import os
from pathlib import Path

# 路径常量
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_CONFIG_DIR = _PROJECT_ROOT / 'config'
_CONFIG_FILE = _CONFIG_DIR / 'config.json'
_MEMORY_FILE = _CONFIG_DIR / 'memory.json'

DEFAULT_CONFIG = {
    "model": "qwen2.5-coder-8k",
    # Ollama 可执行文件所在目录（也可填完整 exe 路径）。
    # 修改 ollama 安装位置时，只改这里即可：
    #   - start-kurama.ps1 的 Find-OllamaExe 会读它
    #   - src/ollama_manager/ollama_manager.py 的 find_ollama 也会读它
    "ollama_dir": r"C:\software\ollama-windows-amd64",
    "available_models": [
        "qwen2.5-coder-4k",
        "qwen2.5-coder-8k",
        "qwen2.5-coder-16k",
        "qwen2.5-coder-32k",
    ],
    "memory_path": str(_MEMORY_FILE),
    "temperature": 0.7,
    "num_ctx": 32768,
    "repeat_penalty": 1.15,
    "num_predict": 3072,
    "think": False,
    "max_tool_rounds": 6,
    "enabled_tools": [
        "list_directory", "read_file", "write_file", "search_files",
        "get_system_info", "list_processes", "run_command",
        "fetch_url", "open_url",
    ],
}


def list_ollama_models(host: str = "127.0.0.1:11434") -> list:
    """通过 Ollama /api/tags 拉模型名列表。失败返回空列表。"""
    try:
        import requests
    except ImportError:
        return []
    try:
        r = requests.get(f"http://{host}/api/tags", timeout=3)
        r.raise_for_status()
        data = r.json()
        return [m["name"] for m in data.get("models", []) if m.get("name")]
    except Exception:
        return []


class ConfigManager:
    def __init__(self, path=None):
        if path is None:
            path = str(_CONFIG_FILE)
        self.path = path
        self.data = self._load()

    def _load(self) -> dict:
        merged = dict(DEFAULT_CONFIG)
        if os.path.exists(self.path):
            try:
                with open(self.path, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                if isinstance(loaded, dict):
                    merged.update(loaded)
            except Exception:
                pass
        return merged

    def get(self, key, default=None):
        return self.data.get(key, default)

    def set(self, key, value):
        self.data[key] = value

    def save(self):
        d = os.path.dirname(self.path)
        if d:
            os.makedirs(d, exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False, indent=2)

    def show(self) -> str:
        lines = [f"[配置] {self.path}"]
        for k in sorted(self.data.keys()):
            v = self.data[k]
            if isinstance(v, list) and len(v) > 4:
                vs = f"{v[:3]}... ({len(v)} 项)"
            else:
                vs = v
            lines.append(f"  {k} = {vs}")
        return "\n".join(lines)


def first_run_setup(config):
    """交互式向导：选模型。"""
    print("\n[首次配置向导]")
    models = list_ollama_models()
    if models:
        print("  可用 Ollama 模型：")
        for i, m in enumerate(models, 1):
            print(f"    [{i}] {m}")
        try:
            choice = input("  选择编号（直接回车跳过）：").strip()
        except EOFError:
            choice = ""
        if choice.isdigit():
            idx = int(choice) - 1
            if 0 <= idx < len(models):
                config.set("model", models[idx])
                print(f"  [已选择] {models[idx]}")
                config.set("available_models", models)
    else:
        print("  [警告] 无法从 Ollama 拉取模型列表，跳过模型选择")
    config.save()
    print(f"  [已保存] {config.path}\n")