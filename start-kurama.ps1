# =====================================================
#  Kurama Launcher (v3 - env dump + preflight)
# =====================================================

$ErrorActionPreference = "Continue"
$Host.UI.RawUI.WindowTitle = "Kurama Launcher"

try { chcp 65001 | Out-Null } catch {}
$OutputEncoding = [System.Text.Encoding]::UTF8
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
[Console]::InputEncoding  = [System.Text.Encoding]::UTF8
$env:PYTHONUNBUFFERED = "1"
$env:PYTHONIOENCODING = "utf-8"

Set-Location $PSScriptRoot

# ---- 默认模型存储目录（相对项目根，移植后自动跟随）----
$DEFAULT_MODELS_PATH = Join-Path $PSScriptRoot "sources\models"

# ===== 日志函数 =====
function Write-Step($msg) { Write-Host "[*] $msg" -ForegroundColor Cyan }
function Write-OK($msg)   { Write-Host "[OK] $msg" -ForegroundColor Green }
function Write-Warn($msg) { Write-Host "[!] $msg" -ForegroundColor Yellow }
function Write-Err($msg)  { Write-Host "[X] $msg" -ForegroundColor Red }
function Write-Info($msg) { Write-Host "    $msg" -ForegroundColor DarkGray }

# ============================================================
#  从 config/config.json 读取 ollama_dir
#  每次查询都实时读，避免缓存旧值
# ============================================================
function Get-OllamaDirFromConfig {
    $cfgPath = Join-Path $PSScriptRoot "config\config.json"
    if (-not (Test-Path $cfgPath)) { return $null }
    try {
        $raw = Get-Content $cfgPath -Raw -Encoding UTF8
        $raw = $raw.TrimStart([char]0xFEFF)
        $json = $raw | ConvertFrom-Json
        if ($json.ollama_dir -and $json.ollama_dir.Trim() -ne "") {
            return $json.ollama_dir.Trim()
        }
    } catch {
        Write-Info "读取 config.json 的 ollama_dir 失败：$($_.Exception.Message)"
    }
    return $null
}

# ============================================================
#  查找 ollama.exe
#  1. config.json 的 ollama_dir（用户可改，支持相对/绝对）
#  2. PATH
#  3. 旧默认安装路径
# ============================================================
function Find-OllamaExe {
    # 1. config.json
    $dir = Get-OllamaDirFromConfig
    if ($dir) {
        # 相对路径 → 相对项目根
        if (-not [System.IO.Path]::IsPathRooted($dir)) {
            $dir = Join-Path $PSScriptRoot $dir
        }
        if ($dir -match '\.exe\s*$') {
            if (Test-Path $dir) { return $dir }
            Write-Info "config.json 的 ollama_dir 指向 exe 但不存在：$dir"
        } else {
            $exe = Join-Path $dir "ollama.exe"
            if (Test-Path $exe) { return $exe }
            Write-Info "config.json 的 ollama_dir 中找不到 ollama.exe：$exe"
        }
    }
    # 2. PATH
    $found = (Get-Command ollama.exe -ErrorAction SilentlyContinue).Source
    if ($found) { return $found }
    # 3. 旧默认
    $oldDefault = Join-Path $env:LOCALAPPDATA "Programs\Ollama\ollama.exe"
    if (Test-Path $oldDefault) { return $oldDefault }
    return $null
}

# ============================================================
#  环境变量 dump
# ============================================================
function Show-Environment {
    Write-Host ""
    Write-Host "===== 环境变量 =====" -ForegroundColor Cyan

    Write-Host "  -- Ollama --" -ForegroundColor Yellow
    $ollamaVars = @(
        "OLLAMA_HOST", "OLLAMA_MODELS", "OLLAMA_VULKAN", "OLLAMA_IGPU_ENABLE",
        "OLLAMA_INTEL_GPU", "OLLAMA_FLASH_ATTENTION", "OLLAMA_KV_CACHE_TYPE",
        "OLLAMA_KEEP_ALIVE", "OLLAMA_CONTEXT_LENGTH", "OLLAMA_NUM_PARALLEL",
        "OLLAMA_MAX_LOADED_MODELS", "OLLAMA_LOAD_TIMEOUT", "OLLAMA_GPU_OVERHEAD",
        "OLLAMA_DEBUG", "OLLAMA_ORIGINS", "OLLAMA_NOPRUNE", "OLLAMA_NO_CLOUD"
    )
    foreach ($n in $ollamaVars) {
        $v = [Environment]::GetEnvironmentVariable($n)
        if ($null -ne $v -and $v -ne "") {
            Write-Host ("    {0,-28} = {1}" -f $n, $v)
        } else {
            Write-Host ("    {0,-28} = <unset>" -f $n) -ForegroundColor DarkGray
        }
    }

    Write-Host "  -- GPU / 加速 --" -ForegroundColor Yellow
    $gpuVars = @(
        "CUDA_VISIBLE_DEVICES", "HIP_VISIBLE_DEVICES",
        "GGML_VK_VISIBLE_DEVICES", "ROCR_VISIBLE_DEVICES",
        "ONEAPI_DEVICE_SELECTOR"
    )
    $anyGpu = $false
    foreach ($n in $gpuVars) {
        $v = [Environment]::GetEnvironmentVariable($n)
        if ($null -ne $v -and $v -ne "") {
            Write-Host ("    {0,-28} = {1}" -f $n, $v)
            $anyGpu = $true
        }
    }
    if (-not $anyGpu) { Write-Host "    (无 GPU 相关变量)" -ForegroundColor DarkGray }

    Write-Host "  -- Python --" -ForegroundColor Yellow
    foreach ($n in @("PYTHONUNBUFFERED", "PYTHONIOENCODING", "PYTHONPATH", "VIRTUAL_ENV")) {
        $v = [Environment]::GetEnvironmentVariable($n)
        $disp = if ($null -ne $v -and $v -ne "") { $v } else { "<unset>" }
        Write-Host ("    {0,-28} = {1}" -f $n, $disp)
    }

    Write-Host "  -- 网络代理 --" -ForegroundColor Yellow
    $anyProxy = $false
    foreach ($n in @("HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "http_proxy", "https_proxy", "no_proxy")) {
        $v = [Environment]::GetEnvironmentVariable($n)
        if ($null -ne $v -and $v -ne "") {
            Write-Host ("    {0,-28} = {1}" -f $n, $v)
            $anyProxy = $true
        }
    }
    if (-not $anyProxy) { Write-Host "    (无代理变量)" -ForegroundColor DarkGray }

    Write-Host "  -- 系统路径 --" -ForegroundColor Yellow
    foreach ($n in @("USERPROFILE", "LOCALAPPDATA", "APPDATA", "TEMP", "TMP")) {
        $v = [Environment]::GetEnvironmentVariable($n)
        Write-Host ("    {0,-28} = {1}" -f $n, $v)
    }

    Write-Host "  -- PATH 中相关项 --" -ForegroundColor Yellow
    $paths = $env:PATH -split ';' | Where-Object {
        $_ -and ($_ -match 'ollama|python|venv|LocalAgent|software')
    }
    if ($paths) {
        foreach ($p in $paths) { Write-Host "    $p" -ForegroundColor DarkGray }
    } else {
        Write-Host "    (PATH 中无 ollama/python/venv 相关项)" -ForegroundColor DarkGray
    }

    Write-Host "  -- Ollama 路径 --" -ForegroundColor Yellow
    $cfgDir = Get-OllamaDirFromConfig
    if ($cfgDir) {
        Write-Host ("    config.json ollama_dir = {0}" -f $cfgDir)
    } else {
        Write-Host "    config.json 未设置 ollama_dir（或读取失败）" -ForegroundColor DarkGray
    }
    $resolved = Find-OllamaExe
    if ($resolved) {
        Write-Host ("    实际使用 ollama.exe   = {0}" -f $resolved) -ForegroundColor Green
    } else {
        Write-Host "    实际使用 ollama.exe   = <未找到>" -ForegroundColor Red
    }

    Write-Host "  -- 模型目录 --" -ForegroundColor Yellow
    $effectiveModels = $env:OLLAMA_MODELS
    if (-not $effectiveModels) { $effectiveModels = $DEFAULT_MODELS_PATH }
    Write-Host ("    OLLAMA_MODELS = {0}" -f $effectiveModels)

    Write-Host ""
}

# ============================================================
#  预检查
# ============================================================
function Test-Prereqs {
    $ok = $true

    Write-Host ""
    Write-Host "===== 预检查 =====" -ForegroundColor Cyan

    # 1. 系统信息
    Write-Host "  -- 系统 --" -ForegroundColor Yellow
    try {
        $os = Get-CimInstance Win32_OperatingSystem -ErrorAction SilentlyContinue
        if ($os) {
            $totalGB = [math]::Round($os.TotalVisibleMemorySize / 1MB, 1)
            $freeGB  = [math]::Round($os.FreePhysicalMemory / 1MB, 1)
            Write-Host ("    OS           : {0} {1}" -f $os.Caption, $os.Version)
            Write-Host ("    内存         : 总 {0} GB / 可用 {1} GB" -f $totalGB, $freeGB)
            if ($freeGB -lt 4) { Write-Warn "可用内存 < 4 GB，可能影响模型加载" }
        }
    } catch { Write-Warn "读取系统信息失败" }

    # 2. 磁盘
    Write-Host "  -- 磁盘 --" -ForegroundColor Yellow
    try {
        $driveName = (Get-Item $PSScriptRoot).PSDrive.Name
        $d = Get-PSDrive -Name $driveName -ErrorAction SilentlyContinue
        if ($d) {
            $freeDiskGB = [math]::Round($d.Free / 1GB, 1)
            Write-Host ("    {0}: 剩余 {1} GB" -f $driveName, $freeDiskGB)
            if ($freeDiskGB -lt 5) { Write-Warn "项目盘剩余 < 5 GB" }
        }
    } catch { Write-Warn "读取磁盘信息失败" }

    # 3. Python / venv / 依赖
    Write-Host "  -- Python / venv --" -ForegroundColor Yellow
    $venvPy = Join-Path $PSScriptRoot "venv\Scripts\python.exe"
    if (Test-Path $venvPy) {
        try {
            $pv = (& $venvPy --version 2>&1 | Out-String).Trim()
            Write-OK "venv Python: $pv"
            $deps = @("langchain_ollama", "requests", "bs4", "psutil")
            $missing = @()
            foreach ($dep in $deps) {
                $null = & $venvPy -c "import $dep" 2>&1
                if ($LASTEXITCODE -ne 0) { $missing += $dep }
            }
            if ($missing.Count -eq 0) {
                Write-Info "依赖 OK: $($deps -join ', ')"
            } else {
                Write-Warn "依赖缺失: $($missing -join ', ')"
                Write-Info "修复: .\venv\Scripts\python.exe -m pip install $($missing -join ' ')"
                $ok = $false
            }
        } catch {
            Write-Err "venv python 调用失败: $_"
            $ok = $false
        }
    } else {
        Write-Err "venv Python 不存在：$venvPy"
        Write-Info "先创建: python -m venv venv"
        $ok = $false
    }

    # 4. Ollama
    Write-Host "  -- Ollama --" -ForegroundColor Yellow
    $ollamaExe = Find-OllamaExe
    if ($ollamaExe) {
        try {
            $ov = (& $ollamaExe --version 2>&1 | Out-String).Trim()
            $ov = ($ov -split "`n" | Where-Object { $_ -notmatch 'could not connect' }) -join "`n"
            Write-OK "ollama: $($ov.Trim())"
            Write-Info "路径: $ollamaExe"
        } catch {
            Write-Warn "ollama --version 调用失败"
        }
    } else {
        Write-Err "找不到 ollama.exe"
        $cfgDir = Get-OllamaDirFromConfig
        if ($cfgDir) {
            Write-Info "config.json 里的 ollama_dir = $cfgDir，但该目录下找不到 ollama.exe"
        } else {
            Write-Info "config.json 里未设置 ollama_dir"
        }
        Write-Info "请在 config\config.json 中设置：""ollama_dir"": ""sources\\ollama""（相对）或绝对路径"
        $ok = $false
    }

    # 5. 配置文件
    Write-Host "  -- 配置 --" -ForegroundColor Yellow
    $cfgPath = Join-Path $PSScriptRoot "config\config.json"
    if (Test-Path $cfgPath) {
        Write-OK "config: $cfgPath"
        try {
            $null = Get-Content $cfgPath -Raw -Encoding UTF8 | ConvertFrom-Json
            Write-Info "JSON 合法"
        } catch {
            Write-Warn "JSON 解析失败: $($_.Exception.Message)"
            $ok = $false
        }
    } else {
        Write-Warn "config.json 不存在: $cfgPath"
        Write-Info "首次运行会启动交互向导"
    }

    # 6. 端口 11434
    Write-Host "  -- 端口 11434 --" -ForegroundColor Yellow
    try {
        $conn = Get-NetTCPConnection -LocalPort 11434 -State Listen -ErrorAction SilentlyContinue
        if ($conn) {
            $pids = ($conn | Select-Object -ExpandProperty OwningProcess -Unique) -join ","
            Write-Warn "已被占用 (PID $pids)，稍后会强杀"
        } else {
            Write-OK "空闲"
        }
    } catch {
        Write-Warn "无法检查端口（可能权限不足）"
    }

    Write-Host ""
    return $ok
}

# ============================================================
#  清理进程
# ============================================================
function Clear-OllamaProcesses {
    param(
        [int]$MaxWaitSeconds = 60,
        [double]$SharedMemWarnGB = 3.0
    )

    Write-Step "清理 Ollama / Llama 相关进程..."

    # zip 解压版没有 GUI 进程，这里会静默失败，无所谓
    foreach ($n in @("ollama app")) {
        try {
            $procs = Get-Process -Name $n -ErrorAction SilentlyContinue
            foreach ($p in $procs) {
                Write-Info "杀 GUI: $($p.Name) (PID $($p.Id))"
                Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue
            }
        } catch {}
    }
    Start-Sleep -Milliseconds 500

    foreach ($name in @(
        "ollama.exe", "ollama app.exe",
        "llama-server.exe", "llama_server.exe",
        "ollama_llama_server.exe",
        "ollama-runner.exe", "ollama_runner.exe"
    )) {
        try { $null = & taskkill /F /T /IM $name 2>&1 } catch {}
    }

    try {
        $wmiProcs = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
            Where-Object {
                ($_.Name -and $_.Name -match '(?i)ollama|llama') -or
                ($_.CommandLine -and $_.CommandLine -match '(?i)ollama|llama[-_]?server')
            }
        foreach ($p in $wmiProcs) {
            if ($p.ProcessId -and $p.ProcessId -ne $PID) {
                Write-Info "WMI 兜底杀: $($p.Name) (PID $($p.ProcessId))"
                Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue
            }
        }
    } catch {}

    try {
        $conns = Get-NetTCPConnection -LocalPort 11434 -State Listen -ErrorAction SilentlyContinue
        if ($conns) {
            foreach ($c in $conns) {
                $op = $c.OwningProcess
                if ($op -and $op -ne $PID) {
                    $on = (Get-Process -Id $op -ErrorAction SilentlyContinue).Name
                    Write-Info "端口 11434 被占用：$on (PID $op)，强杀"
                    $null = & taskkill /F /T /PID $op 2>&1
                }
            }
        }
    } catch {}

    Write-Step "等待进程完全退出（最多 $MaxWaitSeconds 秒）..."
    $waited = 0
    $lastCount = -1
    while ($waited -lt $MaxWaitSeconds) {
        $remain = Get-Process -Name "ollama*", "llama*" -ErrorAction SilentlyContinue
        $count = if ($remain) { @($remain).Count } else { 0 }
        if ($count -eq 0) { break }
        if ($count -ne $lastCount -and $waited -gt 0) {
            Write-Info "仍有 $count 个进程，补杀一轮..."
            foreach ($p in $remain) {
                Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue
            }
        }
        $lastCount = $count
        Start-Sleep -Seconds 2
        $waited += 2
    }
    Write-Info "已等待 $waited 秒"

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
            Write-Warn "共享显存仍占用 $sharedGB GB（阈值 $SharedMemWarnGB GB）"
            Write-Warn "  建议：关闭浏览器硬件加速后重试；或降低 num_ctx / 换 q4_0 KV Cache"
            return $false
        } else {
            Write-OK "共享显存已释放：$sharedGB GB"
        }
    } else {
        Write-Warn "无法读取共享显存计数器，跳过校验"
    }

    $final = Get-Process -Name "ollama*", "llama*" -ErrorAction SilentlyContinue
    if ($final) {
        Write-Warn "仍有进程残留：$($final.Name -join ', ')"
        return $false
    }
    return $true
}


# ============================================================
#  [0/5] 环境 dump + 预检查
# ============================================================
Write-Step "[0/5] 环境变量与预检查"
Show-Environment
$prereqOK = Test-Prereqs
if (-not $prereqOK) {
    Write-Err "预检查发现问题（见上面 [X]/[!] 行）"
    $go = Read-Host "是否继续启动？(y/N)"
    if ($go -ne "y" -and $go -ne "Y") {
        Write-Host "已取消。" -ForegroundColor Yellow
        Read-Host "按回车退出"
        exit 1
    }
}

# ============================================================
#  读配置
# ============================================================
$configPath = Join-Path $PSScriptRoot "config\config.json"

if (-not (Test-Path $configPath)) {
    Write-Err "未找到配置文件：$configPath"
    Write-Step "将使用默认配置继续（首次运行会启动 agent 交互向导）"
    $cfg = [PSCustomObject]@{ model = ""; available_models = @(); ollama_dir = "" }
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

# ============================================================
#  模型存储路径（自愈 OLLAMA_MODELS）
#  优先级：ollama.yaml 的 models_path → 内置默认
#  相对路径按项目根解析
# ============================================================
$ollamaYaml = Join-Path $PSScriptRoot "config\ollama.yaml"
$modelsPath = ""

if (Test-Path $ollamaYaml) {
    try {
        $yamlText = Get-Content $ollamaYaml -Raw -Encoding UTF8
        if ($yamlText -match 'models_path\s*:\s*["'']?([^"''\r\n#]+)["'']?') {
            $modelsPath = $Matches[1].Trim()
        }
    } catch {}
}

# 相对路径按项目根解析
if ($modelsPath -and -not [System.IO.Path]::IsPathRooted($modelsPath)) {
    $modelsPath = Join-Path $PSScriptRoot $modelsPath
}

# 清理指向已不存在目录的持久化 OLLAMA_MODELS（避免旧用户目录干扰）
$persisted = [Environment]::GetEnvironmentVariable("OLLAMA_MODELS", "User")
if ($persisted -and -not (Test-Path $persisted)) {
    Write-Warn "清理无效的持久化 OLLAMA_MODELS：$persisted"
    [Environment]::SetEnvironmentVariable("OLLAMA_MODELS", $null, "User")
    try { [Environment]::SetEnvironmentVariable("OLLAMA_MODELS", $null, "Machine") } catch {}
    Remove-Item -Path "Env:OLLAMA_MODELS" -ErrorAction SilentlyContinue
}

# 决定最终使用的模型目录
if (-not $modelsPath) {
    $modelsPath = $DEFAULT_MODELS_PATH
    Write-Info "config\ollama.yaml 未指定 models_path，使用内置默认：$DEFAULT_MODELS_PATH"
} elseif ($modelsPath -ne $DEFAULT_MODELS_PATH -and -not (Test-Path $modelsPath)) {
    Write-Warn "config\ollama.yaml 里的 models_path 不存在：$modelsPath"
    Write-Info "回退到内置默认：$DEFAULT_MODELS_PATH"
    $modelsPath = $DEFAULT_MODELS_PATH
}

# 确保目录存在
if (-not (Test-Path $modelsPath)) {
    try {
        New-Item -ItemType Directory -Path $modelsPath -Force | Out-Null
        Write-Info "已创建模型目录：$modelsPath"
    } catch {
        Write-Warn "创建模型目录失败：$modelsPath（$($_.Exception.Message)）"
    }
}

if (Test-Path $modelsPath) {
    $env:OLLAMA_MODELS = $modelsPath
    Write-OK "OLLAMA_MODELS = $modelsPath"
} else {
    Write-Err "模型目录不可用：$modelsPath"
    Write-Info "请检查 config\ollama.yaml 的 models_path，或手动创建该目录"
    Read-Host "按回车继续（可能无法加载模型）"
}

# ============================================================
#  交互式选择模型
# ============================================================
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

# ============================================================
#  [1/5] 清理旧进程
# ============================================================
Write-Step "[1/5] 停止所有 Ollama / Llama 进程..."
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

# ============================================================
#  设置 GPU 环境变量
# ============================================================
Write-Step "设置 GPU 加速环境变量..."
foreach ($name in @(
    "OLLAMA_FLASH_ATTENTION", "OLLAMA_KV_CACHE_TYPE", "OLLAMA_GPU_OVERHEAD",
    "OLLAMA_NUM_PARALLEL", "OLLAMA_MAX_LOADED_MODELS", "HIP_VISIBLE_DEVICES"
)) {
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

# ============================================================
#  [2/5] 启动 Ollama
# ============================================================
Write-Step "[2/5] 后台启动 Ollama serve..."

$ollamaExe = Find-OllamaExe
if (-not $ollamaExe) {
    Write-Err "找不到 ollama.exe"
    $cfgDir = Get-OllamaDirFromConfig
    if ($cfgDir) {
        Write-Info "config.json 的 ollama_dir = $cfgDir，但该目录下无 ollama.exe"
    } else {
        Write-Info "config.json 里未设置 ollama_dir"
    }
    Write-Info "请在 config\config.json 中设置：""ollama_dir"": ""sources\\ollama""（相对）或绝对路径"
    Read-Host "按回车退出"
    exit 1
}
Write-Info "使用 ollama: $ollamaExe"
Write-Info "模型目录:   $env:OLLAMA_MODELS"

$stdoutLog = Join-Path $PSScriptRoot "ollama-serve.log"
$stderrLog = Join-Path $PSScriptRoot "ollama-serve.err.log"
Remove-Item $stdoutLog, $stderrLog -ErrorAction SilentlyContinue

Start-Process -FilePath $ollamaExe -ArgumentList "serve" `
    -RedirectStandardOutput $stdoutLog `
    -RedirectStandardError $stderrLog `
    -WindowStyle Hidden

$apiReady = $false
for ($i = 0; $i -lt 30; $i++) {
    Start-Sleep -Seconds 1
    try {
        $r = Invoke-RestMethod -Uri "http://127.0.0.1:11434/api/version" -TimeoutSec 2 -ErrorAction Stop
        if ($r.version) { $apiReady = $true; break }
    } catch {}
}
if (-not $apiReady) {
    Write-Err "Ollama API 30 秒内未就绪"
    Write-Step "请检查：Get-NetTCPConnection -LocalPort 11434"
    Write-Step "详细日志：$stderrLog"
    if (Test-Path $stderrLog) {
        Write-Host ""
        Write-Host "----- ollama-serve.err.log (tail 20) -----" -ForegroundColor Yellow
        Get-Content $stderrLog -Tail 20
        Write-Host "------------------------------------------" -ForegroundColor Yellow
    }
    Read-Host "按回车退出"
    exit 1
}
Write-OK "Ollama API 已就绪"

# ============================================================
#  [3/5] 预热
# ============================================================
Write-Step "[3/5] 预热模型 '$model'（首次可能 30-90 秒）..."

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
    Write-Warn "排查："
    Write-Warn "  1. ollama ps              # 看是否加载成功"
    Write-Warn "  2. 降低 num_ctx：/set num_ctx 8192"
    Write-Warn "  3. 看 stderr 日志：$stderrLog"
    Write-Warn "  4. 确认模型目录：$env:OLLAMA_MODELS"
}

Write-Host ""
Write-Host "----- Ollama GPU status -----" -ForegroundColor Cyan
$psOutput = ""
try { $psOutput = (& $ollamaExe ps 2>&1 | Out-String) } catch { $psOutput = "(ollama ps 执行失败)" }
Write-Host $psOutput
Write-Host "-----------------------------" -ForegroundColor Cyan
if ($psOutput -match "100% GPU") {
    Write-OK "Model is running 100% on GPU."
} else {
    Write-Warn "Model is NOT running 100% on GPU"
}
Write-Host ""

# ============================================================
#  [4/5] 启动 Agent
# ============================================================
Write-Step "[4/5] 启动 Kurama Agent..."

$pythonExe = Join-Path $PSScriptRoot "venv\Scripts\python.exe"
if (-not (Test-Path $pythonExe)) {
    Write-Err "找不到 venv python：$pythonExe"
    Read-Host "按回车退出"
    exit 1
}

# 记录 ollama serve 的 PID（精确清理用）
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

Read-Host "按回车关闭窗口"