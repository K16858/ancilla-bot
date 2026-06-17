"""
Research Assistant Plugin
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Any
from urllib.parse import quote

import httpx

from ancilla_bot.plugins.base import AncillaPlugin


def search_arxiv(query: str, max_results: int = 5, **kwargs: Any) -> str:
    _ = kwargs
    url = (
        "http://export.arxiv.org/api/query?"
        f"search_query=all:{quote(query)}&start=0&max_results={max_results}"
    )
    try:
        resp = httpx.get(url, timeout=30.0)
        resp.raise_for_status()
    except Exception as e:
        return f"Error: arXiv search failed: {e}"
    root = ET.fromstring(resp.text)
    ns = {"a": "http://www.w3.org/2005/Atom"}
    entries = root.findall("a:entry", ns)
    if not entries:
        return "No papers found."
    lines: list[str] = []
    for entry in entries:
        title = (entry.findtext("a:title", default="", namespaces=ns) or "").strip()
        summary = (entry.findtext("a:summary", default="", namespaces=ns) or "").strip()
        link = ""
        for link_el in entry.findall("a:link", ns):
            if link_el.attrib.get("rel") == "alternate":
                link = link_el.attrib.get("href", "")
                break
        arxiv_id = (entry.findtext("a:id", default="", namespaces=ns) or "").split("/abs/")[-1]
        lines.append(f"- {title}\n  id: {arxiv_id}\n  url: {link}\n  {summary[:300]}...")
    return "\n\n".join(lines)


class ResearchPlugin(AncillaPlugin):
    name = "research"
    tools = {"search_arxiv": search_arxiv}
    descriptions = {
        "search_arxiv": (
            "Search arXiv papers. action_input: {\"query\": \"...\", \"max_results\": 5}."
        ),
    }
