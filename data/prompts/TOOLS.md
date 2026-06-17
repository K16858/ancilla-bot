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
- add_task: Add a user task. action_input: {"content": "...", "scheduled_at": "YYYY-MM-DD HH:MM:SS"}. scheduled_at optional (defaults to now).
- list_tasks: List user tasks. action_input: {"completed": false, "limit": 10}. Both optional.
- complete_task: Mark a user task complete. action_input: {"id": 3}.
- add_reminder: Schedule a reminder (heartbeat notifies at scheduled_at). action_input: {"content": "...", "scheduled_at": "YYYY-MM-DD HH:MM:SS"}.
- add_finance: Record income/expense. action_input: {"amount": -1200, "category": "food", "memo": "...", "date": "YYYY-MM-DD"}. memo and date optional.
- add_interest: Track a topic. action_input: {"name": "...", "description": "...", "url": "..."}. description and url optional.

### Notifications

- notify_user: Send a proactive notification to the user (via Discord). action_input: {"message": "...", "title": "...", "source": "report|system|email", "level": "info|notice|warning|critical"}. title, source, level are optional.

### Edge device

- use_edgedevice: Switch to edge session to enable microphone and camera. action_input: {"reason": "..."} (optional). Use when the user wants to speak by voice or use the camera.
- end_edge_session: End the edge session and return to main session. action_input: {}. Use when the agent has finished its edge-session goal.
- get_image: Agent-initiated camera capture during an edge session. action_input: {"reason": "...", "timeout_sec": 60}. On success, the image is passed to the vision model in the next LLM turn. Requires an active edge session (use_edgedevice first).
- get_audio: Agent-initiated microphone capture during an edge session; returns STT text. action_input: {"reason": "...", "timeout_sec": 60}. Requires an active edge session (use_edgedevice first).

---

## Skill: tasks and reminders

Use the dedicated tools above for common operations. scheduled_at must be YYYY-MM-DD HH:MM:SS.

**Reminder** (always use add_reminder for timed user notifications):
```json
{"content": "Meeting reminder", "scheduled_at": "2026-03-25 19:00:00"}
```

**User task**:
```json
{"content": "Submit report", "scheduled_at": "2026-03-26 09:00:00"}
```

**Finance** (negative = expense):
```json
{"amount": -1200, "category": "food", "memo": "Lunch", "date": "2026-03-25"}
```

For agent_tasks (self-managed work log with source=self/heartbeat), use manage_state directly — see internal docs if needed.

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
