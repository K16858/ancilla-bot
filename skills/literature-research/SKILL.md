---
name: literature-research
version: 1
description: 論文とウェブ資料を調べて出典付きでまとめる。
requires:
  capabilities:
    - web_search
    - fetch_page
recommended_modes:
  - research
risk: read_only
---

Research a question with sources. Do not change permissions. Prefer research mode (`set_mode` name=research); do not switch unless the user asks.

1. Call `set_mode` with name=research only when the user wants research behavior.
2. `web_search` for current discussion and terms.
3. If `search_arxiv` is listed, use it for papers. Otherwise stay on web_search + fetch_page.
4. `fetch_page` on a few primary URLs. Do not dump raw HTML into the answer.
5. Answer with claims tied to URLs or arXiv ids. Say when a source was not opened.
