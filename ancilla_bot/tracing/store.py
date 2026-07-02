from __future__ import annotations

import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

TRACE_DIR = Path("data/traces")
EVENTS_FILE = "events.jsonl"


def new_run_id() -> str:
    return uuid.uuid4().hex


def write_event(
    run_id: str,
    event_type: str,
    *,
    turn_index: int | None = None,
    payload: dict[str, Any] | None = None,
) -> None:
    TRACE_DIR.mkdir(parents=True, exist_ok=True)
    record = {
        "ts": datetime.now().isoformat(timespec="seconds"),
        "run_id": run_id,
        "event_type": event_type,
        "turn_index": turn_index,
        "payload": payload or {},
    }
    path = TRACE_DIR / EVENTS_FILE
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
