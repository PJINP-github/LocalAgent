- - # Ollama 部署与模型创建（完整版）

    ## 一、安装 Ollama
  
    ### 1.1 下载安装

    1. 访问 https://ollama.com/download
  2. 下载 `OllamaSetup.exe`
    3. 双击安装，默认装到 `C:\Users\<用户名>\AppData\Local\Programs\Ollama\`
  4. 装完后托盘出现羊驼图标
  
    ### 1.2 验证版本
  
  ```powershell
    ollama --version
  ```
  
    本教程基于 **Ollama 0.32.6**（0.40.x 在 Intel Arc 上有 Vulkan 显存分配 bug，0.32.6 更稳定）。
  
  如果装的是 0.40.x，先卸载，去 GitHub Releases 下载 0.32.6：
    ```text
  https://github.com/ollama/ollama/releases/tag/v0.32.6
    ```

    安装后在设置里**关闭自动更新**，否则会升回 0.40.x。

    ### 1.3 配置 GPU 加速环境变量

    ```powershell
    setx OLLAMA_VULKAN 1
    setx OLLAMA_IGPU_ENABLE 1
    setx OLLAMA_INTEL_GPU true
    ```

    **重启 Ollama**（托盘图标右键退出，再重新打开），让变量生效。

    验证：

    ```powershell
  echo $env:OLLAMA_VULKAN
    ```
  
    应输出 `1`。
  
    ---

    ## 二、下载 qwen2.5-coder-7b GGUF

    Ollama 官方库里的 `qwen2.5-coder:7b` 是 Q4_K_M 量化，可以直接拉：

    ```powershell
  ollama pull ollama.com/library/qwen2.5-coder:7b
    ```
  
    > **注意**：0.32.6 下模型名要带 `ollama.com/library/` 前缀。
  
    **如果拉取慢**，可以用 ModelScope 下载 GGUF 后本地导入（更灵活，能控制量化版本）：

    ### 2.1 从 ModelScope 下载 GGUF

    ```powershell
  # 安装 modelscope
    D:\APP\python\python.exe -m pip install modelscope
  
    # 下载 Q4_K_M 版本
  D:\APP\python\python.exe -c "from modelscope import snapshot_download; snapshot_download('QuantFactory/Qwen2.5-Coder-7B-Instruct-GGUF', allow_patterns=['*Q4_K_M*.gguf'], local_dir='D:/Models/Qwen2.5-Coder-7B')"
    ```

    文件下载到 `D:\Models\Qwen2.5-Coder-7B\`，约 4.36 GB。

    验证：
  
    ```powershell
    Get-ChildItem "D:\Models\Qwen2.5-Coder-7B" -Filter "*.gguf" | 
        Select-Object Name, @{N="GB";E={[math]::Round($_.Length/1GB,2)}}
    ```
  
    应看到类似：
    ```text
    Qwen2.5-Coder-7B-Instruct.Q4_K_M.gguf    4.36
    ```
  
    ---
  
    ## 三、创建不同上下文的模型
  
    在 `D:\Models\Qwen2.5-Coder-7B\` 下为每个上下文版本创建 Modelfile 并构建。
  
  ### 3.1 创建 4K 版本（最快，短对话）
  
  ```powershell
    cd D:\Models\Qwen2.5-Coder-7B
  
    @'
  FROM ./Qwen2.5-Coder-7B-Instruct.Q4_K_M.gguf
    PARAMETER num_ctx 4096
    PARAMETER temperature 0.2
    PARAMETER top_p 0.95
    '@ | Set-Content -Encoding ascii Modelfile.4k
  
    ollama create qwen2.5-coder-4k -f Modelfile.4k
  ```
  
  ### 3.2 创建 8K 版本（推荐日常代码用）
  
  ```powershell
    @'
    FROM ./Qwen2.5-Coder-7B-Instruct.Q4_K_M.gguf
    PARAMETER num_ctx 8192
  PARAMETER temperature 0.2
    PARAMETER top_p 0.95
  '@ | Set-Content -Encoding ascii Modelfile.8k
    
  ollama create qwen2.5-coder-8k -f Modelfile.8k
    ```

    ### 3.3 创建 16K 版本（中等长度文件）

    ```powershell
  @'
    FROM ./Qwen2.5-Coder-7B-Instruct.Q4_K_M.gguf
    PARAMETER num_ctx 16384
    PARAMETER temperature 0.2
    PARAMETER top_p 0.95
    '@ | Set-Content -Encoding ascii Modelfile.16k
    
    ollama create qwen2.5-coder-16k -f Modelfile.16k
    ```
  
    ### 3.4 创建 32K 版本（长文件/多文件参考）

    ```powershell
  @'
    FROM ./Qwen2.5-Coder-7B-Instruct.Q4_K_M.gguf
  PARAMETER num_ctx 32768
    PARAMETER temperature 0.2
  PARAMETER top_p 0.95
    '@ | Set-Content -Encoding ascii Modelfile.32k
  
    ollama create qwen2.5-coder-32k -f Modelfile.32k
  ```
  
  ---
  
    ## 四、验证模型列表
  
    ```powershell
    ollama list
    ```
  
    应看到：
  
    ```text
    NAME                        ID              SIZE      MODIFIED
    qwen2.5-coder-4k:latest     ...             4.4 GB    ...
    qwen2.5-coder-8k:latest     ...             4.4 GB    ...
    qwen2.5-coder-16k:latest    ...             4.4 GB    ...
    qwen2.5-coder-32k:latest    ...             4.4 GB    ...
    ```
  
    **注意**：4 个模型共享同一份权重 blob（4.36 GB），只有 manifest 不同，总磁盘占用**不会翻倍**。
  
    ---
  
    ## 五、各上下文版本对比
  
    | 版本    | KV Cache | 总显存占用 | 推荐场景                       |
    | :------ | :------- | :--------- | :----------------------------- |
    | **4K**  | ~0.15 GB | ~4.6 GB    | 快速问答、单文件小修改         |
    | **8K**  | ~0.3 GB  | ~4.8 GB    | **日常代码修改**（推荐）       |
    | **16K** | ~0.6 GB  | ~5.1 GB    | 中等长度文件，含上下文参考     |
    | **32K** | ~1.0 GB  | ~5.6 GB    | 长文件、多文件对照，需显存干净 |
  
    **选择建议**：
    - 笔记本显存共享，其他程序（浏览器等）也吃显存
    - **默认用 8K**，日常代码任务完全够用
    - 需要更长上下文时用 `/model` 临时切换
  
    ---
  
    ## 六、逐个测试加载
  
    每次测试前，先杀掉 `llama-server.exe` 释放显存，再运行：
  
    ```powershell
    # 测试 8K
    ollama run qwen2.5-coder-8k "写一个Python快速排序函数"
    ```
  
    **另开一个 PowerShell 窗口**：
  
    ```powershell
    ollama ps
    ```
  
    期望输出：
  
    ```text
    NAME                        ID              SIZE      PROCESSOR    CONTEXT
    qwen2.5-coder-8k:latest     ...             ~5 GB     100% GPU     8192
    ```
  
    逐个测试 4K / 8K / 16K / 32K，记录哪个能 `100% GPU`。
  
    ---
  
    ## 七、把模型加入 config.json
  
    把测试通过的模型写进配置：
  
    ```powershell
    $dir = "D:\APP\LocalAgent\.local-agent"
    
    $json = @'
    {
      "available_models": [
        "qwen2.5-coder-8k",
        "qwen2.5-coder-16k",
        "qwen2.5-coder-32k",
        "qwen3.5-2b-8k",
        "lfm2.5-thinking-32k"
      ],
      "model": "qwen2.5-coder-8k",
      "memory_path": "D:/APP/LocalAgent/.local-agent/memory.json",
      "temperature": 0.2,
      "num_ctx": 8192,
      "repeat_penalty": 1.05,
      "num_predict": 2048,
      "think": false,
      "max_tool_rounds": 6,
      "enabled_tools": [
        "list_directory", "read_file", "write_file", "search_files",
        "get_system_info", "list_processes", "run_command",
        "fetch_url", "open_url"
      ]
    }
    '@
    
    [System.IO.File]::WriteAllText("$dir\config.json", $json, [System.Text.UTF8Encoding]::new($false))
    Write-Host "已更新：$dir\config.json"
    ```
  
    `available_models` 里的模型会在 `start-kurama.ps1` 的菜单里显示。
  
    ---
  
    ## 八、显存问题速查
  
    如果某个上下文版本加载失败（500 错误），按顺序排查：
  
    ### 8.1 检查是否有 llama-server.exe 残留
  
  ```powershell
    Get-Process -Name "llama-server" -ErrorAction SilentlyContinue
  Get-Process -Name "*ollama*" -ErrorAction SilentlyContinue
    ```

    有就杀：

    ```powershell
  Get-Process -Name "llama-server" -ErrorAction SilentlyContinue | Stop-Process -Force
    Get-Process -Name "*ollama*" -ErrorAction SilentlyContinue | Stop-Process -Force
  Start-Sleep -Seconds 10
    ```

    ### 8.2 检查共享显存占用
  
    ```powershell
    Get-Counter "\GPU Adapter Memory(*)\Shared Usage" | 
        Select-Object -ExpandProperty CounterSamples |
        Sort-Object CookedValue -Descending |
        Select-Object -First 1 |
        ForEach-Object { 
            "共享显存：{0:N2} GB" -f ($_.CookedValue / 1GB)
        }
    ```
  
    - 小于 2 GB → 干净，可以启动
    - 大于 6 GB → 有其他程序占用（浏览器、音乐播放器），关闭硬件加速
  
    ### 8.3 上下文降级
  
    如果 32K 加载不了，逐级降：**32K → 16K → 8K → 4K**，直到成功。
  
    ---
  
    ## 九、一键部署总流程
  
    ```powershell
    # ========== 1. 安装 Ollama 0.32.6 ==========
    # 从 https://github.com/ollama/ollama/releases/tag/v0.32.6
    # 下载 OllamaSetup.exe 并安装
    
    # ========== 2. 配置 GPU 环境 ==========
    setx OLLAMA_VULKAN 1
    setx OLLAMA_IGPU_ENABLE 1
    setx OLLAMA_INTEL_GPU true
    # 重启 Ollama
    
    # ========== 3. 下载模型 ==========
    D:\APP\python\python.exe -m pip install modelscope
    
    D:\APP\python\python.exe -c "from modelscope import snapshot_download; snapshot_download('QuantFactory/Qwen2.5-Coder-7B-Instruct-GGUF', allow_patterns=['*Q4_K_M*.gguf'], local_dir='D:/Models/Qwen2.5-Coder-7B')"
    
    # ========== 4. 创建 4K / 8K / 16K / 32K 四个版本 ==========
    cd D:\Models\Qwen2.5-Coder-7B
    
    foreach ($ctx in @(4096, 8192, 16384, 32768)) {
        $tag = $ctx / 1024
        @"
    FROM ./Qwen2.5-Coder-7B-Instruct.Q4_K_M.gguf
    PARAMETER num_ctx $ctx
    PARAMETER temperature 0.2
    PARAMETER top_p 0.95
    "@ | Set-Content -Encoding ascii "Modelfile.${tag}k"
        ollama create "qwen2.5-coder-${tag}k" -f "Modelfile.${tag}k"
    }
    
    # ========== 5. 验证 ==========
    ollama list
    
    # ========== 6. 逐个测试 ==========
    ollama run qwen2.5-coder-8k "hi"
    # 另开窗口
    ollama ps
    
    # ========== 7. 更新 Kurama 配置 ==========
    # 见上方第七节的 PowerShell 命令
    ```
  
    ---
  
    ## 十、常见问题
  
    | 现象                       | 原因                          | 解决                                                     |
    | :------------------------- | :---------------------------- | :------------------------------------------------------- |
    | `ollama create` 报 500     | 显存被 `llama-server.exe` 占  | 杀进程 + 等 10 秒                                        |
    | `ollama list` 看不到新模型 | 0.32.6 写的 manifest 位置不对 | 用 `ollama.com/library/` 前缀命名，或见《manifest 修复》 |
    | 32K 加载 OOM               | 其他程序吃显存                | 关浏览器/音乐播放器，或降级到 8K                         |
    | `100% CPU` 而非 GPU        | Vulkan 变量未生效             | 检查 `echo $env:OLLAMA_VULKAN`，重启 Ollama              |
    | 模型下载慢                 | Ollama CDN 阻塞               | 用 ModelScope 镜像下载 GGUF 后本地导入                   |
    | `huggingface.co` 连不上    | 网络限制                      | 用 ModelScope 或设置 `HF_ENDPOINT=https://hf-mirror.com` |
  
    ---
  
    ## 十一、完整目录结构总览
  
    ```text
    D:\
    ├── APP\
    │   ├── python\                    ← Python 3.13
    │   ├── LocalAgent\                ← Kurama 项目
    │   │   ├── .local-agent\
    │   │   │   ├── config.json
    │   │   │   └── memory.json
    │   │   ├── venv\
    │   │   ├── agent.py
    │   │   ├── config_manager.py
    │   │   ├── memory_manager.py
    │   │   ├── tools.py
    │   │   ├── start-kurama.bat
    │   │   └── start-kurama.ps1
    │   └── ollama-ipex\               ← 已废弃，可删除
    ├── Models\
    │   └── Qwen2.5-Coder-7B\
    │       ├── Qwen2.5-Coder-7B-Instruct.Q4_K_M.gguf
    │       ├── Modelfile.4k
    │       ├── Modelfile.8k
    │       ├── Modelfile.16k
    │       └── Modelfile.32k
    └── Code\
        └── test\                      ← 用户代码目录
    
    C:\Users\Administrator\
    └── .ollama\
        └── models\
            ├── blobs\                 ← 所有模型权重
            ├── manifests\             ← 0.32.6 读取
            └── manifests-v2\          ← 0.40.x 读取（可忽略）
    ```
  
    ---
  
    现在整个部署链路完整了：
  
    1. **安装 Ollama 0.32.6** → 配置 Vulkan 变量
    2. **下载 qwen2.5-coder-7b**（官方 pull 或 ModelScope 拉 GGUF）
    3. **创建 4K/8K/16K/32K 四个版本** → 逐一测试 GPU 加载
    4. **写入 config.json** 的 `available_models`
    5. **双击 start-kurama.bat** → 菜单选模型 → 自动预热 → 进入 Agent
  
    日常用 8K，需要长上下文时切 32K，显存不足就降级。
  
  - # Kurama 本地 AI 助手部署脚本（完整版）
  
    ## 一、目录结构
  
    ```text
    D:\APP\LocalAgent\
    ├── .local-agent\
    │   ├── config.json          ← 配置（首次运行交互生成）
    │   └── memory.json          ← 记忆文件（自动生成）
    ├── venv\                    ← Python 虚拟环境
    ├── agent.py                 ← Agent 主程序
    ├── config_manager.py        ← 配置管理
    ├── memory_manager.py        ← 记忆系统
    ├── tools.py                 ← 工具库
    ├── start-kurama.ps1         ← 启动主逻辑
    └── start-kurama.bat         ← 双击启动器
    ```
  
    ---
  
    ## 二、`start-kurama.bat`（双击入口）
  
    ```bat
    @echo off
    pwsh -NoProfile -ExecutionPolicy Bypass -File "%~dp0start-kurama.ps1"
    if errorlevel 1 (
        echo.
        echo [启动失败] 错误码 %errorlevel%
        pause
    )
    ```
  
    **作用**：调用 PowerShell 7 运行主脚本，出错时暂停显示错误码。
  
    ---
  
    ## 三、`start-kurama.ps1`（启动主逻辑）
  
    **流程**：读配置 → 选模型 → 杀进程（含 `llama-server.exe`）→ 等显存释放 → 设 GPU 变量 → 启动 Ollama → 预热 → 启动 Agent。
  
    ```powershell
    # =====================================================
    #  Kurama Launcher - Ollama 0.32.6 + Intel Arc 130T
    # =====================================================
    
    $ErrorActionPreference = "Continue"
    $Host.UI.RawUI.WindowTitle = "Kurama Launcher"
    
    try { chcp 65001 | Out-Null } catch {}
    $OutputEncoding = [System.Text.Encoding]::UTF8
    [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
    [Console]::InputEncoding  = [System.Text.Encoding]::UTF8
    $env:PYTHONUNBUFFERED = "1"
    $env:PYTHONIOENCODING = "utf-8"
    
    function Write-Step($m){ Write-Host "[*] $m" -ForegroundColor Cyan }
    function Write-OK($m){ Write-Host "[OK] $m" -ForegroundColor Green }
    function Write-Warn($m){ Write-Host "[!] $m" -ForegroundColor Yellow }
    function Write-Err($m){ Write-Host "[X] $m" -ForegroundColor Red }
    
    # ===== 1. 读配置 =====
    $configPath = Join-Path $PSScriptRoot ".local-agent\config.json"
    if (-not (Test-Path $configPath)) {
        Write-Err "未找到配置文件：$configPath"; Read-Host "按回车退出"; exit 1
    }
    try {
        $raw = (Get-Content $configPath -Raw -Encoding UTF8).TrimStart([char]0xFEFF)
        $cfg = $raw | ConvertFrom-Json
    } catch {
        Write-Err "配置解析失败：$($_.Exception.Message)"; Read-Host "按回车退出"; exit 1
    }
    
    $available = @($cfg.available_models)
    $lastModel = $cfg.model
    if ($available.Count -eq 0) { Write-Err "available_models 为空"; Read-Host; exit 1 }
    
    # ===== 2. 选择模型 =====
    Write-Host "`n===============================" -ForegroundColor Cyan
    Write-Host "  请选择要使用的模型" -ForegroundColor Cyan
    Write-Host "===============================`n" -ForegroundColor Cyan
    for ($i=0; $i -lt $available.Count; $i++) {
        $mark = if ($available[$i] -eq $lastModel) { "  (上次使用)" } else { "" }
        Write-Host ("  [{0}] {1}{2}" -f ($i+1), $available[$i], $mark)
    }
    Write-Host ""
    $choice = Read-Host "输入编号（回车使用上次：$lastModel）"
    $model = $lastModel
    if ($choice -match '^\d+$') {
        $idx = [int]$choice - 1
        if ($idx -ge 0 -and $idx -lt $available.Count) { $model = $available[$idx] }
    }
    Write-Host "`n[已选择] $model`n" -ForegroundColor Green
    
    # 回写配置
    try {
        $cfg.model = $model
        [System.IO.File]::WriteAllText($configPath, ($cfg | ConvertTo-Json -Depth 10),
            [System.Text.UTF8Encoding]::new($false))
    } catch { Write-Warn "保存配置失败：$($_.Exception.Message)" }
    
    # ===== 3. 杀进程（含 llama-server.exe）=====
    Write-Step "[1/4] Stopping existing Ollama processes..."
  foreach ($pat in @("ollama*", "llama-server*", "llama_server*")) {
        Get-Process -Name $pat -ErrorAction SilentlyContinue | ForEach-Object {
          try {
                Write-Host "  杀：$($_.Name) (PID $($_.Id))" -ForegroundColor DarkGray
              Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue
            } catch {}
      }
    }
  
    # 轮询等待进程退出，最多 30 秒
  Write-Step "Waiting for GPU memory release..."
    $waited = 0
    while ($waited -lt 30) {
        $still = Get-Process -Name "ollama*","llama-server*","llama_server*" -ErrorAction SilentlyContinue
        if (-not $still) { break }
        Start-Sleep -Seconds 2; $waited += 2
    }
    Start-Sleep -Seconds 3
    Write-Host "[*] 已等待 $waited 秒`n" -ForegroundColor Cyan
    
    # 检查共享显存
    try {
        $shared = (Get-Counter "\GPU Adapter Memory(*)\Shared Usage" -ErrorAction SilentlyContinue).CounterSamples |
            Sort-Object CookedValue -Descending | Select-Object -First 1
        if ($shared) {
            $gb = [math]::Round($shared.CookedValue / 1GB, 2)
            Write-Host "[*] 共享显存占用：$gb GB" -ForegroundColor Cyan
            if ($gb -gt 6) { Write-Warn "显存仍高，可能其他程序占用（浏览器/音乐播放器）" }
        }
    } catch {}
    
    # ===== 4. GPU 环境变量 =====
    Write-Step "Setting GPU environment variables..."
    foreach ($name in @("OLLAMA_FLASH_ATTENTION","OLLAMA_KV_CACHE_TYPE","OLLAMA_GPU_OVERHEAD",
                         "OLLAMA_NUM_PARALLEL","OLLAMA_MAX_LOADED_MODELS","HIP_VISIBLE_DEVICES")) {
        [Environment]::SetEnvironmentVariable($name, $null, "User")
        Remove-Item -Path "Env:$name" -ErrorAction SilentlyContinue
    }
    $env:OLLAMA_VULKAN        = "1"
    $env:OLLAMA_IGPU_ENABLE   = "1"
    $env:OLLAMA_INTEL_GPU     = "true"
    $env:OLLAMA_FLASH_ATTENTION = "0"
    $env:OLLAMA_KV_CACHE_TYPE = "f16"
    $env:OLLAMA_KEEP_ALIVE    = "5m"
    [Environment]::SetEnvironmentVariable("OLLAMA_VULKAN", "1", "User")
    [Environment]::SetEnvironmentVariable("OLLAMA_IGPU_ENABLE", "1", "User")
    [Environment]::SetEnvironmentVariable("OLLAMA_INTEL_GPU", "true", "User")
    
    # ===== 5. 启动 Ollama =====
    Write-Step "[2/4] Starting Ollama serve..."
    $ollamaExe = Join-Path $env:LOCALAPPDATA "Programs\Ollama\ollama.exe"
    if (-not (Test-Path $ollamaExe)) {
        Write-Err "找不到 Ollama：$ollamaExe"; Read-Host; exit 1
    }
    Start-Process -FilePath $ollamaExe -ArgumentList "serve" -WindowStyle Hidden
    Start-Sleep -Seconds 6
    
    # ===== 6. 预热 =====
    Write-Step "[3/4] Loading '$model' onto GPU..."
    $body = @{ model = $model; prompt = "hi"; stream = $false } | ConvertTo-Json
    try {
        Invoke-RestMethod -Uri "http://127.0.0.1:11434/api/generate" -Method Post `
            -Body $body -ContentType "application/json" -TimeoutSec 300 | Out-Null
        Write-OK "Warmup OK"
    } catch { Write-Err "WARMUP FAILED: $($_.Exception.Message)" }
    
    Write-Host "`n----- GPU status -----" -ForegroundColor Cyan
    $psOutput = ollama ps 2>&1 | Out-String
    Write-Host $psOutput
    Write-Host "----------------------" -ForegroundColor Cyan
    if ($psOutput -match "100% GPU") { Write-OK "100% GPU" } else { Write-Warn "非 100% GPU" }
    Write-Host ""
    
    # ===== 7. 启动 Agent =====
    Write-Step "[4/4] Starting Kurama Agent..."
    $pythonExe = Join-Path $PSScriptRoot "venv\Scripts\python.exe"
    $agentPy   = Join-Path $PSScriptRoot "agent.py"
    if (-not (Test-Path $pythonExe)) { Write-Err "找不到 python：$pythonExe"; Read-Host; exit 1 }
    if (-not (Test-Path $agentPy))   { Write-Err "找不到 agent.py：$agentPy"; Read-Host; exit 1 }
    
    & $pythonExe -u $agentPy
    
    Write-Host "`nAgent 已退出。" -ForegroundColor Cyan
    Read-Host "按回车关闭"
    ```
  
    ---
  
    ## 四、`config_manager.py`（配置管理）
  
    **作用**：读写 `.local-agent/config.json`，首次运行进入交互式向导。
  
    ```python
    import json, os, urllib.request
    
    SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
    CONFIG_DIR = os.path.join(SCRIPT_DIR, ".local-agent")
    CONFIG_PATH = os.path.join(CONFIG_DIR, "config.json")
    DEFAULT_MEMORY_PATH = os.path.join(CONFIG_DIR, "memory.json")
    
    DEFAULT_CONFIG = {
        "available_models": [
            "qwen2.5-coder-4bit:latest",
            "qwen3.5-2b-8k",
            "lfm2.5-thinking-32k"
        ],
        "model": "qwen2.5-coder-4bit:latest",
        "memory_path": DEFAULT_MEMORY_PATH,
        "temperature": 0.2,
        "num_ctx": 32768,
        "repeat_penalty": 1.05,
        "num_predict": 2048,
        "think": False,
        "max_tool_rounds": 6,
        "enabled_tools": [
            "list_directory", "read_file", "write_file", "search_files",
            "get_system_info", "list_processes", "run_command",
            "fetch_url", "open_url"
        ],
    }
    
    
    def list_ollama_models():
        try:
            with urllib.request.urlopen("http://127.0.0.1:11434/api/tags", timeout=5) as r:
                data = json.loads(r.read().decode("utf-8"))
                return [m["name"] for m in data.get("models", [])]
        except Exception:
            return []
    
    
    class ConfigManager:
        def __init__(self, path=CONFIG_PATH):
            self.path = path
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            self.data = self._load()
    
        def _load(self):
            if os.path.exists(self.path):
                try:
                    raw = open(self.path, "r", encoding="utf-8").read().lstrip("\ufeff")
                    cfg = json.loads(raw)
                    merged = dict(DEFAULT_CONFIG)
                    merged.update(cfg)
                    return merged
                except Exception as e:
                    print(f"[警告] 配置解析失败：{e}")
            return dict(DEFAULT_CONFIG)
    
        def save(self):
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(self.data, f, ensure_ascii=False, indent=2)
    
        def get(self, key, default=None):  return self.data.get(key, default)
        def set(self, key, value):         self.data[key] = value
    
        def show(self):
            return "\n".join(["当前配置："] + [f"  {k} = {v}" for k, v in self.data.items()])
    
    
    def first_run_setup(config: ConfigManager):
        print("\n" + "="*60 + "\n  交互式配置向导\n" + "="*60)
        models = list_ollama_models()
        if not models:
            print("\n[警告] 未检测到 Ollama 模型，使用默认配置。\n")
            config.save(); return
    
        print("\n可用模型：")
        for i, m in enumerate(models, 1):
            print(f"  {i}. {m}")
        choice = input("\n模型编号（回车保持默认）：").strip()
        if choice.isdigit() and 0 < int(choice) <= len(models):
            config.set("model", models[int(choice) - 1])
    
        v = input(f"\nnum_ctx（当前 {config.get('num_ctx')}）：").strip()
        if v.isdigit(): config.set("num_ctx", int(v))
  
        v = input(f"\ntemperature（当前 {config.get('temperature')}）：").strip()
      if v:
            try: config.set("temperature", float(v))
          except ValueError: pass
    
      v = input(f"\n开启 thinking？(y/n，当前 {config.get('think')})：").strip().lower()
        if v == "y": config.set("think", True)
      elif v == "n": config.set("think", False)
    
      config.save()
        print(f"\n已保存：{config.path}\n")
    ```
  
    ---
  
    ## 五、`memory_manager.py`（记忆系统）
  
    **作用**：JSON 持久化记忆，每 20 轮触发摘要压缩。
  
    ```python
    import json, os, re
    from datetime import datetime
    
    
    def split_thinking(text):
        if not text: return "", text
        m = re.search(r"Thinking\.\.\.(.*?)\.\.\.done thinking\.\s*", text,
                      flags=re.DOTALL | re.IGNORECASE)
        if m: return m.group(1).strip(), text[m.end():].strip()
        m = re.search(r"<think(?:ing)?>(.*?)</think(?:ing)?>", text,
                      flags=re.DOTALL | re.IGNORECASE)
        if m: return m.group(1).strip(), (text[:m.start()] + text[m.end():]).strip()
        return "", text.strip()
    
    
    def clean_output(text):
        _, answer = split_thinking(text)
        return answer
    
    
    class MemoryManager:
        def __init__(self, path="~/.local-agent/memory.json", llm=None):
            self.path = os.path.expanduser(path)
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            self.llm = llm
            self.data = self._load()
            self.compress_threshold = 20
    
        def switch_path(self, new_path):
            self.path = os.path.expanduser(new_path)
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            self.data = self._load()
            print(f"[记忆文件已切换] {self.path}")
    
        def _load(self):
            if os.path.exists(self.path):
                with open(self.path, "r", encoding="utf-8") as f:
                    return json.load(f)
            return {
                "created_at": datetime.now().isoformat(),
                "updated_at": datetime.now().isoformat(),
                "summary": "", "recent_messages": [],
                "total_turns": 0, "topics": [],
            }
    
        def save(self):
            self.data["updated_at"] = datetime.now().isoformat()
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(self.data, f, ensure_ascii=False, indent=2)
    
        def add_turn(self, user_msg, assistant_msg):
            assistant_msg = clean_output(assistant_msg)
            self.data["recent_messages"].extend([
                {"role": "user", "content": user_msg},
                {"role": "assistant", "content": assistant_msg},
            ])
            self.data["total_turns"] += 1
            if len(self.data["recent_messages"]) > 20:
                self.data["recent_messages"] = self.data["recent_messages"][-20:]
            self.save()
    
        def compress(self):
            if self.data["total_turns"] < self.compress_threshold or not self.llm:
                return
            recent = "\n".join(f"{m['role']}: {m['content']}" for m in self.data["recent_messages"])
            prompt = ("把以下对话压缩为 200 字以内的中文摘要，保留关键信息和用户偏好。直接输出摘要。\n\n"
                      f"旧摘要：{self.data['summary']}\n\n对话：\n{recent}\n\n新摘要：")
            try:
              resp = self.llm.invoke(prompt)
                _, new_summary = split_thinking(resp.content)
              self.data["summary"] = new_summary
            except Exception:
              pass
            self.data["recent_messages"] = []
          self.data["total_turns"] = 0
            self.save()
            print("\n[记忆已压缩]\n")
    
        def get_context(self):
            parts = []
            if self.data["summary"]:
                parts.append(f"[长期记忆]\n{self.data['summary']}")
            if self.data["recent_messages"]:
                recent = "\n".join(f"{m['role']}: {m['content']}"
                                  for m in self.data["recent_messages"][-6:])
                parts.append(f"[近期对话]\n{recent}")
          return "\n\n".join(parts)
    ```

    ---

    ## 六、`tools.py`（工具库）

    **作用**：9 个工具（目录、文件、系统、进程、命令、网页），重依赖延迟 import。

    ```python
  import os, subprocess, platform, webbrowser
    
    ALLOWED_COMMANDS = [
        "dir", "ls", "type", "cat", "echo", "whoami", "hostname",
        "ipconfig", "systeminfo", "tasklist", "where", "find",
        "python --version", "pip --version", "git --version",
        "ollama list", "ollama ps",
    ]
    SAFE_ROOTS = [os.path.expanduser("~"), "D:\\", "C:\\Users"]
    ENABLED_TOOLS = {
        "list_directory", "read_file", "write_file", "search_files",
        "get_system_info", "list_processes", "run_command",
        "fetch_url", "open_url",
    }
  
    
  def set_enabled_tools(names): 
        global ENABLED_TOOLS
      ENABLED_TOOLS = set(names)
    
  
    def _is_safe_path(path):
        abs_path = os.path.abspath(os.path.expanduser(path))
        return any(abs_path.lower().startswith(r.lower()) for r in SAFE_ROOTS)
    
    
  def list_directory(path="."):
        path = os.path.expanduser(path)
      if not _is_safe_path(path): return f"[拒绝] 路径不安全：{path}"
        if not os.path.isdir(path): return f"[错误] 非目录：{path}"
      try:
            items = []
          for n in sorted(os.listdir(path)):
                full = os.path.join(path, n)
                items.append(f"[DIR] {n}" if os.path.isdir(full)
                             else f"[FILE] {n} ({os.path.getsize(full)} B)")
            return f"目录 {path}：\n" + "\n".join(items) if items else f"[空] {path}"
        except Exception as e:
            return f"[错误] {e}"
    
    
  def read_file(path, max_chars=8000):
        path = os.path.expanduser(path)
      if not _is_safe_path(path): return f"[拒绝] 路径不安全：{path}"
        if not os.path.isfile(path): return f"[错误] 无此文件：{path}"
      try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                content = f.read(max_chars)
            if len(content) == max_chars: content += f"\n[... 截断，前 {max_chars} 字]"
            return content
        except Exception as e:
            return f"[错误] {e}"
    
    
    def write_file(path, content):
        path = os.path.expanduser(path)
      if not _is_safe_path(path): return f"[拒绝] 路径不安全：{path}"
        try:
          os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)
            return f"[成功] 已写入 {len(content)} 字符到 {path}"
        except Exception as e:
            return f"[错误] {e}"
    
    
    def search_files(keyword, path=".", max_results=30):
        path = os.path.expanduser(path)
        if not _is_safe_path(path): return f"[拒绝] 路径不安全：{path}"
        results = []
        try:
            for root, dirs, files in os.walk(path):
                dirs[:] = [d for d in dirs if not d.startswith(".") and d != "Windows"]
                for n in files:
                    if keyword.lower() in n.lower():
                        results.append(os.path.join(root, n))
                        if len(results) >= max_results:
                            return f"找到 {len(results)} 个：\n" + "\n".join(results)
            return (f"找到 {len(results)} 个：\n" + "\n".join(results)) if results \
                   else f"[未找到] '{keyword}'"
        except Exception as e:
            return f"[错误] {e}"
    
    
    def run_command(command):
        if not any(command.strip().lower().startswith(p) for p in ALLOWED_COMMANDS):
            return f"[拒绝] 命令不在白名单：{command}"
        try:
            r = subprocess.run(command, shell=True, capture_output=True, text=True,
                                timeout=15, encoding="utf-8", errors="replace")
            out = (r.stdout or "") + (r.stderr or "")
            return out[:4000] if out else "[无输出]"
        except subprocess.TimeoutExpired:
            return "[错误] 超时"
        except Exception as e:
            return f"[错误] {e}"
    
    
    def open_url(url):
        try:
            webbrowser.open(url)
            return f"[成功] 已打开：{url}"
        except Exception as e:
            return f"[错误] {e}"
    
    
    def get_system_info():
        try: import psutil
        except ImportError: return "[错误] 需要 pip install psutil"
        try:
            mem = psutil.virtual_memory()
            disk = psutil.disk_usage("C:\\")
            return "\n".join([
                f"系统: {platform.system()} {platform.release()}",
                f"主机名: {platform.node()}",
                f"CPU: {platform.processor()} 使用率 {psutil.cpu_percent(0.5)}%",
                f"内存: {mem.used/1e9:.1f}/{mem.total/1e9:.1f} GB ({mem.percent}%)",
                f"C盘: {disk.used/1e9:.1f}/{disk.total/1e9:.1f} GB ({disk.percent}%)",
            ])
        except Exception as e:
            return f"[错误] {e}"
    
    
    def list_processes(top_n=15):
        try: import psutil
        except ImportError: return "[错误] 需要 pip install psutil"
        procs = []
        for p in psutil.process_iter(["pid", "name", "memory_info"]):
            try:
                info = p.info
                if info["memory_info"]:
                    procs.append((info["pid"], info["name"], info["memory_info"].rss))
            except Exception: continue
        procs.sort(key=lambda x: x[2], reverse=True)
        return "\n".join(["PID\t内存(MB)\t名称"] +
                          [f"{p}\t{r/1e6:.1f}\t{n}" for p, n, r in procs[:top_n]])
    
    
    def fetch_url(url, max_chars=4000):
        try:
            import requests
            from bs4 import BeautifulSoup
        except ImportError:
            return "[错误] 需要 pip install requests beautifulsoup4"
        try:
            r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
            r.raise_for_status()
            soup = BeautifulSoup(r.text, "html.parser")
            for t in soup(["script", "style", "noscript"]): t.decompose()
            text = "\n".join(l.strip() for l in soup.get_text("\n").splitlines() if l.strip())
            title = soup.title.string.strip() if soup.title and soup.title.string else "(无标题)"
            if len(text) > max_chars: text = text[:max_chars] + f"\n[...截断]"
            return f"标题: {title}\nURL: {url}\n\n{text}"
        except Exception as e:
            return f"[错误] {e}"
    
    
    _ALL_SCHEMAS = [
        {"type": "function", "function": {"name": "list_directory", "description": "列出目录内容",
         "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}}},
        {"type": "function", "function": {"name": "read_file", "description": "读取文本文件",
         "parameters": {"type": "object", "properties": {"path": {"type": "string"}, "max_chars": {"type": "integer"}}, "required": ["path"]}}},
        {"type": "function", "function": {"name": "write_file", "description": "写入文本文件",
         "parameters": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]}}},
        {"type": "function", "function": {"name": "search_files", "description": "按文件名搜索",
         "parameters": {"type": "object", "properties": {"keyword": {"type": "string"}, "path": {"type": "string"}}, "required": ["keyword"]}}},
        {"type": "function", "function": {"name": "get_system_info", "description": "系统信息",
         "parameters": {"type": "object", "properties": {}}}},
        {"type": "function", "function": {"name": "list_processes", "description": "列出高内存进程",
         "parameters": {"type": "object", "properties": {"top_n": {"type": "integer"}}}}},
        {"type": "function", "function": {"name": "run_command", "description": "执行白名单命令",
         "parameters": {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]}}},
        {"type": "function", "function": {"name": "fetch_url", "description": "抓取网页纯文本",
         "parameters": {"type": "object", "properties": {"url": {"type": "string"}, "max_chars": {"type": "integer"}}, "required": ["url"]}}},
        {"type": "function", "function": {"name": "open_url", "description": "浏览器打开网页",
         "parameters": {"type": "object", "properties": {"url": {"type": "string"}}, "required": ["url"]}}},
    ]
    
    
    def get_tool_schemas():
        return [s for s in _ALL_SCHEMAS if s["function"]["name"] in ENABLED_TOOLS]
    
    
    TOOL_REGISTRY = {
        "list_directory": list_directory, "read_file": read_file,
        "write_file": write_file, "search_files": search_files,
        "get_system_info": get_system_info, "list_processes": list_processes,
        "run_command": run_command, "fetch_url": fetch_url, "open_url": open_url,
    }
    
    
    def execute_tool(name, args):
        if name not in ENABLED_TOOLS: return f"[拒绝] 工具未启用：{name}"
        if name not in TOOL_REGISTRY: return f"[错误] 未知工具：{name}"
        try:    return str(TOOL_REGISTRY[name](**args))
        except TypeError as e: return f"[错误] 参数错误：{e}"
        except Exception as e: return f"[错误] {e}"
    ```
  
    ---
  
    ## 七、`agent.py`（Agent 主程序）
  
    **作用**：流式对话 + 工具调用 + 文本兜底解析（Ollama 0.32.6 兼容）。
  
    ```python
    import json, os, re, sys
    import requests
    from langchain_ollama import ChatOllama
    
    from config_manager import ConfigManager, first_run_setup, list_ollama_models
    from memory_manager import MemoryManager
    import tools as tools_module
    
    try:
        sys.stdout.reconfigure(line_buffering=True, write_through=True)
        sys.stderr.reconfigure(line_buffering=True, write_through=True)
    except Exception: pass
    
    OLLAMA_URL = "http://127.0.0.1:11434/api/chat"
    
    SYSTEM_PROMPT = (
        "你是本地 AI 助手，可调用工具完成用户请求。\n"
        "规则：\n"
        "1. 需要文件/目录/系统/网络信息时，主动调用工具。\n"
        "2. 工具返回后必须用完整通顺的中文总结，不要复述字段。\n"
        "3. 读文件用 read_file；改文件先 read_file 再 write_file。\n"
        "4. 不要凭记忆编造文件内容，以工具返回为准。\n"
        "5. 不需要工具时直接回答。\n"
        "Windows 下用绝对路径，如 D:\\Code\\test\\file.py。"
    )
    
    _KNOWN_TOOLS = {
        "list_directory", "read_file", "write_file", "search_files",
        "get_system_info", "list_processes", "run_command",
        "fetch_url", "open_url",
    }
    _RE_CODE_JSON = re.compile(r"```(?:json|tool_call|tool)?\s*(\{.*?\})\s*```", re.DOTALL | re.I)
    _RE_TOOL_TAG = re.compile(r"<tool_call>\s*(\{.*?\})\s*</tool_call>", re.DOTALL | re.I)
    
    
    def _w(text):
        sys.stdout.write(text); sys.stdout.flush()
    
    
    def _normalize_call(obj):
        if not isinstance(obj, dict): return None
        if "name" in obj and "arguments" in obj:
            return {"function": {"name": obj["name"], "arguments": obj["arguments"]}}
        if "function" in obj and isinstance(obj["function"], dict):
            fn = obj["function"]
            return {"function": {"name": fn.get("name", ""), "arguments": fn.get("arguments", {})}}
        return None
    
    
    def _extract_fake_calls(text):
        if not text: return [], text
        calls, spans = [], []
        for regex in (_RE_TOOL_TAG, _RE_CODE_JSON):
            for m in regex.finditer(text):
                try: obj = json.loads(m.group(1))
                except json.JSONDecodeError: continue
                call = _normalize_call(obj)
                if call and call["function"]["name"] in _KNOWN_TOOLS:
                    calls.append(call); spans.append(m.span())
            if calls: break
        if spans:
            chars = list(text)
            for s, e in sorted(spans, reverse=True): del chars[s:e]
            text = "".join(chars).strip()
        return calls, text
    
    
    def stream_chat(model, messages, cfg, max_rounds=6):
        working = list(messages)
        schemas = tools_module.get_tool_schemas()
    
        for _ in range(max_rounds):
            payload = {
                "model": model, "messages": working, "stream": True,
                "think": cfg.get("think", False),
                "options": {
                    "temperature": cfg.get("temperature", 0.7),
                    "repeat_penalty": cfg.get("repeat_penalty", 1.05),
                    "num_predict": cfg.get("num_predict", 2048),
                    "num_ctx": cfg.get("num_ctx", 32768),
                },
            }
            if schemas: payload["tools"] = schemas
    
            thinking, answer, tool_calls = [], [], []
            buf = ""
            try:
                with requests.post(OLLAMA_URL, json=payload, stream=True, timeout=600) as r:
                    r.raise_for_status()
                    for raw in r.iter_content(chunk_size=1, decode_unicode=False):
                        if not raw: continue
                        buf += raw.decode("utf-8", errors="ignore")
                        while "\n" in buf:
                            line, buf = buf.split("\n", 1)
                            line = line.strip()
                            if not line: continue
                            try: chunk = json.loads(line)
                            except json.JSONDecodeError: continue
                            msg = chunk.get("message", {})
    
                            if msg.get("thinking"):
                                if not thinking:
                                    _w("\n[思考过程]\n")
                                _w(msg["thinking"]); thinking.append(msg["thinking"])
    
                            for tc in msg.get("tool_calls", []) or []:
                                tool_calls.append(tc)
    
                            c = msg.get("content") or ""
                            if c:
                                if not answer:
                                    _w("\n\n[回答]\n")
                                _w(c); answer.append(c)
    
                            if chunk.get("done"): break
            except requests.exceptions.ConnectionError:
                raise RuntimeError("无法连接 Ollama")
    
            _w("\n")
            raw_answer = "".join(answer)
    
            if not tool_calls and raw_answer.strip():
                fake, cleaned = _extract_fake_calls(raw_answer)
                if fake:
                    _w(f"\n[检测到文本工具调用，已解析 {len(fake)} 个]\n")
                    tool_calls = fake
                    answer = [cleaned] if cleaned.strip() else []
    
            final = "".join(answer).strip()
            if not final and thinking and not tool_calls:
                final = "".join(thinking).strip()
    
            if not tool_calls:
                return final
    
            assistant_content = final or f"（调用 {len(tool_calls)} 个工具）"
            working.append({"role": "assistant", "content": assistant_content, "tool_calls": tool_calls})
    
            for tc in tool_calls:
                fn = tc.get("function", {})
                name, args = fn.get("name", ""), fn.get("arguments", {})
                if isinstance(args, str):
                    try: args = json.loads(args)
                    except json.JSONDecodeError: args = {}
                if not isinstance(args, dict): args = {}
    
                _w(f"\n[调用工具] {name}({args})\n")
                try: result = tools_module.execute_tool(name, args)
                except Exception as e: result = f"[错误] {e}"
                preview = result if len(result) <= 500 else result[:500] + "..."
                _w(f"[工具返回]\n{preview}\n\n")
                working.append({"role": "tool", "content": result})
    
            working.append({"role": "user",
                "content": "请根据以上工具返回，用简洁中文给出最终回答。"})
    
        return "[达到最大工具轮数]"
    
    
    def handle_command(cmd, config, memory):
        parts = cmd.strip().split(maxsplit=2)
        c = parts[0].lower()
    
        if c == "/help":
            print("""
    /model <name>    切换模型
    /set <k> <v>     设置参数（temperature/num_ctx/think）
    /memory <path>   切换记忆文件
    /config          显示配置
    /tools           查看/启用/禁用工具
    /save            保存配置
    /quit            退出
    """); return True
    
        if c == "/model" and len(parts) >= 2:
            config.set("model", parts[1]); config.save()
            print(f"[模型已切换] {parts[1]}"); return True
    
        if c == "/set" and len(parts) >= 3:
            k, v = parts[1], parts[2]
            try:
                if k in ("num_ctx", "num_predict", "max_tool_rounds"): v = int(v)
                elif k in ("temperature", "repeat_penalty"): v = float(v)
                elif k == "think": v = v.lower() in ("true", "1", "yes", "y")
                config.set(k, v); config.save()
                print(f"[已设置] {k} = {v}")
            except ValueError:
                print(f"[错误] 值无效：{v}")
            return True
    
        if c == "/memory" and len(parts) >= 2:
            memory.switch_path(parts[1])
            config.set("memory_path", parts[1]); config.save()
            return True
    
        if c == "/config":
            print(config.show())
            print(f"  工具 = {sorted(tools_module.ENABLED_TOOLS)}")
            return True
    
        if c == "/tools":
            if len(parts) == 1:
                for name in sorted(tools_module.TOOL_REGISTRY.keys()):
                    s = "启用" if name in tools_module.ENABLED_TOOLS else "禁用"
                    print(f"  [{s}] {name}")
                return True
            if len(parts) >= 3:
                act, name = parts[1].lower(), parts[2]
                if name not in tools_module.TOOL_REGISTRY:
                    print(f"[错误] 未知工具：{name}"); return True
                if act == "enable":
                    tools_module.ENABLED_TOOLS.add(name)
                elif act == "disable":
                    tools_module.ENABLED_TOOLS.discard(name)
                config.set("enabled_tools", sorted(tools_module.ENABLED_TOOLS))
                config.save()
                print(f"[{act}] {name}")
            return True
    
        if c == "/save":
            config.save(); print("[已保存]"); return True
    
        return False
    
    
    def main():
        config = ConfigManager()
        if not os.path.exists(config.path):
            first_run_setup(config)
        else:
            print(f"[配置] {config.path}")
    
        if config.get("enabled_tools"):
            tools_module.set_enabled_tools(config.get("enabled_tools"))
    
        model = config.get("model")
        memory = MemoryManager(path=config.get("memory_path"), llm=ChatOllama(model=model))
    
        print(f"\nKurama | 模型：{model} | 记忆：{memory.path}")
        print("/help 查看命令，q 退出\n")
    
        while True:
            try: user_input = input("你 > ").strip()
            except (EOFError, KeyboardInterrupt): print("\n再见"); break
            if not user_input: continue
            if user_input.lower() in ("quit", "exit", "q"): print("再见"); break
    
            if user_input.startswith("/") and handle_command(user_input, config, memory):
                continue
    
            msgs = [{"role": "system", "content": SYSTEM_PROMPT}]
            mem = memory.get_context()
            if mem: msgs.append({"role": "system", "content": f"[对话记忆]\n{mem}"})
            msgs.append({"role": "user", "content": user_input})
    
            _w("\n[推理中...]\n")
            try: answer = stream_chat(model, msgs, config.data)
            except Exception as e:
                print(f"\n[错误] {e}\n"); continue
    
            if answer:
                memory.add_turn(user_input, answer)
                memory.compress()
            else:
                print("\n[警告] 无回答\n")
    
    
    if __name__ == "__main__":
        main()
    ```
  
    ---
  
    ## 八、初始化步骤
  
    ```powershell
    # 1. 创建目录
    mkdir D:\APP\LocalAgent
    cd D:\APP\LocalAgent
    
    # 2. 创建虚拟环境
    D:\APP\python\python.exe -m venv venv
    
    # 3. 安装依赖
    D:\APP\LocalAgent\venv\Scripts\python.exe -m pip install `
        langchain-ollama requests beautifulsoup4 psutil
    
    # 4. 把上面 7 个文件保存到 D:\APP\LocalAgent\
    #    start-kurama.bat
    #    start-kurama.ps1
    #    config_manager.py
    #    memory_manager.py
    #    tools.py
    #    agent.py
    
    # 5. 拉取 qwen2.5-coder
    ollama pull ollama.com/library/qwen2.5-coder:7b
    
    # 6. 创建 4-bit 模型（用户下载的 GGUF）
    cd D:\Models\Qwen2.5-Coder-7B
    @'
    FROM ./Qwen2.5-Coder-7B-Instruct.Q4_K_M.gguf
    PARAMETER num_ctx 32768
    PARAMETER temperature 0.2
    PARAMETER top_p 0.95
    '@ | Set-Content -Encoding ascii Modelfile
    ollama create qwen2.5-coder-4bit -f Modelfile
    ```
  
    ---
  
    ## 九、使用
  
    双击 `start-kurama.bat`，流程：
  
    1. **选择模型**（菜单里列出 `available_models`）
    2. **杀进程 + 等显存**（含 `llama-server.exe`）
    3. **预热模型**（第一次 30-90 秒）
    4. **检查 GPU 状态**（应显示 `100% GPU`）
    5. **进入 Agent**（输入 `q` 退出）
  
    日常命令：
  
    ```text
    你 > 读取 D:\Code\test\file.py
    你 > 修改 file.py，把时间格式改成 ISO 8601
    /model lfm2.5-thinking-32k
    /set temperature 0.1
    /tools
    ```
  
    ---
  
    ## 十、关键设计点
  
    | 文件                | 职责                                |
    | :------------------ | :---------------------------------- |
    | `start-kurama.bat`  | Windows 双击入口                    |
    | `start-kurama.ps1`  | 进程管理 + GPU 环境 + 模型预热      |
    | `agent.py`          | HTTP 流式对话 + 工具调用 + 文本兜底 |
    | `config_manager.py` | 配置读写 + 交互向导                 |
    | `memory_manager.py` | JSON 记忆 + 摘要压缩                |
    | `tools.py`          | 9 个工具 + schema 定义              |
  
    **核心机制**：
    - 进程清理包含 `llama-server.exe`（显存泄漏元凶）
    - GPU 变量确保 Vulkan 路径正确
    - `think` 参数控制思考流
    - 文本兜底解析解决 Ollama 0.32.6 工具调用格式不兼容
    - 记忆每 20 轮压缩一次