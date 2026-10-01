# Office Agent

A backend-only office agent: a DeepAgents runnable exposed through an AG-UI
gateway, scaffolded with `agentseek create deepagents` and adapted for
everyday office work on documents, spreadsheets, and presentations. It is
intentionally minimal and does not include a frontend.

- Runtime model: DeepSeek `deepseek-flash`, resolved as `openai:deepseek-flash`
  through DeepSeek's OpenAI-compatible endpoint (see Environment below).
- System prompt: an office assistant persona that must read files through
  tools before commenting on them and answers in the user's language.
- Tools (all paths confined to the agent workspace, see Environment):
  - `read_text_file(path)` — plain-text files (.txt, .csv, .md).
  - `read_pdf_file(path)` — PDF text extraction, page by page.
  - `read_spreadsheet(path)` — .xlsx workbooks rendered as Markdown tables.
  - `write_spreadsheet(path, sheet_name, rows)` — create .xlsx files.
  - `write_presentation(path, title, slides)` — create .pptx decks.

The binding export is:

```text
office_agent.binding:build_spec
```

## Quickstart

```bash
cp .env.example .env
$EDITOR .env

uvx agentseek info
uvx agentseek doctor
uvx agentseek task --list
uvx agentseek task sync

uvx agentseek dev
```

The gateway is declared in `.agentseek/lifecycle.toml` and defaults to
`http://127.0.0.1:18088/agent`. AgentSeek is used as
the external lifecycle tool; the generated runtime is the project dependency
set in `pyproject.toml`.

## Environment

Copy `.env.example` to `.env` before running lifecycle checks. The generated
settings read `BUB_MODEL`, `BUB_API_KEY`, and optional `BUB_API_BASE`, with
`AGENTSEEK_*` and OpenAI-compatible aliases accepted where noted in the file.
The template defaults to the DeepSeek `deepseek-flash` model via DeepSeek's
OpenAI-compatible endpoint, so set `BUB_API_KEY` to a DeepSeek API key.

`OFFICE_AGENT_WORKSPACE` (optional) sets the absolute root directory the
office tools may read from and write to. It defaults to the working
directory of the gateway process. Every tool resolves its path argument
inside this root and rejects any path that escapes it.

## Testing

### Static checks

```bash
uvx agentseek info     # env vars and lifecycle wiring
uvx agentseek doctor   # lifecycle spec, uv, paths, env checks
```

### Test suite

```bash
uv run pytest -q
```

- `tests/test_binding.py` — the binding registers the `openai`
  ProviderProfile, passes the configured model and the office tools to
  `create_deep_agent()`, and runs the real DeepAgents stack against a local
  stub Chat Completions server (no network or API key required).
- `tests/test_tools.py` — workspace confinement (inside allowed, escapes
  rejected for both reads and writes) and per-tool behavior: text read,
  PDF page extraction, spreadsheet roundtrip, presentation writing.

### Manual end-to-end

Start the gateway in the foreground with `uvx agentseek dev`, then from
another terminal:

```bash
# Health check
curl -sS http://127.0.0.1:18088/agent/health

# One agent turn: streams SSE events, one real deepseek-flash call
curl -sS -N -X POST http://127.0.0.1:18088/agent \
  -H 'Content-Type: application/json' \
  -d '{"threadId":"t1","runId":"r1","messages":[{"id":"m1","role":"user","content":"xin chào"}],"state":null,"tools":[],"context":[],"forwardedProps":{}}'
```

Expect an SSE stream of `RUN_STARTED` → `TEXT_MESSAGE_START` →
`TEXT_MESSAGE_CONTENT` → `TEXT_MESSAGE_END` → `RUN_FINISHED`, with the reply
language matching the question. To exercise the office tools, put a file in
the workspace (for example `notes.txt`) and ask the agent to read it. Asking
the model to identify itself is not a reliable check — LLMs frequently
hallucinate their identity; verify the model via the `model` field of a
direct DeepSeek API response instead.

## DeepAgents profiles

DeepAgents profiles are named configuration layers that DeepAgents applies when
it builds an agent. They let an application customize a provider or the agent
harness without replacing `create_deep_agent()` or copying its internal
defaults. A profile must be registered before the agent is built, and
DeepAgents selects it from the provider or model specification being resolved.

There are two different profile scopes:

- `HarnessProfile` changes agent runtime behavior, such as prompts, middleware,
  tool visibility, and default subagent settings. It answers: "how should this
  agent behave?"
- `ProviderProfile` changes model construction and initialization arguments
  while a `provider:model` string is resolved into a chat model. It answers:
  "how should this provider's model be initialized?"

This template uses a `ProviderProfile`, not a `HarnessProfile`, because the
model-construction option `use_responses_api=False` must be applied while
DeepAgents resolves an `openai:<model>` string into a chat model.

For example, the generated binding registers:

```python
register_provider_profile(
    "openai",
    ProviderProfile(init_kwargs={"use_responses_api": False}),
)
```

This makes `openai:<model>` specifications use the Chat Completions API. It
is useful for OpenAI-compatible endpoints that support Chat Completions but do
not implement the OpenAI Responses API. This is a short-term compatibility
workaround: because the profile is registered for the `openai` provider, every
`openai:<model>` specification in this generated binding is forced to use Chat
Completions, including models that may also support the Responses API.

Learn more in the official [DeepAgents profiles documentation](https://docs.langchain.com/oss/python/deepagents/profiles),
[model documentation](https://docs.langchain.com/oss/python/deepagents/models),
and [DeepAgents overview](https://docs.langchain.com/oss/python/deepagents/overview).

## Files

| File | Purpose |
| --- | --- |
| `.agentseek/lifecycle.toml` | Declares AgentSeek `info`, `doctor`, `dev`, and `task` behavior. |
| `.env.example` | Documents runtime model, provider, LangChain binding, AG-UI port, and workspace variables. |
| `src/office_agent/binding.py` | Builds the DeepAgents runnable and exports `build_spec()`. |
| `src/office_agent/tools.py` | Office file tools with workspace confinement. |
| `src/office_agent/settings.py` | Reads env vars; bridges `AGENTSEEK_*` into `OPENAI_*` when needed. |
| `requirements.txt` | Extra Python dependencies. |
| `tests/test_binding.py` | Unit and stub-server integration tests for the binding. |
| `tests/test_tools.py` | Workspace confinement and tool behavior tests. |

Author: Dino
