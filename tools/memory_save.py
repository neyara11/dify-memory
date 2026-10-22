from collections.abc import Generator
from typing import Any

from dify_plugin import Tool
from dify_plugin.entities.tool import ToolInvokeMessage

from utils.user_memory import UserMemory


class MemorySaveTool(Tool):
    def _invoke(self, tool_parameters: dict[str, Any]) -> Generator[ToolInvokeMessage, None, None]:
        try:
            memory = UserMemory(self.session.storage, self.runtime.credentials)
            user_key = memory.resolve_user_key(tool_parameters, self.runtime)
            content = str(tool_parameters.get("content") or "").strip()
            if not content:
                yield self.create_text_message("memory_save: content is empty, nothing saved")
                return
            kind = str(tool_parameters.get("kind") or "fact").strip().lower() or "fact"
            keywords_raw = str(tool_parameters.get("keywords") or "").strip()
            keywords = [k.strip() for k in keywords_raw.split(",") if k.strip()]
            result = memory.save(user_key, content, kind, keywords)
            yield self.create_json_message(result)
            yield self.create_text_message(
                f"Saved memory [{result.get('chunk_id')}] for {user_key}: {content}"
            )
        except Exception as e:
            yield self.create_text_message(f"memory_save failed: {e}")
