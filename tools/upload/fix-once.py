#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fix-once.py — 一键修复 Kurama 项目全部已知问题

覆盖项（幂等，可重复执行）：
  1.   start-kurama.ps1 退出段：try/finally + PID 追踪 + 进程清理
  1b.  start-kurama.ps1 $DEFAULT_MODELS_PATH → Join-Path $PSScriptRoot
  2.   新建 src/common/paths.py 统一路径解析
  3.   src/config_manager/config_manager.py 默认值 → 相对路径
  4.   src/ollama_manager/ollama_manager.py 模型目录 → PROJECT_ROOT 推导 + _models_dir
  5.   src/memory_manager/memory_manager.py 使用 resolve()
  6.   src/agent/agent.py SYSTEM_PROMPT 路径段（lambda 包裹防 re.sub 陷阱）
  7.   移除 config/config_manager/ 冗余副本（移至 config/.trash/）

安全：
  - 幂等：命中已修状态即 ok
  - BOM 保真
  - 首次写入前 .bak 备份
  - agent.py 检测到"被上一版破坏"时自动从 .bak 恢复再重新 patch
  - 末尾 ast.parse 语法守门员

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
# 常量：src/common/paths.py 内容
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


def show_diff(old: str, new: str, max_lines: int = 60) -> str:
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


# =============================================================
# 各 fix 函数：返回 (status, detail)
# status ∈ {ok, need, applied, skip, error}
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
        return "error", "未匹配到 agent 启动段（找 `& $pythonExe -u -m src.agent` ~ `Read-Host 按回车关闭窗口`）"

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
        return "skip", "未找到旧 DEFAULT_MODELS_PATH 字面量（可能已手动改过）"

    if mode == "check":
        return "need", "DEFAULT_MODELS_PATH → Join-Path $PSScriptRoot"
    if mode == "dry-run":
        print(f"- {old}\n+ {new}")
        return "need", "DEFAULT_MODELS_PATH → Join-Path $PSScriptRoot"

    backup(target)
    write_text_preserve_bom(target, text.replace(old, new, 1), bom)
    return "applied", "DEFAULT_MODELS_PATH → Join-Path $PSScriptRoot"


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
        print("变更:")
        for c in changes:
            print(f"  - {c}")
        return "need", "; ".join(changes)

    backup(target)
    write_text_preserve_bom(target, text, bom)
    return "applied", "; ".join(changes)


def fix_ollama_manager(root: Path, mode: str) -> tuple[str, str]:
    target = root / "src" / "ollama_manager" / "ollama_manager.py"
    rel = target.relative_to(root)
    if not target.is_file():
        return "skip", f"{rel} 不存在"

    text, bom = read_text_preserve_bom(target)
    changes = []

    # ① DEFAULT_MODELS_PATH 定义：硬编码 → PROJECT_ROOT 推导 + _models_dir
    old_def = r'DEFAULT_MODELS_PATH = r"C:\software\LocalAgent\sources\models"'
    new_def = (
        'DEFAULT_MODELS_REL = "sources/models"\n'
        'DEFAULT_MODELS_PATH = str(PROJECT_ROOT / DEFAULT_MODELS_REL)\n'
        '\n'
        '\n'
        'def _models_dir(cfg_or_ollama) -> str:\n'
        '    """取有效的模型目录（相对 → 绝对）。Ollama 必须用绝对路径。"""\n'
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

    # ② DEFAULT_CONFIG.models_path → 相对
    old_cfg = '"models_path": DEFAULT_MODELS_PATH,'
    new_cfg = '"models_path": DEFAULT_MODELS_REL,'
    if old_cfg in text:
        text = text.replace(old_cfg, new_cfg, 1)
        changes.append("DEFAULT_CONFIG.models_path → 相对")

    # ③ build_env
    old_be = 'models_path = (o.get("models_path") or "").strip() or DEFAULT_MODELS_PATH'
    new_be = 'models_path = _models_dir(o)'
    if old_be in text:
        text = text.replace(old_be, new_be)
        changes.append("build_env 使用 _models_dir")

    # ④ start_service
    old_ss = 'models_path = (cfg["ollama"].get("models_path") or "").strip() or DEFAULT_MODELS_PATH'
    new_ss = 'models_path = _models_dir(cfg)'
    if old_ss in text:
        text = text.replace(old_ss, new_ss)
        changes.append("start_service 使用 _models_dir")

    # ⑤ show_status
    old_es = 'effective_models = (cfg["ollama"].get("models_path") or "").strip() or DEFAULT_MODELS_PATH'
    new_es = 'effective_models = _models_dir(cfg)'
    if old_es in text:
        text = text.replace(old_es, new_es)
        changes.append("show_status 使用 _models_dir")

    # ⑥ show_menu
    old_sm = 'models_eff = (cfg["ollama"].get("models_path") or "").strip() or DEFAULT_MODELS_PATH'
    new_sm = 'models_eff = _models_dir(cfg)'
    if old_sm in text:
        text = text.replace(old_sm, new_sm)
        changes.append("show_menu 使用 _models_dir")

    if not changes:
        return "ok", "已是相对路径"

    if mode == "check":
        return "need", "; ".join(changes)
    if mode == "dry-run":
        print("变更:")
        for c in changes:
            print(f"  - {c}")
        return "need", "; ".join(changes)

    backup(target)
    write_text_preserve_bom(target, text, bom)
    return "applied", "; ".join(changes)


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
            text = text.replace(
                anchor,
                anchor + "\nfrom ..common.paths import resolve",
                1,
            )
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
        return "skip", "未找到可替换的路径逻辑（可能已被手动修改）"

    if mode == "check":
        return "need", "; ".join(changes)
    if mode == "dry-run":
        print("变更:")
        for c in changes:
            print(f"  - {c}")
        return "need", "; ".join(changes)

    backup(target)
    write_text_preserve_bom(target, text, bom)
    return "applied", "; ".join(changes)


def fix_agent_prompt(root: Path, mode: str) -> tuple[str, str]:
    """SYSTEM_PROMPT 路径段。

    ★ 关键：re.sub 的 repl 会被 re 模块二次处理反斜杠。
    必须用 lambda 包裹 new_block，否则源码里的字面 \\n 会被写成真换行，
    导致 `"【路径规范】\\n"` 变成断开的字符串 → SyntaxError。
    """
    target = root / "src" / "agent" / "agent.py"
    rel = target.relative_to(root)
    if not target.is_file():
        return "skip", f"{rel} 不存在"

    text, bom = read_text_preserve_bom(target)

    # ① 已正确：源码里有字面 \n 且有新语义标记
    if '"【路径规范】\\n"' in text and "相对项目根目录的路径" in text:
        return "ok", "SYSTEM_PROMPT 已更新（格式合法）"

    # ② 已损坏：有语义标记但缺字面 \n（上一版 re.sub 事故）
    if "相对项目根目录的路径" in text and '"【路径规范】\\n"' not in text:
        bak = target.with_name(target.name + ".bak")
        if not bak.exists():
            return "error", "agent.py 已损坏且无 .bak，请手动修复或从版本库重新拉取"
        if mode == "check":
            return "need", "agent.py 已损坏，需从 .bak 恢复后重新 patch"
        if mode == "dry-run":
            return "need", "将从 .bak 恢复 agent.py，再重新 patch"
        # 保留损坏副本供排查
        corrupted = target.with_name(target.name + ".corrupted")
        shutil.copy2(target, corrupted)
        shutil.copy2(bak, target)
        text, bom = read_text_preserve_bom(target)
        # 继续往下走正常 patch 流程

    # ③ 未 patch：匹配旧版路径段
    pat = re.compile(
        r'"【路径规范】\\n".*?"- 用户没给路径时，先问用户要哪个路径，不要自己假设。\\n"',
        re.DOTALL,
    )
    if not pat.search(text):
        return "skip", "未匹配到路径规范段（可能已被手动修改，跳过）"

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
        print(f"--- {rel}\n+++ {rel}\n（替换 [路径规范] 段，lambda 包裹防转义）")
        return "need", detail

    backup(target)
    # ★ lambda 包裹：跳过 re 模块对 repl 的反斜杠二次处理
    text = pat.sub(lambda _: new_block, text, count=1)
    write_text_preserve_bom(target, text, bom)
    return "applied", detail


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
]


def syntax_check(root: Path) -> list[tuple[str, str, str]]:
    """修补后语法守门员，返回失败列表。"""
    import ast
    results: list[tuple[str, str, str]] = []
    targets = [
        "src/agent/agent.py",
        "src/config_manager/config_manager.py",
        "src/ollama_manager/ollama_manager.py",
        "src/memory_manager/memory_manager.py",
        "src/common/paths.py",
    ]
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

    # 语法守门员（仅 apply 模式下写盘了才有意义）
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
            print(f"\n[mode=check] 有 {len(needs)} 项待修补。运行 `python fix-once.py` 应用。")
        elif not failed:
            print("\n[mode=check] 全部 OK。")
    if failed:
        print(f"\n[!] {len(failed)} 项失败")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())