"""
ツールレジストリ
"""

from datetime import datetime
from typing import Any, Callable

from ancilla_bot.tools.searxng_client import search as searxng_search

# プロンプト用のツール説明
TOOL_DESCRIPTIONS: dict[str, str] = {
    "get_time": "現在の日時を返す。action_input は {} でよい。",
    "web_search": "Web を検索する。action_input は {\"query\": \"検索クエリ\", \"max_results\": 5} の形。max_results は省略可（デフォルト 5）。",
}


def get_time(**kwargs: Any) -> str:
    """
    現在の日時を返す。action_input は {} でよい。
    """
    _ = kwargs
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def web_search(query: str, max_results: int = 5, **kwargs: Any) -> str:
    """
    SearXNG で Web 検索を行う。
    action_input: {"query": "検索クエリ", "max_results": 5}
    """
    _ = kwargs
    return searxng_search(query=query, max_results=max_results)


TOOL_REGISTRY: dict[str, Callable[..., str]] = {
    "get_time": get_time,
    "web_search": web_search,
}


def build_tools_system_prompt() -> str:
    """
    ツール呼び出し用の System メッセージを組み立てる。
    """
    tools_block = "\n".join(
        f"- {name}: {desc}" for name, desc in TOOL_DESCRIPTIONS.items()
    )
    return f"""あなたは思考過程（thought）と、必要に応じてツール呼び出し（action, action_input）または最終回答（final_answer）を、次の JSON 形式だけで出力するアシスタントです。

## 利用可能なツール

{tools_block}

## 出力ルール

- thought: 必須。ユーザーの質問の意図を整理し、どう答えるか考える（内部用。短くてよい）。
- ツールを呼ぶとき: action にツール名、action_input に引数オブジェクトを書く。final_answer は null または省略。
- ツールを呼ばないとき: action と action_input は null または省略。final_answer にユーザーに表示する日本語の回答を書く。
- JSON 以外の説明や前後の文章は一切出力しないでください。"""
