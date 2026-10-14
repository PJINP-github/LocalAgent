import json
import os
import urllib.request

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_DIR = os.path.join(SCRIPT_DIR, ".local-agent")
CONFIG_PATH = os.path.join(CONFIG_DIR, "config.json")
DEFAULT_MEMORY_PATH = os.path.join(CONFIG_DIR, "memory.json")

DEFAULT_CONFIG = {
    "model": "qwen3.5-9b-8k",
    "memory_path": DEFAULT_MEMORY_PATH,
    "temperature": 0.7,
    "num_ctx": 32768,
    "repeat_penalty": 1.15,
    "num_predict": 3072,
    "think": True,
    "max_tool_rounds": 6,
    "enabled_tools": [
        "list_directory", "read_file", "write_file", "search_files",
        "get_system_info", "list_processes", "run_command",
        "fetch_url", "open_url",
    ],
}


def list_ollama_models():
    try:
        with urllib.request.urlopen("http://127.0.0.1:11434/api/tags", timeout=5) as r:
            data = json.loads(r.read().decode("utf-8"))
            return [m["name"] for m in data.get("models", [])]
    except Exception:
        return []


class ConfigManager:
    def __init__(self, path=CONFIG_PATH):
        self.path = path
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        self.data = self._load()

    def _load(self):
        if os.path.exists(self.path):
            try:
                raw = open(self.path, "r", encoding="utf-8").read()
                raw = raw.lstrip("\ufeff")
                cfg = json.loads(raw)
                merged = dict(DEFAULT_CONFIG)
                merged.update(cfg)
                return merged
            except Exception as e:
                print(f"[警告] 配置文件解析失败：{e}")
        return dict(DEFAULT_CONFIG)

    def save(self):
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False, indent=2)

    def get(self, key, default=None):
        return self.data.get(key, default)

    def set(self, key, value):
        self.data[key] = value

    def show(self):
        lines = ["当前配置："]
        for k, v in self.data.items():
            lines.append(f"  {k} = {v}")
        return "\n".join(lines)


def first_run_setup(config: ConfigManager):
    """首次运行或 /config-edit 时调用，交互式选择模型与参数。"""
    print("\n" + "=" * 60)
    print("  交互式配置向导")
    print("=" * 60)

    models = list_ollama_models()
    if not models:
        print("\n[警告] 未检测到任何 Ollama 模型。")
        print("请先运行 ollama pull <模型名> 拉取模型。")
        print("现在将使用默认配置继续。\n")
        config.save()
        return

    print("\n检测到以下可用模型：")
    for i, m in enumerate(models, 1):
        print(f"  {i}. {m}")

    cur = config.get("model")
    if cur:
        print(f"\n当前：{cur}")

    choice = input("\n请输入模型编号（回车保持当前）：").strip()
    if choice.isdigit():
        idx = int(choice) - 1
        if 0 <= idx < len(models):
            config.set("model", models[idx])

    print(f"\n当前 num_ctx = {config.get('num_ctx')}")
    print("提示：4B/8B 建议 32768 或 65536；9B 及以上建议 16384 或 8192")
    v = input("请输入 num_ctx（回车保持）：").strip()
    if v.isdigit():
        config.set("num_ctx", int(v))

    print(f"\n当前 temperature = {config.get('temperature')}")
    v = input("请输入 temperature（回车保持）：").strip()
    try:
        if v:
            config.set("temperature", float(v))
    except ValueError:
        pass

    print(f"\n当前 think = {config.get('think')}")
    v = input("开启 thinking？(y/n，回车保持)：").strip().lower()
    if v == "y":
        config.set("think", True)
    elif v == "n":
        config.set("think", False)

    config.save()
    print(f"\n配置已保存到：{config.path}\n")