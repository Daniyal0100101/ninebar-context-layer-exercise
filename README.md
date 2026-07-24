# Ninebar Context Layer Exercise

A prototype implementation of a **Context Layer for Agents** — demonstrating how an agent can use both structured and unstructured data to work autonomously, with privacy/staleness boundaries and compound learning.

## Problem Statement

Design how an agent can use both structured data (trackers, records, tasks, calendar) and unstructured data (meeting notes, documents, emails, messages, PDFs, user preferences) to:
- Get the right context for autonomous decisions
- Avoid stale or private information
- Decide what it can do next
- Learn from outcomes (compound)

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                        CONTEXT LAYER                                │
├─────────────────────────────────────────────────────────────────────┤
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐              │
│  │  Structured  │  │ Unstructured │  │   User       │              │
│  │  Adapters    │  │  Adapters    │  │  Preferences │              │
│  │  (calendar,  │  │  (notes,     │  │  (privacy,   │              │
│  │   tasks,     │  │   docs,      │  │   staleness) │              │
│  │   trackers)  │  │   emails)    │  │              │              │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘              │
│         │                 │                 │                      │
│         └─────────────────┼─────────────────┘                      │
│                           ▼                                         │
│              ┌────────────────────────┐                             │
│              │   Normalization &      │                             │
│              │   Room Construction    │                             │
│              │   (Typed Schemas)      │                             │
│              └───────────┬────────────┘                             │
│                           ▼                                         │
│              ┌────────────────────────┐                             │
│              │   Privacy/Staleness    │                             │
│              │   Gates                │                             │
│              └───────────┬────────────┘                             │
│                           ▼                                         │
│              ┌────────────────────────┐                             │
│              │   Agent Decision       │                             │
│              │   Pipeline             │                             │
│              │   (Propose→Critic→     │                             │
│              │    Override→Commit)    │                             │
│              └───────────┬────────────┘                             │
│                           ▼                                         │
│              ┌────────────────────────┐                             │
│              │   Compound Logger      │                             │
│              │   (Outcomes→Learning)  │                             │
│              └────────────────────────┘                             │
└─────────────────────────────────────────────────────────────────────┘
```

## Quick Start

```bash
# Using Docker (recommended)
docker compose up --build

# Or locally
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m context_layer.demo
```

## Demo Path

1. Run the demo: `python -m context_layer.demo`
2. See sample inputs in `examples/`
3. Check outputs in `outputs/`
4. Run tests: `pytest tests/`

## Architecture Notes

### Context Representation: "Rooms"

Borrowing Ninebar's terminology: **Rooms** are typed, structured contexts that agents can trust. Each room has:
- A schema (Pydantic model) defining structure
- Source adapters that populate it
- Privacy/staleness metadata per field
- TTL and decay policies

### Privacy & Staleness Gates

Three tag-based categories:
- **PII** — personal identifiers, requires human approval for agent access
- **Proprietary** — company secrets, requires human approval
- **Ephemeral** — time-sensitive, auto-expires via TTL

### Compound Loop

Every agent action → outcome → confidence delta → room schema evolution proposal (human-approved).

## Assumptions & Limitations

- **LLM optional**: Mock mode provided for demo; real LLM integration via `GEMINI_API_KEY` or similar
- **No production deployment**: Local development only
- **Single-user context**: Multi-tenancy not implemented
- **File-based storage**: No database; JSON/Markdown files for demo

## Reviewer Instructions

1. Run `docker compose up --build` or local setup
2. Execute `python -m context_layer.demo` for the demo path
3. Check `tests/` for validation checklist
4. Read `AGENT_WORKFLOW.md` for the design session transcript
5. See `examples/` for sample inputs/outputs

## License

MIT — for evaluation purposes only.