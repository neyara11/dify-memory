from collections.abc import Generator
from typing import Any

from dify_plugin import Tool
from dify_plugin.entities.tool import ToolInvokeMessage

from utils.user_memory import UserMemory


class MemoryRecentTool(Tool):
    def _invoke(self, tool_parameters: dict[str, Any]) -> Generator[ToolInvokeMessage, None, None]:
        try:
            memory = UserMemory(self.session.storage, self.runtime.credentials)
            user_key = memory.resolve_user_key(tool_parameters, self.runtime)
            limit = int(tool_parameters.get("limit") or 10)
            limit = max(1, min(limit, 50))
            result = memory.recent(user_key, limit)
            yield self.create_json_message(result)
            items = result.get("items") or []
            if not items:
                yield self.create_text_message(f"No memories stored for {user_key} yet")
                return
            lines = [f"Recent memories for {user_key}:"]
            for item in items:
                lines.append(f"- [{item.get('chunk_id')}] {item.get('content')}")
            yield self.create_text_message("\n".join(lines))
        except Exception as e:
            yield self.create_text_message(f"memory_recent failed: {e}")
