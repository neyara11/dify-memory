import time
from typing import Any

import requests

UUID_RE = r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"

DOC_NAME_PREFIX = "memory::"
USER_FIELD_NAME = "user_id"


class KnowledgeError(RuntimeError):
    pass


class KnowledgeClient:
    def __init__(self, api_base: str, api_key: str, dataset_id: str, timeout: int = 30):
        self.dataset_id = dataset_id
        self.timeout = timeout
        self.base = api_base.rstrip("/")
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            }
        )

    def _url(self, path: str) -> str:
        root = f"{self.base}/datasets/{self.dataset_id}"
        return f"{root}{path}" if path else root

    def _send(self, method: str, url: str, **kwargs: Any) -> Any:
        resp = self.session.request(method, url, timeout=self.timeout, **kwargs)
        if resp.status_code >= 400:
            try:
                detail: Any = resp.json()
            except ValueError:
                detail = resp.text[:500]
            raise KnowledgeError(f"{method} {url} -> {resp.status_code}: {detail}")
        if resp.content:
            return resp.json()
        return {}

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        return self._send(method, self._url(path), **kwargs)

    def ping(self) -> Any:
        data = self._send("GET", f"{self.base}/datasets", params={"page": 1, "limit": 100})
        items = data.get("data") or []
        ids = {str(item.get("id")) for item in items}
        if self.dataset_id not in ids:
            visible = ", ".join(
                f"{item.get('name')} ({item.get('id')})" for item in items[:20]
            ) or "none"
            raise KnowledgeError(
                f"knowledge base {self.dataset_id} is not visible to this API key. "
                f"Visible knowledge bases: {visible}. "
                "Use the ID of the memory knowledge base or widen the API key scope. "
                "If the list is empty, the API base URL must point to the Dify Service API root ending in /v1."
            )
        return data

    def list_metadata_fields(self) -> list[dict[str, Any]]:
        data = self._request("GET", "/metadata")
        if isinstance(data, list):
            return data
        return data.get("data") or []

    def ensure_metadata_field(self, name: str = USER_FIELD_NAME) -> str | None:
        try:
            for field in self.list_metadata_fields():
                if field.get("name") == name and field.get("id"):
                    return str(field["id"])
        except KnowledgeError:
            return None
        try:
            data = self._request("POST", "/metadata", json={"type": "string", "name": name})
            if data.get("id"):
                return str(data["id"])
        except KnowledgeError:
            pass
        try:
            for field in self.list_metadata_fields():
                if field.get("name") == name and field.get("id"):
                    return str(field["id"])
        except KnowledgeError:
            return None
        return None

    def set_document_metadata(self, doc_id: str, field_id: str, field_name: str, value: str) -> None:
        self._request(
            "POST",
            "/documents/metadata",
            json={
                "operation_data": [
                    {
                        "document_id": doc_id,
                        "metadata_list": [{"id": field_id, "name": field_name, "value": value}],
                        "partial_update": True,
                    }
                ]
            },
        )

    def create_document(self, name: str, seed_text: str) -> str:
        body = {
            "name": name,
            "text": seed_text,
            "indexing_technique": "high_quality",
            "doc_form": "text_model",
            "process_rule": {"mode": "automatic"},
        }
        data = self._request("POST", "/document/create-by-text", json=body)
        doc = data.get("document") or data.get("doc") or {}
        doc_id = doc.get("id")
        if not doc_id:
            raise KnowledgeError(f"create_document: no document id in response: {data}")
        batch = data.get("batch")
        if batch:
            try:
                self._wait_batch(str(batch))
            except KnowledgeError:
                pass
        return str(doc_id)

    def _wait_batch(self, batch: str, timeout: float = 60.0) -> None:
        deadline = time.time() + timeout
        while time.time() < deadline:
            data = self._request("GET", f"/documents/{batch}/indexing-status")
            items = data.get("data") or []
            statuses = [item.get("indexing_status") for item in items]
            if any(status == "error" for status in statuses):
                raise KnowledgeError(f"document indexing failed: {data}")
            if statuses and all(status == "completed" for status in statuses):
                return
            time.sleep(1.0)

    def find_document_by_name(self, name: str) -> str | None:
        for page in range(1, 11):
            data = self._request("GET", "/documents", params={"page": page, "limit": 100})
            items = data.get("data") or []
            for doc in items:
                if doc.get("name") == name and doc.get("id"):
                    return str(doc["id"])
            if len(items) < 100:
                return None
        return None

    def add_chunk(self, doc_id: str, content: str, keywords: list[str]) -> dict[str, Any]:
        last_error: Exception | None = None
        for _ in range(6):
            try:
                data = self._request(
                    "POST",
                    f"/documents/{doc_id}/segments",
                    json={"segments": [{"content": content, "keywords": keywords}]},
                )
                items = data.get("data") or []
                return items[0] if items else {}
            except KnowledgeError as e:
                last_error = e
                message = str(e).lower()
                if any(
                    marker in message
                    for marker in ("not completed", "not found", "404", "indexing")
                ):
                    time.sleep(1.5)
                    continue
                raise
        raise KnowledgeError(f"add_chunk failed: {last_error}")

    def list_chunks(self, doc_id: str, limit: int = 100, keyword: str | None = None) -> list[dict[str, Any]]:
        chunks: list[dict[str, Any]] = []
        page = 1
        while len(chunks) < limit:
            params: dict[str, Any] = {"page": page, "limit": 100}
            if keyword:
                params["keyword"] = keyword
            data = self._request("GET", f"/documents/{doc_id}/segments", params=params)
            batch = data.get("data") or []
            chunks.extend(batch)
            if len(batch) < 100:
                break
            page += 1
        return chunks[:limit]

    def update_chunk(self, doc_id: str, segment_id: str, content: str, keywords: list[str]) -> None:
        self._request(
            "PATCH",
            f"/documents/{doc_id}/segments/{segment_id}",
            json={"segment": {"content": content, "keywords": keywords}},
        )

    def delete_chunk(self, doc_id: str, segment_id: str) -> None:
        self._request("DELETE", f"/documents/{doc_id}/segments/{segment_id}")

    def retrieve(
        self,
        query: str,
        top_k: int,
        search_method: str,
        metadata_value: str | None = None,
    ) -> list[dict[str, Any]]:
        query = query[:250]
        retrieval_model: dict[str, Any] = {
            "search_method": search_method,
            "reranking_enable": False,
            "top_k": max(top_k, 10),
            "score_threshold_enabled": False,
        }
        if search_method == "hybrid_search":
            retrieval_model["weights"] = {"weight_type": "semantic_first"}
        if metadata_value:
            retrieval_model["metadata_filtering_conditions"] = {
                "logical_operator": "and",
                "conditions": [
                    {"name": USER_FIELD_NAME, "comparison_operator": "is", "value": metadata_value}
                ],
            }
        try:
            data = self._request("POST", "/retrieve", json={"query": query, "retrieval_model": retrieval_model})
        except KnowledgeError:
            if search_method != "hybrid_search":
                raise
            retrieval_model["search_method"] = "semantic_search"
            retrieval_model.pop("weights", None)
            data = self._request("POST", "/retrieve", json={"query": query, "retrieval_model": retrieval_model})
        return data.get("records") or []
