# packages

The parts of sūveryn's engine, one folder each: the Python packages are one uv workspace, the chat UI is its own npm project. Each has a README saying what is in it; [docs/architecture.md](../docs/architecture.md) says how they fit together.

| Package | What it holds | Spec |
|---|---|---|
| [`harness`](harness/README.md) | Everything between the model and the person: the grounded prompt, the model server client, the checks on an answer | [docs/harness.md](../docs/harness.md) |
| [`rag`](rag/README.md) | Reading documents in an isolated reader, storing their passages, finding them again | [docs/architecture.md](../docs/architecture.md) |
| [`api-gateway`](api-gateway/README.md) | The server the browser talks to: sign-in, rights, the API, the playbook runtime | [docs/architecture.md](../docs/architecture.md), [openapi.json](api-gateway/openapi.json) |
| [`playbooks`](playbooks/README.md) | The official playbooks as manifests, and the loader | [docs/design/playbooks.md](../docs/design/playbooks.md), [Writing a playbook](https://github.com/suveryn/suveryn-docs/blob/main/playbooks/writing-a-playbook.md) |
| [`chat-ui`](chat-ui/README.md) | The interface in the browser, and the appliance's first-boot web setup | [docs/design/chat-ui.md](../docs/design/chat-ui.md), [docs/design/admin.md](../docs/design/admin.md) |
| [`mcp-host`](mcp-host/README.md), [`connectors`](connectors/README.md) | Placeholders for the MCP host and the official connectors, not built | [docs/design/platform.md](../docs/design/platform.md) |
