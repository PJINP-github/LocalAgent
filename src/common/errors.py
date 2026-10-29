from __future__ import annotations
"""统一异常封装。"""
from typing import Optional


class KuramaError(Exception):
    """所有 Kurama 异常的基类。

    属性：
      level   - INFO | WARN | ERROR | DEBUG
      tag     - 简短分类（如 "ollama", "config"）
      message - 人类可读信息
      cause   - 可选原始异常
    """
    level = "ERROR"
    tag = "general"

    def __init__(self, message: str, tag: Optional[str] = None,
                 cause: Optional[BaseException] = None) -> None:
        self.message = message
        self.tag = tag or type(self).tag
        self.cause = cause
        super().__init__(self.render())

    def render(self) -> str:
        return f"[{self.level}|{self.tag}|{self.message}]"


class ConfigError(KuramaError):
    tag = "config"


class OllamaError(KuramaError):
    tag = "ollama"


class MemoryError2(KuramaError):
    tag = "memory"


class ToolError(KuramaError):
    tag = "tool"


class WarnOnly(KuramaError):
    level = "WARN"
