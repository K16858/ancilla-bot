"""
ツールレジストリ
"""

from datetime import datetime
from typing import Any, Callable


def get_time(**kwargs: Any) -> str:
    """
    現在の日時を返す。action_input は {} でよい。
    """
    _ = kwargs
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


TOOL_REGISTRY: dict[str, Callable[..., str]] = {
    "get_time": get_time,
}
