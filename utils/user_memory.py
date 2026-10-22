import re
from typing import Any

from utils.knowledge import (
    DOC_NAME_PREFIX,
    USER_FIELD_NAME,
    UUID_RE,
    KnowledgeClient,
    KnowledgeError,
)

FIELD_ID_KEY = "memory-meta::field-id"


def storage_get(storage: Any, key: str) -> bytes | None:
    try:
        value = storage.get(key)
    except Exception:
        return None
    return value or None


def storage_set(storage: Any, key: str, value: bytes) -> None:
    try:
        storage.set(key, value)
    except Exception:
        pass


def storage_delete(storage: Any, key: str) -> None:
    try:
        storage.delete(key)
    except Exception:
        pass


class UserMemory:
    def __init__(self, storage: Any, credentials: dict[str, Any]):
        self.storage = storage
        self.client = KnowledgeClient(
            api_base=str(credentials.get("api_base") or "").strip(),
            api_key=str(credentials.get("dataset_api_key") or "").strip(),
            dataset_id=str(credentials.get("dataset_id") or "").strip(),
        )
        self.search_method = str(credentials.get("search_method") or "hybrid_search").strip()

    def resolve_user_key(self, tool_parameters: dict[str, Any], runtime: Any) -> str:
        key = str(tool_parameters.get("user_key") or "").strip()
        if key:
            return key
        for attr in ("user_id", "conversation_id"):
            value = getattr(runtime, attr, None)
            if value:
                return str(value)
        raise ValueError(
            "user_key is required: pass it explicitly or call from a Dify app with an identified end user"
        )

    def _doc_key(self, user_key: str) -> str:
        return f"memory-doc::{user_key}"

    def _invalidate(self, user_key: str) -> None:
        storage_delete(self.storage, self._doc_key(user_key))

    def _metadata_field_id(self) -> str | None:
        raw = storage_get(self.storage, FIELD_ID_KEY)
        if raw:
            return raw.decode("utf-8")
        field_id = self.client.ensure_metadata_field(USER_FIELD_NAME)
        if field_id:
            storage_set(self.storage, FIELD_ID_KEY, field_id.encode("utf-8"))
        return field_id

    def get_doc(self, user_key: str, create: bool = False) -> str | None:
        raw = storage_get(self.storage, self._doc_key(user_key))
        if raw:
            return raw.decode("utf-8")
        doc_id = self.client.find_document_by_name(f"{DOC_NAME_PREFIX}{user_key}")
        if doc_id:
            storage_set(self.storage, self._doc_key(user_key), doc_id.encode("utf-8"))
            return doc_id
        if not create:
            return None
        doc_id = self.client.create_document(
            f"{DOC_NAME_PREFIX}{user_key}",
            f"Memory file for {user_key}. Facts are stored as individual chunks in this document.",
        )
        storage_set(self.storage, self._doc_key(user_key), doc_id.encode("utf-8"))
        field_id = self._metadata_field_id()
        if field_id:
            try:
                self.client.set_document_metadata(doc_id, field_id, USER_FIELD_NAME, user_key)
            except KnowledgeError:
                pass
        return doc_id

    def save(self, user_key: str, content: str, kind: str, keywords: list[str]) -> dict[str, Any]:
        merged = [kind] + [k for k in keywords if k and k != kind]
        chunk: dict[str, Any] = {}
        for attempt in range(2):
            doc_id = self.get_doc(user_key, create=True)
            try:
                chunk = self.client.add_chunk(doc_id or "", content, merged)
                break
            except KnowledgeError as e:
                if attempt == 0 and "not found" in str(e).lower():
                    self._invalidate(user_key)
                    continue
                raise
        return {
            "ok": True,
            "user_key": user_key,
            "chunk_id": chunk.get("id"),
            "content": content,
            "keywords": merged,
        }

    def search(self, user_key: str, query: str, top_k: int) -> dict[str, Any]:
        for attempt in range(2):
            doc_id = self.get_doc(user_key)
            if not doc_id:
                return {"ok": True, "user_key": user_key, "query": query, "results": [], "note": "no memory yet"}
            try:
                return self._search_in_doc(user_key, doc_id, query, top_k)
            except KnowledgeError as e:
                if attempt == 0 and "not found" in str(e).lower():
                    self._invalidate(user_key)
                    continue
                raise
        return {"ok": True, "user_key": user_key, "query": query, "results": [], "note": "no memory yet"}

    def _search_in_doc(self, user_key: str, doc_id: str, query: str, top_k: int) -> dict[str, Any]:
        field_id = self._metadata_field_id()
        records = self.client.retrieve(
            query,
            top_k=top_k,
            search_method=self.search_method,
            metadata_value=user_key if field_id else None,
        )
        results: list[dict[str, Any]] = []
        seen: set[str] = set()
        for record in records:
            segment = record.get("segment") or {}
            chunk_id = str(segment.get("id") or "")
            if not chunk_id or chunk_id in seen:
                continue
            if segment.get("document_id") and segment.get("document_id") != doc_id:
                continue
            seen.add(chunk_id)
            results.append(
                {
                    "chunk_id": chunk_id,
                    "score": record.get("score"),
                    "content": segment.get("content"),
                    "keywords": segment.get("keywords") or [],
                    "matched_by": "retrieval",
                }
            )
        if len(results) < top_k:
            results.extend(self._keyword_fallback(doc_id, query, top_k - len(results), seen))
        return {"ok": True, "user_key": user_key, "query": query, "results": results[:top_k]}

    def _keyword_fallback(
        self, doc_id: str, query: str, needed: int, seen: set[str]
    ) -> list[dict[str, Any]]:
        if needed <= 0:
            return []
        words = [w for w in re.split(r"\W+", query.lower()) if len(w) > 2]
        if not words:
            return []
        ranked: list[tuple[int, dict[str, Any]]] = []
        for chunk in self.client.list_chunks(doc_id, limit=200):
            chunk_id = str(chunk.get("id") or "")
            if not chunk_id or chunk_id in seen:
                continue
            text = (chunk.get("content") or "").lower()
            hits = sum(1 for word in words if word in text)
            if hits:
                ranked.append((hits, chunk))
        ranked.sort(key=lambda item: item[0], reverse=True)
        picked: list[dict[str, Any]] = []
        for _, chunk in ranked[:needed]:
            picked.append(
                {
                    "chunk_id": chunk.get("id"),
                    "score": None,
                    "content": chunk.get("content"),
                    "keywords": chunk.get("keywords") or [],
                    "matched_by": "keyword",
                }
            )
        return picked

    def forget(self, user_key: str, target: str) -> dict[str, Any]:
        for attempt in range(2):
            doc_id = self.get_doc(user_key)
            if not doc_id:
                return {"ok": True, "user_key": user_key, "deleted": [], "note": "no memory yet"}
            try:
                return self._forget_in_doc(user_key, doc_id, target)
            except KnowledgeError as e:
                if attempt == 0 and "not found" in str(e).lower():
                    self._invalidate(user_key)
                    continue
                raise
        return {"ok": True, "user_key": user_key, "deleted": [], "note": "no memory yet"}

    def _forget_in_doc(self, user_key: str, doc_id: str, target: str) -> dict[str, Any]:
        deleted: list[dict[str, Any]] = []
        target = target.strip()
        if re.match(UUID_RE, target):
            self.client.delete_chunk(doc_id, target)
            deleted.append({"chunk_id": target})
        else:
            needle = target.lower()
            for chunk in self.client.list_chunks(doc_id, limit=200):
                if needle in (chunk.get("content") or "").lower():
                    chunk_id = str(chunk.get("id") or "")
                    self.client.delete_chunk(doc_id, chunk_id)
                    deleted.append({"chunk_id": chunk_id, "content": chunk.get("content")})
        return {"ok": True, "user_key": user_key, "deleted": deleted}

    def recent(self, user_key: str, limit: int) -> dict[str, Any]:
        for attempt in range(2):
            doc_id = self.get_doc(user_key)
            if not doc_id:
                return {"ok": True, "user_key": user_key, "items": [], "note": "no memory yet"}
            try:
                return self._recent_in_doc(user_key, doc_id, limit)
            except KnowledgeError as e:
                if attempt == 0 and "not found" in str(e).lower():
                    self._invalidate(user_key)
                    continue
                raise
        return {"ok": True, "user_key": user_key, "items": [], "note": "no memory yet"}

    def _recent_in_doc(self, user_key: str, doc_id: str, limit: int) -> dict[str, Any]:
        chunks = self.client.list_chunks(doc_id, limit=max(limit * 3, 30))
        chunks.sort(key=lambda chunk: chunk.get("updated_at") or 0, reverse=True)
        items = [
            {
                "chunk_id": chunk.get("id"),
                "content": chunk.get("content"),
                "keywords": chunk.get("keywords") or [],
                "updated_at": chunk.get("updated_at"),
            }
            for chunk in chunks[:limit]
        ]
        return {"ok": True, "user_key": user_key, "items": items}
