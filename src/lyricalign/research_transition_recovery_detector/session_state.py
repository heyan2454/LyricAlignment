from __future__ import annotations
from pathlib import Path
import json, os, tempfile

PHASE_STATUSES = ("pending", "in_progress", "complete", "negative_result", "bounded_insufficient", "blocked_global", "not_executed_dependency")

class SessionState:
    def __init__(self, root: Path | str, *, hard_budget_seconds: int = 43200):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "logs").mkdir(exist_ok=True)
        self.state_path = self.root / "SESSION_STATE.json"
        self.events_path = self.root / "logs" / "events.jsonl"
        self.data = self._load_or_init(hard_budget_seconds)
    def _load_or_init(self, hard_budget_seconds):
        if self.state_path.exists():
            data = json.loads(self.state_path.read_text("utf-8"))
            if "phases" not in data: data["phases"] = {}
            return data
        return {"session_root": str(self.root), "current_phase": "phase_0", "phases": {}, "gpu_seconds_used": 0.0, "hard_budget_seconds": hard_budget_seconds, "resume_command": ""}
    def _flush(self):
        tmp = self.state_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(self.data, indent=2, ensure_ascii=False), "utf-8")
        os.replace(tmp, self.state_path)
    def _log(self, event: str, detail: dict):
        with open(self.events_path, "a", encoding="utf-8") as f:
            f.write(json.dumps({"ts": self._now(), "event": event, **detail}, ensure_ascii=False) + "\n")
    @staticmethod
    def _now() -> str:
        import datetime; return datetime.datetime.now(datetime.timezone.utc).isoformat()
    def begin_phase(self, name: str):
        if self.data["phases"].get(name, "pending") == "complete":
            raise ValueError(f"phase {name} already complete")
        self.data["current_phase"] = name
        self.data["phases"][name] = "in_progress"
        self._flush(); self._log("phase_begin", {"phase": name})
    def complete_phase(self, name: str, status: str = "complete"):
        if status not in PHASE_STATUSES: raise ValueError(f"invalid status {status}")
        self.data["phases"][name] = status
        self._flush(); self._log("phase_end", {"phase": name, "status": status})
    def update_gpu_seconds(self, delta: float):
        self.data["gpu_seconds_used"] = float(self.data.get("gpu_seconds_used", 0.0)) + float(delta)
        self._flush(); self._log("gpu_update", {"delta": float(delta)})
    def phase_status(self, name: str) -> str:
        return self.data["phases"].get(name, "pending")
