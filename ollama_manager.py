#!/usr/bin/env python3
"""
Ollama Manager - 交互式启动/停止/状态查看
配置文件: config.yaml (同目录，首次运行自动生成)

v2 强化版：解决 Ollama 0.40.x 推理进程（llama-server / ollama-runner）
未彻底退出导致显存不释放的问题。
"""

import os
import sys
import time
import json
import shutil
import subprocess
import urllib.request
from pathlib import Path
from typing import Dict, Any, Optional

# Windows 下启用 ANSI 颜色 + UTF-8
if os.name == "nt":
    os.system("")
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

try:
    import yaml
except ImportError:
    print("[ERROR] 缺少 pyyaml，请运行: pip install pyyaml")
    sys.exit(1)

SCRIPT_DIR = Path(__file__).resolve().parent
CONFIG_PATH = SCRIPT_DIR / "config.yaml"


# ---------------- ANSI 颜色 ----------------
class C:
    RESET = "\033[0m"
    BOLD  = "\033[1m"
    RED   = "\033[31m"
    GREEN = "\033[32m"
    YELLOW= "\033[33m"
    BLUE  = "\033[34m"
    CYAN  = "\033[36m"
    GRAY  = "\033[90m"


def cprint(msg: str, color: str = ""):
    print(f"{color}{msg}{C.RESET}")


def clear_screen():
    os.system("cls" if os.name == "nt" else "clear")


# ---------------- 默认配置 ----------------
DEFAULT_CONFIG: Dict[str, Any] = {
    "ollama": {
        "executable": "",
        "models_path": "D:/APP/Ollama/Models",
        "host": "127.0.0.1:11434",
    },
    "gpu": {
        "use_vulkan": True,
        "enable_igpu": True,
        "kv_cache_type": "f16",
    },
    "context": {
        "length": 32768,
        "flash_attention": False,
    },
    "memory": {
        "max_gb": 21,
        "keep_alive": "5m",
    },
    "runtime": {
        "num_parallel": 1,
        "max_loaded_models": 1,
        "load_timeout": "10m",
    },
    "preload": {
        "enabled": True,
        "model": "qwen3-coder-48k:latest",
    },
    "cpu_mode": False,
    # ---- 清理相关的新增配置 ----
    "cleanup": {
        "wait_seconds": 60,          # 轮询等待进程退出的最长秒数
        "shared_mem_warn_gb": 3.0,   # 共享显存超过这个值就警告
        "api_ready_timeout": 30,     # API 就绪等待秒数
    },
}


# ---------------- 配置加载 ----------------
def deep_merge(base: dict, override: dict) -> dict:
    result = dict(base)
    for k, v in override.items():
        if k in result and isinstance(result[k], dict) and isinstance(v, dict):
            result[k] = deep_merge(result[k], v)
        else:
            result[k] = v
    return result


def load_config() -> Dict[str, Any]:
    if not CONFIG_PATH.exists():
        cprint(f"[INFO] 未找到 {CONFIG_PATH}，正在创建默认配置...", C.YELLOW)
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            yaml.safe_dump(DEFAULT_CONFIG, f, allow_unicode=True,
                           sort_keys=False, default_flow_style=False)
        return dict(DEFAULT_CONFIG)
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return deep_merge(DEFAULT_CONFIG, data)


def save_config(cfg: Dict[str, Any]):
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        yaml.safe_dump(cfg, f, allow_unicode=True,
                       sort_keys=False, default_flow_style=False)


# ---------------- 工具函数 ----------------
def find_ollama(cfg) -> Optional[str]:
    exe = cfg["ollama"].get("executable", "").strip()
    if exe and Path(exe).exists():
        return exe
    found = shutil.which("ollama")
    if found:
        return found
    candidates = [
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs/Ollama/ollama.exe",
        Path("C:/Program Files/Ollama/ollama.exe"),
    ]
    for p in candidates:
        if p.exists():
            return str(p)
    return None


def build_env(cfg) -> dict:
    env = os.environ.copy()
    o, g, ct, m, rt = (cfg["ollama"], cfg["gpu"], cfg["context"],
                       cfg["memory"], cfg["runtime"])
    cpu = cfg.get("cpu_mode", False)

    env["OLLAMA_HOST"] = o["host"]
    env["OLLAMA_MODELS"] = o["models_path"]

    if cpu:
        env["OLLAMA_VULKAN"] = "0"
        env["OLLAMA_IGPU_ENABLE"] = "0"
    else:
        env["OLLAMA_VULKAN"] = "1" if g["use_vulkan"] else "0"
        env["OLLAMA_IGPU_ENABLE"] = "1" if g["enable_igpu"] else "0"

    env["OLLAMA_KV_CACHE_TYPE"] = g["kv_cache_type"]
    env["OLLAMA_CONTEXT_LENGTH"] = str(ct["length"])
    env["OLLAMA_FLASH_ATTENTION"] = "1" if ct["flash_attention"] else "0"
    env["OLLAMA_KEEP_ALIVE"] = m["keep_alive"]
    env["OLLAMA_NUM_PARALLEL"] = str(rt["num_parallel"])
    env["OLLAMA_MAX_LOADED_MODELS"] = str(rt["max_loaded_models"])
    env["OLLAMA_LOAD_TIMEOUT"] = rt["load_timeout"]

    env["no_proxy"] = "localhost,127.0.0.1"
    env["NO_PROXY"] = "localhost,127.0.0.1"
    return env


def estimate_memory_gb(cfg):
    ctx = cfg["context"]["length"]
    kv_type = cfg["gpu"]["kv_cache_type"]
    kv_f16 = ctx / 1000 * 0.25
    if kv_type == "q8_0":
        kv = kv_f16 / 2
    elif kv_type == "q4_0":
        kv = kv_f16 / 4
    else:
        kv = kv_f16
    model = 10.0
    buf = 2.0
    return model + kv + buf, model, kv, buf


def is_running(host: str = "127.0.0.1:11434") -> bool:
    try:
        with urllib.request.urlopen(
            f"http://{host}/api/version", timeout=2
        ) as r:
            return r.status == 200
    except Exception:
        return False


# ============================================================
#  强化清理：彻底杀掉所有 Ollama / Llama 进程
# ============================================================
def _run_powershell(cmd: str, timeout: int = 30) -> str:
    """执行 PowerShell 单行命令，返回 stdout。失败返回空串。"""
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", cmd],
            capture_output=True, text=True, timeout=timeout,
            encoding="utf-8", errors="replace",
        )
        return (r.stdout or "").strip()
    except Exception:
        return ""


def _list_ollama_processes() -> list:
    """列出所有名字/命令行含 ollama 或 llama-server 的进程 (pid, name)。"""
    if os.name != "nt":
        try:
            out = subprocess.check_output(
                ["pgrep", "-af", "ollama|llama-server"],
                text=True, timeout=5,
            )
            result = []
            for line in out.strip().splitlines():
                parts = line.split(maxsplit=1)
                if parts:
                    result.append((parts[0], line))
            return result
        except Exception:
            return []

    # Windows: WMI 扫描（比 Get-Process -Name 更可靠）
    ps = (
        "Get-CimInstance Win32_Process | "
        "Where-Object { "
        "($_.Name -and $_.Name -match '(?i)ollama|llama') -or "
        "($_.CommandLine -and $_.CommandLine -match '(?i)ollama|llama[-_]?server') "
        "} | "
        "Select-Object ProcessId, Name, CommandLine | "
        "ConvertTo-Json -Compress"
    )
    out = _run_powershell(ps, timeout=15)
    if not out:
        return []
    try:
        data = json.loads(out)
        if isinstance(data, dict):
            data = [data]
        return [(str(p["ProcessId"]), f'{p["Name"]} (PID {p["ProcessId"]})')
                for p in data if p.get("ProcessId")]
    except Exception:
        return []


def _get_shared_mem_gb() -> float:
    """读取共享显存占用（GB），失败返回 -1。"""
    if os.name != "nt":
        return -1.0
    ps = (
        "(Get-Counter '\\GPU Adapter Memory(*)\\Shared Usage' "
        "-ErrorAction SilentlyContinue).CounterSamples | "
        "Sort-Object CookedValue -Descending | "
        "Select-Object -First 1 -ExpandProperty CookedValue"
    )
    out = _run_powershell(ps, timeout=10)
    if not out:
        return -1.0
    try:
        return round(float(out) / (1024 ** 3), 2)
    except ValueError:
        return -1.0


def kill_ollama(cfg=None) -> bool:
    """
    强化清理：
      1. 先杀 GUI（ollama app），防自动重启
      2. taskkill /F /T 杀进程树
      3. WMI 兜底扫全进程
      4. 查 11434 端口占用
      5. 轮询等进程真死
      6. 校验共享显存
    返回 True 表示清理干净。
    """
    cfg = cfg or {}
    wait_seconds = cfg.get("cleanup", {}).get("wait_seconds", 60)
    warn_gb = cfg.get("cleanup", {}).get("shared_mem_warn_gb", 3.0)

    cprint("[*] 清理 Ollama / Llama 相关进程...", C.CYAN)

    # ---- 1. 先杀 GUI（防止它重启 serve）----
    if os.name == "nt":
        for gui_name in ("ollama app.exe", "ollama app"):
            try:
                subprocess.run(
                    ["taskkill", "/F", "/T", "/IM", gui_name],
                    capture_output=True, timeout=5,
                )
            except Exception:
                pass
    time.sleep(0.5)

    # ---- 2. taskkill /F /T 杀进程树 ----
    kill_names = [
        "ollama.exe", "ollama app.exe",
        "llama-server.exe", "llama_server.exe",
        "ollama_llama_server.exe",
        "ollama-runner.exe", "ollama_runner.exe",
    ]
    if os.name == "nt":
        for name in kill_names:
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

    # ---- 3. WMI 兜底 ----
    procs = _list_ollama_processes()
    for pid, desc in procs:
        cprint(f"  WMI 兜底杀: {desc}", C.GRAY)
        if os.name == "nt":
            try:
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", pid],
                    capture_output=True, timeout=5,
                )
            except Exception:
                pass
        else:
            try:
                subprocess.run(["kill", "-9", pid],
                               capture_output=True, timeout=5)
            except Exception:
                pass

    # ---- 4. 检查 11434 端口占用 ----
    if os.name == "nt":
        port_pids = _run_powershell(
            "Get-NetTCPConnection -LocalPort 11434 -State Listen "
            "-ErrorAction SilentlyContinue | "
            "Select-Object -ExpandProperty OwningProcess",
            timeout=10,
        )
        for line in port_pids.splitlines():
            pid = line.strip()
            if pid and pid.isdigit() and int(pid) != os.getpid():
                cprint(f"  端口 11434 被占用 PID {pid}，强杀", C.GRAY)
                try:
                    subprocess.run(
                        ["taskkill", "/F", "/T", "/PID", pid],
                        capture_output=True, timeout=5,
                    )
                except Exception:
                    pass

    # ---- 5. 轮询等待进程真死 ----
    cprint(f"[*] 等待进程完全退出（最多 {wait_seconds} 秒）...", C.CYAN)
    waited = 0
    last_count = -1
    while waited < wait_seconds:
        remain = _list_ollama_processes()
        count = len(remain)
        if count == 0:
            break
        if count != last_count and waited > 0:
            cprint(f"  仍有 {count} 个进程，补杀一轮...", C.GRAY)
            for pid, desc in remain:
                if os.name == "nt":
                    try:
                        subprocess.run(
                            ["taskkill", "/F", "/T", "/PID", pid],
                            capture_output=True, timeout=5,
                        )
                    except Exception:
                        pass
                else:
                    try:
                        subprocess.run(["kill", "-9", pid],
                                       capture_output=True, timeout=5)
                    except Exception:
                        pass
        last_count = count
        time.sleep(2)
        waited += 2
    cprint(f"  已等待 {waited} 秒", C.GRAY)

    # ---- 6. 校验共享显存 ----
    shared = _get_shared_mem_gb()
    if shared >= 0:
        if shared > warn_gb:
            cprint(f"[!] 共享显存仍占用 {shared} GB（阈值 {warn_gb} GB）", C.YELLOW)
            cprint("    可能有其他程序在用显存（浏览器硬件加速 / 音乐播放器 / 上一轮残留）", C.YELLOW)
            cprint("    建议：关闭浏览器后重试；或降低 context.length / 换 q4_0 KV Cache", C.YELLOW)
            return False
        else:
            cprint(f"[OK] 共享显存已释放：{shared} GB", C.GREEN)

    # ---- 7. 最终确认 ----
    final = _list_ollama_processes()
    if final:
        cprint(f"[!] 仍有进程残留：{', '.join(d for _, d in final)}", C.YELLOW)
        return False
    return True


# ---------------- 查看状态 ----------------
def show_status(cfg):
    clear_screen()
    cprint("=" * 60, C.CYAN)
    cprint("   Ollama 当前状态", C.BOLD + C.CYAN)
    cprint("=" * 60, C.CYAN)
    print()

    running = is_running(cfg["ollama"]["host"])
    procs = _list_ollama_processes()

    cprint("[服务]", C.BOLD)
    cprint(f"  地址:    {cfg['ollama']['host']}", C.GRAY)
    cprint(f"  状态:    {'● 运行中' if running else '○ 未运行'}",
           C.GREEN if running else C.RED)
    cprint(f"  进程数:  {len(procs)}", C.GRAY)
    for pid, desc in procs:
        cprint(f"    - {desc}", C.GRAY)
    print()

    shared = _get_shared_mem_gb()
    if shared >= 0:
        color = C.GREEN if shared <= cfg["cleanup"]["shared_mem_warn_gb"] else C.YELLOW
        cprint(f"[共享显存] {shared} GB", color)
        print()

    cprint("[当前配置]", C.BOLD)
    mode = "CPU" if cfg.get("cpu_mode") else "GPU/Vulkan"
    rows = [
        ("运行模式", mode),
        ("模型路径", cfg["ollama"]["models_path"]),
        ("Vulkan", cfg["gpu"]["use_vulkan"]),
        ("iGPU",   cfg["gpu"]["enable_igpu"]),
        ("KV Cache", cfg["gpu"]["kv_cache_type"]),
        ("上下文长度", cfg["context"]["length"]),
        ("Flash Attention", cfg["context"]["flash_attention"]),
        ("内存上限", f"{cfg['memory']['max_gb']} GB"),
    ]
    for k, v in rows:
        cprint(f"  {k:<18} = {v}", C.GRAY)
    print()

    total, model, kv, buf = estimate_memory_gb(cfg)
    max_gb = cfg["memory"]["max_gb"]
    cprint("[内存估算]", C.BOLD)
    cprint(f"  模型权重:  ~{model:.1f} GB", C.GRAY)
    cprint(f"  KV Cache:  ~{kv:.1f} GB", C.GRAY)
    cprint(f"  计算缓冲:  ~{buf:.1f} GB", C.GRAY)
    color = C.GREEN if total <= max_gb else C.YELLOW
    cprint(f"  预计总占用: ~{total:.1f} GB / 上限 {max_gb} GB", color)
    print()

    if running:
        try:
            with urllib.request.urlopen(
                f"http://{cfg['ollama']['host']}/api/ps", timeout=3
            ) as r:
                data = json.loads(r.read().decode())
                models = data.get("models", [])
                cprint(f"[已加载模型] {len(models)} 个", C.BOLD)
                for m in models:
                    name = m.get("name", "?")
                    size_gb = m.get("size", 0) / 1e9
                    cprint(f"  - {name}   {size_gb:.1f} GB", C.GRAY)
        except Exception:
            pass
        print()

    input("按回车返回主菜单...")


# ---------------- 启动服务 ----------------
def start_service(cfg):
    clear_screen()
    cprint("=" * 60, C.CYAN)
    cprint("   启动 Ollama 服务", C.BOLD + C.CYAN)
    cprint("=" * 60, C.CYAN)
    print()

    if is_running(cfg["ollama"]["host"]):
        cprint("[WARN] Ollama 已在运行。", C.YELLOW)
        choice = input("是否先关闭再重启？(y/N): ").strip().lower()
        if choice != "y":
            return

    # 内存检查
    total, model, kv, buf = estimate_memory_gb(cfg)
    max_gb = cfg["memory"]["max_gb"]
    cprint("[内存估算]", C.CYAN)
    cprint(f"  模型权重:  ~{model:.1f} GB", C.GRAY)
    cprint(f"  KV Cache:  ~{kv:.1f} GB", C.GRAY)
    cprint(f"  计算缓冲:  ~{buf:.1f} GB", C.GRAY)
    cprint(f"  合计:      ~{total:.1f} GB", C.GRAY)
    cprint(f"  配置上限:   {max_gb} GB", C.GRAY)

    if total > max_gb:
        cprint("\n[警告] 预计占用超过配置上限。", C.YELLOW)
        cprint("       建议降低 context.length 或改用 q4_0 KV Cache。", C.YELLOW)
        choice = input("\n仍要继续吗？(y/N): ").strip().lower()
        if choice != "y":
            return

    # ---- 强化清理 ----
    clean = kill_ollama(cfg)
    if not clean:
        cprint("\n[WARN] 清理未完全成功，继续启动可能失败。", C.YELLOW)
        if input("是否继续？(y/N): ").strip().lower() != "y":
            return

    exe = find_ollama(cfg)
    if not exe:
        cprint("\n[ERROR] 找不到 ollama.exe。", C.RED)
        cprint("        请在 config.yaml 中设置 ollama.executable", C.YELLOW)
        input("\n按回车返回主菜单...")
        return

    mode = "CPU" if cfg.get("cpu_mode") else "GPU/Vulkan"
    cprint(f"\n[启动] {exe}", C.GRAY)
    cprint(f"[模式] {mode}", C.GRAY)
    cprint(f"[上下文] {cfg['context']['length']}", C.GRAY)
    cprint(f"[KV Cache] {cfg['gpu']['kv_cache_type']}", C.GRAY)
    cprint("\n按 Ctrl+C 停止服务并返回菜单", C.YELLOW)
    cprint("-" * 60, C.GRAY)

    env = build_env(cfg)
    try:
        proc = subprocess.Popen([exe, "serve"], env=env)

        # ---- 轮询等待 API 就绪 ----
        timeout = cfg["cleanup"]["api_ready_timeout"]
        ready = False
        for _ in range(timeout):
            if is_running(cfg["ollama"]["host"]):
                ready = True
                break
            time.sleep(1)
        if ready:
            cprint("[OK] Ollama API 已就绪", C.GREEN)
        else:
            cprint(f"[WARN] {timeout} 秒内 API 未就绪", C.YELLOW)

        # ---- 预热 ----
        if ready and cfg["preload"]["enabled"] and cfg["preload"]["model"]:
            model_name = cfg["preload"]["model"]
            cprint(f"\n[预热] 加载模型 {model_name} ...", C.CYAN)
            try:
                req = urllib.request.Request(
                    f"http://{cfg['ollama']['host']}/api/generate",
                    data=json.dumps({
                        "model": model_name,
                        "prompt": "hi",
                        "stream": False,
                        "options": {"num_predict": 1},
                    }).encode(),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=900) as r:
                    r.read()
                cprint("[预热] 完成 ✓", C.GREEN)
            except Exception as e:
                cprint(f"[预热] 失败: {e}", C.YELLOW)

        cprint("\n" + "=" * 60, C.GREEN)
        cprint("  服务运行中。日志如下（Ctrl+C 停止）：", C.GREEN)
        cprint("=" * 60, C.GREEN)
        print()

        proc.wait()

    except KeyboardInterrupt:
        cprint("\n\n[INFO] 收到 Ctrl+C，正在停止服务...", C.YELLOW)
    except Exception as e:
        cprint(f"\n[ERROR] 运行异常: {e}", C.RED)
    finally:
        kill_ollama(cfg)
        cprint("[OK] 服务已停止。", C.GREEN)

    input("\n按回车返回主菜单...")


# ---------------- 停止服务 ----------------
def stop_service(cfg):
    clear_screen()
    cprint("=" * 60, C.CYAN)
    cprint("   关闭所有 Ollama 进程", C.BOLD + C.CYAN)
    cprint("=" * 60, C.CYAN)
    print()

    procs = _list_ollama_processes()
    if not procs:
        cprint("[INFO] 当前没有运行中的 Ollama 进程。", C.YELLOW)
        input("\n按回车返回主菜单...")
        return

    cprint(f"[INFO] 正在关闭 {len(procs)} 个进程", C.YELLOW)
    clean = kill_ollama(cfg)

    if is_running(cfg["ollama"]["host"]):
        cprint("[WARN] 服务仍在响应，可能还有残留。", C.RED)
    elif clean:
        cprint("[OK] 已全部关闭，显存已释放。", C.GREEN)
    else:
        cprint("[WARN] 部分进程仍在运行。", C.YELLOW)

    input("\n按回车返回主菜单...")


# ---------------- 切换模式 ----------------
def toggle_mode(cfg):
    current = cfg.get("cpu_mode", False)
    cfg["cpu_mode"] = not current
    save_config(cfg)
    new_mode = "CPU" if cfg["cpu_mode"] else "GPU/Vulkan"
    cprint(f"\n[OK] 已切换到 {new_mode} 模式", C.GREEN)
    if new_mode == "GPU/Vulkan":
        cprint("     下次启动时将使用 Vulkan + iGPU。", C.GRAY)
    else:
        cprint("     下次启动时将强制使用 CPU。", C.GRAY)
    input("\n按回车返回主菜单...")


# ---------------- 编辑配置 ----------------
def edit_config(cfg):
    clear_screen()
    cprint(f"配置文件: {CONFIG_PATH}", C.CYAN)
    cprint("编辑完成后保存关闭，返回主菜单会自动重新加载。", C.GRAY)
    print()
    editor = os.environ.get("EDITOR")
    if not editor:
        editor = "notepad" if os.name == "nt" else "vim"
    try:
        subprocess.run([editor, str(CONFIG_PATH)])
    except Exception as e:
        cprint(f"[ERROR] 无法启动编辑器: {e}", C.RED)
        input("按回车返回主菜单...")


# ---------------- 主菜单 ----------------
def show_menu(cfg):
    clear_screen()
    cprint("=" * 60, C.CYAN)
    cprint("   Ollama Manager - Intel Arc / Vulkan", C.BOLD + C.CYAN)
    cprint("=" * 60, C.CYAN)
    print()

    running = is_running(cfg["ollama"]["host"])
    status = f"{C.GREEN}● 运行中{C.RESET}" if running else f"{C.RED}○ 未运行{C.RESET}"
    mode = "CPU" if cfg.get("cpu_mode") else "GPU/Vulkan"
    kv = cfg["gpu"]["kv_cache_type"]
    ctx = cfg["context"]["length"]
    procs = _list_ollama_processes()
    shared = _get_shared_mem_gb()

    cprint(f"  状态: {status}   进程: {len(procs)}   模式: {mode}", C.GRAY)
    cprint(f"  上下文: {ctx}   KV: {kv}", C.GRAY)
    if shared >= 0:
        cprint(f"  共享显存: {shared} GB", C.GRAY)
    print()

    cprint("  [1] 启动服务", C.BOLD)
    cprint("  [2] 关闭所有 Ollama 进程", C.BOLD)
    cprint("  [3] 查看当前状态", C.BOLD)
    cprint("  [4] 切换 CPU / GPU 模式", C.BOLD)
    cprint("  [5] 编辑配置 (config.yaml)", C.BOLD)
    cprint("  [c] 仅清理进程（不启动）", C.BOLD)
    cprint("  [r] 重新加载配置", C.BOLD)
    cprint("  [q] 退出", C.BOLD)
    print()


def main():
    cfg = load_config()
    while True:
        try:
            show_menu(cfg)
            choice = input("请选择 > ").strip().lower()
            if choice == "1":
                start_service(cfg)
            elif choice == "2":
                stop_service(cfg)
            elif choice == "3":
                show_status(cfg)
            elif choice == "4":
                toggle_mode(cfg)
            elif choice == "5":
                edit_config(cfg)
                cfg = load_config()
                cprint("\n[OK] 配置已重新加载", C.GREEN)
                time.sleep(1)
            elif choice == "c":
                clear_screen()
                cprint("=" * 60, C.CYAN)
                cprint("   仅清理进程", C.BOLD + C.CYAN)
                cprint("=" * 60, C.CYAN)
                print()
                kill_ollama(cfg)
                input("\n按回车返回主菜单...")
            elif choice == "r":
                cfg = load_config()
                cprint("\n[OK] 配置已重新加载", C.GREEN)
                time.sleep(1)
            elif choice == "q":
                cprint("\n再见！", C.CYAN)
                break
            else:
                cprint("\n无效选项。", C.YELLOW)
                time.sleep(1)
        except KeyboardInterrupt:
            cprint("\n\n[INFO] 中断，返回主菜单", C.YELLOW)
            time.sleep(1)


if __name__ == "__main__":
    main()