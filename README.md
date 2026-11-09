# ODB SHADY 6.9
## Dotson's Super AI

ODB SHADY 6.9 is an independent, modular personal AI assistant project by Dotson Labs.

## Mission

Build one central AI capable of coordinating multiple model providers, retaining user-controlled memory, researching information, developing software, managing authorized projects, and performing approved tasks safely.

## Current foundation

- Shady's stable identity and behavioral principles
- Provider-neutral model adapter contract
- Multi-provider routing with ordered fallback and explicit preference
- Local SQLite memory and conversation history
- Bounded conversation context and relevant-memory retrieval
- Default-deny approval gate for consequential and destructive actions
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

The memory database is created locally at `data/shady.sqlite3` by default. Set `SHADY_DB_PATH` to choose another path. Keep database files and credentials out of Git.

## Connecting models

Implement the `ModelProvider` contract in `src/shady/providers.py`, then pass one or more provider adapters to `ModelRouter`. Provider credentials must be supplied through environment variables or a secret manager; never hard-code or commit API keys.

No commercial model provider is bundled or configured yet. The core deliberately does not pretend to be connected when it is not.

## Safety and control

- Read-only actions may proceed without approval.
- Reversible, consequential, and destructive actions require explicit approval.
- Memory is local-first and can be listed or deleted through `MemoryStore`.
- Do not save passwords, API keys, payment information, or other secrets as memories.
- Model fallback is limited to the configured providers; it does not silently add services or spend money.

## Roadmap

1. Complete and test the core memory/conversation layer.
2. Add opt-in model-provider adapters and configuration.
3. Add tool registry with permission checks and auditable execution.
4. Add task planning, background jobs, and human approval workflow.
5. Add web research, project integrations, voice, and secure deployment.
6. Add backup, restore, monitoring, and emergency-stop controls.

## Design principles

- Independent, modular, expandable architecture
- Privacy and security first
- Human oversight for consequential actions
- Transparent decision-making and verifiable execution
- No unnecessary recurring platform dependency

## Project boundary

This is a clean rebuild. The original `Dotsons-AI-LAB` repository remains untouched.

## Developer

Dotson Labs
