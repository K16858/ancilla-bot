"""CLI: ancilla persona list|show|use"""

from __future__ import annotations

import argparse
import yaml

from ancilla_bot.runtime.persona import (
    get_active_name,
    list_persona_names,
    load_persona,
    set_persona,
)


def cmd_persona(args: argparse.Namespace) -> int:
    action = getattr(args, "persona_command", None) or "list"
    if action == "list":
        active = get_active_name()
        for name in list_persona_names():
            mark = " *" if name == active else ""
            print(f"{name}{mark}")
        return 0
    if action == "show":
        key = (getattr(args, "name", None) or get_active_name()).strip()
        if key not in list_persona_names():
            print(f"Error: unknown persona: {key}")
            return 1
        spec = load_persona(key)
        data = {
            "name": spec.name,
            "role": spec.role,
            "goals": list(spec.goals),
            "preferred_skills": list(spec.preferred_skills),
            "memory_read": list(spec.memory_read),
            "memory_write": list(spec.memory_write),
            "tools_deny": list(spec.tools_deny),
            "tools_require_approval": list(spec.tools_require_approval),
            "resources_notes": spec.resources_notes,
            "output": spec.output,
        }
        print(yaml.safe_dump(data, allow_unicode=True, sort_keys=False).rstrip())
        return 0
    if action == "use":
        key = (getattr(args, "name", None) or "").strip()
        msg = set_persona(key)
        print(msg)
        return 0 if not msg.startswith("Error:") else 1
    print(f"Error: unknown persona command: {action}")
    return 1
