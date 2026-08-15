---
name: bash
description: シェルコマンド実行の手順と制約。スクリプト実行、ファイル一覧、タイムアウト指定のときに使う。
---

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
