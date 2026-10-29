from __future__ import annotations

"""多记忆系统管理。

启动后 active_id 恒为 None（无记忆状态）。
/sms 开启/关闭；/sms show 交互选择。
"""
import json
import uuid
from datetime import datetime

from ..common.paths import resolve


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


class MemorySystemManager:
    def __init__(self, config, llm=None):
        self.llm = llm
        self.base_dir = resolve(config.get("memory_system_dir") or "config/memory")
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.index_path = self.base_dir / "index.json"
        self.index = self._load_index()
        self.active_id: str | None = None
        self._active = None

    # ---- 索引 ----
    def _load_index(self) -> dict:
        if self.index_path.exists():
            try:
                data = json.loads(self.index_path.read_text(encoding="utf-8"))
                if isinstance(data, dict) and isinstance(data.get("systems"), list):
                    data.setdefault("version", 1)
                    data.setdefault("last_active_id", None)
                    return data
            except Exception:
                pass
        return {"version": 1, "last_active_id": None, "systems": []}

    def _save_index(self) -> None:
        self.index_path.write_text(
            json.dumps(self.index, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    # ---- 查询 ----
    def list_systems(self) -> list:
        return sorted(
            self.index["systems"],
            key=lambda s: s.get("last_active_at", ""),
            reverse=True,
        )

    def _meta(self, sid: str):
        return next((s for s in self.index["systems"] if s["id"] == sid), None)

    def get_active(self):
        return self._active

    # ---- 生命周期 ----
    def create(self, name: str) -> str:
        sid = uuid.uuid4().hex[:8]
        now = _now()
        self.index["systems"].append({
            "id": sid,
            "name": name,
            "description": "",
            "created_at": now,
            "last_active_at": now,
            "total_turns": 0,
        })
        self._save_index()
        self.activate(sid)
        return sid

    def activate(self, sid: str) -> bool:
        meta = self._meta(sid)
        if meta is None:
            return False
        from .memory_manager import MemoryManager
        self._active = MemoryManager(
            path=str(self.base_dir / f"ms_{sid}.json"),
            llm=self.llm,
        )
        self.active_id = sid
        meta["last_active_at"] = _now()
        self.index["last_active_id"] = sid
        self._save_index()
        return True

    def deactivate(self) -> None:
        self.active_id = None
        self._active = None

    def delete(self, sid: str) -> bool:
        before = len(self.index["systems"])
        self.index["systems"] = [s for s in self.index["systems"] if s["id"] != sid]
        if len(self.index["systems"]) == before:
            return False
        try:
            (self.base_dir / f"ms_{sid}.json").unlink(missing_ok=True)
        except Exception:
            pass
        if self.active_id == sid:
            self.deactivate()
        if self.index.get("last_active_id") == sid:
            self.index["last_active_id"] = None
        self._save_index()
        return True

    # ---- 开关 ----
    def toggle(self) -> str:
        if self.active_id:
            meta = self._meta(self.active_id)
            name = meta["name"] if meta else "?"
            self.deactivate()
            return f"已关闭（{name}）"
        last = self.index.get("last_active_id")
        if last and self._meta(last):
            self.activate(last)
            meta = self._meta(last)
            return f"已恢复：{meta['name']} ({last})"
        return "当前无激活系统，请用 /sms show 选择或 /sms new <name> 新建"

    # ---- 元数据同步 ----
    def sync_meta_after_turn(self, sid: str) -> None:
        if not sid:
            return
        meta = self._meta(sid)
        if meta is None:
            return
        meta["last_active_at"] = _now()
        self.index["last_active_id"] = sid
        mem = self._active
        if mem is not None:
            meta["total_turns"] = mem.data.get("total_turns", 0)
            if not meta.get("description") and mem.data.get("recent_messages"):
                first_user = next(
                    (m["content"] for m in mem.data["recent_messages"]
                     if m["role"] == "user"),
                    "",
                )
                desc = first_user.replace("\n", " ").strip()
                if desc:
                    meta["description"] = desc[:30] + ("…" if len(desc) > 30 else "")
        self._save_index()
