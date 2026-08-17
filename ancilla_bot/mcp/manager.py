"""
MCP マネージャ: 専用 asyncio ループで ClientSession を維持する。
"""

from __future__ import annotations

import asyncio
import os
import threading
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from typing import Any

from loguru import logger
from mcp import ClientSession, StdioServerParameters, types
from mcp.client.session import HANDSHAKE_PROTOCOL_VERSIONS
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import create_mcp_http_client, streamable_http_client

from ancilla_bot.mcp.config import (
    HttpServerConfig,
    ServerConfig,
    StdioServerConfig,
    load_mcp_config,
)
from ancilla_bot.mcp.results import (
    stringify_call_tool_result,
    stringify_prompt_result,
    stringify_resource_contents,
)

DEFAULT_READ_TIMEOUT = float(os.getenv("ANCILLA_MCP_TIMEOUT_SEC", "60"))
CLIENT_INFO = types.Implementation(name="ancilla-bot", version="0.1.0")


@dataclass
class ServerRuntime:
    name: str
    session: ClientSession
    capabilities: types.ServerCapabilities
    instructions: str | None = None
    tools: list[types.Tool] = field(default_factory=list)
    resources: list[types.Resource] = field(default_factory=list)
    prompts: list[types.Prompt] = field(default_factory=list)
    stop: asyncio.Event = field(default_factory=asyncio.Event)


class McpManager:
    def __init__(self) -> None:
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()
        self._settle = threading.Event()
        self._servers: dict[str, ServerRuntime] = {}
        self._lock = threading.Lock()
        self._started = False
        self._expected = 0
        self._finished = 0

    @property
    def started(self) -> bool:
        return self._started

    def start(self, configs: list[ServerConfig] | None = None) -> None:
        if self._started:
            return
        servers = configs if configs is not None else load_mcp_config()
        if not servers:
            logger.info("mcp: no servers configured")
            self._started = True
            from ancilla_bot.mcp.bridge import sync_registry_from_manager

            sync_registry_from_manager(self)
            return
        self._expected = len(servers)
        self._finished = 0
        self._settle.clear()
        self._thread = threading.Thread(
            target=self._thread_main,
            args=(servers,),
            name="mcp-manager",
            daemon=True,
        )
        self._thread.start()
        if not self._ready.wait(timeout=DEFAULT_READ_TIMEOUT + 30):
            logger.warning("mcp: start timed out waiting for event loop")
        if not self._settle.wait(timeout=DEFAULT_READ_TIMEOUT + 60):
            logger.warning(
                "mcp: start timed out waiting for servers ({}/{})",
                self._finished,
                self._expected,
            )
        self._started = True

    def shutdown(self) -> None:
        if self._loop is None:
            self._started = False
            return
        fut = asyncio.run_coroutine_threadsafe(self._shutdown_async(), self._loop)
        try:
            fut.result(timeout=DEFAULT_READ_TIMEOUT + 30)
        except Exception as exc:
            logger.warning("mcp shutdown error: {}", exc)
        if self._thread is not None:
            self._thread.join(timeout=DEFAULT_READ_TIMEOUT + 5)
        self._thread = None
        self._loop = None
        self._started = False
        with self._lock:
            self._servers.clear()

    def list_server_names(self) -> list[str]:
        with self._lock:
            return sorted(self._servers.keys())

    def get_instructions(self) -> dict[str, str]:
        with self._lock:
            return {
                name: rt.instructions
                for name, rt in self._servers.items()
                if rt.instructions
            }

    def get_tools(self) -> list[tuple[str, types.Tool]]:
        with self._lock:
            return [(name, tool) for name, rt in self._servers.items() for tool in rt.tools]

    def get_resources(self) -> list[tuple[str, types.Resource]]:
        with self._lock:
            return [
                (name, res) for name, rt in self._servers.items() for res in rt.resources
            ]

    def get_prompts(self) -> list[tuple[str, types.Prompt]]:
        with self._lock:
            return [
                (name, prompt)
                for name, rt in self._servers.items()
                for prompt in rt.prompts
            ]

    def call_tool(self, server: str, name: str, arguments: dict[str, Any] | None = None) -> str:
        return self._run(self._call_tool_async(server, name, arguments or {}))

    def list_resources_text(self) -> str:
        rows = self.get_resources()
        if not rows:
            return "No MCP resources."
        lines = []
        for server, res in rows:
            desc = f" — {res.description}" if res.description else ""
            lines.append(f"- [{server}] {res.uri} ({res.name}){desc}")
        return "\n".join(lines)

    def list_prompts_text(self) -> str:
        rows = self.get_prompts()
        if not rows:
            return "No MCP prompts."
        lines = []
        for server, prompt in rows:
            desc = f" — {prompt.description}" if prompt.description else ""
            lines.append(f"- [{server}] {prompt.name}{desc}")
        return "\n".join(lines)

    def read_resource(self, server: str, uri: str) -> str:
        return self._run(self._read_resource_async(server, uri))

    def get_prompt(
        self,
        server: str,
        name: str,
        arguments: dict[str, str] | None = None,
    ) -> str:
        return self._run(self._get_prompt_async(server, name, arguments or {}))

    def _run(self, coro: Any) -> str:
        if self._loop is None:
            return "Error: MCP manager is not running"
        fut = asyncio.run_coroutine_threadsafe(coro, self._loop)
        try:
            return fut.result(timeout=DEFAULT_READ_TIMEOUT + 5)
        except Exception as exc:
            return f"Error: {exc}"

    def _thread_main(self, servers: list[ServerConfig]) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._loop = loop
        self._ready.set()
        try:
            loop.run_until_complete(self._run_all(servers))
        finally:
            try:
                loop.run_until_complete(loop.shutdown_asyncgens())
            except Exception:
                pass
            loop.close()

    async def _run_all(self, servers: list[ServerConfig]) -> None:
        tasks = [asyncio.create_task(self._serve(cfg), name=f"mcp-{cfg.name}") for cfg in servers]
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _shutdown_async(self) -> None:
        with self._lock:
            runtimes = list(self._servers.values())
        for rt in runtimes:
            rt.stop.set()
        await asyncio.sleep(0)

    async def _serve(self, config: ServerConfig) -> None:
        try:
            async with AsyncExitStack() as stack:
                read, write = await self._open_transport(stack, config)
                session = await stack.enter_async_context(
                    ClientSession(
                        read,
                        write,
                        read_timeout_seconds=DEFAULT_READ_TIMEOUT,
                        logging_callback=self._make_logging_callback(config.name),
                        message_handler=self._make_message_handler(config.name),
                        client_info=CLIENT_INFO,
                    )
                )
                init = await session.initialize()
                if init.protocol_version not in HANDSHAKE_PROTOCOL_VERSIONS:
                    logger.warning(
                        "mcp {}: unsupported protocolVersion {}; disconnecting",
                        config.name,
                        init.protocol_version,
                    )
                    self._mark_finished()
                    return
                runtime = ServerRuntime(
                    name=config.name,
                    session=session,
                    capabilities=init.capabilities,
                    instructions=init.instructions,
                )
                with self._lock:
                    self._servers[config.name] = runtime
                await self._refresh_all(config.name)
                from ancilla_bot.mcp.bridge import sync_registry_from_manager

                sync_registry_from_manager(self)
                self._mark_finished()
                logger.info(
                    "mcp {}: connected protocol={} tools={} resources={} prompts={}",
                    config.name,
                    init.protocol_version,
                    len(runtime.tools),
                    len(runtime.resources),
                    len(runtime.prompts),
                )
                await runtime.stop.wait()
        except Exception as exc:
            logger.warning("mcp {}: connection failed: {}", config.name, exc)
            self._mark_finished()
        finally:
            with self._lock:
                self._servers.pop(config.name, None)
            try:
                from ancilla_bot.mcp.bridge import sync_registry_from_manager

                sync_registry_from_manager(self)
            except Exception as exc:
                logger.warning("mcp {}: registry sync failed after disconnect: {}", config.name, exc)

    def _mark_finished(self) -> None:
        with self._lock:
            self._finished += 1
            done = self._finished >= self._expected
        if done:
            self._settle.set()

    async def _open_transport(
        self,
        stack: AsyncExitStack,
        config: ServerConfig,
    ) -> tuple[Any, Any]:
        if isinstance(config, StdioServerConfig):
            params = StdioServerParameters(
                command=config.command,
                args=config.args,
                env=config.env or None,
                cwd=config.cwd,
            )
            return await stack.enter_async_context(stdio_client(params))
        assert isinstance(config, HttpServerConfig)
        http_client = create_mcp_http_client(headers=config.headers or None)
        await stack.enter_async_context(http_client)
        return await stack.enter_async_context(
            streamable_http_client(config.url, http_client=http_client)
        )

    def _make_logging_callback(self, server: str):
        async def _on_log(params: types.LoggingMessageNotificationParams) -> None:
            level = (params.level or "info").lower()
            mapped = {
                "debug": "DEBUG",
                "info": "INFO",
                "notice": "INFO",
                "warning": "WARNING",
                "error": "ERROR",
                "critical": "CRITICAL",
                "alert": "CRITICAL",
                "emergency": "CRITICAL",
            }.get(level, "INFO")
            logger.log(mapped, "mcp {}: {}", server, params.data)

        return _on_log

    def _make_message_handler(self, server: str):
        async def _on_message(message: types.ServerNotification | Exception) -> None:
            if isinstance(message, Exception):
                logger.warning("mcp {}: transport exception: {}", server, message)
                return
            if isinstance(message, types.ToolListChangedNotification):
                await self._refresh_tools(server)
                from ancilla_bot.mcp.bridge import sync_registry_from_manager

                sync_registry_from_manager(self)
            elif isinstance(message, types.ResourceListChangedNotification):
                await self._refresh_resources(server)
            elif isinstance(message, types.PromptListChangedNotification):
                await self._refresh_prompts(server)

        return _on_message

    async def _refresh_all(self, server: str) -> None:
        await self._refresh_tools(server)
        await self._refresh_resources(server)
        await self._refresh_prompts(server)

    def _runtime(self, server: str) -> ServerRuntime | None:
        with self._lock:
            return self._servers.get(server)

    async def _refresh_tools(self, server: str) -> None:
        rt = self._runtime(server)
        if rt is None or rt.capabilities.tools is None:
            return
        tools = await self._paginate_tools(rt.session)
        with self._lock:
            if server in self._servers:
                self._servers[server].tools = tools

    async def _refresh_resources(self, server: str) -> None:
        rt = self._runtime(server)
        if rt is None or rt.capabilities.resources is None:
            return
        resources = await self._paginate_resources(rt.session)
        with self._lock:
            if server in self._servers:
                self._servers[server].resources = resources

    async def _refresh_prompts(self, server: str) -> None:
        rt = self._runtime(server)
        if rt is None or rt.capabilities.prompts is None:
            return
        prompts = await self._paginate_prompts(rt.session)
        with self._lock:
            if server in self._servers:
                self._servers[server].prompts = prompts

    async def _paginate_tools(self, session: ClientSession) -> list[types.Tool]:
        items: list[types.Tool] = []
        cursor: str | None = None
        while True:
            params = types.PaginatedRequestParams(cursor=cursor) if cursor else None
            result = await session.list_tools(params=params)
            items.extend(result.tools)
            cursor = result.next_cursor
            if not cursor:
                break
        return items

    async def _paginate_resources(self, session: ClientSession) -> list[types.Resource]:
        items: list[types.Resource] = []
        cursor: str | None = None
        while True:
            params = types.PaginatedRequestParams(cursor=cursor) if cursor else None
            result = await session.list_resources(params=params)
            items.extend(result.resources)
            cursor = result.next_cursor
            if not cursor:
                break
        return items

    async def _paginate_prompts(self, session: ClientSession) -> list[types.Prompt]:
        items: list[types.Prompt] = []
        cursor: str | None = None
        while True:
            params = types.PaginatedRequestParams(cursor=cursor) if cursor else None
            result = await session.list_prompts(params=params)
            items.extend(result.prompts)
            cursor = result.next_cursor
            if not cursor:
                break
        return items

    async def _call_tool_async(
        self,
        server: str,
        name: str,
        arguments: dict[str, Any],
    ) -> str:
        rt = self._runtime(server)
        if rt is None:
            return f"Error: unknown MCP server: {server}"
        try:
            result = await rt.session.call_tool(name, arguments=arguments)
        except Exception as exc:
            return f"Error: {exc}"
        if not isinstance(result, types.CallToolResult):
            return f"Error: unexpected tool result type: {type(result).__name__}"
        return stringify_call_tool_result(result)

    async def _read_resource_async(self, server: str, uri: str) -> str:
        rt = self._runtime(server)
        if rt is None:
            return f"Error: unknown MCP server: {server}"
        try:
            result = await rt.session.read_resource(uri)
        except Exception as exc:
            return f"Error: {exc}"
        if not isinstance(result, types.ReadResourceResult):
            return f"Error: unexpected resource result type: {type(result).__name__}"
        return stringify_resource_contents(result)

    async def _get_prompt_async(
        self,
        server: str,
        name: str,
        arguments: dict[str, str],
    ) -> str:
        rt = self._runtime(server)
        if rt is None:
            return f"Error: unknown MCP server: {server}"
        try:
            result = await rt.session.get_prompt(name, arguments=arguments or None)
        except Exception as exc:
            return f"Error: {exc}"
        if not isinstance(result, types.GetPromptResult):
            return f"Error: unexpected prompt result type: {type(result).__name__}"
        return stringify_prompt_result(result)


_MANAGER: McpManager | None = None
_MANAGER_LOCK = threading.Lock()


def get_manager() -> McpManager:
    global _MANAGER
    with _MANAGER_LOCK:
        if _MANAGER is None:
            _MANAGER = McpManager()
        return _MANAGER
