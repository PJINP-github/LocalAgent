import json
import os
import re
import sys

import requests
from langchain_ollama import ChatOllama

from ..config_manager import ConfigManager, first_run_setup, list_ollama_models
from ..memory_manager import MemoryManager
from .. import tools as tools_module

try:
    sys.stdout.reconfigure(line_buffering=True, write_through=True)
    sys.stderr.reconfigure(line_buffering=True, write_through=True)
except Exception:
    pass

OLLAMA_URL = "http://127.0.0.1:11434/api/chat"

SYSTEM_PROMPT = (
    "你是一个本地智能助手 Kurama，可以调用工具完成用户请求。\n"
    "\n"
    "【第一原则：判断是否需要工具】\n"
    "调用工具前先问自己：用户的这句话，是否明确在请求外部数据或操作？\n"
    "- 打招呼、闲聊、问身份、表达感谢、告别 → 直接回答，禁止调用工具。\n"
    "  例：hi / hello / 你好 / 在吗 / 谢谢 / 你是谁 → 直接文字回复。\n"
    "- 用户输入与「文件 / 目录 / 系统 / 网络 / 命令」无直接关系 → 直接回答，禁止调用工具。\n"
    "- 只有在需要真实外部数据时，才调用工具。不要为了「展示能力」而调用。\n"
    "\n"
    "【第二原则：不要被历史记忆带偏】\n"
    "- 只根据用户「当前这一句话」判断意图，不要因为近期对话聊过某路径/某文件，就主动再去查。\n"
    "- 历史记忆只用于「理解上下文」和「保持人称/语气」，不能作为「继续上次操作」的依据。\n"
    "- 如果用户没提具体路径、具体命令、具体 URL，不要自行编造或猜测一个。\n"
    "\n"
    "【工具调用规则】\n"
    "1. 需要查看文件、目录、系统信息、网络内容时，主动调用相应工具。\n"
    "2. 每次调用工具后，必须根据工具返回的结果，用完整的中文句子给用户一个最终总结。\n"
    "   不要只调用工具就结束，也不要复述原始字段。\n"
    "3. 工具调用失败时最多重试一次，然后直接告诉用户失败原因。\n"
    "4. 不需要工具时，直接回答即可。\n"
    "5. 读取文件时调用 read_file；修改文件时先 read_file 再 write_file。\n"
    "6. 不要凭记忆编造文件内容，必须以工具返回为准。\n"
    "7. 工具返回「[拒绝] 路径不在安全范围内」或「[错误] ...」时，"
    "   直接把这个原因告诉用户，不要自己换一个路径再试。\n"
    "\n"
    "【何时该调用工具（举例）】\n"
    "- 「读一下 xxx 文件」「列一下 xxx 目录」→ list_directory / read_file\n"
    "- 「把 yyy 改成 zzz」→ read_file 后再 write_file\n"
    "- 「看下系统内存/CPU」→ get_system_info\n"
    "- 「搜一下 xxx」→ bing_search\n"
    "- 「打开 xxx 网页」/「抓一下 xxx 的内容」→ open_url / fetch_url\n"
    "- 「执行 dir / ipconfig / ollama list」→ run_command\n"
    "\n"
    "【何时不要调用工具（举例）】\n"
    "- 打招呼 / 道谢 / 告别 / 简单询问 → 直接答\n"
    "- 「你是谁」「能做什么」「介绍一下自己」→ 直接答\n"
    "- 用户只丢一个单词或短语、没有明确指令 → 先反问「你想让我做什么」，不要猜\n"
    "\n"
    "【回答格式】\n"
    "- 用简洁、通顺的中文回答，不要随机拼接关键词。\n"
    "- 不要输出 JSON、Markdown 代码块、工具名、参数名等内部结构给用户看。\n"
    "- 工具失败时用一句中文说明原因即可，不要贴原始报错栈。\n"
    "\n"
        "【路径规范】\n"
    "- 需要绝对路径时，优先使用用户主目录（%USERPROFILE%）下的路径。\n"
    "- 项目内文件使用相对项目根目录的路径，例如 config/、sources/、src/。\n"
    "- 不要编造不存在的盘符（如 D:\\、E:\\），除非用户明确提供了该路径。\n"
    "- 用户没给路径时，先问用户要哪个路径，不要自己假设。\n"
)

_KNOWN_TOOLS = {
    "list_directory", "read_file", "write_file", "search_files",
    "get_system_info", "list_processes", "run_command",
    "fetch_url", "open_url", "bing_search",
}
_RE_CODE_JSON = re.compile(r"```(?:json|tool_call|tool)?\s*(\{.*?\})\s*```", re.DOTALL | re.I)
_RE_TOOL_TAG = re.compile(r"<tool_call>\s*(\{.*?\})\s*</tool_call>", re.DOTALL | re.I)

# ===== 会话级 token 统计 =====
_LAST_PROMPT_TOKENS = 0
_LAST_COMPLETION_TOKENS = 0
_SESSION_PROMPT_TOTAL = 0
_SESSION_COMPLETION_TOTAL = 0


def _w(text):
    sys.stdout.write(text)
    sys.stdout.flush()


# ===== token 估算（当 Ollama 未返回精确值时使用）=====
def _estimate_tokens(text):
    if not text:
        return 0
    chinese = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
    others = len(text) - chinese
    return int(chinese * 1.5 + others / 3.5)


def _estimate_messages_tokens(messages):
    total = 0
    for m in messages:
        content = m.get("content", "") or ""
        total += _estimate_tokens(content)
        total += 4  # 角色和结构开销
        for tc in m.get("tool_calls", []) or []:
            total += _estimate_tokens(json.dumps(tc, ensure_ascii=False))
    return total


# ===== 文本兜底解析 =====
def _normalize_call(obj):
    if not isinstance(obj, dict):
        return None
    if "name" in obj and "arguments" in obj:
        return {"function": {"name": obj["name"], "arguments": obj["arguments"]}}
    if "function" in obj and isinstance(obj["function"], dict):
        fn = obj["function"]
        return {"function": {"name": fn.get("name", ""), "arguments": fn.get("arguments", {})}}
    return None


def _extract_fake_calls(text):
    if not text:
        return [], text
    calls, spans = [], []
    for regex in (_RE_TOOL_TAG, _RE_CODE_JSON):
        for m in regex.finditer(text):
            try:
                obj = json.loads(m.group(1))
            except json.JSONDecodeError:
                continue
            call = _normalize_call(obj)
            if call and call["function"]["name"] in _KNOWN_TOOLS:
                calls.append(call)
                spans.append(m.span())
        if calls:
            break
    if spans:
        chars = list(text)
        for s, e in sorted(spans, reverse=True):
            del chars[s:e]
        text = "".join(chars).strip()
    return calls, text


# ===== 主对话循环 =====
def stream_chat(model, messages, cfg, max_rounds=6):
    global _LAST_PROMPT_TOKENS, _LAST_COMPLETION_TOKENS
    global _SESSION_PROMPT_TOTAL, _SESSION_COMPLETION_TOTAL

    working = list(messages)
    schemas = tools_module.get_tool_schemas()
    last_prompt_t = 0
    last_completion_t = 0

    for _ in range(max_rounds):
        payload = {
            "model": model,
            "messages": working,
            "stream": True,
            "think": cfg.get("think", False),
            "options": {
                "temperature": cfg.get("temperature", 0.7),
                "repeat_penalty": cfg.get("repeat_penalty", 1.05),
                "num_predict": cfg.get("num_predict", 2048),
                "num_ctx": cfg.get("num_ctx", 32768),
            },
        }
        if schemas:
            payload["tools"] = schemas

        thinking, answer, tool_calls = [], [], []
        buf = ""

        try:
            with requests.post(OLLAMA_URL, json=payload, stream=True, timeout=600) as r:
                r.raise_for_status()
                for line in r.iter_lines(decode_unicode=True):
                    if not line:
                        continue
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        chunk = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    msg = chunk.get("message", {})

                    if msg.get("thinking"):
                        if not thinking:
                            _w("\n[思考过程]\n")
                        _w(msg["thinking"])
                        thinking.append(msg["thinking"])

                    for tc in msg.get("tool_calls", []) or []:
                        tool_calls.append(tc)

                    c = msg.get("content") or ""
                    if c:
                        if not answer:
                            _w("\n\n[回答]\n")
                        _w(c)
                        answer.append(c)

                    if chunk.get("done"):
                        # 记录本次请求的 token
                        last_prompt_t = chunk.get("prompt_eval_count", 0) or 0
                        last_completion_t = chunk.get("eval_count", 0) or 0
                        break
        except requests.exceptions.ConnectionError:
            raise RuntimeError("无法连接 Ollama (127.0.0.1:11434)。")

        _w("\n")

        # 无 token 信息时用估算
        if last_prompt_t == 0:
            last_prompt_t = _estimate_messages_tokens(working)
        if last_completion_t == 0:
            last_completion_t = _estimate_tokens("".join(answer) + "".join(thinking))

        raw_answer = "".join(answer)

        # 兜底：文本工具调用
        if not tool_calls and raw_answer.strip():
            fake, cleaned = _extract_fake_calls(raw_answer)
            if fake:
                _w(f"\n[检测到文本形式的工具调用，已自动解析 {len(fake)} 个]\n")
                tool_calls = fake
                answer = [cleaned] if cleaned.strip() else []

        final = "".join(answer).strip()
        if not final and thinking and not tool_calls:
            final = "".join(thinking).strip()

        if not tool_calls:
            _LAST_PROMPT_TOKENS = last_prompt_t
            _LAST_COMPLETION_TOKENS = last_completion_t
            _SESSION_PROMPT_TOTAL += last_prompt_t
            _SESSION_COMPLETION_TOTAL += last_completion_t
            return final

        assistant_content = final or f"（调用 {len(tool_calls)} 个工具）"
        working.append({"role": "assistant", "content": assistant_content, "tool_calls": tool_calls})

        for tc in tool_calls:
            fn = tc.get("function", {})
            name, args = fn.get("name", ""), fn.get("arguments", {})
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except json.JSONDecodeError:
                    args = {}
            if not isinstance(args, dict):
                args = {}

            _w(f"\n[调用工具] {name}({args})\n")
            try:
                result = tools_module.execute_tool(name, args)
            except Exception as e:
                result = f"[错误] {e}"
            preview = result if len(result) <= 500 else result[:500] + "..."
            _w(f"[工具返回]\n{preview}\n\n")
            working.append({"role": "tool", "content": result})

        working.append({
            "role": "user",
            "content": "请根据以上工具返回的结果，用简洁的中文给用户一个完整的最终回答。",
        })

    _LAST_PROMPT_TOKENS = last_prompt_t
    _LAST_COMPLETION_TOKENS = last_completion_t
    return "[达到最大工具轮数，已停止]"


# ===== 新增：上下文余量显示 =====
def _show_overplus(config):
    num_ctx = config.get("num_ctx", 32768)
    prompt_t = _LAST_PROMPT_TOKENS
    completion_t = _LAST_COMPLETION_TOKENS
    used = prompt_t
    remaining = max(0, num_ctx - used)
    percent = (used / num_ctx * 100) if num_ctx else 0

    # 可视化进度条（30 格）
    bar_len = 30
    filled = int(percent / 100 * bar_len)
    bar = "█" * filled + "░" * (bar_len - filled)

    print(f"\n[上下文用量]")
    print(f"  模型上限   : {num_ctx:>7,} tokens  ({num_ctx/1024:>5.1f}K)")
    print(f"  输入已用   : {prompt_t:>7,} tokens  ({prompt_t/1024:>5.1f}K)")
    print(f"  上次输出   : {completion_t:>7,} tokens  ({completion_t/1024:>5.1f}K)")
    print(f"  剩余可用   : {remaining:>7,} tokens  ({remaining/1024:>5.1f}K)")
    print(f"  占用比例   : [{bar}] {percent:.1f}%")
    print(f"  本会话累计 : 输入 {_SESSION_PROMPT_TOTAL:,} / 输出 {_SESSION_COMPLETION_TOTAL:,}")
    print()


# ===== 新增：记忆轮廓 =====
def _show_adumbration(memory, config):
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
    print()


# ===== 命令处理 =====
def handle_command(cmd, config, memory):
    parts = cmd.strip().split(maxsplit=2)
    c = parts[0].lower()

    if c == "/help":
        print("""
可用命令：
  /overplus              显示上下文剩余 token
  /model <name>          切换模型
  /set <key> <value>     设置参数（temperature, num_ctx, think 等）
  /memory <path>         切换记忆文件
  /config                显示当前配置
  /config-edit           重新进入配置向导
  /models                列出可用模型
  /tools                 查看工具状态
  /tools enable <name>   启用工具
  /tools disable <name>  禁用工具
  /save                  保存配置
  /help                  显示帮助
""")
        return True

    if c == "/overplus":
        _show_overplus(config)
        return True

    if c == "/model" and len(parts) >= 2:
        config.set("model", parts[1])
        config.save()
        print(f"[模型已切换] {parts[1]}")
        return True

    if c == "/set" and len(parts) >= 3:
        key, val = parts[1], parts[2]
        try:
            if key in ("num_ctx", "num_predict", "max_tool_rounds"):
                val = int(val)
            elif key in ("temperature", "repeat_penalty"):
                val = float(val)
            elif key == "think":
                val = val.lower() in ("true", "1", "yes", "y")
            config.set(key, val)
            config.save()
            print(f"[已设置] {key} = {val}")
        except ValueError:
            print(f"[错误] 无效的值：{val}")
        return True

    if c == "/memory" and len(parts) >= 2:
        memory.switch_path(parts[1])
        config.set("memory_path", parts[1])
        config.save()
        return True

    if c == "/config":
        print(config.show())
        print(f"  启用的工具 = {sorted(tools_module.ENABLED_TOOLS)}")
        return True

    if c == "/config-edit":
        first_run_setup(config)
        return True

    if c == "/models":
        for m in list_ollama_models():
            print(f"  {m}")
        return True

    if c == "/tools":
        if len(parts) == 1:
            print("所有工具：")
            for name in sorted(tools_module.TOOL_REGISTRY.keys()):
                status = "启用" if name in tools_module.ENABLED_TOOLS else "禁用"
                print(f"  [{status}] {name}")
            return True
        if len(parts) >= 3:
            action, name = parts[1].lower(), parts[2]
            if name not in tools_module.TOOL_REGISTRY:
                print(f"[错误] 未知工具：{name}")
                return True
            if action == "enable":
                tools_module.ENABLED_TOOLS.add(name)
                config.set("enabled_tools", sorted(tools_module.ENABLED_TOOLS))
                config.save()
                print(f"[已启用] {name}")
            elif action == "disable":
                tools_module.ENABLED_TOOLS.discard(name)
                config.set("enabled_tools", sorted(tools_module.ENABLED_TOOLS))
                config.save()
                print(f"[已禁用] {name}")
            return True

    if c == "/save":
        config.save()
        print("[配置已保存]")
        return True

    return False


# ===== 主入口 =====
def main():
    global _SESSION_PROMPT_TOTAL, _SESSION_COMPLETION_TOTAL
    _SESSION_PROMPT_TOTAL = 0
    _SESSION_COMPLETION_TOTAL = 0

    config = ConfigManager()

    if not os.path.exists(config.path):
        first_run_setup(config)
    else:
        print(f"[配置] {config.path}")

    enabled = config.get("enabled_tools")
    if enabled:
        tools_module.set_enabled_tools(enabled)

    model = config.get("model")
    memory = MemoryManager(path=config.get("memory_path"), llm=ChatOllama(model=model))

    print(f"\nKurama | 模型：{model} | 记忆：{memory.path}")
    print("/help 查看命令，/overplus 查看余量，q 退出\n")

    while True:
        try:
            user_input = input("你 > ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n再见！")
            break

        if not user_input:
            continue
        if user_input.lower() in ("quit", "exit", "q"):
            print("再见！")
            break

        if user_input.startswith("/"):
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
            print("\n[警告] 模型没有返回回答。\n")


if __name__ == "__main__":
    main()