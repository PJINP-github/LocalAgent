import os
import subprocess
import platform
import webbrowser


ALLOWED_COMMANDS = [
    "dir", "ls", "type", "cat", "echo", "whoami", "hostname",
    "ipconfig", "systeminfo", "tasklist", "where", "find",
    "python --version", "pip --version", "git --version",
    "ollama list", "ollama ps",
]

SAFE_ROOTS = [
    os.path.expanduser("~"),
    "D:\\",
    "C:\\Users",
]

# 默认启用的工具集合（可通过 config 或 /tools 动态调整）
ENABLED_TOOLS = {
    "list_directory", "read_file", "write_file", "search_files",
    "get_system_info", "list_processes", "run_command",
    "fetch_url", "open_url", "bing_search",
}


def set_enabled_tools(names):
    global ENABLED_TOOLS
    ENABLED_TOOLS = set(names)


def _is_safe_path(path):
    abs_path = os.path.abspath(os.path.expanduser(path))
    return any(abs_path.lower().startswith(r.lower()) for r in SAFE_ROOTS)


# ===== 轻依赖工具 =====

def list_directory(path="."):
    path = os.path.expanduser(path)
    if not _is_safe_path(path):
        return f"[拒绝] 路径不在安全范围内：{path}"
    if not os.path.isdir(path):
        return f"[错误] 不是目录：{path}"
    try:
        items = []
        for name in sorted(os.listdir(path)):
            full = os.path.join(path, name)
            if os.path.isdir(full):
                items.append(f"[DIR]  {name}")
            else:
                size = os.path.getsize(full)
                items.append(f"[FILE] {name}  ({size} bytes)")
        if not items:
            return f"[空目录] {path}"
        return f"目录 {path} 内容：\n" + "\n".join(items)
    except Exception as e:
        return f"[错误] {e}"


def read_file(path, max_chars=8000):
    path = os.path.expanduser(path)
    if not _is_safe_path(path):
        return f"[拒绝] 路径不在安全范围内：{path}"
    if not os.path.isfile(path):
        return f"[错误] 文件不存在：{path}"
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read(max_chars)
        if len(content) == max_chars:
            content += f"\n\n[... 已截断，仅显示前 {max_chars} 字符]"
        return content
    except Exception as e:
        return f"[错误] {e}"


def write_file(path, content):
    path = os.path.expanduser(path)
    if not _is_safe_path(path):
        return f"[拒绝] 路径不在安全范围内：{path}"
    try:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return f"[成功] 已写入 {len(content)} 字符到 {path}"
    except Exception as e:
        return f"[错误] {e}"


def search_files(keyword, path=".", max_results=30):
    path = os.path.expanduser(path)
    if not _is_safe_path(path):
        return f"[拒绝] 路径不在安全范围内：{path}"
    if not os.path.isdir(path):
        return f"[错误] 不是目录：{path}"
    results = []
    keyword_lower = keyword.lower()
    try:
        for root, dirs, files in os.walk(path):
            dirs[:] = [d for d in dirs if not d.startswith(".") and d not in ("Windows", "$Recycle.Bin")]
            for name in files:
                if keyword_lower in name.lower():
                    results.append(os.path.join(root, name))
                    if len(results) >= max_results:
                        return f"找到 {len(results)} 个匹配（已截断）：\n" + "\n".join(results)
        if not results:
            return f"[未找到] 在 {path} 下没有匹配 '{keyword}' 的文件"
        return f"找到 {len(results)} 个匹配：\n" + "\n".join(results)
    except Exception as e:
        return f"[错误] {e}"


def run_command(command):
    cmd_lower = command.strip().lower()
    if not any(cmd_lower.startswith(prefix) for prefix in ALLOWED_COMMANDS):
        return f"[拒绝] 命令不在白名单内：{command}"
    try:
        result = subprocess.run(
            command, shell=True, capture_output=True, text=True,
            timeout=15, encoding="utf-8", errors="replace",
        )
        out = (result.stdout or "") + (result.stderr or "")
        return out[:4000] if out else "[无输出]"
    except subprocess.TimeoutExpired:
        return "[错误] 命令执行超时（15 秒）"
    except Exception as e:
        return f"[错误] {e}"


def open_url(url):
    try:
        webbrowser.open(url)
        return f"[成功] 已在浏览器中打开：{url}"
    except Exception as e:
        return f"[错误] {e}"


# ===== 重依赖工具（延迟 import）=====

def get_system_info():
    try:
        import psutil
    except ImportError:
        return "[错误] 需要安装 psutil：pip install psutil"
    try:
        cpu_percent = psutil.cpu_percent(interval=0.5)
        mem = psutil.virtual_memory()
        disk = psutil.disk_usage("C:\\")
        return "\n".join([
            f"系统: {platform.system()} {platform.release()}",
            f"主机名: {platform.node()}",
            f"CPU: {platform.processor()}",
            f"CPU 使用率: {cpu_percent}%",
            f"内存: {mem.used / 1e9:.1f} GB / {mem.total / 1e9:.1f} GB ({mem.percent}%)",
            f"C盘: {disk.used / 1e9:.1f} GB / {disk.total / 1e9:.1f} GB ({disk.percent}%)",
        ])
    except Exception as e:
        return f"[错误] {e}"


def list_processes(top_n=15):
    try:
        import psutil
    except ImportError:
        return "[错误] 需要安装 psutil：pip install psutil"
    try:
        procs = []
        for p in psutil.process_iter(["pid", "name", "memory_info"]):
            try:
                info = p.info
                if info["memory_info"]:
                    procs.append((info["pid"], info["name"], info["memory_info"].rss))
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        procs.sort(key=lambda x: x[2], reverse=True)
        lines = [f"{'PID':>8}  {'内存(MB)':>10}  名称"]
        for pid, name, rss in procs[:top_n]:
            lines.append(f"{pid:>8}  {rss / 1e6:>10.1f}  {name}")
        return "\n".join(lines)
    except Exception as e:
        return f"[错误] {e}"


def fetch_url(url, max_chars=4000):
    try:
        import requests
        from bs4 import BeautifulSoup
    except ImportError:
        return "[错误] 需要安装 requests 和 beautifulsoup4"
    try:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        resp = requests.get(url, headers=headers, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()
        text = soup.get_text(separator="\n")
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        text = "\n".join(lines)
        title = soup.title.string.strip() if soup.title and soup.title.string else "(无标题)"
        if len(text) > max_chars:
            text = text[:max_chars] + f"\n\n[... 已截断，仅显示前 {max_chars} 字符]"
        return f"标题: {title}\nURL: {url}\n\n{text}"
    except Exception as e:
        return f"[错误] {e}"


# ===== 新增：Bing 搜索 =====

def bing_search(query, max_results=8):
    """
    用 Bing 搜索，返回前 N 条结果的标题、摘要和链接。
    """
    try:
        import requests
        from bs4 import BeautifulSoup
    except ImportError:
        return "[错误] 需要安装 requests 和 beautifulsoup4"

    try:
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        }
        url = "https://www.bing.com/search"
        params = {"q": query, "count": str(max_results * 2)}
        resp = requests.get(url, headers=headers, params=params, timeout=20)
        resp.raise_for_status()

        soup = BeautifulSoup(resp.text, "html.parser")
        results = []

        # Bing 搜索结果主要在 <li class="b_algo"> 里
        for item in soup.select("li.b_algo"):
            if len(results) >= max_results:
                break
            h2 = item.find("h2")
            if not h2:
                continue
            a = h2.find("a")
            if not a:
                continue
            title = h2.get_text(strip=True)
            link = a.get("href", "").strip()
            if not link.startswith("http"):
                continue

            caption = item.find("div", class_="b_caption")
            snippet = ""
            if caption:
                p = caption.find("p")
                if p:
                    snippet = p.get_text(strip=True)
            if not snippet:
                p = item.find("p")
                if p:
                    snippet = p.get_text(strip=True)

            results.append({
                "title": title,
                "url": link,
                "snippet": snippet[:300],
            })

        if not results:
            return f"[未找到结果] 查询：{query}"

        lines = [f"Bing 搜索：{query}", f"共 {len(results)} 条结果", ""]
        for i, r in enumerate(results, 1):
            lines.append(f"{i}. {r['title']}")
            lines.append(f"   链接：{r['url']}")
            if r["snippet"]:
                lines.append(f"   摘要：{r['snippet']}")
            lines.append("")
        return "\n".join(lines).strip()

    except Exception as e:
        return f"[错误] Bing 搜索失败：{e}"


# ===== Tool Schemas =====

_ALL_SCHEMAS = [
    {"type": "function", "function": {"name": "list_directory", "description": "列出指定目录下的文件和子目录。", "parameters": {"type": "object", "properties": {"path": {"type": "string", "description": "目录路径。"}}, "required": ["path"]}}},
    {"type": "function", "function": {"name": "read_file", "description": "读取文本文件内容。", "parameters": {"type": "object", "properties": {"path": {"type": "string"}, "max_chars": {"type": "integer"}}, "required": ["path"]}}},
    {"type": "function", "function": {"name": "write_file", "description": "写入文本文件。", "parameters": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]}}},
    {"type": "function", "function": {"name": "search_files", "description": "按文件名模糊搜索。", "parameters": {"type": "object", "properties": {"keyword": {"type": "string"}, "path": {"type": "string"}}, "required": ["keyword"]}}},
    {"type": "function", "function": {"name": "get_system_info", "description": "获取 CPU、内存、磁盘信息。", "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {"name": "list_processes", "description": "列出占用内存最高的进程。", "parameters": {"type": "object", "properties": {"top_n": {"type": "integer"}}}}},
    {"type": "function", "function": {"name": "run_command", "description": "执行白名单内的命令。", "parameters": {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]}}},
    {"type": "function", "function": {"name": "fetch_url", "description": "抓取网页并提取纯文本。", "parameters": {"type": "object", "properties": {"url": {"type": "string"}, "max_chars": {"type": "integer"}}, "required": ["url"]}}},
    {"type": "function", "function": {"name": "open_url", "description": "用默认浏览器打开网页。", "parameters": {"type": "object", "properties": {"url": {"type": "string"}}, "required": ["url"]}}},
    {"type": "function", "function": {"name": "bing_search", "description": "用 Bing 搜索引擎查询网页信息，返回前几条结果的标题、摘要和链接。", "parameters": {"type": "object", "properties": {"query": {"type": "string", "description": "搜索关键词"}, "max_results": {"type": "integer", "description": "返回结果数，默认 8"}}, "required": ["query"]}}},
]


def get_tool_schemas():
    return [s for s in _ALL_SCHEMAS if s["function"]["name"] in ENABLED_TOOLS]


TOOL_REGISTRY = {
    "list_directory": list_directory,
    "read_file": read_file,
    "write_file": write_file,
    "search_files": search_files,
    "get_system_info": get_system_info,
    "list_processes": list_processes,
    "run_command": run_command,
    "fetch_url": fetch_url,
    "open_url": open_url,
    "bing_search": bing_search,
}


def execute_tool(name, args):
    if name not in ENABLED_TOOLS:
        return f"[拒绝] 工具未启用：{name}（/tools enable {name}）"
    if name not in TOOL_REGISTRY:
        return f"[错误] 未知工具：{name}"
    try:
        return str(TOOL_REGISTRY[name](**args))
    except TypeError as e:
        return f"[错误] 参数错误：{e}"
    except Exception as e:
        return f"[错误] 工具执行异常：{e}"