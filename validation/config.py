import yaml
from pathlib import Path

def load_rules(config_path: str = "rules/default_rules.yaml") -> dict:
    """Загружает правила валидации из YAML"""
    path = Path(config_path)
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}