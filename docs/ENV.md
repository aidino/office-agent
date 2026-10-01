# Environment Variables

All environment variables used across the `office-agent` repository,
extracted from `.env.example`, `lifecycle.toml`, and source code.

## Office Agent Runtime

<!-- GENERATED:env-agent — do not edit manually -->

| Variable | Required | Description | Default | Aliases |
|---|---|---|---|---|
| `BUB_MODEL` | **Yes** | Model ID used by the DeepAgents binding | — | `AGENTSEEK_MODEL`, `DEEPAGENTS_MODEL` |
| `BUB_API_KEY` | **Yes** | Provider API key (DeepSeek) | — | `AGENTSEEK_API_KEY`, `OPENAI_API_KEY` |
| `BUB_API_BASE` | No | OpenAI-compatible provider base URL | `https://api.deepseek.com` | `AGENTSEEK_API_BASE`, `OPENAI_API_BASE`, `OPENAI_BASE_URL` |
| `BUB_LANGCHAIN_SPEC` | **Yes** | Import path for the LangChain RunnableSpec | `office_agent.binding:build_spec` | `AGENTSEEK_LANGCHAIN_SPEC` |
| `BUB_AG_UI_PORT` | **Yes** | AG-UI gateway bind port | `18088` | `AGENTSEEK_AG_UI_PORT` |
| `BUB_STREAM_OUTPUT` | No | Enable SSE streaming | `true` | — |
| `OFFICE_AGENT_WORKSPACE` | No | Root directory the office tools may read/write | Working directory | — |

<!-- /GENERATED:env-agent -->

### Notes

- `BUB_API_KEY` must be a valid DeepSeek API key from
  [platform.deepseek.com/api_keys](https://platform.deepseek.com/api_keys).
- `OFFICE_AGENT_WORKSPACE` confines all file tool operations. Every tool
  resolves its path argument inside this root and rejects escapes.
- During benchmark runs, the harness sets `OFFICE_AGENT_WORKSPACE` per-task
  via the AG-UI payload's `state._runtime_workspace` field.

## Benchmark Harness — LLM Judge

<!-- GENERATED:env-judge — do not edit manually -->

| Variable | Required | Description | Default | Fallback |
|---|---|---|---|---|
| `JUDGE_MODEL` | For FORTE | LLM judge model name | `deepseek-chat` | — |
| `JUDGE_BASE_URL` | For FORTE | Judge API base URL | `https://api.deepseek.com` | — |
| `JUDGE_API_KEY` | For FORTE | Judge API key | — | `BUB_API_KEY` |

<!-- /GENERATED:env-judge -->

### Notes

- These variables are only needed when running suites that use LLM-as-judge
  evaluation (currently FORTE).
- `JUDGE_API_KEY` falls back to `BUB_API_KEY` if unset, so a single
  DeepSeek key covers both the agent and the judge.
- The judge uses the OpenAI-compatible `/chat/completions` endpoint with
  `temperature=0.0` for deterministic grading.

## Third-Party / Optional

<!-- GENERATED:env-optional — do not edit manually -->

| Variable | Description | Used By |
|---|---|---|
| `OPENROUTER_API_KEY` | OpenRouter API key for JEV judge (future) | `judges/jev.py` (not yet implemented) |

<!-- /GENERATED:env-optional -->

## Setup

```bash
# Copy the template and fill in your API key
cd office_agent
cp .env.example .env
$EDITOR .env
```

The `.env` file is gitignored. Never commit real API keys.
