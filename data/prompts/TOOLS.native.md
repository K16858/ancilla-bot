## Available Tools

Use the tool names exactly as listed. Tool parameters are defined by the API; call a tool when you need it.

### Information retrieval

- get_time: Return the current date and time.
- web_search: Search the web via SearXNG. Provide a query string.
- fetch_page: Fetch the main text of a web page (http/https only).

### File operations

- list_workspace: List files and directories inside workspace.
- read_file: Read a file inside workspace.
- write_file: Overwrite a file inside workspace. Use edit_file_safe for partial edits.
- edit_file_safe: Append or partially replace a file (no full overwrite).
- bash: Run a shell command with workspace as the working directory.

### Memory / state

- search_memory: Search past conversation summaries (long-term memory).
- add_task: Add a user task.
- list_tasks: List user tasks.
- complete_task: Mark a user task complete by id.
- add_reminder: Schedule a reminder (notified at scheduled_at via heartbeat).
- add_finance: Record income or expense.
- add_interest: Track a topic the user cares about.
- get_user_context: Return the structured user profile snapshot.
- update_user_goal: Add a short-term or long-term user goal.

### Notifications

- notify_user: Send a proactive notification to the user (via Discord).

### Edge device

- use_edgedevice: Switch to edge session for microphone and camera.
- end_edge_session: End the edge session and return to main session.
- get_image: Capture a camera frame during an edge session (vision on next turn).
- get_audio: Capture microphone audio during an edge session (returns STT text).

### Notes

- For timed user notifications, always use add_reminder.
- scheduled_at must be YYYY-MM-DD HH:MM:SS.
- Edge device tools require an active edge session (use_edgedevice first).
