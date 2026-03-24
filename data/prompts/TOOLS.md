## Available Tools

Use the tool name exactly as listed. action must be a string matching the tool name; action_input must be a JSON object.

### Information retrieval

- get_time: Return current date/time. action_input: {}.
- web_search: Search the web via SearXNG. action_input: {"query": "search terms", "max_results": 5}. max_results optional (default 5).
- fetch_page: Fetch the main text of a web page (HTML stripped). action_input: {"url": "https://example.com", "max_chars": 8000}. max_chars optional. Only http/https; private IPs and localhost are rejected.

### File operations

- list_workspace: List files and directories inside workspace. action_input: {"path": ""}, optional {"max_entries": 100, "max_depth": 4}. Returns relative paths usable as-is in read_file.
- read_file: Read a file inside workspace. action_input: {"path": "NOTE.md"}, optional {"max_lines": 2000}. Output is truncated at max_lines.
- write_file: Overwrite a file inside workspace. action_input: {"path": "NOTE.md", "content": "..."}. Replaces the entire file. Use edit_file_safe for partial edits.
- edit_file_safe: Append or partially replace a file (no full overwrite). operation="append": {"path": "...", "content": "..."}. operation="replace" (string): {"path": "...", "old": "...", "new": "..."}. operation="replace" (lines): {"path": "...", "start_line": N, "end_line": M, "new": "..."} (1-based).
- bash: Run a shell command (cwd=workspace root). Returns stdout+stderr. action_input: {"command": "ls -la"}, optional {"timeout_sec": 60, "stdin_text": "..."}. timeout_sec default 60, max 300. Python also works: {"command": "python script.py"}.

### Memory / state

- search_memory: Vector-search past conversation summaries (long-term memory). action_input: {"query": "search terms", "max_results": 3}. Use when recalling previously discussed topics. max_results optional (default 3).
- manage_state: SQLite CRUD. See skill guide below.

### Notifications

- notify_user: Send a proactive notification to the user (via Discord). action_input: {"message": "...", "title": "...", "source": "report|system|email", "level": "info|notice|warning|critical"}. title, source, level are optional.

### Edge device

- use_edgedevice: Switch to edge session to enable microphone and camera. action_input: {"reason": "..."} (optional). Use when the user wants to speak by voice or use the camera.
- end_edge_session: End the edge session and return to main session. action_input: {}. Use when the agent has finished its edge-session goal.
- get_image: Agent-initiated camera capture during an edge session. action_input: {"reason": "...", "timeout_sec": 60}. On success, the image is passed to the vision model in the next LLM turn. Requires an active edge session (use_edgedevice first).
- get_audio: Agent-initiated microphone capture during an edge session; returns STT text. action_input: {"reason": "...", "timeout_sec": 60}. Requires an active edge session (use_edgedevice first).

---

## Skill: manage_state

manage_state has 6 tables. Always choose the correct table; misuse can cause heartbeat misfires.

| table | purpose |
|---|---|
| user_tasks | Things the user said they will do — their TODO list. Always set scheduled_at and content. |
| agent_tasks | Work the agent plans to do later. Has two modes controlled by `source` field (see below). |
| reminders | Notify the user at a specific time. Heartbeat fires ReAct at scheduled_at and calls notify_user. **Always insert timed reminders here; never tell the user you cannot do timed reminders.** |
| finances | Income / expense notes. Set amount and category; memo and date are optional. |
| interests | Things the user is curious about or wants to track. Always set name; description, status, url are optional. |
| audit_log | Automatic tool-call audit log — do not insert manually. |

### agent_tasks — two modes via `source` field

| source | purpose | heartbeat triggers? |
|---|---|---|
| `heartbeat` (default) | Schedule future work for the system to run at `scheduled_at` | YES |
| `self` | Your own cross-session TODO and work log — never triggered by heartbeat | NO |

**Rule: always use `source="self"` for your own task tracking. Only use `source="heartbeat"` when you want the system to run something at a specific time.**

#### Self-managed TODO pattern (plan-first)

Before doing any multi-step work during idle reflection, follow this pattern:

**Step 1 — Check what you already did** (always do this first to avoid repeating work):
```json
{"table": "agent_tasks", "operation": "select", "payload": {"source": "self", "limit": 30}}
```
If a similar task exists with `completed=1`, skip it.

**Step 2 — Plan: create a TODO before starting**:
```json
{"table": "agent_tasks", "operation": "insert", "payload": {"scheduled_at": "2026-03-25 03:00:00", "content": "[TODO] Research Rust async patterns", "source": "self"}}
```

**Step 3 — Do the work**, then mark it done with a note about what you produced:
```json
{"table": "agent_tasks", "operation": "update", "payload": {"id": 42, "completed": 1, "content": "[DONE] Research Rust async patterns → wrote workspace/notes/rust_async.md"}}
```

This creates a persistent work log across idle cycles, preventing repeated research.

### insert examples

**reminders** (scheduled_at required, must be YYYY-MM-DD HH:MM:SS):
```json
{"table": "reminders", "operation": "insert", "payload": {"scheduled_at": "2026-03-25 19:00:00", "content": "Meeting reminder"}}
```

**user_tasks**:
```json
{"table": "user_tasks", "operation": "insert", "payload": {"scheduled_at": "2026-03-26 09:00:00", "content": "Submit report"}}
```

**agent_tasks (heartbeat-triggered)**:
```json
{"table": "agent_tasks", "operation": "insert", "payload": {"scheduled_at": "2026-03-26 08:00:00", "content": "Generate daily summary", "source": "heartbeat"}}
```

**finances** (negative amount = expense, positive = income):
```json
{"table": "finances", "operation": "insert", "payload": {"amount": -1200, "category": "food", "memo": "Lunch", "date": "2026-03-25"}}
```

**interests**:
```json
{"table": "interests", "operation": "insert", "payload": {"name": "Rust language", "description": "Systems programming", "url": "https://www.rust-lang.org"}}
```

### select

```json
{"table": "reminders", "operation": "select", "payload": {"limit": 10, "completed": false}}
```

completed=false returns only incomplete items. limit defaults to 100 when omitted.

Filter agent_tasks by source:
```json
{"table": "agent_tasks", "operation": "select", "payload": {"source": "self", "limit": 20}}
```

### update

```json
{"table": "user_tasks", "operation": "update", "payload": {"id": 3, "completed": 1}}
```

### delete

```json
{"table": "interests", "operation": "delete", "payload": {"id": 5}}
```

---

## Skill: bash

bash runs any shell command with workspace root as the working directory.
On Windows: cmd.exe. On Linux/macOS: /bin/sh.

**Run a Python script**:
```json
{"command": "python scripts/my_script.py --flag value"}
```

**List files**:
```json
{"command": "dir workspace"}
```

**With explicit timeout** (default 60 s, max 300 s):
```json
{"command": "python long_task.py", "timeout_sec": 120}
```

Notes:
- Output longer than 20,000 chars is truncated.
- Pipes and command chaining (|, &&) are supported.
- Avoid destructive system-level commands outside the workspace.

---

## Skill: edge device workflow

Edge device (PC or smartphone with camera/mic) must be connected to use these tools.

**Typical flow**:
1. Call `use_edgedevice` to switch to the edge session.
2. Call `get_image` to capture a camera frame (passed to vision model next turn).
3. Call `get_audio` to record mic audio and receive STT text.
4. Call `end_edge_session` when done to return to main session.

If the device is not connected, use_edgedevice will fail — inform the user accordingly.
