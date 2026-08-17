"""MCP ツール/リソース/プロンプト結果の文字列化。"""

from __future__ import annotations

import json
from typing import Any

from mcp import types


def stringify_call_tool_result(result: types.CallToolResult) -> str:
    parts: list[str] = []
    for item in result.content or []:
        parts.append(_stringify_content(item))
    text = "\n".join(p for p in parts if p)
    structured = result.structured_content
    if structured is not None:
        try:
            structured_text = json.dumps(structured, ensure_ascii=False, indent=2)
        except (TypeError, ValueError):
            structured_text = str(structured)
        text = f"{text}\n\nstructuredContent:\n{structured_text}".strip() if text else structured_text
    if result.is_error:
        return f"Error: {text}" if text else "Error: tool execution failed"
    return text or "(empty tool result)"


def _stringify_content(item: Any) -> str:
    if isinstance(item, types.TextContent):
        return item.text or ""
    if isinstance(item, types.ImageContent):
        return f"[image mimeType={item.mime_type}]"
    if isinstance(item, types.AudioContent):
        return f"[audio mimeType={item.mime_type}]"
    if isinstance(item, types.ResourceLink):
        return f"[resource_link uri={item.uri} name={item.name}]"
    if isinstance(item, types.EmbeddedResource):
        resource = item.resource
        if isinstance(resource, types.TextResourceContents):
            body = resource.text or ""
            return f"[resource uri={resource.uri}]\n{body}"
        if isinstance(resource, types.BlobResourceContents):
            return f"[resource uri={resource.uri} blob mimeType={resource.mime_type or 'unknown'}]"
        return "[resource]"
    return f"[{getattr(item, 'type', type(item).__name__)}]"


def stringify_resource_contents(result: types.ReadResourceResult) -> str:
    parts: list[str] = []
    for item in result.contents or []:
        if isinstance(item, types.TextResourceContents):
            parts.append(item.text or "")
        elif isinstance(item, types.BlobResourceContents):
            parts.append(f"[blob uri={item.uri} mimeType={item.mime_type or 'unknown'}]")
        else:
            parts.append(str(item))
    return "\n".join(parts) if parts else "(empty resource)"


def stringify_prompt_result(result: types.GetPromptResult) -> str:
    lines: list[str] = []
    if result.description:
        lines.append(f"description: {result.description}")
    for msg in result.messages or []:
        role = getattr(msg, "role", "?")
        content = msg.content
        if isinstance(content, types.TextContent):
            body = content.text or ""
        else:
            body = _stringify_content(content)
        lines.append(f"[{role}] {body}")
    return "\n".join(lines) if lines else "(empty prompt)"
