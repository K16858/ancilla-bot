---
name: task-planning
version: 1
description: 作業を分解して tasks / reminders に落とす。
requires:
  capabilities:
    - manage_state
    - load_skill
recommended_modes:
  - general
risk: read_only
---

Turn a goal into scheduled work. Load `tasks-and-reminders` for payload shapes.

1. Confirm due times in YYYY-MM-DD HH:MM:SS.
2. User-facing items go to user_tasks or reminders (kind=user_reminder).
3. Agent follow-up uses agent_tasks or reminders kind=agent_wakeup. Do not create user-owned rows while autonomous.
4. Do not invent permissions. manage_state still goes through the policy gate.
