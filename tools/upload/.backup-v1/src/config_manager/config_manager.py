DEFAULT_CONFIG = {
    "model": "qwen2.5-coder-8k",
    # ---- 新增：启动菜单用的模型列表 ----
    "available_models": [
        "qwen2.5-coder-4k",
        "qwen2.5-coder-8k",
        "qwen2.5-coder-16k",
        "qwen2.5-coder-32k",
    ],
    "memory_path": DEFAULT_MEMORY_PATH,
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