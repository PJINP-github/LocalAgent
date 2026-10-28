# Kurama — 本地 AI 助手

基于 **Ollama** 的本地化中文 AI 助手，支持流式对话、思考过程展示、工具调用与长期记忆。无需联网（除可选工具外），全部模型在本地 GPU 上运行。

---

## 目录

- [简介](#简介)
- [核心特性](#核心特性)
- [目录结构](#目录结构)
- [环境要求](#环境要求)
- [安装部署](#安装部署)
- [配置说明](#配置说明)
- [使用说明](#使用说明)
- [命令一览](#命令一览)
- [内置工具](#内置工具)
- [记忆系统](#记忆系统)
- [上下文用量监控](#上下文用量监控)
- [工作流程](#工作流程)
- [常见问题](#常见问题)
- [开发者说明](#开发者说明)

---

## 简介

**Kurama** 是一个完全本地运行的 AI 助手命令行应用，通过 Ollama 调用本地大语言模型（默认推荐 `qwen2.5-coder` 或 `qwen3.5` 系列）。它具备：

- 流式输出（thinking 过程与正式回答分开展示）
- 工具调用能力（读写文件、执行命令、搜索网页等）
- 跨会话记忆（JSON 持久化 + 自动压缩摘要）
- 上下文用量可视化
- Ollama 0.32.6 文本工具调用兜底解析

目标是提供一个**轻量、可扩展、隐私友好**的本地 Agent 框架，适合在日常编码、文档处理、系统运维查询中作为辅助工具。

---

## 核心特性

| 特性 | 说明 |
| :--- | :--- |
| **流式对话** | SSE 逐 token 输出，`[思考过程]` 与 `[回答]` 分离显示 |
| **工具调用** | 10 个内置工具，支持 Ollama 原生 `tool_calls` 与文本形式兜底解析 |
| **思考模式** | 通过 `think` 参数开启（qwen3 等推理模型支持） |
| **记忆系统** | 长期摘要 + 近期消息注入，每 20 轮触发 LLM 压缩 |
| **上下文监控** | `/overplus` 显示 token 占用、进度条、剩余余量 |
| **动态工具管理** | `/tools enable/disable` 运行时开关工具 |
| **交互式配置向导** | 首次运行或 `/config-edit` 引导选模型、设参数 |
| **纯本地** | 模型推理、记忆文件、配置全部本地保存 |

---

## 目录结构

```text
D:\APP\LocalAgent\
├── .local-agent\
│   ├── config.json            # 配置文件（首次运行生成）
│   └── memory.json            # 记忆文件（自动生成）
├── venv\                       # Python 虚拟环境
├── agent.py                    # 主程序：流式对话 + 工具调用
├── config_manager.py           # 配置读写 + 交互式向导
├── memory_manager.py           # 记忆持久化 + 摘要压缩
├── tools.py                    # 工具库（10 个工具 + schema）
├── start-kurama.ps1            # 启动主逻辑（进程清理 + 预热）
└── start-kurama.bat            # 双击入口
```

---

## 环境要求

| 项目 | 要求 |
| :--- | :--- |
| **操作系统** | Windows 10 / 11（脚本为 PowerShell） |
| **Python** | 3.10+（推荐 3.13） |
| **Ollama** | **0.32.6**（0.40.x 在 Intel Arc 上有 Vulkan 显存问题） |
| **GPU** | Intel Arc / NVIDIA / AMD（Vulkan 或 CUDA 加速均可） |
| **显存** | 8K 上下文 ≈ 4.8 GB；32K 上下文 ≈ 5.6 GB |

> **推荐模型**：`qwen2.5-coder-8k`（日常编码）或 `qwen3.5-2b-8k`（轻量）。

---

## 安装部署

### 1. 安装 Ollama

1. 从 https://ollama.com/download 下载安装 `OllamaSetup.exe`
2. **关闭自动更新**（避免升级到 0.40.x）
3. 配置 GPU 环境变量（Intel Arc 用户）：

```powershell
setx OLLAMA_VULKAN 1
setx OLLAMA_IGPU_ENABLE 1
setx OLLAMA_INTEL_GPU true
```

4. **重启 Ollama**（托盘退出 → 重新打开）

### 2. 准备模型

**方式一：官方拉取**

```powershell
ollama pull ollama.com/library/qwen2.5-coder:7b
```

**方式二：ModelScope 下载 GGUF 后本地导入**

```powershell
D:\APP\python\python.exe -m pip install modelscope
D:\APP\python\python.exe -c "from modelscope import snapshot_download; snapshot_download('QuantFactory/Qwen2.5-Coder-7B-Instruct-GGUF', allow_patterns=['*Q4_K_M*.gguf'], local_dir='D:/Models/Qwen2.5-Coder-7B')"
```

创建不同上下文版本（4K / 8K / 16K / 32K）：

```powershell
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
```

验证：

```powershell
ollama list
ollama run qwen2.5-coder-8k "hi"
# 另开窗口
ollama ps   # 应显示 100% GPU
```

### 3. 安装 Python 依赖

```powershell
mkdir D:\APP\LocalAgent
cd D:\APP\LocalAgent
D:\APP\python\python.exe -m venv venv
.\venv\Scripts\python.exe -m pip install langchain-ollama requests beautifulsoup4 psutil
```

### 4. 复制项目文件

将以下文件放入 `D:\APP\LocalAgent\`：

```text
agent.py
config_manager.py
memory_manager.py
tools.py
start-kurama.ps1
start-kurama.bat
```

### 5. 首次运行

双击 `start-kurama.bat`，流程如下：

1. **选择模型**（从 `available_models` 菜单中选）
2. **杀进程 + 等显存**（自动清理 `llama-server.exe`）
3. **设置 GPU 环境变量**
4. **预热模型**（首次 30–90 秒）
5. **检查 GPU 状态**（应显示 `100% GPU`）
6. **进入 Agent 交互界面**

---

## 配置说明

配置文件：`.local-agent\config.json`

| 键 | 默认值 | 说明 |
| :--- | :--- | :--- |
| `model` | `qwen3.5-9b-8k` | 当前使用的模型名 |
| `available_models` | — | 启动菜单中可选的模型列表 |
| `memory_path` | `.local-agent/memory.json` | 记忆文件路径 |
| `temperature` | `0.7` | 采样温度 |
| `num_ctx` | `32768` | 上下文窗口大小 |
| `repeat_penalty` | `1.15` | 重复惩罚 |
| `num_predict` | `3072` | 最大输出 token 数 |
| `think` | `true` | 是否开启思考模式 |
| `max_tool_rounds` | `6` | 单次对话最多工具调用轮数 |
| `enabled_tools` | 见下 | 启用的工具列表 |

**默认启用工具**：

```json
["list_directory", "read_file", "write_file", "search_files",
 "get_system_info", "list_processes", "run_command",
 "fetch_url", "open_url"]
```

---

## 使用说明

### 启动

双击 `start-kurama.bat`，选择模型后进入交互界面：

```text
Kurama | 模型：qwen2.5-coder-8k | 记忆：...memory.json
/help 查看命令，/overplus 查看余量，q 退出

你 > 读取 D:\Code\test\file.py
你 > 把 file.py 里的时间格式改成 ISO 8601
你 > 查看当前系统内存占用
你 > 搜索 Ollama Vulkan 相关的配置
```

### 退出

输入 `q`、`quit` 或 `exit`，或按 `Ctrl+C`。

---

## 命令一览

| 命令 | 说明 |
| :--- | :--- |
| `/help` | 显示所有命令 |
| `/overplus` | 显示上下文 token 使用情况（含进度条） |
| `/model <name>` | 切换模型 |
| `/set <key> <value>` | 设置参数（temperature、num_ctx、think 等） |
| `/memory <path>` | 切换记忆文件 |
| `/config` | 显示当前配置 |
| `/config-edit` | 重新进入交互式配置向导 |
| `/models` | 列出 Ollama 已安装模型 |
| `/tools` | 查看所有工具状态 |
| `/tools enable <name>` | 启用工具 |
| `/tools disable <name>` | 禁用工具 |
| `/save` | 保存当前配置 |

**示例**：

```text
/set temperature 0.2
/set num_ctx 16384
/set think false
/tools enable bing_search
/model qwen2.5-coder-32k
```

---

## 内置工具

| 工具 | 功能 | 安全限制 |
| :--- | :--- | :--- |
| `list_directory` | 列出目录内容 | 仅限 `SAFE_ROOTS`（用户目录、`D:\`、`C:\Users`） |
| `read_file` | 读取文本文件 | 同上，最多 8000 字符 |
| `write_file` | 写入文本文件 | 同上 |
| `search_files` | 按文件名模糊搜索 | 跳过隐藏目录和 `Windows` |
| `get_system_info` | CPU / 内存 / 磁盘 | — |
| `list_processes` | 高内存进程 Top N | — |
| `run_command` | 执行白名单命令 | 仅限 `dir`、`type`、`ipconfig` 等 |
| `fetch_url` | 抓取网页正文 | requests + BeautifulSoup |
| `open_url` | 浏览器打开链接 | — |
| `bing_search` | Bing 搜索前 N 条 | requests + BeautifulSoup |

**白名单命令**（`ALLOWED_COMMANDS`）：

```text
dir, ls, type, cat, echo, whoami, hostname,
ipconfig, systeminfo, tasklist, where, find,
python --version, pip --version, git --version,
ollama list, ollama ps
```

> 扩展工具：在 `tools.py` 中定义函数 + `_ALL_SCHEMAS` 中加入 schema + `TOOL_REGISTRY` 注册即可。

---

## 记忆系统

`MemoryManager` 采用**双层记忆结构**：

```json
{
  "created_at": "...",
  "updated_at": "...",
  "summary": "长期记忆摘要（LLM 压缩生成）",
  "recent_messages": [
    {"role": "user", "content": "..."},
    {"role": "assistant", "content": "..."}
  ],
  "total_turns": 0,
  "topics": []
}
```

| 参数 | 说明 |
| :--- | :--- |
| `recent_messages` | 最近消息，最多保留 20 条 |
| `total_turns` | 累计对话轮数 |
| `compress_threshold` | 默认 20 轮，达到后触发 LLM 压缩 |
| 注入上下文 | 长期摘要 + 最近 6 条消息 |

**压缩流程**：

```text
累计 ≥ 20 轮 → LLM 生成 200 字以内摘要 → 清空 recent_messages → total_turns 归零
```

每次对话前显示**记忆轮廓**：

```text
[记忆轮廓]
  长期摘要  : ...
  近期对话  : 12 条  (注入最近 6 条)
  累计轮数  : 8  (每 20 轮压缩一次)
  话题标签  : （无）
  启用工具  : 10 / 10
  记忆文件  : ...memory.json
```

---

## 上下文用量监控

输入 `/overplus` 显示：

```text
[上下文用量]
  模型上限   :  32,768 tokens  ( 32.0K)
  输入已用   :   1,234 tokens  (  1.2K)
  上次输出   :     256 tokens  (  0.3K)
  剩余可用   :  31,534 tokens  ( 30.8K)
  占用比例   : [█░░░░░░░░░░░░░░░░░░░░░░░░░░░░░] 3.8%
  本会话累计 : 输入 12,345 / 输出 2,678
```

**Token 估算规则**（当 Ollama 未返回精确值时）：

- 中文字符：`1.5 token / 字`
- 其他字符：`1 token / 3.5 字符`
- 每条消息 +4 token 结构开销

---

## 工作流程

```text
┌──────────────┐
│  用户输入     │
└──────┬───────┘
       ▼
┌──────────────────┐
│ 命令判断（/xxx）  │──是──▶ 执行命令 ──▶ 返回
└──────┬───────────┘
       │否
       ▼
┌──────────────────┐
│ 显示记忆轮廓      │
└──────┬───────────┘
       ▼
┌──────────────────────────────┐
│ 构造 messages：               │
│   system prompt              │
│   + 记忆上下文               │
│   + 用户输入                 │
└──────┬───────────────────────┘
       ▼
┌──────────────────┐
│ 流式调用 Ollama   │◀─────┐
└──────┬───────────┘      │
       ▼                  │
  ┌────────────┐          │
  │ 有 tool_call? │──是──▶ 执行工具，追加 tool 消息，回到推理
  └──────┬─────┘          │
         │否              │
         ▼                │
    ┌────────────┐        │
    │ 最终回答     │────────┘
    └──────┬─────┘
           ▼
    ┌────────────────┐
    │ 保存到记忆系统    │
    │ 可能触发压缩      │
    └────────────────┘
```

**兜底解析**：

Ollama 0.32.6 有时将工具调用输出为文本：

```text
```json
{"name": "read_file", "arguments": {"path": "D:\\Code\\test\\file.py"}}
```
```

`_extract_fake_calls()` 会自动识别以下格式并转为原生 tool_call：

- `<tool_call>{...}</tool_call>`
- ` ```json\n{...}\n``` `

---

## 常见问题

### Q1: 启动报 `WARMUP FAILED` / 500

显存被占用。按顺序排查：

```powershell
# 1. 杀残留进程
Get-Process -Name "llama-server" -ErrorAction SilentlyContinue | Stop-Process -Force
Get-Process -Name "*ollama*" -ErrorAction SilentlyContinue | Stop-Process -Force
Start-Sleep -Seconds 10

# 2. 检查共享显存
Get-Counter "\GPU Adapter Memory(*)\Shared Usage" | Select-Object -ExpandProperty CounterSamples | Sort-Object CookedValue -Descending | Select-Object -First 1 | ForEach-Object { "共享显存：{0:N2} GB" -f ($_.CookedValue / 1GB) }
```

- < 2 GB → 干净
- \> 6 GB → 关闭浏览器/音乐播放器硬件加速

**上下文降级**：32K → 16K → 8K → 4K

### Q2: `100% CPU` 而非 GPU

Vulkan 变量未生效：

```powershell
echo $env:OLLAMA_VULKAN   # 应输出 1
```

重启 Ollama 后再试。

### Q3: `ollama list` 看不到新建的模型

0.32.6 manifest 路径问题。用 `ollama.com/library/` 前缀命名，或参考 Ollama 文档中的 manifest 修复。

### Q4: 模型下载慢

用 ModelScope 镜像下载 GGUF 后本地导入（见安装部署 → 方式二）。

### Q5: 工具调用没有执行

Ollama 0.32.6 有时以文本形式返回。程序会自动兜底解析，但若格式异常，请检查模型是否支持 tool_calling。

### Q6: `/model` 切换后立即生效吗？

是的，但需保证目标模型已 `ollama pull` 过。首次调用会触发加载（30–90 秒）。

---

## 开发者说明

### 扩展新工具

1. **在 `tools.py` 定义函数**：

```python
def my_tool(param1: str, param2: int = 10) -> str:
    try:
        import heavy_dependency  # 延迟导入
    except ImportError:
        return "[错误] 需要安装 heavy_dependency"
    # ... 业务逻辑
    return "结果"
```

2. **加入 `_ALL_SCHEMAS`**：

```python
{"type": "function", "function": {
    "name": "my_tool",
    "description": "工具功能描述",
    "parameters": {
        "type": "object",
        "properties": {
            "param1": {"type": "string"},
            "param2": {"type": "integer"},
        },
        "required": ["param1"],
    },
}}
```

3. **加入 `TOOL_REGISTRY`**：

```python
TOOL_REGISTRY = {..., "my_tool": my_tool}
```

4. **加入默认 `ENABLED_TOOLS`**（可选）：

```python
ENABLED_TOOLS = {..., "my_tool"}
```

### 替换记忆压缩策略

编辑 `memory_manager.py` 的 `compress_threshold` 或在 `compress()` 中替换 prompt 模板。

### 修改系统提示词

编辑 `agent.py` 顶部的 `SYSTEM_PROMPT` 常量。

### 增加模型

在 `config.json` 的 `available_models` 中加入模型名，重启 `start-kurama.bat` 即可在菜单中看到。

---

## 关键设计点

| 文件 | 职责 |
| :--- | :--- |
| `start-kurama.bat` | Windows 双击入口 |
| `start-kurama.ps1` | 进程管理 + GPU 环境 + 模型预热 |
| `agent.py` | HTTP 流式对话 + 工具调用 + 文本兜底 |
| `config_manager.py` | 配置读写 + 交互向导 |
| `memory_manager.py` | JSON 记忆 + 摘要压缩 |
| `tools.py` | 10 个工具 + schema 定义 |

**核心机制**：

- **进程清理包含 `llama-server.exe`** — 显存泄漏元凶
- **GPU 变量确保 Vulkan 路径正确** — Intel Arc 必配
- **`think` 参数控制思考流** — qwen3 / deepseek-r1 等支持
- **文本兜底解析** — 解决 Ollama 0.32.6 工具调用格式不兼容
- **记忆每 20 轮压缩** — 控制上下文膨胀

---

## License

本项目为个人本地工具，代码可自由修改分发。第三方依赖遵循各自许可证（`langchain-ollama` MIT、`ollama` MIT 等）。

---

**祝使用愉快，Happy Hacking 🦙**