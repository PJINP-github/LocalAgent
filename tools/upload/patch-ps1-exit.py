#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""patch-ps1-exit.py — 替换 start-kurama.ps1 的 [4/5]-[5/5] 退出段

改动：
  1. try/finally 包住 agent 调用
  2. 记录 ollama serve 的 PID，finally 里 taskkill /T 精确清理
  3. Clear-OllamaProcesses 兜底 + taskkill 二次兜底

用法:
    python tools/upload/patch-ps1-exit.py --dry-run
    python tools/upload/patch-ps1-exit.py
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


NEW_BLOCK = r'''# 记录 ollama serve 的 PID（精确清理用）
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


def main() -> int:
    root = find_root(Path(__file__).resolve().parent)
    target = root / "start-kurama.ps1"
    log("root", str(root))
    log("target", str(target.relative_to(root)))

    if not target.is_file():
        log("error", f"not found: {target}")
        return 1

    # 保留 BOM
    raw = target.read_bytes()
    bom = b""
    if raw.startswith(b"\xef\xbb\xbf"):
        bom = b"\xef\xbb\xbf"
        raw = raw[3:]
    text = raw.decode("utf-8")

    if "$script:OllamaServePid" in text and "PipelineStoppedException" in text:
        log("info", "已 patch（幂等）")
        return 0

    # 匹配从 `& $pythonExe -u -m src.agent` 到 `Read-Host "按回车关闭窗口"` 的整段
    pat = re.compile(
        r'&\s*\$pythonExe\s+-u\s+-m\s+src\.agent.*?Read-Host\s+"按回车关闭窗口"',
        re.DOTALL,
    )
    m = pat.search(text)
    if not m:
        log("error", "未匹配到 agent 启动段（找 `& $pythonExe -u -m src.agent` ~ `Read-Host 按回车关闭窗口`）")
        log("hint", "打开 start-kurama.ps1 搜 `src.agent`，把附近 20 行贴出来")
        return 1

    new_text = text[:m.start()] + NEW_BLOCK + text[m.end():]
    log("fix", "替换 [4/5]-[5/5] 段（try/finally + PID 追踪）")

    if DRY_RUN:
        log("mode", "DRY-RUN — 未写入")
        # 显示匹配范围
        preview = m.group(0)
        log("preview", f"原段 {len(preview)} 字符，新段 {len(NEW_BLOCK)} 字符")
        return 0

    bak = target.with_suffix(".ps1.bak")
    if not bak.exists():
        shutil.copy2(target, bak)
        log("backup", str(bak.relative_to(root)))

    out = bom + new_text.encode("utf-8")
    target.write_bytes(out)
    log("done", f"已写入 {target.relative_to(root)}")

    # BOM 校验
    new_raw = target.read_bytes()
    ok = new_raw.startswith(b"\xef\xbb\xbf")
    log("info", f"BOM: {'EF BB BF ✓' if ok else '✗ 缺失，请手动补'}")

    print()
    print("下一步:")
    print("  $errors = $null")
    print("  $null = [System.Management.Automation.Language.Parser]::ParseFile(")
    print("      (Resolve-Path .\\start-kurama.ps1), [ref]$null, [ref]$errors)")
    print("  if ($errors) { $errors | Format-List } else { '语法 OK' }")
    return 0


if __name__ == "__main__":
    sys.exit(main())