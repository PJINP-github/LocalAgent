# =====================================================
#  Kurama Launcher - 强化进程清理版
#  Target: Ollama 0.40.x (含 0.40.5) + Intel Arc 130T
#  核心改动：彻底清理 ollama / llama-server / ollama-runner
# =====================================================

$ErrorActionPreference = "Continue"
$Host.UI.RawUI.WindowTitle = "Kurama Launcher"

try { chcp 65001 | Out-Null } catch {}
$OutputEncoding = [System.Text.Encoding]::UTF8
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
[Console]::InputEncoding  = [System.Text.Encoding]::UTF8
$env:PYTHONUNBUFFERED = "1"
$env:PYTHONIOENCODING = "utf-8"

# ===== 统一模型目录 =====
$env:OLLAMA_MODELS = "D:\APP\Ollama\Models"
[Environment]::SetEnvironmentVariable("OLLAMA_MODELS", "D:\APP\Ollama\Models", "User")

function Write-Step($msg) { Write-Host "[*] $msg" -ForegroundColor Cyan }
function Write-OK($msg)   { Write-Host "[OK] $msg" -ForegroundColor Green }
function Write-Warn($msg) { Write-Host "[!] $msg" -ForegroundColor Yellow }
function Write-Err($msg)  { Write-Host "[X] $msg" -ForegroundColor Red }


# ============================================================
#  强化清理函数：彻底杀掉所有 Ollama / Llama 相关进程
#  返回：$true 表示清理干净（显存已释放），$false 表示仍有残留
# ============================================================
function Clear-OllamaProcesses {
    param(
        [int]$MaxWaitSeconds = 60,
        [double]$SharedMemWarnGB = 3.0
    )

    Write-Step "清理 Ollama / Llama 相关进程..."

    # ---- 1. 先杀 GUI 托盘，防止它自动重启 serve ----
    $guiNames = @("ollama app")
    foreach ($n in $guiNames) {
        try {
            $procs = Get-Process -Name $n -ErrorAction SilentlyContinue
            foreach ($p in $procs) {
                Write-Host "  杀 GUI: $($p.Name) (PID $($p.Id))" -ForegroundColor DarkGray
                Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue
            }
        } catch {}
    }
    Start-Sleep -Milliseconds 500

    # ---- 2. 用 taskkill /T 杀进程树（覆盖子进程）----
    $killNames = @(
        "ollama.exe",
        "ollama app.exe",
        "llama-server.exe",
        "llama_server.exe",
        "ollama_llama_server.exe",
        "ollama-runner.exe",
        "ollama_runner.exe"
    )
    foreach ($name in $killNames) {
        try {
            $out = & taskkill /F /T /IM $name 2>&1
            if ($LASTEXITCODE -eq 0) {
                Write-Host "  taskkill: $name" -ForegroundColor DarkGray
            }
        } catch {}
    }

    # ---- 3. WMI 兜底：扫所有名字/命令行含 ollama 或 llama-server 的进程 ----
    #   这一步能抓到 Get-Process -Name 因名字特殊/空格/变体而漏掉的进程
    try {
        $wmiProcs = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
            Where-Object {
                ($_.Name -and $_.Name -match '(?i)ollama|llama') -or
                ($_.CommandLine -and $_.CommandLine -match '(?i)ollama|llama[-_]?server')
            }
        foreach ($p in $wmiProcs) {
            if ($p.ProcessId -and $p.ProcessId -ne $PID) {
                Write-Host "  WMI 兜底杀: $($p.Name) (PID $($p.ProcessId))" -ForegroundColor DarkGray
                Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue
            }
        }
    } catch {}

    # ---- 4. 检查 11434 端口占用，有僵尸占用就杀 ----
    try {
        $conns = Get-NetTCPConnection -LocalPort 11434 -State Listen -ErrorAction SilentlyContinue
        if ($conns) {
            foreach ($c in $conns) {
                $ownerPid = $c.OwningProcess
                if ($ownerPid -and $ownerPid -ne $PID) {
                    $ownerName = (Get-Process -Id $ownerPid -ErrorAction SilentlyContinue).Name
                    Write-Host "  端口 11434 被占用：$ownerName (PID $ownerPid)，强杀" -ForegroundColor DarkGray
                    & taskkill /F /T /PID $ownerPid 2>&1 | Out-Null
                }
            }
        }
    } catch {}

    # ---- 5. 轮询等待所有相关进程真正退出 ----
    Write-Step "等待进程完全退出（最多 $MaxWaitSeconds 秒）..."
    $waited = 0
    $lastCount = -1
    while ($waited -lt $MaxWaitSeconds) {
        $remain = Get-Process -Name "ollama*", "llama*" -ErrorAction SilentlyContinue
        $count = if ($remain) { @($remain).Count } else { 0 }
        if ($count -eq 0) { break }

        # 每 2 秒再补杀一次（应对被重启的进程）
        if ($count -ne $lastCount -and $waited -gt 0) {
            Write-Host "  仍有 $count 个进程，补杀一轮..." -ForegroundColor DarkGray
            foreach ($p in $remain) {
                Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue
            }
        }
        $lastCount = $count
        Start-Sleep -Seconds 2
        $waited += 2
    }
    Write-Host "  已等待 $waited 秒" -ForegroundColor DarkGray

    # ---- 6. 校验共享显存 ----
    $sharedGB = -1
    try {
        $samples = (Get-Counter "\GPU Adapter Memory(*)\Shared Usage" -ErrorAction SilentlyContinue).CounterSamples
        if ($samples) {
            $max = ($samples | Sort-Object CookedValue -Descending | Select-Object -First 1).CookedValue
            $sharedGB = [math]::Round($max / 1GB, 2)
        }
    } catch {}

    if ($sharedGB -ge 0) {
        if ($sharedGB -gt $SharedMemWarnGB) {
            Write-Warn "共享显存仍占用 ${sharedGB} GB（阈值 $SharedMemWarnGB GB）"
            Write-Warn "  可能有其他程序在用显存（浏览器硬件加速 / 音乐播放器 / 上一轮残留）"
            Write-Warn "  建议：关闭浏览器后重试；或降低 num_ctx / 换 q4_0 KV Cache"
            return $false
        } else {
            Write-OK "共享显存已释放：${sharedGB} GB"
        }
    } else {
        Write-Warn "无法读取共享显存计数器，跳过校验"
    }

    # ---- 7. 最终确认没有残留 ----
    $final = Get-Process -Name "ollama*", "llama*" -ErrorAction SilentlyContinue
    if ($final) {
        Write-Warn "仍有进程残留：$($final.Name -join ', ')"
        return $false
    }

    return $true
}


# ===== 1. 读取配置 =====
$configPath = Join-Path $PSScriptRoot ".local-agent\config.json"

if (-not (Test-Path $configPath)) {
    Write-Err "未找到配置文件：$configPath"
    Write-Step "将使用默认配置继续（首次运行会启动 agent.py 交互向导）"
    $cfg = [PSCustomObject]@{ model = ""; available_models = @() }
} else {
    $cfg = $null
    try {
        $raw = Get-Content $configPath -Raw -Encoding UTF8
        $raw = $raw.TrimStart([char]0xFEFF)
        $cfg = $raw | ConvertFrom-Json
    } catch {
        Write-Err "配置文件解析失败：$($_.Exception.Message)"
        Read-Host "按回车退出"
        exit 1
    }
}

$available = @($cfg.available_models)
$lastModel = $cfg.model

# ===== 2. 交互式选择模型 =====
if ($available.Count -gt 0) {
    Write-Host ""
    Write-Host "===============================" -ForegroundColor Cyan
    Write-Host "  请选择要使用的模型" -ForegroundColor Cyan
    Write-Host "===============================" -ForegroundColor Cyan
    Write-Host ""

    for ($i = 0; $i -lt $available.Count; $i++) {
        $mark = ""
        if ($available[$i] -eq $lastModel) { $mark = "  (上次使用)" }
        Write-Host ("  [{0}] {1}{2}" -f ($i + 1), $available[$i], $mark)
    }

    Write-Host ""
    $choice = Read-Host "输入编号后回车（直接回车使用上次：$lastModel）"

    $model = $lastModel
    if ($choice -match '^\d+$') {
        $idx = [int]$choice - 1
        if ($idx -ge 0 -and $idx -lt $available.Count) {
            $model = $available[$idx]
        } else {
            Write-Warn "编号超出范围，使用上次选择"
        }
    }
    Write-Host ""
    Write-Host "[已选择] $model" -ForegroundColor Green
    Write-Host ""

    # 保存选择
    try {
        $cfg.model = $model
        $newJson = $cfg | ConvertTo-Json -Depth 10
        [System.IO.File]::WriteAllText($configPath, $newJson, [System.Text.UTF8Encoding]::new($false))
        Write-Step "已保存选择到 config.json"
    } catch {
        Write-Warn "保存配置失败：$($_.Exception.Message)"
    }
} else {
    Write-Warn "config.json 未配置 available_models，跳过模型选择"
    $model = $lastModel
    if (-not $model) {
        Write-Err "没有可用模型，请先在 config.json 中配置 available_models 和 model"
        Read-Host "按回车退出"
        exit 1
    }
    Write-Host "[使用] $model" -ForegroundColor Green
}

# ===== 3. 清理旧进程（核心改进）=====
Write-Step "[1/4] 停止所有 Ollama / Llama 进程..."

$clean = Clear-OllamaProcesses -MaxWaitSeconds 60 -SharedMemWarnGB 3.0
if (-not $clean) {
    Write-Warn "清理未完全成功，继续尝试启动（可能失败）"
    $go = Read-Host "是否继续启动？(y/N)"
    if ($go -ne "y" -and $go -ne "Y") {
        Write-Host "已取消。" -ForegroundColor Yellow
        Read-Host "按回车退出"
        exit 1
    }
}

# ===== 4. 设置 GPU 环境变量 =====
Write-Step "设置 GPU 加速环境变量..."

# 清理可能冲突的旧变量
$stale = @(
    "OLLAMA_FLASH_ATTENTION",
    "OLLAMA_KV_CACHE_TYPE",
    "OLLAMA_GPU_OVERHEAD",
    "OLLAMA_NUM_PARALLEL",
    "OLLAMA_MAX_LOADED_MODELS",
    "HIP_VISIBLE_DEVICES"
)
foreach ($name in $stale) {
    [Environment]::SetEnvironmentVariable($name, $null, "User")
    Remove-Item -Path "Env:$name" -ErrorAction SilentlyContinue
}

$env:OLLAMA_VULKAN          = "1"
$env:OLLAMA_IGPU_ENABLE     = "1"
$env:OLLAMA_INTEL_GPU       = "true"
$env:OLLAMA_FLASH_ATTENTION = "0"
$env:OLLAMA_KV_CACHE_TYPE   = "f16"
$env:OLLAMA_KEEP_ALIVE      = "5m"

[Environment]::SetEnvironmentVariable("OLLAMA_VULKAN", "1", "User")
[Environment]::SetEnvironmentVariable("OLLAMA_IGPU_ENABLE", "1", "User")
[Environment]::SetEnvironmentVariable("OLLAMA_INTEL_GPU", "true", "User")

# ===== 5. 启动 Ollama =====
Write-Step "[2/4] 后台启动 Ollama serve..."

$ollamaExe = Join-Path $env:LOCALAPPDATA "Programs\Ollama\ollama.exe"
if (-not (Test-Path $ollamaExe)) {
    # 兜底：从 PATH 找
    $found = (Get-Command ollama.exe -ErrorAction SilentlyContinue).Source
    if ($found) { $ollamaExe = $found }
}
if (-not (Test-Path $ollamaExe)) {
    Write-Err "找不到 ollama.exe（尝试过 LOCALAPPDATA 和 PATH）"
    Read-Host "按回车退出"
    exit 1
}

Start-Process -FilePath $ollamaExe -ArgumentList "serve" -WindowStyle Hidden

# 轮询等待 API 就绪（而不是死等 6 秒）
$apiReady = $false
for ($i = 0; $i -lt 30; $i++) {
    Start-Sleep -Seconds 1
    try {
        $r = Invoke-RestMethod -Uri "http://127.0.0.1:11434/api/version" -TimeoutSec 2 -ErrorAction Stop
        if ($r.version) { $apiReady = $true; break }
    } catch {}
}
if (-not $apiReady) {
    Write-Err "Ollama API 30 秒内未就绪，可能被端口占用或进程冲突"
    Write-Step "请检查：Get-NetTCPConnection -LocalPort 11434"
    Read-Host "按回车退出"
    exit 1
}
Write-OK "Ollama API 已就绪"

# ===== 6. 预热选中的模型 =====
Write-Step "[3/4] 预热模型 '$model'（首次可能 30-90 秒）..."

$body = @{
    model  = $model
    prompt = "hi"
    stream = $false
    options = @{ num_predict = 1 }
} | ConvertTo-Json -Depth 5

try {
    Invoke-RestMethod -Uri "http://127.0.0.1:11434/api/generate" `
        -Method Post -Body $body -ContentType "application/json" `
        -TimeoutSec 300 | Out-Null
    Write-OK "Warmup OK"
} catch {
    Write-Err "WARMUP FAILED: $($_.Exception.Message)"
    Write-Warn "常见原因：显存不足 / 模型文件损坏 / 上次进程未彻底退出"
    Write-Warn "排障："
    Write-Warn "  1. ollama ps              # 看是否加载成功"
    Write-Warn "  2. ollama logs            # 看 Ollama 日志"
    Write-Warn "  3. 降低 num_ctx：/set num_ctx 8192"
}

Write-Host ""
Write-Host "----- Ollama GPU status -----" -ForegroundColor Cyan
$psOutput = ollama ps 2>&1 | Out-String
Write-Host $psOutput
Write-Host "-----------------------------" -ForegroundColor Cyan

if ($psOutput -match "100% GPU") {
    Write-OK "Model is running 100% on GPU."
} else {
    Write-Warn "Model is NOT running 100% on GPU（可能 CPU 模式或加载失败）"
}
Write-Host ""

# ===== 7. 启动 Agent =====
Write-Step "[4/4] 启动 Kurama Agent..."

$pythonExe = Join-Path $PSScriptRoot "venv\Scripts\python.exe"
$agentPy   = Join-Path $PSScriptRoot "agent.py"

if (-not (Test-Path $pythonExe)) {
    Write-Err "找不到 venv python：$pythonExe"
    Write-Warn "请先创建 venv：python -m venv venv"
    Read-Host "按回车退出"
    exit 1
}
if (-not (Test-Path $agentPy)) {
    Write-Err "找不到 agent.py：$agentPy"
    Read-Host "按回车退出"
    exit 1
}

& $pythonExe -u $agentPy

Write-Host ""
Write-Host "Agent 已退出。" -ForegroundColor Cyan

# Agent 退出后，顺便清理一次 Ollama，防止残留
Write-Step "Agent 退出后清理 Ollama 进程..."
Clear-OllamaProcesses -MaxWaitSeconds 30 -SharedMemWarnGB 3.0 | Out-Null

Read-Host "按回车键关闭窗口"