# validation/audit.py
"""Журналирование действий экспертов для compliance и отладки"""
import json
from pathlib import Path
from datetime import datetime

def log_expert_action(user_id: str, action: str, details: dict, log_dir: str = "reports"):
    Path(log_dir).mkdir(parents=True, exist_ok=True)
    log_path = Path(log_dir) / "audit_log.jsonl"
    
    entry = {
        "timestamp": datetime.now().isoformat(),
        "user_id": user_id or "anonymous",
        "action": action,
        "details": details
    }
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")