---
name: tasks-and-reminders
description: タスク・リマインダ・家計の操作手順。予定、リマインド、支出記録のときに使う。
---

Use manage_state. scheduled_at must be YYYY-MM-DD HH:MM:SS.

User reminders use payload.kind=user_reminder (default on user turns). Agent self-wakeups use kind=agent_wakeup and owner=agent; they do not notify the user.

**Reminder** (table=reminders):
```json
{"table": "reminders", "operation": "insert", "payload": {"content": "Meeting reminder", "scheduled_at": "2026-03-25 19:00:00"}}
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

**User task** (table=user_tasks):
```json
{"table": "user_tasks", "operation": "insert", "payload": {"content": "Submit report", "scheduled_at": "2026-03-26 09:00:00"}}
```

**Finance** (table=finances, negative = expense):
```json
{"table": "finances", "operation": "insert", "payload": {"amount": -1200, "category": "food", "memo": "Lunch", "date": "2026-03-25"}}
```

For agent_tasks (self-managed work log with source=self/heartbeat), use table=agent_tasks.
