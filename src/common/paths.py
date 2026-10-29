from __future__ import annotations

"""统一路径解析。

规则:
  - 相对路径 → 相对项目根（PROJECT_ROOT）
  - 绝对路径 → 原样返回
  - 落盘用相对，消费端 resolve() 成绝对
"""
import os
from pathlib import Path

# src/common/paths.py -> 项目根
PROJECT_ROOT = Path(__file__).resolve().parents[2]

CONFIG_DIR   = PROJECT_ROOT / "config"
CONFIG_FILE  = CONFIG_DIR / "config.json"
MEMORY_FILE  = CONFIG_DIR / "memory.json"
OLLAMA_YAML  = CONFIG_DIR / "ollama.yaml"
SOURCES_DIR  = PROJECT_ROOT / "sources"
MODELS_DIR   = SOURCES_DIR / "models"
OLLAMA_DIR   = SOURCES_DIR / "ollama"


def resolve(p, base: Path = PROJECT_ROOT) -> Path:
    """相对路径相对项目根；绝对路径原样返回；空值返回 base。"""
    if p is None or str(p).strip() == "":
        return base
    path = Path(os.path.expanduser(str(p)))
    if not path.is_absolute():
        path = base / path
    return path.resolve()


def to_posix_rel(p) -> str:
    """尽量转成相对项目根的 POSIX 字符串；跨盘时保留绝对。"""
    path = resolve(p)
    try:
        return path.relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return str(path)
