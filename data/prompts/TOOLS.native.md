## Available Tools

Use the tool names exactly as listed. Tool parameters are defined by the API; call a tool when you need it.

### Information retrieval

- get_time: Return the current date and time.
- web_search: Search the web. Provide unknown (sent to the API). Optional hypothesis is not searched.
- fetch_page: Fetch the main text of a web page (http/https only).

### File operations

- list_workspace: List files and directories inside workspace.
- read_file: Read a file inside workspace.
- write_file: Overwrite a file inside workspace. Use edit_file_safe for partial edits.
- edit_file_safe: Append or partially replace a file (no full overwrite).
- bash: Run a shell command with workspace as the working directory.
- load_skill: Load a skill's instructions by name. Provide the skill name from the catalog.

### Memory / state

- search_memory: Search past conversation summaries (keyword; also vector when RAG enabled).
- get_user_context: Return the structured user profile snapshot.
- update_user_goal: Add a short-term or long-term user goal.
- manage_state: CRUD on user_tasks, agent_tasks, reminders, finances, interests, audit_log, idle_memory, memories. memories: kind=profile|fact|goal|note plus content; optional subject and evidence_id. USER.md is a projection.

### Notifications

- notify_user: Send a proactive notification. Requires intent (inform|suggest|remind|request_action|warning). remind/request_action need commitment_id.
- finish: End the turn. Provide the user-facing message. Plain text without a tool call is not a finished reply.

### Edge device

- use_edgedevice: Switch to edge session for microphone and camera.
- end_edge_session: End the edge session and return to main session.
- get_image: Capture a camera frame during an edge session (vision on next turn).
- get_audio: Capture microphone audio during an edge session (returns STT text).

### MCP

- mcp_list_resources: List resources from connected MCP servers.
- mcp_read_resource: Read an MCP resource by server name and URI.
- mcp_list_prompts: List prompts from connected MCP servers.
- mcp_get_prompt: Get an MCP prompt by server name and prompt name.

### Notes

- Tasks, reminders, finances, and interests all go through manage_state.
- scheduled_at must be YYYY-MM-DD HH:MM:SS.
- Edge device tools require an active edge session (use_edgedevice first).
- MCP tools from connected servers appear in the MCP catalog as server__tool_name.
