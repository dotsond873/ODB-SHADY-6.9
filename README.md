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
- Initial automated tests

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

## Connecting models

Implement the `ModelProvider` contract in `src/shady/providers.py`, then pass provider adapters to `ModelRouter`. Credentials must come from environment variables or a secret manager. Never hard-code or commit API keys.

No commercial model provider is bundled or configured yet. The core does not pretend to be connected when it is not.

## Safety and control

- Memory is local-first and can be listed or deleted through `MemoryStore`.
- Do not save passwords, API keys, payment details, or other secrets as memories.
- Consequential and destructive actions require explicit user approval.
- Model fallback is limited to configured providers; it does not silently add services or spend money.
- Audit records are local and should be protected like other application data.

## Roadmap

1. Run and harden the current test suite.
2. Add opt-in model-provider adapters and configuration.
3. Add authenticated approval UI and secure tool sandboxing.
4. Add task planning, background jobs, and human approval workflow.
5. Add web research, project integrations, voice, and secure deployment.
6. Add backup, restore, monitoring, and emergency-stop controls.

## Project boundary

This is a clean rebuild. The original `Dotsons-AI-LAB` repository remains untouched.

## Developer

Dotson Labs
