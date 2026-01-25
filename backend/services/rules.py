import os
import yaml
from functools import lru_cache

@lru_cache(maxsize=1)
def load_rules():
    path = os.getenv("RULES_PATH", "/app/rules/pai_rules.yaml")
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}

def configured_datasets():
    rules = load_rules()
    return rules.get("datasets", [])

def pericol_rank_map():
    rules = load_rules()
    return rules.get("rank", {})

def template_map():
    rules = load_rules()
    return rules.get("templates", {})

def infer_tipo_from_pericol(pericol: str) -> str:
    p = (pericol or "").upper().strip()
    if p.startswith("PF"):
        return "idrogeologico"
    if p.startswith("PI"):
        return "idraulico"
    if p.startswith("B") or p in {"A", "B", "C"} or " - " in p:
        return "idraulico"
    return "auto"
