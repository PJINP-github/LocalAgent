from pathlib import Path
import json
import os
import re
from datetime import datetime
from ..common.paths import resolve


def split_thinking(text: str):
    if not text:
        return "", text
    m = re.search(r"Thinking\.\.\.(.*?)\.\.\.done thinking\.\s*", text, flags=re.DOTALL | re.IGNORECASE)
    if m:
        return m.group(1).strip(), text[m.end():].strip()
    m = re.search(r"<think(?:ing)?>(.*?)</think(?:ing)?>", text, flags=re.DOTALL | re.IGNORECASE)
    if m:
        return m.group(1).strip(), (text[:m.start()] + text[m.end():]).strip()
    return "", text.strip()


def clean_output(text: str) -> str:
    _, answer = split_thinking(text)
    return answer


class MemoryManager:
    def __init__(self, path=None, llm=None):
        if path is None:
            path = "config/memory.json"
        self.path = str(resolve(path))
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        self.llm = llm
        self.data = self._load()
        self.compress_threshold = 20

    def switch_path(self, new_path: str):
        self.path = str(resolve(new_path))
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
            "summary": "",
            "recent_messages": [],
            "total_turns": 0,
            "topics": [],
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
        old_summary = self.data["summary"]
        recent_text = "\n".join(f"{m['role']}: {m['content']}" for m in self.data["recent_messages"])
        prompt = (
            "请将以下对话历史压缩为一段简洁的摘要（200字以内），保留关键信息、用户偏好和重要结论。直接输出摘要。\n\n"
            f"旧摘要：{old_summary}\n\n近期对话：\n{recent_text}\n\n新摘要："
        )
        response = self.llm.invoke(prompt)
        _, new_summary = split_thinking(response.content)
        self.data["summary"] = new_summary
        self.data["recent_messages"] = []
        self.data["total_turns"] = 0
        self.save()
        print("\n[记忆已压缩并保存]\n")

    def get_context(self) -> str:
        parts = []
        if self.data["summary"]:
            parts.append(f"[长期记忆]\n{self.data['summary']}")
        if self.data["recent_messages"]:
            recent = "\n".join(f"{m['role']}: {m['content']}" for m in self.data["recent_messages"][-6:])
            parts.append(f"[近期对话]\n{recent}")
        return "\n\n".join(parts) if parts else ""