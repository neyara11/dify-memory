from collections.abc import Generator
from typing import Any

from dify_plugin import Tool
from dify_plugin.entities.tool import ToolInvokeMessage

from utils.user_memory import UserMemory


class MemorySearchTool(Tool):
    def _invoke(self, tool_parameters: dict[str, Any]) -> Generator[ToolInvokeMessage, None, None]:
        try:
            memory = UserMemory(self.session.storage, self.runtime.credentials)
            user_key = memory.resolve_user_key(tool_parameters, self.runtime)
            query = str(tool_parameters.get("query") or "").strip()
            if not query:
                yield self.create_text_message("memory_search: query is empty")
                return
            top_k = int(tool_parameters.get("top_k") or 5)
            top_k = max(1, min(top_k, 10))
            result = memory.search(user_key, query, top_k)
            yield self.create_json_message(result)
            results = result.get("results") or []
            if not results:
                yield self.create_text_message(f"No memories found for {user_key} matching '{query}'")
                return
            lines = [f"Memories for {user_key} matching '{query}':"]
            for item in results:
                lines.append(f"- [{item.get('chunk_id')}] {item.get('content')}")
            yield self.create_text_message("\n".join(lines))
        except Exception as e:
            yield self.create_text_message(f"memory_search failed: {e}")
