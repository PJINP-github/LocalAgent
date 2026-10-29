from __future__ import annotations

"""记忆系统列表 UI。"""
import sys

from ..common.console_input import read_key


def _visual_width(s: str) -> int:
    return sum(
        2 if "\u4e00" <= c <= "\u9fff" or "\u3000" <= c <= "\u303f" else 1
        for c in s
    )


def _pad(s: str, width: int) -> str:
    return s + " " * max(0, width - _visual_width(s))


def _render(systems, page, page_size, total_pages, current_id):
    start = page * page_size
    end = min(start + page_size, len(systems))
    print()
    print("=" * 78)
    cur = "无" if not current_id else (
        next((s["name"] for s in systems if s["id"] == current_id), "?")
    )
    print(f"  记忆系统  ·  第 {page + 1}/{total_pages} 页  ·  共 {len(systems)} 个  ·  当前：{cur}")
    print("=" * 78)
    for i in range(start, end):
        s = systems[i]
        mark = "●" if s["id"] == current_id else " "
        desc = (s.get("description") or "").strip() or "（暂无描述）"
        line = (
            f"  [{i + 1:>2}] {_pad(s['name'], 20)} {_pad(desc, 30)} "
            f"{s.get('total_turns', 0):>4} 次   "
            f"{s.get('last_active_at', '?'):>19}  {mark}"
        )
        print(line)
    print("-" * 78)
    print("  ← 上一页    → 下一页    1-5 选择    n 新建    q 退出")
    print()


def interactive_select(ms_mgr):
    """返回选中 id / 新建的 id / None。"""
    systems = ms_mgr.list_systems()
    if not systems:
        print("[无记忆系统] 使用 /sms new <名称> 创建")
        return None

    page_size = 5
    page = 0
    total_pages = (len(systems) + page_size - 1) // page_size

    # 非 tty：降级为 input()
    if not sys.stdin.isatty():
        _render(systems, page, page_size, total_pages, ms_mgr.active_id)
        try:
            choice = input("选择序号（n 新建 / q 退出）: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            return None
        if choice in ("", "q"):
            return None
        if choice == "n":
            try:
                name = input("新记忆系统名称: ").strip()
            except (EOFError, KeyboardInterrupt):
                return None
            if name:
                return ms_mgr.create(name)
            return None
        if choice.isdigit():
            n = int(choice)
            if 1 <= n <= len(systems):
                return systems[n - 1]["id"]
        print("[错误] 无效输入")
        return None

    # 交互式
    while True:
        _render(systems, page, page_size, total_pages, ms_mgr.active_id)
        key = read_key()
        if key in ("q", "esc"):
            return None
        if key == "":
            print("[提示] 当前终端不支持按键读取，请使用 /sms <N> 直接切换")
            return None
        if key == "left":
            if page > 0:
                page -= 1
        elif key == "right":
            if page < total_pages - 1:
                page += 1
        elif key.isdigit():
            n = int(key)
            if 1 <= n <= page_size:
                idx = page * page_size + (n - 1)
                if 0 <= idx < len(systems):
                    return systems[idx]["id"]
        elif key == "n":
            try:
                name = input("新记忆系统名称: ").strip()
            except (EOFError, KeyboardInterrupt):
                return None
            if name:
                return ms_mgr.create(name)
