from typing import Any

from dify_plugin import ToolProvider
from dify_plugin.errors.tool import ToolProviderCredentialValidationError

from utils.knowledge import KnowledgeClient, KnowledgeError


class DifyKbMemoryProvider(ToolProvider):
    def _validate_credentials(self, credentials: dict[str, Any]) -> None:
        try:
            client = KnowledgeClient(
                api_base=credentials["api_base"],
                api_key=credentials["dataset_api_key"],
                dataset_id=credentials["dataset_id"],
            )
            client.ping()
        except (KnowledgeError, KeyError) as e:
            raise ToolProviderCredentialValidationError(str(e))
