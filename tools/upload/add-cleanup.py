#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""add-cleanup.py — 给 src/agent/agent.py 加退出清理

插入：
  1. 顶部 import atexit / signal / subprocess（若缺）
  2. OLLAMA_URL 定义前：清理函数 + atexit 注册 + signal handler
  3. def main() 后第一行：_install_signal_handlers()

幂等：检测到 _run_cleanup_once 就跳过。

用法:
    python tools/upload/add-cleanup.py --dry-run
    python tools/upload/add-cleanup.py
"""
from __future__ import annotations

import re
import shutil
import sys
from pathlib import Path

DRY_RUN = "--dry-run" in sys.argv or "-n" in sys.argv


def log(level: str, tag: str, msg: str) -> None:
    print(f"[{level}|{tag}|{msg}]")


def find_root(start: Path) -> Path:
    for p in [start, *start.parents]:
        for m in ("start-kurama.ps1", "src"):
            if (p / m).exists():
                return p
    raise SystemExit(f"[ERROR|root|no marker from {start}]")


CLEANUP_CODE = r'''
# ============================================================
#  退出清理：正常/异常/Ctrl+C 时自动停止 Ollama 相关进程
# ============================================================
_CLEANUP_DONE = False


def _cleanup_ollama_processes() -> None:
    """停止所有 Ollama / Llama 相关进程。"""
    if os.name == "nt":
        names = [
            "ollama app.exe", "ollama.exe",
            "llama-server.exe", "llama_server.exe",
            "ollama_llama_server.exe",
            "ollama-runner.exe", "ollama_runner.exe",
        ]
        for name in names:
            try:
                subprocess.run(
                    ["taskkill", "/F", "/T", "/IM", name],
                    capture_output=True, timeout=5,
                )
            except Exception:
                pass
    else:
        for pattern in ("ollama", "llama-server", "ollama-runner"):
            try:
                subprocess.run(
                    ["pkill", "-9", "-f", pattern],
                    capture_output=True, timeout=5,
                )
            except Exception:
                pass


def _run_cleanup_once(reason: str = "exit") -> None:
    global _CLEANUP_DONE
    if _CLEANUP_DONE:
        return
    _CLEANUP_DONE = True
    try:
        _w(f"\n[清理|ollama|{reason}] 停止 Ollama 相关进程...\n")
    except Exception:
        pass
    _cleanup_ollama_processes()


# atexit：正常 / 异常 / Ctrl+C 都会触发
atexit.register(_run_cleanup_once, "atexit")


def _sigint_handler(signum, frame):
    try:
        signal.signal(signal.SIGINT, signal.SIG_DFL)
        if hasattr(signal, "SIGTERM"):
            signal.signal(signal.SIGTERM, signal.SIG_DFL)
        if hasattr(signal, "SIGBREAK"):
            signal.signal(signal.SIGBREAK, signal.SIG_DFL)
    except Exception:
        pass
    raise KeyboardInterrupt


def _install_signal_handlers() -> None:
    try:
        signal.signal(signal.SIGINT, _sigint_handler)
        if hasattr(signal, "SIGTERM"):
            signal.signal(signal.SIGTERM, _sigint_handler)
        if hasattr(signal, "SIGBREAK"):
            signal.signal(signal.SIGBREAK, _sigint_handler)
    except Exception:
        pass
'''


def main() -> int:
    root = find_root(Path(__file__).resolve().parent)
    target = root / "src" / "agent" / "agent.py"
    log("root", str(root))
    log("target", str(target.relative_to(root)))

    if not target.is_file():
        log("error", f"not found: {target}")
        return 1

    text = target.read_text(encoding="utf-8")
    if "_run_cleanup_once" in text:
        log("info", "已存在 _run_cleanup_once，跳过（幂等）")
        return 0

    orig = text

    # 1) import
    if "import atexit" not in text:
        m = re.search(r"^(import |from )", text, re.MULTILINE)
        pos = m.start() if m else 0
        text = text[:pos] + "import atexit\nimport signal\nimport subprocess\n" + text[pos:]
        log("fix", "顶部插入 import atexit / signal / subprocess")
    else:
        # 补齐缺失的
        for mod in ("signal", "subprocess"):
            if f"import {mod}" not in text and f"from {mod}" not in text:
                m = re.search(r"^import atexit\s*$", text, re.MULTILINE)
                pos = m.end() if m else 0
                text = text[:pos] + f"\nimport {mod}" + text[pos:]
                log("fix", f"补充 import {mod}")

    # 2) 清理函数：插到 OLLAMA_URL 之前
    marker = 'OLLAMA_URL = '
    idx = text.find(marker)
    if idx < 0:
        log("warn", "未找到 OLLAMA_URL，插到文件末尾")
        text = text.rstrip() + "\n" + CLEANUP_CODE + "\n"
    else:
        text = text[:idx] + CLEANUP_CODE.lstrip("\n") + "\n\n" + text[idx:]
    log("fix", "插入清理函数 + atexit + signal handler")

    # 3) main() 后加 _install_signal_handlers()
    m = re.search(r"^(def main\(\):[^\n]*\n)", text, re.MULTILINE)
    if m:
        if "_install_signal_handlers()" not in text[m.end():m.end()+500]:
            text = text[:m.end()] + "    _install_signal_handlers()\n" + text[m.end():]
            log("fix", "main() 内安装 signal handler")
    else:
        log("warn", "未找到 def main():，跳过 handler 安装")

    if text == orig:
        log("info", "无改动")
        return 0

    if DRY_RUN:
        log("mode", "DRY-RUN — 未写入")
        return 0

    bak = target.with_suffix(".py.bak")
    if not bak.exists():
        shutil.copy2(target, bak)
        log("backup", str(bak.relative_to(root)))

    target.write_text(text, encoding="utf-8", newline="\n")
    log("done", f"已写入 {target.relative_to(root)}")
    print()
    print("下一步:")
    print("  .\\venv\\Scripts\\python.exe -c \"import src.agent; print('OK')\"")
    return 0


if __name__ == "__main__":
    sys.exit(main())