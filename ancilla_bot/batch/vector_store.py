"""
要約レコードを ChromaDB に格納（RAG オプション）
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from loguru import logger

DEFAULT_VECTOR_STORE_DIR = Path(os.getenv("ANCILLA_VECTOR_STORE_DIR", "data/vector_store"))
COLLECTION_NAME = "conversation_summaries"


def is_rag_enabled() -> bool:
    return os.getenv("ANCILLA_RAG_ENABLED", "true").strip().lower() in ("1", "true", "yes")


def _get_client():
    import chromadb

    path = os.getenv("ANCILLA_VECTOR_STORE_DIR", str(DEFAULT_VECTOR_STORE_DIR))
    Path(path).mkdir(parents=True, exist_ok=True)
    return chromadb.PersistentClient(path=path)


def add_summaries_to_store(records: list[dict]) -> None:
    """
    要約レコードのリストを埋め込みにして Chroma に追加する。
    RAG 無効時は何もしない。
    埋め込みに失敗したレコードはスキップし、ログを出して続行する。
    """
    if not records or not is_rag_enabled():
        return
    from ancilla_bot.llm import embed_text

    client = _get_client()
    collection = client.get_or_create_collection(name=COLLECTION_NAME)
    ids = []
    embeddings = []
    documents = []
    metadatas = []
    for rec in records:
        doc_id = f"{rec.get('date', '')}_{rec.get('start_index', 0)}"
        summary = rec.get("summary") or ""
        if not summary.strip():
            logger.warning("skip empty summary id={}", doc_id)
            continue
        try:
            vec = embed_text(summary)
        except Exception as e:
            logger.warning("embed failed id={} error={}", doc_id, e)
            continue
        ids.append(doc_id)
        embeddings.append(vec)
        documents.append(summary)
        metadatas.append(
            {
                "date": rec.get("date", ""),
                "start_index": rec.get("start_index", 0),
                "end_index": rec.get("end_index", 0),
                "tool_used": rec.get("tool_used", False),
            }
        )
    if ids:
        collection.add(ids=ids, embeddings=embeddings, documents=documents, metadatas=metadatas)
        logger.info("vector_store added {} summaries", len(ids))


def search_summaries(query: str, n_results: int = 3) -> list[dict[str, Any]]:
    """
    クエリに近い要約を Chroma で検索する。
    RAG 無効時や失敗時は空リスト。
    戻り値は [{"document": str, "metadata": dict, "source": "rag"}, ...]
    """
    if not query.strip() or n_results <= 0 or not is_rag_enabled():
        return []
    from ancilla_bot.llm import embed_text

    try:
        vec = embed_text(query)
    except Exception as e:
        logger.warning("embed query failed: {}", e)
        return []
    try:
        client = _get_client()
        collection = client.get_or_create_collection(name=COLLECTION_NAME)
    except Exception as e:
        logger.warning("vector_store client failed: {}", e)
        return []
    if collection.count() == 0:
        return []
    try:
        result = collection.query(
            query_embeddings=[vec],
            n_results=min(n_results, collection.count()),
        )
    except Exception as e:
        logger.warning("vector_store query failed: {}", e)
        return []
    docs = (result.get("documents") or [[]])[0] or []
    metas = (result.get("metadatas") or [[]])[0] or []
    out: list[dict[str, Any]] = []
    for i, doc in enumerate(docs):
        meta = metas[i] if i < len(metas) else {}
        out.append({"document": doc, "metadata": meta, "source": "rag"})
    return out
