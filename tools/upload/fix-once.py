#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fix-once.py — 一键修复 Kurama 项目全部已知问题

覆盖项（幂等，可重复执行）：
  1.   start-kurama.ps1 退出段：try/finally + PID 追踪 + 进程清理
  1b.  start-kurama.ps1 $DEFAULT_MODELS_PATH → Join-Path $PSScriptRoot
  2.   新建 src/common/paths.py 统一路径解析
  3.   src/config_manager/config_manager.py 默认值 → 相对路径
  4.   src/ollama_manager/ollama_manager.py 模型目录 → PROJECT_ROOT 推导
  5.   src/memory_manager/memory_manager.py 使用 resolve()
  6.   src/agent/agent.py SYSTEM_PROMPT 路径段（lambda 包裹防 re.sub 陷阱）
  7.   移除 config/config_manager/ 冗余副本
  8.   新建 src/common/console_input.py（方向键读取）
  9.   新建 src/memory_manager/ms_manager.py（多记忆系统管理）
  10.  新建 src/memory_manager/ms_ui.py（交互式列表 UI）
  11.  src/memory_manager/__init__.py 追加导出
  12.  src/agent/agent.py 集成 /sms 命令

用法:
    python fix-once.py --check
    python fix-once.py --dry-run
    python fix-once.py
"""
from __future__ import annotations

import difflib
import re
import shutil
import sys
import time
from pathlib import Path
from typing import Callable

# =============================================================
# 常量：PS1 退出段
# =============================================================

PS1_NEW_BLOCK = r'''# 记录 ollama serve 的 PID（精确清理用）
$script:OllamaServePid = 0
try {
    $conn = Get-NetTCPConnection -LocalPort 11434 -State Listen -ErrorAction SilentlyContinue |
            Select-Object -First 1
    if ($conn) { $script:OllamaServePid = $conn.OwningProcess }
} catch {}

$agentExitCode = 0
$agentInterrupted = $false
try {
    & $pythonExe -u -m src.agent
    $agentExitCode = $LASTEXITCODE
    if ($null -eq $agentExitCode) { $agentExitCode = 0 }
}
catch [System.Management.Automation.PipelineStoppedException] {
    Write-Warn "Agent 被 Ctrl+C 中断"
    $agentInterrupted = $true
    $agentExitCode = 130
}
catch {
    Write-Warn "Agent 异常退出: $($_.Exception.Message)"
    $agentExitCode = 1
}
finally {
    Write-Host ""
    $reason = if ($agentInterrupted) { "Ctrl+C" } else { "exit=$agentExitCode" }
    Write-Step "[5/5] Agent 已退出（$reason），清理 Ollama 进程..."

    # ① 精确：按 PID 杀进程树（含 llama-server 子进程）
    if ($script:OllamaServePid -gt 0) {
        Write-Info "按 PID 清理进程树: $($script:OllamaServePid)"
        try { & taskkill /F /T /PID $script:OllamaServePid 2>&1 | Out-Null } catch {}
    }

    # ② 兜底：按名字清所有 ollama / llama 进程
    try {
        Clear-OllamaProcesses -MaxWaitSeconds 30 -SharedMemWarnGB 3.0 | Out-Null
    } catch {
        Write-Warn "Clear-OllamaProcesses 失败，taskkill 兜底"
        foreach ($n in @(
            "ollama.exe", "ollama app.exe",
            "llama-server.exe", "llama_server.exe",
            "ollama_llama_server.exe",
            "ollama-runner.exe", "ollama_runner.exe"
        )) {
            try { & taskkill /F /T /IM $n 2>&1 | Out-Null } catch {}
        }
    }
    Write-OK "清理完成"
}

Write-Host ""
Write-Host "Agent 已退出。" -ForegroundColor Cyan

Read-Host "按回车关闭窗口"'''

# =============================================================
# 常量：src/common/paths.py
# =============================================================

PATHS_PY_CONTENT = '''from __future__ import annotations

"""统一路径解析。

规则:
  - 相对路径 → 相对项目根（PROJECT_ROOT）
  - 绝对路径 → 原样返回
  - 落盘用相对，消费端 resolve() 成绝对
"""
import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]

CONFIG_DIR   = PROJECT_ROOT / "config"
CONFIG_FILE  = CONFIG_DIR / "config.json"
MEMORY_FILE  = CONFIG_DIR / "memory.json"
OLLAMA_YAML  = CONFIG_DIR / "ollama.yaml"
SOURCES_DIR  = PROJECT_ROOT / "sources"
MODELS_DIR   = SOURCES_DIR / "models"
OLLAMA_DIR   = SOURCES_DIR / "ollama"


def resolve(p, base: Path = PROJECT_ROOT) -> Path:
    if p is None or str(p).strip() == "":
        return base
    path = Path(os.path.expanduser(str(p)))
    if not path.is_absolute():
        path = base / path
    return path.resolve()


def to_posix_rel(p) -> str:
    path = resolve(p)
    try:
        return path.relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return str(path)
'''

# =============================================================
# 常量：src/common/console_input.py
# =============================================================

CONSOLE_INPUT_PY = '''from __future__ import annotations

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
        if ch in (b"\\x00", b"\\xe0"):
            nxt = msvcrt.getch()
            return {b"H": "up", b"P": "down", b"K": "left", b"M": "right"}.get(nxt, "")
        if ch == b"\\r":
            return "enter"
        if ch == b"\\x1b":
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
        if c1 == "\\x1b":
            c2 = sys.stdin.read(1)
            if c2 == "[":
                c3 = sys.stdin.read(1)
                return {"A": "up", "B": "down", "C": "right", "D": "left"}.get(c3, "")
            return "esc"
        if c1 in ("\\r", "\\n"):
            return "enter"
        return c1.lower()
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)
'''

# =============================================================
# 常量：src/memory_manager/ms_manager.py
# =============================================================

MS_MANAGER_PY = '''from __future__ import annotations

"""多记忆系统管理。

启动后 active_id 恒为 None（无记忆状态）。
/sms 开启/关闭；/sms show 交互选择。
"""
import json
import uuid
from datetime import datetime

from ..common.paths import resolve


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


class MemorySystemManager:
    def __init__(self, config, llm=None):
        self.llm = llm
        self.base_dir = resolve(config.get("memory_system_dir") or "config/memory")
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.index_path = self.base_dir / "index.json"
        self.index = self._load_index()
        self.active_id: str | None = None
        self._active = None

    # ---- 索引 ----
    def _load_index(self) -> dict:
        if self.index_path.exists():
            try:
                data = json.loads(self.index_path.read_text(encoding="utf-8"))
                if isinstance(data, dict) and isinstance(data.get("systems"), list):
                    data.setdefault("version", 1)
                    data.setdefault("last_active_id", None)
                    return data
            except Exception:
                pass
        return {"version": 1, "last_active_id": None, "systems": []}

    def _save_index(self) -> None:
        self.index_path.write_text(
            json.dumps(self.index, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    # ---- 查询 ----
    def list_systems(self) -> list:
        return sorted(
            self.index["systems"],
            key=lambda s: s.get("last_active_at", ""),
            reverse=True,
        )

    def _meta(self, sid: str):
        return next((s for s in self.index["systems"] if s["id"] == sid), None)

    def get_active(self):
        return self._active

    # ---- 生命周期 ----
    def create(self, name: str) -> str:
        sid = uuid.uuid4().hex[:8]
        now = _now()
        self.index["systems"].append({
            "id": sid,
            "name": name,
            "description": "",
            "created_at": now,
            "last_active_at": now,
            "total_turns": 0,
        })
        self._save_index()
        self.activate(sid)
        return sid

    def activate(self, sid: str) -> bool:
        meta = self._meta(sid)
        if meta is None:
            return False
        from .memory_manager import MemoryManager
        self._active = MemoryManager(
            path=str(self.base_dir / f"ms_{sid}.json"),
            llm=self.llm,
        )
        self.active_id = sid
        meta["last_active_at"] = _now()
        self.index["last_active_id"] = sid
        self._save_index()
        return True

    def deactivate(self) -> None:
        self.active_id = None
        self._active = None

    def delete(self, sid: str) -> bool:
        before = len(self.index["systems"])
        self.index["systems"] = [s for s in self.index["systems"] if s["id"] != sid]
        if len(self.index["systems"]) == before:
            return False
        try:
            (self.base_dir / f"ms_{sid}.json").unlink(missing_ok=True)
        except Exception:
            pass
        if self.active_id == sid:
            self.deactivate()
        if self.index.get("last_active_id") == sid:
            self.index["last_active_id"] = None
        self._save_index()
        return True

    # ---- 开关 ----
    def toggle(self) -> str:
        if self.active_id:
            meta = self._meta(self.active_id)
            name = meta["name"] if meta else "?"
            self.deactivate()
            return f"已关闭（{name}）"
        last = self.index.get("last_active_id")
        if last and self._meta(last):
            self.activate(last)
            meta = self._meta(last)
            return f"已恢复：{meta['name']} ({last})"
        return "当前无激活系统，请用 /sms show 选择或 /sms new <name> 新建"

    # ---- 元数据同步 ----
    def sync_meta_after_turn(self, sid: str) -> None:
        if not sid:
            return
        meta = self._meta(sid)
        if meta is None:
            return
        meta["last_active_at"] = _now()
        self.index["last_active_id"] = sid
        mem = self._active
        if mem is not None:
            meta["total_turns"] = mem.data.get("total_turns", 0)
            if not meta.get("description") and mem.data.get("recent_messages"):
                first_user = next(
                    (m["content"] for m in mem.data["recent_messages"]
                     if m["role"] == "user"),
                    "",
                )
                desc = first_user.replace("\\n", " ").strip()
                if desc:
                    meta["description"] = desc[:30] + ("…" if len(desc) > 30 else "")
        self._save_index()
'''

# =============================================================
# 常量：src/memory_manager/ms_ui.py
# =============================================================

MS_UI_PY = '''from __future__ import annotations

"""记忆系统列表 UI。"""
import sys

from ..common.console_input import read_key


def _visual_width(s: str) -> int:
    return sum(
        2 if "\\u4e00" <= c <= "\\u9fff" or "\\u3000" <= c <= "\\u303f" else 1
        for c in s
    )


def _pad(s: str, width: int) -> str:
    return s + " " * max(0, width - _visual_width(s))


def _render(systems, page, page_size, total_pages, current_id):
    start = page * page_size
    end = min(start + page_size, len(systems))
    print()
    print("=" * 78)
    cur = "无" if not current_id else (
        next((s["name"] for s in systems if s["id"] == current_id), "?")
    )
    print(f"  记忆系统  ·  第 {page + 1}/{total_pages} 页  ·  共 {len(systems)} 个  ·  当前：{cur}")
    print("=" * 78)
    for i in range(start, end):
        s = systems[i]
        mark = "●" if s["id"] == current_id else " "
        desc = (s.get("description") or "").strip() or "（暂无描述）"
        line = (
            f"  [{i + 1:>2}] {_pad(s['name'], 20)} {_pad(desc, 30)} "
            f"{s.get('total_turns', 0):>4} 次   "
            f"{s.get('last_active_at', '?'):>19}  {mark}"
        )
        print(line)
    print("-" * 78)
    print("  ← 上一页    → 下一页    1-5 选择    n 新建    q 退出")
    print()


def interactive_select(ms_mgr):
    """返回选中 id / 新建的 id / None。"""
    systems = ms_mgr.list_systems()
    if not systems:
        print("[无记忆系统] 使用 /sms new <名称> 创建")
        return None

    page_size = 5
    page = 0
    total_pages = (len(systems) + page_size - 1) // page_size

    # 非 tty：降级为 input()
    if not sys.stdin.isatty():
        _render(systems, page, page_size, total_pages, ms_mgr.active_id)
        try:
            choice = input("选择序号（n 新建 / q 退出）: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            return None
        if choice in ("", "q"):
            return None
        if choice == "n":
            try:
                name = input("新记忆系统名称: ").strip()
            except (EOFError, KeyboardInterrupt):
                return None
            if name:
                return ms_mgr.create(name)
            return None
        if choice.isdigit():
            n = int(choice)
            if 1 <= n <= len(systems):
                return systems[n - 1]["id"]
        print("[错误] 无效输入")
        return None

    # 交互式
    while True:
        _render(systems, page, page_size, total_pages, ms_mgr.active_id)
        key = read_key()
        if key in ("q", "esc"):
            return None
        if key == "":
            print("[提示] 当前终端不支持按键读取，请使用 /sms <N> 直接切换")
            return None
        if key == "left":
            if page > 0:
                page -= 1
        elif key == "right":
            if page < total_pages - 1:
                page += 1
        elif key.isdigit():
            n = int(key)
            if 1 <= n <= page_size:
                idx = page * page_size + (n - 1)
                if 0 <= idx < len(systems):
                    return systems[idx]["id"]
        elif key == "n":
            try:
                name = input("新记忆系统名称: ").strip()
            except (EOFError, KeyboardInterrupt):
                return None
            if name:
                return ms_mgr.create(name)
'''

# =============================================================
# 辅助
# =============================================================

def read_text_preserve_bom(path: Path) -> tuple[str, bytes]:
    raw = path.read_bytes()
    bom = b""
    if raw.startswith(b"\xef\xbb\xbf"):
        bom = b"\xef\xbb\xbf"
        raw = raw[3:]
    return raw.decode("utf-8"), bom


def write_text_preserve_bom(path: Path, text: str, bom: bytes) -> None:
    path.write_bytes(bom + text.encode("utf-8"))


def backup(path: Path) -> Path:
    bak = path.with_name(path.name + ".bak")
    if not bak.exists():
        shutil.copy2(path, bak)
    return bak


def show_diff(old: str, new: str, max_lines: int = 80) -> str:
    diff = list(difflib.unified_diff(
        old.splitlines(keepends=True),
        new.splitlines(keepends=True),
        fromfile="old", tofile="new", n=2,
    ))
    if len(diff) > max_lines:
        diff = diff[:max_lines] + ["... (diff 已截断)\n"]
    return "".join(diff)


def find_root(start: Path) -> Path:
    for p in [start, *start.parents]:
        if (p / "start-kurama.ps1").exists() or (p / "src").exists():
            return p
    raise SystemExit(f"[ERROR|root|no marker from {start}]")

def _normalize_for_match(text: str) -> tuple[str, bool]:
    """CRLF → LF，返回 (normalized, had_crlf)。"""
    had_crlf = "\r\n" in text
    if had_crlf:
        text = text.replace("\r\n", "\n")
    return text, had_crlf


def _denormalize_for_write(text: str, had_crlf: bool) -> str:
    """LF → CRLF（仅原文件是 CRLF 时）。"""
    if had_crlf:
        text = text.replace("\n", "\r\n")
    return text

def _normalize_for_match(text: str) -> tuple[str, bool]:
    """CRLF → LF 归一化，返回 (normalized, had_crlf)。"""
    had_crlf = "\r\n" in text
    if had_crlf:
        text = text.replace("\r\n", "\n")
    return text, had_crlf


def _denormalize_for_write(text: str, had_crlf: bool) -> str:
    """LF → CRLF 还原（仅在原文件是 CRLF 时）。"""
    if had_crlf:
        text = text.replace("\n", "\r\n")
    return text

# =============================================================
# 1. PS1 退出段
# =============================================================

def fix_ps1_exit(root: Path, mode: str) -> tuple[str, str]:
    target = root / "start-kurama.ps1"
    if not target.is_file():
        return "skip", "start-kurama.ps1 不存在"
    text, bom = read_text_preserve_bom(target)
    if "$script:OllamaServePid" in text and "PipelineStoppedException" in text:
        return "ok", "已 patch（幂等）"
    pat = re.compile(
        r'&\s*\$pythonExe\s+-u\s+-m\s+src\.agent.*?Read-Host\s+"按回车关闭窗口"',
        re.DOTALL,
    )
    m = pat.search(text)
    if not m:
        return "error", "未匹配到 agent 启动段"
    new_text = text[:m.start()] + PS1_NEW_BLOCK + text[m.end():]
    detail = f"替换退出段 {len(m.group(0))} → {len(PS1_NEW_BLOCK)} 字符"
    if mode == "check":
        return "need", detail
    if mode == "dry-run":
        print(show_diff(m.group(0), PS1_NEW_BLOCK))
        return "need", detail
    backup(target)
    write_text_preserve_bom(target, new_text, bom)
    return "applied", detail


# =============================================================
# 1b. PS1 DEFAULT_MODELS_PATH 相对化
# =============================================================

def fix_ps1_models_path(root: Path, mode: str) -> tuple[str, str]:
    target = root / "start-kurama.ps1"
    if not target.is_file():
        return "skip", "start-kurama.ps1 不存在"
    text, bom = read_text_preserve_bom(target)
    new = r'$DEFAULT_MODELS_PATH = Join-Path $PSScriptRoot "sources\models"'
    old = r'$DEFAULT_MODELS_PATH = "C:\software\LocalAgent\sources\models"'
    if new in text:
        return "ok", "DEFAULT_MODELS_PATH 已相对化"
    if old not in text:
        return "skip", "未找到旧 DEFAULT_MODELS_PATH"
    if mode == "check":
        return "need", "DEFAULT_MODELS_PATH → Join-Path $PSScriptRoot"
    if mode == "dry-run":
        print(f"- {old}\n+ {new}")
        return "need", "DEFAULT_MODELS_PATH → Join-Path $PSScriptRoot"
    backup(target)
    write_text_preserve_bom(target, text.replace(old, new, 1), bom)
    return "applied", "DEFAULT_MODELS_PATH → Join-Path $PSScriptRoot"


# =============================================================
# 2. src/common/paths.py
# =============================================================

def fix_paths_module(root: Path, mode: str) -> tuple[str, str]:
    target = root / "src" / "common" / "paths.py"
    rel = target.relative_to(root)
    if target.exists():
        return "ok", f"{rel} 已存在"
    if mode == "check":
        return "need", f"创建 {rel}"
    if mode == "dry-run":
        print(f"--- /dev/null\n+++ {rel}\n")
        print(PATHS_PY_CONTENT)
        return "need", f"创建 {rel}"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(PATHS_PY_CONTENT, encoding="utf-8")
    return "applied", f"创建 {rel}"


# =============================================================
# 3. config_manager.py 默认值
# =============================================================

def fix_config_manager(root: Path, mode: str) -> tuple[str, str]:
    target = root / "src" / "config_manager" / "config_manager.py"
    rel = target.relative_to(root)
    if not target.is_file():
        return "skip", f"{rel} 不存在"
    text, bom = read_text_preserve_bom(target)
    changes = []

    old1 = r'"ollama_dir": r"C:\software\ollama-windows-amd64",'
    new1 = '"ollama_dir": "sources/ollama",'
    if old1 in text:
        text = text.replace(old1, new1, 1)
        changes.append("ollama_dir → sources/ollama")

    old2 = '"memory_path": str(_MEMORY_FILE),'
    new2 = '"memory_path": "config/memory.json",'
    if old2 in text:
        text = text.replace(old2, new2, 1)
        changes.append("memory_path → config/memory.json")

    if '"models_path"' not in text and new1 in text:
        text = text.replace(new1, new1 + '\n    "models_path": "sources/models",', 1)
        changes.append("新增 models_path")

    if not changes:
        return "ok", "已是相对路径"
    if mode == "check":
        return "need", "; ".join(changes)
    if mode == "dry-run":
        for c in changes:
            print(f"  - {c}")
        return "need", "; ".join(changes)
    backup(target)
    write_text_preserve_bom(target, text, bom)
    return "applied", "; ".join(changes)


# =============================================================
# 4. ollama_manager.py 模型目录
# =============================================================

def fix_ollama_manager(root: Path, mode: str) -> tuple[str, str]:
    target = root / "src" / "ollama_manager" / "ollama_manager.py"
    rel = target.relative_to(root)
    if not target.is_file():
        return "skip", f"{rel} 不存在"
    text, bom = read_text_preserve_bom(target)
    changes = []

    old_def = r'DEFAULT_MODELS_PATH = r"C:\software\LocalAgent\sources\models"'
    new_def = (
        'DEFAULT_MODELS_REL = "sources/models"\n'
        'DEFAULT_MODELS_PATH = str(PROJECT_ROOT / DEFAULT_MODELS_REL)\n'
        '\n'
        '\n'
        'def _models_dir(cfg_or_ollama) -> str:\n'
        '    """取有效的模型目录（相对 → 绝对）。"""\n'
        '    if "ollama" in cfg_or_ollama:\n'
        '        raw = (cfg_or_ollama.get("ollama", {}).get("models_path") or "").strip()\n'
        '    else:\n'
        '        raw = (cfg_or_ollama.get("models_path") or "").strip()\n'
        '    p = raw or DEFAULT_MODELS_REL\n'
        '    path = Path(p)\n'
        '    if not path.is_absolute():\n'
        '        path = PROJECT_ROOT / path\n'
        '    return str(path.resolve())'
    )
    if old_def in text:
        text = text.replace(old_def, new_def, 1)
        changes.append("DEFAULT_MODELS_PATH → PROJECT_ROOT 推导 + _models_dir")

    old_cfg = '"models_path": DEFAULT_MODELS_PATH,'
    new_cfg = '"models_path": DEFAULT_MODELS_REL,'
    if old_cfg in text:
        text = text.replace(old_cfg, new_cfg, 1)
        changes.append("DEFAULT_CONFIG.models_path → 相对")

    old_be = 'models_path = (o.get("models_path") or "").strip() or DEFAULT_MODELS_PATH'
    if old_be in text:
        text = text.replace(old_be, 'models_path = _models_dir(o)')
        changes.append("build_env 使用 _models_dir")

    old_ss = 'models_path = (cfg["ollama"].get("models_path") or "").strip() or DEFAULT_MODELS_PATH'
    if old_ss in text:
        text = text.replace(old_ss, 'models_path = _models_dir(cfg)')
        changes.append("start_service 使用 _models_dir")

    old_es = 'effective_models = (cfg["ollama"].get("models_path") or "").strip() or DEFAULT_MODELS_PATH'
    if old_es in text:
        text = text.replace(old_es, 'effective_models = _models_dir(cfg)')
        changes.append("show_status 使用 _models_dir")

    old_sm = 'models_eff = (cfg["ollama"].get("models_path") or "").strip() or DEFAULT_MODELS_PATH'
    if old_sm in text:
        text = text.replace(old_sm, 'models_eff = _models_dir(cfg)')
        changes.append("show_menu 使用 _models_dir")

    if not changes:
        return "ok", "已是相对路径"
    if mode == "check":
        return "need", "; ".join(changes)
    if mode == "dry-run":
        for c in changes:
            print(f"  - {c}")
        return "need", "; ".join(changes)
    backup(target)
    write_text_preserve_bom(target, text, bom)
    return "applied", "; ".join(changes)


# =============================================================
# 5. memory_manager.py resolve()
# =============================================================

def fix_memory_manager(root: Path, mode: str) -> tuple[str, str]:
    target = root / "src" / "memory_manager" / "memory_manager.py"
    rel = target.relative_to(root)
    if not target.is_file():
        return "skip", f"{rel} 不存在"
    text, bom = read_text_preserve_bom(target)
    if "from ..common.paths import resolve" in text and "self.path = str(resolve(" in text:
        return "ok", "已使用 resolve()"
    changes = []

    if "from ..common.paths import resolve" not in text:
        anchor = "from datetime import datetime"
        if anchor in text:
            text = text.replace(anchor, anchor + "\nfrom ..common.paths import resolve", 1)
            changes.append("新增 paths 导入")

    old_init = (
        '        if path is None:\n'
        '            path = str(Path(__file__).resolve().parents[2] / "config" / "memory.json")\n'
        '        self.path = os.path.expanduser(path)'
    )
    new_init = (
        '        if path is None:\n'
        '            path = "config/memory.json"\n'
        '        self.path = str(resolve(path))'
    )
    if old_init in text:
        text = text.replace(old_init, new_init, 1)
        changes.append("__init__ 使用 resolve()")

    old_sw = '        self.path = os.path.expanduser(new_path)'
    new_sw = '        self.path = str(resolve(new_path))'
    if old_sw in text:
        text = text.replace(old_sw, new_sw, 1)
        changes.append("switch_path 使用 resolve()")

    if not changes:
        return "skip", "未找到可替换的路径逻辑"
    if mode == "check":
        return "need", "; ".join(changes)
    if mode == "dry-run":
        for c in changes:
            print(f"  - {c}")
        return "need", "; ".join(changes)
    backup(target)
    write_text_preserve_bom(target, text, bom)
    return "applied", "; ".join(changes)


# =============================================================
# 6. agent.py SYSTEM_PROMPT 路径（lambda 防 re.sub 陷阱）
# =============================================================

def fix_agent_prompt(root: Path, mode: str) -> tuple[str, str]:
    target = root / "src" / "agent" / "agent.py"
    rel = target.relative_to(root)
    if not target.is_file():
        return "skip", f"{rel} 不存在"
    text, bom = read_text_preserve_bom(target)

    # ① 已正确
    if '"【路径规范】\\n"' in text and "相对项目根目录的路径" in text:
        return "ok", "SYSTEM_PROMPT 已更新（格式合法）"

    # ② 已损坏（旧版 re.sub 事故）
    if "相对项目根目录的路径" in text and '"【路径规范】\\n"' not in text:
        bak = target.with_name(target.name + ".bak")
        if not bak.exists():
            return "error", "agent.py 已损坏且无 .bak，请手动修复"
        if mode == "check":
            return "need", "agent.py 已损坏，需从 .bak 恢复后重新 patch"
        if mode == "dry-run":
            return "need", "将从 .bak 恢复 agent.py，再重新 patch"
        corrupted = target.with_name(target.name + ".corrupted")
        shutil.copy2(target, corrupted)
        shutil.copy2(bak, target)
        text, bom = read_text_preserve_bom(target)

    # ③ 未 patch
    pat = re.compile(
        r'"【路径规范】\\n".*?"- 用户没给路径时，先问用户要哪个路径，不要自己假设。\\n"',
        re.DOTALL,
    )
    if not pat.search(text):
        return "skip", "未匹配到路径规范段"
    new_block = (
        r'    "【路径规范】\n"' + "\n"
        r'    "- 需要绝对路径时，优先使用用户主目录（%USERPROFILE%）下的路径。\n"' + "\n"
        r'    "- 项目内文件使用相对项目根目录的路径，例如 config/、sources/、src/。\n"' + "\n"
        r'    "- 不要编造不存在的盘符（如 D:\\、E:\\），除非用户明确提供了该路径。\n"' + "\n"
        r'    "- 用户没给路径时，先问用户要哪个路径，不要自己假设。\n"'
    )
    detail = "替换 SYSTEM_PROMPT 路径规范"
    if mode == "check":
        return "need", detail
    if mode == "dry-run":
        print(f"--- {rel}\n+++ {rel}\n（替换 [路径规范] 段）")
        return "need", detail
    backup(target)
    # ★ lambda 包裹：跳过 re 模块对 repl 的反斜杠二次处理
    text = pat.sub(lambda _: new_block, text, count=1)
    write_text_preserve_bom(target, text, bom)
    return "applied", detail


# =============================================================
# 7. 移除 config/config_manager/ 冗余副本
# =============================================================

def fix_remove_redundant(root: Path, mode: str) -> tuple[str, str]:
    src = root / "config" / "config_manager"
    if not src.exists():
        return "ok", "已不存在"
    trash_root = root / "config" / ".trash"
    dst = trash_root / "config_manager"
    if dst.exists():
        dst = trash_root / f"config_manager.{int(time.time())}"
    detail = f"{src.relative_to(root)} → {dst.relative_to(root)}"
    if mode == "check":
        return "need", detail
    if mode == "dry-run":
        return "need", f"将移动 {detail}"
    trash_root.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(dst))
    return "applied", detail


# =============================================================
# 8. src/common/console_input.py
# =============================================================

def fix_console_input(root: Path, mode: str) -> tuple[str, str]:
    target = root / "src" / "common" / "console_input.py"
    rel = target.relative_to(root)
    if target.exists():
        return "ok", f"{rel} 已存在"
    if mode == "check":
        return "need", f"创建 {rel}"
    if mode == "dry-run":
        print(f"--- /dev/null\n+++ {rel}\n")
        print(CONSOLE_INPUT_PY)
        return "need", f"创建 {rel}"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(CONSOLE_INPUT_PY, encoding="utf-8")
    return "applied", f"创建 {rel}"


# =============================================================
# 9. src/memory_manager/ms_manager.py
# =============================================================

def fix_ms_manager(root: Path, mode: str) -> tuple[str, str]:
    target = root / "src" / "memory_manager" / "ms_manager.py"
    rel = target.relative_to(root)
    if target.exists():
        return "ok", f"{rel} 已存在"
    if mode == "check":
        return "need", f"创建 {rel}"
    if mode == "dry-run":
        print(f"--- /dev/null\n+++ {rel}\n")
        print(MS_MANAGER_PY)
        return "need", f"创建 {rel}"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(MS_MANAGER_PY, encoding="utf-8")
    return "applied", f"创建 {rel}"


# =============================================================
# 10. src/memory_manager/ms_ui.py
# =============================================================

def fix_ms_ui(root: Path, mode: str) -> tuple[str, str]:
    target = root / "src" / "memory_manager" / "ms_ui.py"
    rel = target.relative_to(root)
    if target.exists():
        return "ok", f"{rel} 已存在"
    if mode == "check":
        return "need", f"创建 {rel}"
    if mode == "dry-run":
        print(f"--- /dev/null\n+++ {rel}\n")
        print(MS_UI_PY)
        return "need", f"创建 {rel}"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(MS_UI_PY, encoding="utf-8")
    return "applied", f"创建 {rel}"


# =============================================================
# 11. memory_manager/__init__.py 追加导出
# =============================================================
def fix_memory_init(root: Path, mode: str) -> tuple[str, str]:
    target = root / "src" / "memory_manager" / "__init__.py"
    rel = target.relative_to(root)
    if not target.is_file():
        return "skip", f"{rel} 不存在"
    text, bom = read_text_preserve_bom(target)
    text, had_crlf = _normalize_for_match(text)

    if "MemorySystemManager" in text and "interactive_select" in text:
        return "ok", "已导出"

    # 容忍 from ... 和 __all__ 之间的空行
    pat = re.compile(
        r'from __future__ import annotations\n'
        r'from \.memory_manager import MemoryManager, split_thinking, clean_output\n'
        r'\s*'
        r'__all__ = \[[^\]]*\]\n*',
    )
    new_block = (
        'from __future__ import annotations\n'
        'from .memory_manager import MemoryManager, split_thinking, clean_output\n'
        'from .ms_manager import MemorySystemManager\n'
        'from .ms_ui import interactive_select\n'
        '\n'
        '__all__ = [\n'
        '    "MemoryManager", "split_thinking", "clean_output",\n'
        '    "MemorySystemManager", "interactive_select",\n'
        ']\n'
    )
    if not pat.search(text):
        return "error", "未匹配 __init__.py（请贴实际内容）"
    new_text = pat.sub(lambda _: new_block, text, count=1)
    detail = "追加 MemorySystemManager / interactive_select 导出"
    if mode == "check":
        return "need", detail
    if mode == "dry-run":
        print(show_diff(text, new_text))
        return "need", detail
    backup(target)
    write_text_preserve_bom(target, _denormalize_for_write(new_text, had_crlf), bom)
    return "applied", detail

# =============================================================
# 12. agent.py 集成 /sms
# =============================================================

_AGENT_REPLACEMENTS = [
    # ① handle_command 签名
    (
        'def handle_command(cmd, config, memory):',
        'def handle_command(cmd, config, ms_mgr):',
        "handle_command 签名",
    ),
    # ② import 追加
    (
        'from ..memory_manager import MemoryManager\n',
        'from ..memory_manager import MemoryManager\n'
        'from ..memory_manager.ms_manager import MemorySystemManager\n'
        'from ..memory_manager.ms_ui import interactive_select\n',
        "import 追加",
    ),
    # ③ main 里 memory 初始化
    (
        '    model = config.get("model")\n'
        '    memory = MemoryManager(path=config.get("memory_path"), llm=ChatOllama(model=model))\n'
        '    print(f"\\nKurama | 模型：{model} | 记忆：{memory.path}")\n',
        '    model = config.get("model")\n'
        '    llm = ChatOllama(model=model)\n'
        '    ms_mgr = MemorySystemManager(config, llm=llm)\n'
        '    print(f"\\nKurama | 模型：{model} | 记忆：无（/sms 开启）")\n',
        "main 创建 ms_mgr",
    ),
    # ④ /help 里 /memory 行 → /sms 若干行
    (
        '  /memory <path>         切换记忆文件\n',
        '  /sms                   记忆系统开关\n'
        '  /sms show              记忆系统列表（←→ 翻页，1-5 选择）\n'
        '  /sms new <name>        新建记忆系统\n'
        '  /sms <N>               切换到第 N 个\n'
        '  /sms rm <id>           删除指定 id\n'
        '  /memory <path>         (已废弃) 使用 /sms\n',
        "/help 输出",
    ),
    # ⑤ 对话循环整段
    (
        r'''        if user_input.startswith("/"):
            if handle_command(user_input, config, memory):
                continue
        # 非命令：先显示记忆轮廓
        _show_adumbration(memory, config)
        messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        mem_ctx = memory.get_context()
        if mem_ctx:
            messages.append({"role": "system", "content": f"[对话记忆]\n{mem_ctx}"})
        messages.append({"role": "user", "content": user_input})
        _w("[推理中...]\n")
        try:
            answer = stream_chat(model, messages, config.data)
        except Exception as e:
            from ..common.logger import error as _lerr
            _lerr("agent", str(e))
            continue
        if answer:
            memory.add_turn(user_input, answer)
            memory.compress()
        else:
            print("\n[警告] 模型没有返回回答。\n")''',
        r'''        if user_input.startswith("/"):
            if handle_command(user_input, config, ms_mgr):
                continue
        active = ms_mgr.get_active()
        messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        if active:
            _show_adumbration(active, ms_mgr)
            mem_ctx = active.get_context()
            if mem_ctx:
                messages.append({"role": "system", "content": f"[对话记忆]\n{mem_ctx}"})
        messages.append({"role": "user", "content": user_input})
        _w("[推理中...]\n")
        try:
            answer = stream_chat(model, messages, config.data)
        except Exception as e:
            from ..common.logger import error as _lerr
            _lerr("agent", str(e))
            continue
        if answer:
            if active:
                active.add_turn(user_input, answer)
                ms_mgr.sync_meta_after_turn(ms_mgr.active_id)
                active.compress()
        else:
            print("\n[警告] 模型没有返回回答。\n")''',
        "对话循环",
    ),
    # ⑥ /memory 分支 → /sms + /memory 废弃
    (
        r'''    if c == "/memory" and len(parts) >= 2:
        memory.switch_path(parts[1])
        config.set("memory_path", parts[1])
        config.save()
        return True''',
        r'''    if c == "/sms":
        if len(parts) == 1:
            print(f"[记忆系统] {ms_mgr.toggle()}")
            return True
        sub = parts[1].lower()
        if sub == "show":
            picked = interactive_select(ms_mgr)
            if picked:
                ms_mgr.activate(picked)
                meta = ms_mgr._meta(picked) or {}
                print(f"[已激活] {meta.get('name', '?')} ({picked})")
            return True
        if sub == "new":
            name = (parts[2] if len(parts) >= 3 else "").strip()
            if not name:
                print("[错误] 用法：/sms new <名称>")
                return True
            sid = ms_mgr.create(name)
            print(f"[已创建并激活] {name} ({sid})")
            return True
        if sub == "rm":
            sid = (parts[2] if len(parts) >= 3 else "").strip()
            if not sid:
                print("[错误] 用法：/sms rm <id>")
                return True
            meta = ms_mgr._meta(sid)
            if not meta:
                print(f"[错误] 未找到 id={sid}")
                return True
            if ms_mgr.delete(sid):
                print(f"[已删除] {meta['name']} ({sid})")
            else:
                print("[错误] 删除失败")
            return True
        if sub.isdigit():
            n = int(sub)
            systems = ms_mgr.list_systems()
            if 1 <= n <= len(systems):
                sid = systems[n - 1]["id"]
                ms_mgr.activate(sid)
                print(f"[已激活] {systems[n - 1]['name']} ({sid})")
            else:
                print(f"[错误] 序号越界（1-{len(systems)}）")
            return True
        print("[错误] 未知子命令。用 /sms show")
        return True

    if c == "/memory":
        print("[已废弃] /memory 已由 /sms 取代，请使用：")
        print("  /sms show        交互式选择")
        print("  /sms new <name>  新建")
        print("  /sms rm <id>     删除")
        return True''',
        "/sms 命令实现",
    ),
    # ⑦ _show_adumbration 整段
    (
        r'''def _show_adumbration(memory, config):
    data = memory.data
    summary = (data.get("summary") or "").strip()
    recent = data.get("recent_messages", [])
    total_turns = data.get("total_turns", 0)
    topics = data.get("topics", [])
    if summary:
        summary_short = summary[:60] + ("..." if len(summary) > 60 else "")
    else:
        summary_short = "（空）"
    enabled_cnt = len(tools_module.ENABLED_TOOLS)
    total_cnt = len(tools_module.TOOL_REGISTRY)
    print(f"\n[记忆轮廓]")
    print(f"  长期摘要  : {summary_short}")
    print(f"  近期对话  : {len(recent)} 条  (注入最近 6 条)")
    print(f"  累计轮数  : {total_turns}  (每 20 轮压缩一次)")
    print(f"  话题标签  : {', '.join(topics) if topics else '（无）'}")
    print(f"  启用工具  : {enabled_cnt} / {total_cnt}")
    print(f"  记忆文件  : {memory.path}")
    print()''',
        r'''def _show_adumbration(memory, ms_mgr):
    data = memory.data
    meta = ms_mgr._meta(ms_mgr.active_id) or {}
    summary = (data.get("summary") or "").strip()
    recent = data.get("recent_messages", [])
    total_turns = data.get("total_turns", 0)
    topics = data.get("topics", [])
    if summary:
        summary_short = summary[:60] + ("..." if len(summary) > 60 else "")
    else:
        summary_short = "（空）"
    enabled_cnt = len(tools_module.ENABLED_TOOLS)
    total_cnt = len(tools_module.TOOL_REGISTRY)
    print(f"\n[记忆轮廓]")
    print(f"  记忆系统  : {meta.get('name', '?')} ({meta.get('id', '?')})")
    print(f"  描述      : {meta.get('description') or '（暂无）'}")
    print(f"  长期摘要  : {summary_short}")
    print(f"  近期对话  : {len(recent)} 条  (注入最近 6 条)")
    print(f"  累计轮数  : {total_turns}  (每 20 轮压缩一次)")
    print(f"  话题标签  : {', '.join(topics) if topics else '（无）'}")
    print(f"  启用工具  : {enabled_cnt} / {total_cnt}")
    print(f"  最后调用  : {meta.get('last_active_at', '?')}")
    print()''',
        "_show_adumbration",
    ),
]

def fix_agent_sms(root: Path, mode: str) -> tuple[str, str]:
    target = root / "src" / "agent" / "agent.py"
    rel = target.relative_to(root)
    if not target.is_file():
        return "skip", f"{rel} 不存在"
    text, bom = read_text_preserve_bom(target)
    text, had_crlf = _normalize_for_match(text)

    # 幂等检测
    if ("MemorySystemManager" in text
            and "interactive_select" in text
            and '"/sms"' in text
            and "ms_mgr = MemorySystemManager" in text):
        return "ok", "已集成 /sms"

    new_text = text
    missing = []

    # ---- ① import 追加 ----
    if "from ..memory_manager.ms_manager import MemorySystemManager" not in new_text:
        old_imp = "from ..memory_manager import MemoryManager\n"
        if old_imp in new_text:
            add = (
                "from ..memory_manager import MemoryManager\n"
                "from ..memory_manager.ms_manager import MemorySystemManager\n"
                "from ..memory_manager.ms_ui import interactive_select\n"
            )
            new_text = new_text.replace(old_imp, add, 1)
        else:
            missing.append("import")

    # ---- ② handle_command 签名 ----
    if "def handle_command(cmd, config, ms_mgr):" not in new_text:
        old_sig = "def handle_command(cmd, config, memory):"
        if old_sig in new_text:
            new_text = new_text.replace(old_sig, "def handle_command(cmd, config, ms_mgr):", 1)
        else:
            missing.append("handle_command 签名")

    # ---- ③ main 里 memory 初始化（容忍空行）----
    pat_mem = re.compile(
        r'model = config\.get\("model"\)\n'
        r'[ \t]*\n?'
        r'[ \t]*memory = MemoryManager\([^\n]*\)\n'
        r'[ \t]*\n?'
        r'[ \t]*print\(f"\\nKurama \|[^\n]*memory\.path[^\n]*\)\n',
    )
    m = pat_mem.search(new_text)
    if m:
        new_mem = (
            'model = config.get("model")\n'
            '    llm = ChatOllama(model=model)\n'
            '    ms_mgr = MemorySystemManager(config, llm=llm)\n'
            '    print(f"\\nKurama | 模型：{model} | 记忆：无（/sms 开启）")\n'
        )
        new_text = new_text[:m.start()] + new_mem + new_text[m.end():]
    elif "ms_mgr = MemorySystemManager" not in new_text:
        missing.append("main 创建 ms_mgr")

    # ---- ④ /help 里 /memory 行 → /sms 若干行 ----
    old_help = "  /memory <path>         切换记忆文件\n"
    if old_help in new_text:
        new_help = (
            '  /sms                   记忆系统开关\n'
            '  /sms show              记忆系统列表（←→ 翻页，1-5 选择）\n'
            '  /sms new <name>        新建记忆系统\n'
            '  /sms <N>               切换到第 N 个\n'
            '  /sms rm <id>           删除指定 id\n'
            '  /memory <path>         (已废弃) 使用 /sms\n'
        )
        new_text = new_text.replace(old_help, new_help, 1)

    # ---- ⑤ 对话循环整段替换（while True 到 if __name__）----
    pat_loop = re.compile(
        r'(    while True:\n)'
        r'(.*?)'
        r'(\n+if __name__ == "__main__":)',
        re.DOTALL,
    )
    m_loop = pat_loop.search(new_text)
    if m_loop:
        new_loop = (
            '        try:\n'
            '            user_input = input("你 > ").strip()\n'
            '        except (EOFError, KeyboardInterrupt):\n'
            '            print("\\n再见！")\n'
            '            break\n'
            '\n'
            '        if not user_input:\n'
            '            continue\n'
            '        if user_input.lower() in ("quit", "exit", "q"):\n'
            '            print("再见！")\n'
            '            break\n'
            '\n'
            '        if user_input.startswith("/"):\n'
            '            if handle_command(user_input, config, ms_mgr):\n'
            '                continue\n'
            '\n'
            '        active = ms_mgr.get_active()\n'
            '        messages = [{"role": "system", "content": SYSTEM_PROMPT}]\n'
            '        if active:\n'
            '            _show_adumbration(active, ms_mgr)\n'
            '            mem_ctx = active.get_context()\n'
            '            if mem_ctx:\n'
            '                messages.append({"role": "system", "content": f"[对话记忆]\\n{mem_ctx}"})\n'
            '        messages.append({"role": "user", "content": user_input})\n'
            '\n'
            '        _w("[推理中...]\\n")\n'
            '        try:\n'
            '            answer = stream_chat(model, messages, config.data)\n'
            '        except Exception as e:\n'
            '            from ..common.logger import error as _lerr\n'
            '            _lerr("agent", str(e))\n'
            '            continue\n'
            '\n'
            '        if answer:\n'
            '            if active:\n'
            '                active.add_turn(user_input, answer)\n'
            '                ms_mgr.sync_meta_after_turn(ms_mgr.active_id)\n'
            '                active.compress()\n'
            '        else:\n'
            '            print("\\n[警告] 模型没有返回回答。\\n")\n'
            '\n'
        )
        new_text = new_text[:m_loop.start(2)] + new_loop + new_text[m_loop.end(2):]
    elif "active = ms_mgr.get_active()" not in new_text:
        missing.append("对话循环")

    # ---- ⑥ /memory 分支 → /sms ----
    pat_mem_cmd = re.compile(
        r'    if c == "/memory" and len\(parts\) >= 2:\n'
        r'(?:        [^\n]*\n)+'
        r'        return True\n',
    )
    if pat_mem_cmd.search(new_text):
        new_cmd = '''    if c == "/sms":
        if len(parts) == 1:
            print(f"[记忆系统] {ms_mgr.toggle()}")
            return True
        sub = parts[1].lower()
        if sub == "show":
            picked = interactive_select(ms_mgr)
            if picked:
                ms_mgr.activate(picked)
                meta = ms_mgr._meta(picked) or {}
                print(f"[已激活] {meta.get('name', '?')} ({picked})")
            return True
        if sub == "new":
            name = (parts[2] if len(parts) >= 3 else "").strip()
            if not name:
                print("[错误] 用法：/sms new <名称>")
                return True
            sid = ms_mgr.create(name)
            print(f"[已创建并激活] {name} ({sid})")
            return True
        if sub == "rm":
            sid = (parts[2] if len(parts) >= 3 else "").strip()
            if not sid:
                print("[错误] 用法：/sms rm <id>")
                return True
            meta = ms_mgr._meta(sid)
            if not meta:
                print(f"[错误] 未找到 id={sid}")
                return True
            if ms_mgr.delete(sid):
                print(f"[已删除] {meta['name']} ({sid})")
            else:
                print("[错误] 删除失败")
            return True
        if sub.isdigit():
            n = int(sub)
            systems = ms_mgr.list_systems()
            if 1 <= n <= len(systems):
                sid = systems[n - 1]["id"]
                ms_mgr.activate(sid)
                print(f"[已激活] {systems[n - 1]['name']} ({sid})")
            else:
                print(f"[错误] 序号越界（1-{len(systems)}）")
            return True
        print("[错误] 未知子命令。用 /sms show")
        return True

    if c == "/memory":
        print("[已废弃] /memory 已由 /sms 取代，请使用：")
        print("  /sms show        交互式选择")
        print("  /sms new <name>  新建")
        print("  /sms rm <id>     删除")
        return True
'''
        new_text = pat_mem_cmd.sub(lambda _: new_cmd, new_text, count=1)
    elif '    if c == "/sms":' not in new_text:
        missing.append("/memory 分支")

    # ---- ⑦ _show_adumbration 整函数替换 ----
    pat_func = re.compile(
        r'def _show_adumbration\(memory, config\):\n'
        r'(?:[ \t].*\n|\n)*'
        r'(?=(?:def |# |class |[A-Z_][A-Z0-9_]* *=|if __name__|\Z))',
        re.MULTILINE,
    )
    m_func = pat_func.search(new_text)
    if m_func:
        new_func = '''def _show_adumbration(memory, ms_mgr):
    data = memory.data
    meta = ms_mgr._meta(ms_mgr.active_id) or {}
    summary = (data.get("summary") or "").strip()
    recent = data.get("recent_messages", [])
    total_turns = data.get("total_turns", 0)
    topics = data.get("topics", [])
    if summary:
        summary_short = summary[:60] + ("..." if len(summary) > 60 else "")
    else:
        summary_short = "（空）"
    enabled_cnt = len(tools_module.ENABLED_TOOLS)
    total_cnt = len(tools_module.TOOL_REGISTRY)
    print(f"\\n[记忆轮廓]")
    print(f"  记忆系统  : {meta.get('name', '?')} ({meta.get('id', '?')})")
    print(f"  描述      : {meta.get('description') or '（暂无）'}")
    print(f"  长期摘要  : {summary_short}")
    print(f"  近期对话  : {len(recent)} 条  (注入最近 6 条)")
    print(f"  累计轮数  : {total_turns}  (每 20 轮压缩一次)")
    print(f"  话题标签  : {', '.join(topics) if topics else '（无）'}")
    print(f"  启用工具  : {enabled_cnt} / {total_cnt}")
    print(f"  最后调用  : {meta.get('last_active_at', '?')}")
    print()


'''
        new_text = new_text[:m_func.start()] + new_func + new_text[m_func.end():]
    elif "def _show_adumbration(memory, ms_mgr):" not in new_text:
        missing.append("_show_adumbration 函数")

    if missing:
        return "error", f"未匹配：{'; '.join(missing)}"

    detail = "集成 /sms（7 个区块，regex 匹配）"
    if mode == "check":
        return "need", detail
    if mode == "dry-run":
        print(show_diff(text, new_text, max_lines=300))
        return "need", detail

    backup(target)
    write_text_preserve_bom(target, _denormalize_for_write(new_text, had_crlf), bom)
    return "applied", detail

# =============================================================
# 注册表 & 主入口
# =============================================================

FIXES: list[tuple[str, Callable[[Path, str], tuple[str, str]]]] = [
    ("1.  PS1 退出段 (try/finally + PID)",  fix_ps1_exit),
    ("1b. PS1 DEFAULT_MODELS_PATH 相对化",  fix_ps1_models_path),
    ("2.  创建 src/common/paths.py",        fix_paths_module),
    ("3.  config_manager.py 默认值",        fix_config_manager),
    ("4.  ollama_manager.py 模型目录",      fix_ollama_manager),
    ("5.  memory_manager.py resolve()",     fix_memory_manager),
    ("6.  agent.py SYSTEM_PROMPT 路径",     fix_agent_prompt),
    ("7.  移除 config/config_manager/",     fix_remove_redundant),
    ("8.  创建 src/common/console_input.py", fix_console_input),
    ("9.  创建 src/memory_manager/ms_manager.py", fix_ms_manager),
    ("10. 创建 src/memory_manager/ms_ui.py", fix_ms_ui),
    ("11. memory_manager/__init__.py 导出",  fix_memory_init),
    ("12. agent.py 集成 /sms",              fix_agent_sms),
]


def syntax_check(root: Path) -> list[tuple[str, str, str]]:
    import ast
    targets = [
        "src/agent/agent.py",
        "src/config_manager/config_manager.py",
        "src/ollama_manager/ollama_manager.py",
        "src/memory_manager/memory_manager.py",
        "src/memory_manager/ms_manager.py",
        "src/memory_manager/ms_ui.py",
        "src/memory_manager/__init__.py",
        "src/common/paths.py",
        "src/common/console_input.py",
    ]
    results: list[tuple[str, str, str]] = []
    print("=" * 60)
    print("语法校验:")
    for py in targets:
        f = root / py
        if not f.exists():
            print(f"  [skip] {py}")
            continue
        try:
            ast.parse(f.read_text(encoding="utf-8"))
            print(f"  [ok]   {py}")
        except SyntaxError as e:
            msg = f"line {e.lineno}: {e.msg}"
            print(f"  [FAIL] {py}: {msg}")
            results.append((f"语法 {py}", "error", msg))
    return results


def main() -> int:
    mode = "apply"
    if "--check" in sys.argv:
        mode = "check"
    elif "--dry-run" in sys.argv or "-n" in sys.argv:
        mode = "dry-run"

    root = find_root(Path(__file__).resolve().parent)
    print(f"[root] {root}")
    print(f"[mode] {mode}")
    print()

    results: list[tuple[str, str, str]] = []
    for name, fn in FIXES:
        print(f"=== {name} ===")
        try:
            status, detail = fn(root, mode)
        except Exception as e:
            status, detail = "error", f"{type(e).__name__}: {e}"
        print(f"  → [{status}] {detail}")
        print()
        results.append((name, status, detail))

    if mode == "apply":
        results.extend(syntax_check(root))

    print("=" * 60)
    print("汇总:")
    for name, status, detail in results:
        print(f"  [{status:8}] {name}: {detail}")

    failed = [r for r in results if r[1] == "error"]
    needs = [r for r in results if r[1] == "need"]

    if mode == "check":
        if needs:
            print(f"\n[mode=check] {len(needs)} 项待修补。运行 `python fix-once.py` 应用。")
        elif not failed:
            print("\n[mode=check] 全部 OK。")
    if failed:
        print(f"\n[!] {len(failed)} 项失败")
        return 1
    if mode == "apply" and not failed:
        print("\n[完成] 请重启 start-kurama.bat 生效。")
    return 0


if __name__ == "__main__":
    sys.exit(main())