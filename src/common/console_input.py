from __future__ import annotations

"""终端按键读取（支持方向键）。

Windows: msvcrt
POSIX:   termios
非 tty:  返回 ""，让调用方降级到 input()
"""
import os
import sys


def read_key() -> str:
    """返回：
    'left'/'right'/'up'/'down'  方向键
    'enter'                      回车
    'esc'                        Esc
    'q'/'n'/'1'..'9'             普通键（小写）
    ''                           非 tty 环境
    """
    if not sys.stdin.isatty():
        return ""
    if os.name == "nt":
        import msvcrt
        ch = msvcrt.getch()
        if ch in (b"\x00", b"\xe0"):
            nxt = msvcrt.getch()
            return {b"H": "up", b"P": "down", b"K": "left", b"M": "right"}.get(nxt, "")
        if ch == b"\r":
            return "enter"
        if ch == b"\x1b":
            return "esc"
        try:
            return ch.decode("utf-8", errors="ignore").lower()
        except Exception:
            return ""
    import termios
    import tty
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        c1 = sys.stdin.read(1)
        if c1 == "\x1b":
            c2 = sys.stdin.read(1)
            if c2 == "[":
                c3 = sys.stdin.read(1)
                return {"A": "up", "B": "down", "C": "right", "D": "left"}.get(c3, "")
            return "esc"
        if c1 in ("\r", "\n"):
            return "enter"
        return c1.lower()
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)
