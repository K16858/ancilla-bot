---
name: tasks-and-reminders
description: タスク・リマインダ・家計の操作手順。予定、リマインド、支出記録のときに使う。
---

scheduled_at must be YYYY-MM-DD HH:MM:SS.

**Reminder** — add with add_reminder, list/update/delete with manage_state (table=reminders):
```json
{"content": "Meeting reminder", "scheduled_at": "2026-03-25 19:00:00"}
```
```json
{"table": "reminders", "operation": "select", "payload": {"completed": false, "limit": 20}}
```
```json
{"table": "reminders", "operation": "update", "payload": {"id": 3, "completed": true}}
```
```json
{"table": "reminders", "operation": "delete", "payload": {"id": 3}}
```

**User task**:
```json
{"content": "Submit report", "scheduled_at": "2026-03-26 09:00:00"}
```

**Finance** (negative = expense):
```json
{"amount": -1200, "category": "food", "memo": "Lunch", "date": "2026-03-25"}
```

For agent_tasks (self-managed work log with source=self/heartbeat), use manage_state.
