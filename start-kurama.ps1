# =====================================================
#  Kurama Launcher - 交互式选择模型
#  Target: Intel Arc 130T via Vulkan (Ollama 0.32.6)
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

# ===== 1. 读取配置 =====
$configPath = Join-Path $PSScriptRoot ".local-agent\config.json"

if (-not (Test-Path $configPath)) {
    Write-Err "未找到配置文件：$configPath"
    Read-Host "按回车退出"
    exit 1
}

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

$available  = @($cfg.available_models)
$lastModel  = $cfg.model

if ($available.Count -eq 0) {
    Write-Err "available_models 为空，请检查配置文件"
    Read-Host "按回车退出"
    exit 1
}

# ===== 2. 交互式选择模型 =====
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

# ===== 3. 保存选择 =====
try {
    $cfg.model = $model
    $newJson = $cfg | ConvertTo-Json -Depth 10
    [System.IO.File]::WriteAllText($configPath, $newJson, [System.Text.UTF8Encoding]::new($false))
    Write-Step "已保存选择到 config.json"
} catch {
    Write-Warn "保存配置失败：$($_.Exception.Message)"
}

# ===== 4. 清理旧进程（包含 llama-server.exe）=====
Write-Step "[1/4] Stopping existing Ollama processes..."

$patterns = @("ollama*", "llama-server*", "llama_server*")
foreach ($pat in $patterns) {
    Get-Process -Name $pat -ErrorAction SilentlyContinue | ForEach-Object {
        try {
            Write-Host "  杀进程：$($_.Name) (PID $($_.Id))" -ForegroundColor DarkGray
            Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue
        } catch {}
    }
}

# 轮询等待所有相关进程退出，最多 30 秒
Write-Step "Waiting for GPU memory release..."
$waited = 0
while ($waited -lt 30) {
    $still = Get-Process -Name "ollama*", "llama-server*", "llama_server*" -ErrorAction SilentlyContinue
    if (-not $still) { break }
    Start-Sleep -Seconds 2
    $waited += 2
}
Start-Sleep -Seconds 3
Write-Host "[*] 已等待 $waited 秒，进程已清理" -ForegroundColor Cyan

# 检查共享显存
try {
    $shared = (Get-Counter "\GPU Adapter Memory(*)\Shared Usage" -ErrorAction SilentlyContinue).CounterSamples |
        Sort-Object CookedValue -Descending |
        Select-Object -First 1
    if ($shared) {
        $gb = [math]::Round($shared.CookedValue / 1GB, 2)
        Write-Host "[*] 当前共享显存占用：$gb GB" -ForegroundColor Cyan
        if ($gb -gt 6) {
            Write-Warn "共享显存仍然占用较高（$gb GB），可能有其他程序在用。"
            Write-Warn "如加载失败，请关闭浏览器/音乐播放器等使用硬件加速的程序。"
        }
    }
} catch {}

# ===== 5. 设置 GPU 环境变量 =====
Write-Step "Setting GPU acceleration environment variables..."

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

$env:OLLAMA_VULKAN = "1"
$env:OLLAMA_IGPU_ENABLE = "1"
$env:OLLAMA_INTEL_GPU = "true"
$env:OLLAMA_FLASH_ATTENTION = "0"
$env:OLLAMA_KV_CACHE_TYPE = "f16"
$env:OLLAMA_KEEP_ALIVE = "5m"

[Environment]::SetEnvironmentVariable("OLLAMA_VULKAN", "1", "User")
[Environment]::SetEnvironmentVariable("OLLAMA_IGPU_ENABLE", "1", "User")
[Environment]::SetEnvironmentVariable("OLLAMA_INTEL_GPU", "true", "User")

# ===== 6. 启动 Ollama =====
Write-Step "[2/4] Starting Ollama serve in background..."
$ollamaExe = Join-Path $env:LOCALAPPDATA "Programs\Ollama\ollama.exe"
if (-not (Test-Path $ollamaExe)) {
    Write-Err "找不到 Ollama：$ollamaExe"
    Read-Host "按回车退出"
    exit 1
}
Start-Process -FilePath $ollamaExe -ArgumentList "serve" -WindowStyle Hidden
Start-Sleep -Seconds 6

# ===== 7. 预热选中的模型 =====
Write-Step "[3/4] Loading model '$model' onto GPU (first load may take 30-90s)..."

$body = @{
    model  = $model
    prompt = "hi"
    stream = $false
} | ConvertTo-Json

try {
    Invoke-RestMethod -Uri "http://127.0.0.1:11434/api/generate" `
        -Method Post -Body $body -ContentType "application/json" `
        -TimeoutSec 300 | Out-Null
    Write-OK "Warmup OK"
} catch {
    Write-Err "WARMUP FAILED: $($_.Exception.Message)"
}

Write-Host ""
Write-Host "----- Ollama GPU status -----" -ForegroundColor Cyan
$psOutput = ollama ps 2>&1 | Out-String
Write-Host $psOutput
Write-Host "-----------------------------" -ForegroundColor Cyan

if ($psOutput -match "100% GPU") {
    Write-OK "Model is running 100% on GPU."
} else {
    Write-Warn "Model is NOT running 100% on GPU."
}
Write-Host ""

# ===== 8. 启动 Agent =====
Write-Step "[4/4] Starting Kurama Agent..."
$pythonExe = Join-Path $PSScriptRoot "venv\Scripts\python.exe"
$agentPy = Join-Path $PSScriptRoot "agent.py"

if (-not (Test-Path $pythonExe)) {
    Write-Err "找不到 venv python：$pythonExe"
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
Read-Host "按回车键关闭窗口"