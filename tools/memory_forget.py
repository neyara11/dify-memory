from collections.abc import Generator
from typing import Any

from dify_plugin import Tool
from dify_plugin.entities.tool import ToolInvokeMessage

from utils.user_memory import UserMemory


class MemoryForgetTool(Tool):
    def _invoke(self, tool_parameters: dict[str, Any]) -> Generator[ToolInvokeMessage, None, None]:
        try:
            memory = UserMemory(self.session.storage, self.runtime.credentials)
            user_key = memory.resolve_user_key(tool_parameters, self.runtime)
            target = str(tool_parameters.get("target") or "").strip()
            if not target:
                yield self.create_text_message("memory_forget: target is empty")
                return
            result = memory.forget(user_key, target)
            yield self.create_json_message(result)
            deleted = result.get("deleted") or []
            if not deleted:
                yield self.create_text_message(f"Nothing matching '{target}' found in memory of {user_key}")
                return
            yield self.create_text_message(
                f"Forgot {len(deleted)} memory(ies) for {user_key}: "
                + "; ".join(str(item.get("content") or item.get("chunk_id")) for item in deleted)
            )
        except Exception as e:
            yield self.create_text_message(f"memory_forget failed: {e}")
