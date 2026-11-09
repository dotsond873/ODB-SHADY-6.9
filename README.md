# ODB SHADY 6.9
## Dotson's Super AI

ODB SHADY 6.9 is an independent, modular personal AI assistant project by Dotson Labs.

## Current foundation

- Shady's stable identity and behavioral principles
- Provider-neutral model adapter contract
- Multi-provider routing with preferred-model selection and ordered fallback
- Local SQLite memory and session-scoped conversation history
- Relevant-memory retrieval for conversations
- Allowlisted tool registry with argument validation
- Risk-classified tool execution
- One-time, action-specific approval requests for non-read-only tools
- Local audit trail that records action metadata without raw arguments
- Model-assisted task-plan proposals with strict registered-tool validation\n- Persistent task plans with ordered steps and SQLite-backed progress
- Resumable step-by-step task coordinator
- Human approval pauses for every non-read-only task action
- Explicit task cancellation and failure tracking
- Automated task-orchestration tests

## Quick start

Requires Python 3.11 or newer.

```bash
python -m venv .venv
```

Activate the virtual environment, then install the project and test dependencies:

```bash
pip install -e ".[dev]"
pytest
```

The SQLite database is created locally at `data/shady.sqlite3` by default. Set `SHADY_DB_PATH` to choose another path. Keep database files and credentials out of Git.

## Tool execution model

Application code must explicitly register each available tool in `ToolRegistry`. The model does not get arbitrary shell, filesystem, network, or database access merely by asking for it.

- Read-only tools can execute after argument validation.
- Reversible, consequential, and destructive tools require a matching approval request.
- Approval requests are action-specific and can be consumed only once.
- Unknown tools and undeclared arguments are rejected.
- The audit log records action name, risk, status, and safe metadata—not raw tool arguments.

The application must present the approval request to the user and call `ApprovalStore.approve` only after receiving the user's explicit confirmation. A future user interface must authenticate that approval step; the current library is the enforcement foundation, not a complete approval UI.

## Task planning and execution

Trusted application code can create a task from an ordered list of registered tool steps using `TaskCoordinator`. The plan is validated against the allowlisted `ToolRegistry` before it is saved. Task and step state is persisted in SQLite, so queued, running, waiting-approval, completed, failed, and cancelled work can be inspected after a restart.

Call `run_next(task_id)` to advance one step. Read-only steps execute after validation. Any other risk class pauses and creates an action-specific approval request. An authenticated application interface must obtain explicit confirmation before calling `approve_and_run(..., user_confirmed=True)`. The coordinator never approves on the model's behalf, and a step executes only after the one-time approval is consumed by `ToolExecutor`. A denied approval marks the step failed; cancellation also requires explicit confirmation.

Plans store their JSON arguments in the local SQLite database. Do not include passwords, API keys, payment data, or other secrets. Protect the database file. This is a deterministic task runner, not yet an LLM task planner or background worker: a future planner may propose plans, but the application must validate them and keep the approval boundary.

## Model-assisted planning

`TaskPlanner` can ask any configured `ModelRouter` provider to propose a task plan. It supplies the model with the registered tool catalog, then strictly parses the returned JSON and rejects unknown tools, undeclared arguments, malformed steps, and plans outside the configured step limit. The planner only proposes; it does not execute tools or grant approvals. A validated `TaskPlan` can be passed to `TaskCoordinator.create(title, steps)` for persistence and controlled execution.

A model provider must be configured before model-assisted planning can run. No provider or API credentials are bundled in this repository. Until a runtime key and model are configured, plans can still be created directly in trusted application code.

## Connecting models

The repository includes an OpenAI-compatible chat-completions adapter in `src/shady/openai_compatible.py`. It uses Python's standard library and can connect to an OpenAI API endpoint or another endpoint implementing the same chat-completions request/response shape.

Set these private environment variables in the deployment/runtime environment:

- `SHADY_API_KEY` — required secret API key
- `SHADY_MODEL` — required model identifier supported by your endpoint
- `SHADY_API_BASE_URL` — optional; defaults to `https://api.openai.com/v1`
- `SHADY_PROVIDER_NAME` — optional display name; defaults to `primary`
- `SHADY_TIMEOUT_SECONDS` — optional request timeout; defaults to 45

Copy `.env.example` as a reference only. The application does not automatically load a local `.env` file. Configure secrets in your shell or hosting platform's private environment settings. Never commit a real API key.

Example application setup:

```python
from shady import ConversationService, MemoryStore, build_router_from_env

router = build_router_from_env()
memory = MemoryStore()
conversation = ConversationService(router=router, memory=memory)
```

The adapter sends requests only when the application calls it. Model usage may incur provider charges; costs, limits, and billing are controlled by the selected provider. No API key is included in this repository.

## Safety and control

- Memory is local-first and can be listed or deleted through `MemoryStore`.
- Do not save passwords, API keys, payment details, or other secrets as memories.
- Consequential and destructive actions require explicit user approval.
- Model fallback is limited to configured providers; it does not silently add services or spend money.
- Audit records are local and should be protected like other application data.

## Roadmap

1. Run and harden the current test suite.
2. Configure the included model adapter with a provider key and supported model.
3. Add authenticated approval UI and secure tool sandboxing.
4. Add a model-assisted planner, authenticated approval UI, and background worker.
5. Add web research, project integrations, voice, and secure deployment.
6. Add backup, restore, monitoring, and emergency-stop controls.

## Project boundary

This is a clean rebuild. The original `Dotsons-AI-LAB` repository remains untouched.

## Developer

Dotson Labs
