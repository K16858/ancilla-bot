"""検索プロバイダの共通型。"""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class SearchHit:
    title: str
    url: str
    content: str


class SearchProvider(Protocol):
    name: str

    def available(self) -> bool: ...

    def search(self, query: str, max_results: int = 5) -> list[SearchHit]: ...
