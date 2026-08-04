from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path
from typing import Any

from kateto.core.manager import PluginManager
from kateto.core.plugin import Plugin

logger = logging.getLogger(__name__)


class MemorySinkPlugin(Plugin):
    """Plugin for storing conversation & event history in a vector memory store (ChromaDB)."""

    def __init__(
        self,
        name: str = "memory_sink",
        *,
        config_dir: Path | None = None,
        collection_name: str = "kateto_events",
    ) -> None:
        super().__init__(name=name, capabilities=("memory", "vector_memory"))
        self.config_dir = config_dir
        self.collection_name = collection_name
        self._client: Any = None
        self._collection: Any = None
        self._fallback_store: list[dict[str, Any]] = []

    async def initialize(self) -> None:
        if self.config_dir is None and self.manager is not None:
            # Resolve config_dir from manager or default
            self.config_dir = Path.home() / ".config" / "kateto"

        db_path = (self.config_dir or Path(".")).resolve() / "memory_db"
        db_path.mkdir(parents=True, exist_ok=True)

        try:
            import chromadb

            self._client = chromadb.PersistentClient(path=str(db_path))
            self._collection = self._client.get_or_create_collection(self.collection_name)
        except Exception as e:
            logger.warning("ChromaDB not available or failed to initialize: %s. Using in-memory fallback.", e)

    def add_memory(
        self,
        text: str,
        *,
        voice: str = "system",
        event_type: str = "event",
        ts: float | None = None,
        trace_id: str = "",
        dept: str = "fun",
    ) -> None:
        if not text:
            return

        now_ts = ts if ts is not None else time.time()
        doc_id = f"mem_{int(now_ts * 1000)}_{len(self._fallback_store)}"
        metadata = {
            "voice": voice,
            "type": event_type,
            "ts": now_ts,
            "trace_id": trace_id,
            "dept": dept,
        }

        if self._collection is not None:
            try:
                self._collection.add(
                    documents=[text],
                    metadatas=[metadata],
                    ids=[doc_id],
                )
                return
            except Exception as e:
                logger.warning("Failed to store document in ChromaDB: %s", e)

        self._fallback_store.append({"id": doc_id, "document": text, "metadata": metadata})

    def query_memory(self, query_text: str, top_k: int = 3, dept: str | None = None) -> list[str]:
        if not query_text:
            return []

        if self._collection is not None:
            try:
                where_clause = {"dept": dept} if dept else None
                res = self._collection.query(
                    query_texts=[query_text],
                    n_results=top_k,
                    where=where_clause,
                )
                if res and res.get("documents") and res["documents"][0]:
                    return list(res["documents"][0])
            except Exception as e:
                logger.warning("ChromaDB query failed: %s", e)

        # Fallback keyword match
        matches = [item["document"] for item in self._fallback_store if query_text.lower() in item["document"].lower()]
        return matches[:top_k]

    async def on_transcription(self, data: Any, envelope: Any = None) -> None:
        text = getattr(data, "text", str(data))
        voice = getattr(envelope, "source", "transcription")
        dept = getattr(envelope, "dept", "fun") or "fun"
        trace_id = getattr(envelope, "trace_id", "") or ""
        self.add_memory(text, voice=voice, event_type="transcription", trace_id=trace_id, dept=dept)

    async def on_text_chunk(self, data: Any, envelope: Any = None) -> None:
        if getattr(data, "final", False):
            text = getattr(data, "text", "")
            voice = getattr(data, "voice_id", "assistant") or "assistant"
            dept = getattr(envelope, "dept", "fun") or "fun"
            self.add_memory(text, voice=voice, event_type="text_chunk", dept=dept)

    async def on_generate(self, data: Any, envelope: Any = None) -> None:
        text = str(data)
        self.add_memory(text, voice="system", event_type="generate")

    async def on_voice_idle(self, data: Any, envelope: Any = None) -> None:
        pass

    async def on_tool_result(self, data: Any, envelope: Any = None) -> None:
        text = str(data)
        self.add_memory(text, voice="tool", event_type="tool_result")
