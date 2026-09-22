---
name: code-review
version: 1
description: workspace のコードを読んで問題と修正案を出す。
requires:
  capabilities:
    - list_workspace
    - read_file
recommended_personas:
  - developer
risk: read_only
---

Review code in workspace. Do not change permissions.

1. Prefer developer persona if the user wants review behavior (`set_persona` name=developer).
2. `list_workspace` then `read_file` on the files in scope. Do not read secrets.
3. Report bugs, risks, and missing tests first. Suggest a minimal patch. Do not write files unless asked.
