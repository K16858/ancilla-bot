## Available Tools

Use the tool name exactly as listed. action must be a string matching the tool name; action_input must be a JSON object.

### Information retrieval

- get_time: Return current date/time. action_input: {}.
- web_search: Search the web. action_input: {"query": "search terms", "max_results": 5}. max_results optional (default 5).
- fetch_page: Fetch the main text of a web page (HTML stripped). action_input: {"url": "https://example.com", "max_chars": 8000}. max_chars optional. Only http/https; private IPs and localhost are rejected.

### File operations

- list_workspace: List files and directories inside workspace. action_input: {"path": ""}, optional {"max_entries": 100, "max_depth": 4}. Returns relative paths usable as-is in read_file.
- read_file: Read a file inside workspace. action_input: {"path": "NOTE.md"}, optional {"max_lines": 2000}. Output is truncated at max_lines.
- write_file: Overwrite a file inside workspace. action_input: {"path": "NOTE.md", "content": "..."}. Replaces the entire file. Use edit_file_safe for partial edits.
- edit_file_safe: Append or partially replace a file (no full overwrite). operation="append": {"path": "...", "content": "..."}. operation="replace" (string): {"path": "...", "old": "...", "new": "..."}. operation="replace" (lines): {"path": "...", "start_line": N, "end_line": M, "new": "..."} (1-based).
- bash: Run a shell command (cwd=workspace root). Returns stdout+stderr. action_input: {"command": "ls -la"}, optional {"timeout_sec": 60, "stdin_text": "..."}. timeout_sec default 60, max 300. Python also works: {"command": "python script.py"}.
- load_skill: Load a skill's instructions by name. action_input: {"name": "skill-name"}. Call when a listed skill matches the current task.

### Memory / state

- search_memory: Search past conversation summaries (long-term memory) via keyword search, plus vector search when RAG is enabled. action_input: {"query": "search terms", "max_results": 3}. Use when recalling previously discussed topics. max_results optional (default 3).
- manage_state: CRUD on user_tasks, agent_tasks, reminders, finances, interests, audit_log. action_input: {"table": "reminders", "operation": "select|insert|update|delete", "payload": {}}. payload may include owner (user|agent), source, and for reminders kind (user_reminder|agent_wakeup). Idle/heartbeat cannot create user-owned rows; use kind=agent_wakeup for the agent's own later resume. select: optional completed/limit. update/delete: payload.id required. insert: reminders/tasks need scheduled_at+content; finances need amount+category; interests need name.

### Notifications

- notify_user: Send a proactive notification. action_input: {"message": "...", "intent": "inform|suggest|remind|request_action|warning"}. remind/request_action require commitment_id of a user-owned reminder or user_task. Optional title, source, level, subject (dedupe key).

### Edge device

- use_edgedevice: Switch to edge session to enable microphone and camera. action_input: {"reason": "..."} (optional). Use when the user wants to speak by voice or use the camera.
- end_edge_session: End the edge session and return to main session. action_input: {}. Use when the agent has finished its edge-session goal.
- get_image: Agent-initiated camera capture during an edge session. action_input: {"reason": "...", "timeout_sec": 60}. On success, the image is passed to the vision model in the next LLM turn. Requires an active edge session (use_edgedevice first).
- get_audio: Agent-initiated microphone capture during an edge session; returns STT text. action_input: {"reason": "...", "timeout_sec": 60}. Requires an active edge session (use_edgedevice first).

### MCP

- mcp_list_resources: List resources from connected MCP servers. action_input: {}.
- mcp_read_resource: Read an MCP resource by server and URI. action_input: {"server": "name", "uri": "file:///..."}.
- mcp_list_prompts: List prompts from connected MCP servers. action_input: {}.
- mcp_get_prompt: Get an MCP prompt by server and name. action_input: {"server": "name", "name": "prompt", "arguments": {}}.
- MCP tools from connected servers appear in the MCP catalog as server__tool_name.
