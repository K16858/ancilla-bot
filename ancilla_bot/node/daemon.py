"""Node デーモン: Core に接続し、config を受けて定期的に telemetry を送る。"""

from __future__ import annotations

import asyncio
import json
import platform
import socket
import ssl
from importlib.metadata import PackageNotFoundError, version

import psutil
from loguru import logger
from websockets.asyncio.client import connect

from ancilla_bot.node import collect
from ancilla_bot.node.execute import Executor

BACKOFF_START_SEC = 1.0
BACKOFF_MAX_SEC = 60.0
CONFIG_TIMEOUT_SEC = 10.0


def _version() -> str:
    try:
        return version("ancilla-bot")
    except PackageNotFoundError:
        return "unknown"


async def _run_command(ws, executor: Executor, cmd: dict) -> None:
    try:
        res = await asyncio.to_thread(executor.handle, cmd)
        await ws.send(json.dumps(res))
    except Exception as e:  # 切断中など。Core 側は timeout になり、再送されても結果は記憶済み
        logger.warning("node: command_result 送信失敗: {}", e)


async def _session(ws, state: dict, backoff_start: float) -> None:
    await ws.send(json.dumps({
        "type": "hello",
        "host_id": state["host_id"],
        "version": _version(),
        "os": platform.system().lower(),
        "hostname": socket.gethostname(),
    }))
    cfg = json.loads(await asyncio.wait_for(ws.recv(), CONFIG_TIMEOUT_SEC))
    state["backoff"] = backoff_start  # 認証と hello が通ったらバックオフをリセット
    loop = asyncio.get_running_loop()
    next_at = loop.time()
    while True:
        if isinstance(cfg, dict) and cfg.get("type") == "config":
            state["interval"] = max(float(cfg.get("interval", 30)), 0.1)
            state["services"] = list(cfg.get("services") or [])
            logger.info("node: config interval={} services={}", state["interval"], len(state["services"]))
        elif isinstance(cfg, dict) and cfg.get("type") == "command":
            task = asyncio.create_task(_run_command(ws, state["executor"], cfg))
            state["tasks"].add(task)
            task.add_done_callback(state["tasks"].discard)
        cfg = None
        delay = next_at - loop.time()
        if delay <= 0:
            state["seq"] += 1
            msg = await asyncio.to_thread(collect.collect, state["seq"], state["services"])
            await ws.send(json.dumps(msg))
            next_at = loop.time() + state["interval"]
            continue
        try:  # 待ち中に新しい config が来たら適用する（recv のキャンセルは安全）
            cfg = json.loads(await asyncio.wait_for(ws.recv(), delay))
        except asyncio.TimeoutError:
            pass


async def run(
    url: str,
    host_id: str,
    token: str,
    *,
    ssl_context: ssl.SSLContext | None = None,
    backoff_start: float = BACKOFF_START_SEC,
    backoff_max: float = BACKOFF_MAX_SEC,
    executor: Executor | None = None,
) -> None:
    """切断・失敗時は指数バックオフで再接続し続ける。切断中の telemetry は送らず捨てる。"""
    state = {"host_id": host_id, "seq": 0, "interval": 30.0, "services": [], "backoff": backoff_start,
             "executor": executor or Executor(host_id), "tasks": set()}  # 既定 Executor は許可リストが空 = 全拒否
    kwargs = {"ssl": ssl_context} if ssl_context is not None else {}
    psutil.cpu_percent(interval=None)  # 初回の 0.0 を捨てる
    while True:
        try:
            async with connect(
                url, additional_headers={"Authorization": f"Bearer {token}"}, **kwargs
            ) as ws:
                logger.info("node: 接続 {}", url)
                await _session(ws, state, backoff_start)
        except Exception as e:  # 認証拒否・切断・タイムアウト等はすべて再接続の対象
            logger.warning("node: 切断/接続失敗 ({}): {}", type(e).__name__, e)
        await asyncio.sleep(state["backoff"])
        state["backoff"] = min(state["backoff"] * 2, backoff_max)


def run_from_env() -> int:
    """`ancilla node`: 環境変数から設定を読んでフォアグラウンドで動かす。"""
    import os
    import sys

    url, host_id, token = (os.getenv(k, "").strip() for k in (
        "ANCILLA_NODE_CORE_URL", "ANCILLA_NODE_HOST_ID", "ANCILLA_NODE_TOKEN"))
    if not (url and host_id and token):
        print("ANCILLA_NODE_CORE_URL / ANCILLA_NODE_HOST_ID / ANCILLA_NODE_TOKEN を設定してください"
              "（ancilla install node で書き込めます）", file=sys.stderr)
        return 1
    ca = os.getenv("ANCILLA_NODE_CA_FILE", "").strip()
    ctx = ssl.create_default_context(cafile=ca) if ca and url.startswith("wss://") else None
    try:
        asyncio.run(run(url, host_id, token, ssl_context=ctx, executor=Executor.from_env(host_id)))
    except KeyboardInterrupt:
        pass
    return 0
