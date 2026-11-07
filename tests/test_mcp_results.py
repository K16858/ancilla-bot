from mcp import types

from ancilla_bot.mcp.results import (
    stringify_call_tool_result,
    stringify_prompt_result,
    stringify_resource_contents,
)


def _text(s):
    return types.TextContent(type="text", text=s)


def test_call_tool_result_joins_content_and_structured():
    result = types.CallToolResult(
        content=[
            _text("hello"),
            types.ImageContent(type="image", data="AA==", mime_type="image/png"),
            types.EmbeddedResource(
                type="resource",
                resource=types.TextResourceContents(uri="file:///a.txt", text="body"),
            ),
        ],
        structured_content={"k": "値"},
    )
    out = stringify_call_tool_result(result)
    assert out.startswith("hello\n[image mimeType=image/png]\n[resource uri=file:///a.txt]\nbody")
    assert out.endswith('structuredContent:\n{\n  "k": "値"\n}')


def test_call_tool_result_error_and_empty():
    assert stringify_call_tool_result(types.CallToolResult(content=[_text("bad")], is_error=True)) == "Error: bad"
    assert stringify_call_tool_result(types.CallToolResult(content=[], is_error=True)) == "Error: tool execution failed"
    assert stringify_call_tool_result(types.CallToolResult(content=[])) == "(empty tool result)"


def test_resource_contents_handles_blob_and_empty():
    result = types.ReadResourceResult(
        contents=[
            types.TextResourceContents(uri="file:///a", text="t"),
            types.BlobResourceContents(uri="file:///b", blob="AA==", mime_type="image/png"),
        ]
    )
    assert stringify_resource_contents(result) == "t\n[blob uri=file:///b mimeType=image/png]"
    assert stringify_resource_contents(types.ReadResourceResult(contents=[])) == "(empty resource)"


def test_prompt_result_lists_roles():
    result = types.GetPromptResult(
        description="d",
        messages=[types.PromptMessage(role="user", content=_text("hi"))],
    )
    assert stringify_prompt_result(result) == "description: d\n[user] hi"
    assert stringify_prompt_result(types.GetPromptResult(messages=[])) == "(empty prompt)"
