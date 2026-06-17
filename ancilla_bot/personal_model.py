"""
構造化ユーザーモデル（personal_model.yaml）
"""

from __future__ import annotations

import json
import os
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from ancilla_bot.llm import send_chat

DEFAULT_PATH = Path(os.getenv("ANCILLA_PERSONAL_MODEL_PATH", "data/personal_model.yaml"))


def _default_model() -> dict[str, Any]:
    return {
        "identity": {
            "name": "",
            "role": "",
            "timezone": "Asia/Tokyo",
            "language": "ja",
        },
        "goals": {"short_term": [], "long_term": []},
        "domains": [],
        "patterns": {
            "active_hours": "10:00-23:00",
            "communication_style": "casual_japanese",
            "preferred_response_length": "concise",
            "interruption_tolerance": "low",
        },
        "knowledge_graph": {"nodes": [], "edges": []},
    }


def load() -> dict[str, Any]:
    path = DEFAULT_PATH
    if not path.exists():
        return _default_model()
    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    base = _default_model()
    for key, value in data.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            base[key].update(value)
        else:
            base[key] = value
    return base


def save(model: dict[str, Any]) -> None:
    path = DEFAULT_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        yaml.safe_dump(model, f, allow_unicode=True, sort_keys=False)


def get_context_slice(situation: str = "") -> dict[str, Any]:
    """プロンプト注入用にモデルの主要部分を返す。"""
    model = load()
    _ = situation
    return {
        "identity": model.get("identity", {}),
        "goals": model.get("goals", {}),
        "domains": model.get("domains", []),
        "patterns": model.get("patterns", {}),
    }


def update_user_goal(goal: str, term: str = "short", **kwargs: Any) -> str:
    _ = kwargs
    model = load()
    key = "short_term" if term == "short" else "long_term"
    goals = model.setdefault("goals", {}).setdefault(key, [])
    goals.append(
        {
            "goal": goal,
            "created_at": datetime.now().strftime("%Y-%m-%d"),
            "status": "active",
        }
    )
    save(model)
    return "OK"


def get_user_context(**kwargs: Any) -> str:
    _ = kwargs
    return yaml.safe_dump(get_context_slice(), allow_unicode=True, sort_keys=False)


def _merge_extracted(current: dict[str, Any], extracted: dict[str, Any]) -> dict[str, Any]:
    merged = deepcopy(current)
    identity = extracted.get("identity") or {}
    for k, v in identity.items():
        if v and not merged.get("identity", {}).get(k):
            merged.setdefault("identity", {})[k] = v
    for domain in extracted.get("domains") or []:
        if not isinstance(domain, dict):
            continue
        name = (domain.get("name") or "").strip()
        if not name:
            continue
        existing = {d.get("name") for d in merged.get("domains", []) if isinstance(d, dict)}
        if name not in existing:
            merged.setdefault("domains", []).append(domain)
    for term in ("short_term", "long_term"):
        for goal in (extracted.get("goals") or {}).get(term) or []:
            if not isinstance(goal, dict) or not goal.get("goal"):
                continue
            goals = merged.setdefault("goals", {}).setdefault(term, [])
            if goal["goal"] not in {g.get("goal") for g in goals if isinstance(g, dict)}:
                goals.append(goal)
    return merged


def extract_and_update(messages: list[dict[str, str]]) -> None:
    """会話から個人情報を抽出して personal_model.yaml をマージ更新する。"""
    if not messages:
        return
    text_lines = []
    for m in messages[-20:]:
        role = m.get("role", "")
        content = (m.get("content") or "").strip()
        if content:
            text_lines.append(f"{role}: {content[:500]}")
    if not text_lines:
        return
    prompt = (
        "Extract user profile updates from this conversation as JSON only. "
        'Keys: identity (name, role), domains [{name, level, notes}], '
        'goals {short_term: [{goal, status}], long_term: [...]}. '
        "Omit empty fields.\n\n"
        + "\n".join(text_lines)
    )
    verify_model = os.getenv("ANCILLA_VERIFY_MODEL") or os.getenv("OLLAMA_MODEL")
    raw = send_chat([{"role": "user", "content": prompt}], format=None, model=verify_model)
    try:
        extracted = json.loads(raw)
    except json.JSONDecodeError:
        return
    if not isinstance(extracted, dict):
        return
    save(_merge_extracted(load(), extracted))
