# Dify KB Memory

Cross-session memory tool plugin for self-hosted Dify. User memory is stored in
a regular Dify knowledge base: **one document per user ("memory file"), one
chunk per fact**. No external services are required: embeddings, indexing, and
retrieval are handled by Dify itself.

Source repository: https://github.com/neyara11/dify-memory

## How it works

- Each user gets a document named `memory::<user_key>` in the configured
  knowledge base.
- Every memory is a separate chunk (fact, preference, goal, dialog summary)
  with keywords.
- The `user_key -> document id` mapping is kept in the plugin's persistent
  key-value storage; it is restored by document name if lost and reset
  automatically when a document no longer exists. No database of your own is
  needed.
- A `user_id` metadata field is set on each document, and retrieval uses
  server-side `metadata_filtering_conditions`, so all top-K slots belong to the
  requested user instead of being mixed across users. Dify caps retrieval at
  ~10 chunks per request; `memory_search` tops up results with a keyword match
  over the chunk list, and `memory_recent` paginates without that cap.
- Identity resolution: the `user_key` tool parameter (user id or email) falls
  back to the Dify runtime end-user id (`self.runtime.user_id`) and then to
  `conversation_id`.

## Tools (for the Agent node)

| Tool | Purpose |
|---|---|
| `memory_save` | Stores a fact (`kind`: fact/preference/goal/dialog/summary) |
| `memory_search` | Semantic/hybrid search over the user's memories |
| `memory_forget` | Deletes by chunk id or by fact text (substring match) |
| `memory_recent` | Lists the most recent memories with chunk ids (no top-K cap) |

All parameters except `top_k`/`limit` use `form: llm`, so the agent decides what
to save or delete and fills in the content itself.

## Installation

1. **Knowledge base.** Create a knowledge base in Dify to hold memories:
   - configure an embedding model in the knowledge base settings (`high_quality`
     indexing is used);
   - enable API Access and create a knowledge base API key;
   - note the knowledge base ID (visible in the Dify URL).
2. **Plugin.** Build and install:
   ```bash
   dify plugin package ./dify-memory   # produces dify-kb-memory.difypkg
   ```
   Install the `.difypkg` through Plugins -> Install plugin (Local), or with
   `dify plugin install`.
3. **Tool configuration** (in the tool card):
   - `Dify service API base URL` — inside docker-compose use
     `http://api:5001/v1`, otherwise `https://your-dify-host/v1`;
   - `Knowledge base API key` — the key from step 1;
   - `Memory knowledge base ID` — the knowledge base ID;
   - `Search method` — `hybrid_search` by default.

The plugin contacts only the configured Dify API base URL. No data is sent to
any third-party service.

## Agent node setup

Add all four tools to the agent and provide a system prompt such as:

```text
You have long-term memory about the user (memory_* tools).
At the start of a conversation, call memory_search on the topic and use what
you find. Save only durable information with memory_save: name, role,
preferences, goals, decisions — one fact per call. Do not save transient
details of the current task. When the user corrects or retracts information,
delete the old memory with memory_forget and save the new one. If the user asks
to forget something, delete it unconditionally. Do not pass user_key unless the
user states their id or email.
```

`user_key` can be left empty: the platform supplies the Dify end-user id. If you
have your own user accounts (email, internal id), have the agent pass that value
in `user_key` so memory is grouped by it.

## Development

```bash
# remote debugging: Plugins -> Get debug key, then .env:
#   INSTALL_METHOD=remote
#   REMOTE_INSTALL_URL=...
#   REMOTE_INSTALL_KEY=...
python -m main
```

## Limitations

- Dify retrieval returns at most ~10 chunks per request. That covers the reply
  context; the full memory is available through `memory_recent` (paginated).
- A newly created chunk is indexed in a few seconds. The plugin waits for the
  document to finish indexing on the first save for a user.
- Retrieval runs across the configured knowledge base; do not store unrelated
  knowledge in the memory knowledge base.
- The document mapping lives in Dify's plugin KV storage (inside your instance).
