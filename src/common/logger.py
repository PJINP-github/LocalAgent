from __future__ import annotations
"""统一日志。格式：[LEVEL|tag|message]

LEVEL ∈ {INFO, WARN, ERROR, DEBUG}
"""
import sys
from enum import Enum
from typing import TextIO, Optional


class Level(str, Enum):
    INFO = "INFO"
    WARN = "WARN"
    ERROR = "ERROR"
    DEBUG = "DEBUG"


_DEBUG_ENABLED = False


def set_debug(enabled: bool) -> None:
    global _DEBUG_ENABLED
    _DEBUG_ENABLED = bool(enabled)


def _emit(level: Level, tag: str, message: str, file: Optional[TextIO] = None) -> None:
    out = file or (sys.stderr if level == Level.ERROR else sys.stdout)
    try:
        out.write(f"[{level.value}|{tag}|{message}]\n")
        out.flush()
    except Exception:
        pass


def info(tag: str, message: str) -> None:
    _emit(Level.INFO, tag, message)


def warn(tag: str, message: str) -> None:
    _emit(Level.WARN, tag, message)


def error(tag: str, message: str) -> None:
    _emit(Level.ERROR, tag, message)


def debug(tag: str, message: str) -> None:
    if _DEBUG_ENABLED:
        _emit(Level.DEBUG, tag, message)
