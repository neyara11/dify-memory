# Privacy Policy — dify-kb-memory

This plugin stores and retrieves user memory exclusively inside your own Dify
knowledge base via the Dify Service API.

- No data is sent to any third-party service or external server.
- The only network calls go to the Dify API base URL you configure.
- The plugin's persistent key-value storage keeps only the mapping
  `user_key -> memory document id`.
- Memory content (facts, preferences, dialog summaries) lives in the knowledge
  base you designate and is governed by your Dify instance's data policies.
- Deleting a memory chunk removes it from the knowledge base index.
