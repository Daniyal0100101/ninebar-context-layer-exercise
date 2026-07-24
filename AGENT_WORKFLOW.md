# Agent Workflow Transcript

This document captures the design sessions, agent-tool interactions, and human judgments that shaped this prototype.

## Session 1: Privacy/Staleness Boundary Design

**Date:** 2026-07-24
**Tool:** [To be filled during actual session]
**Participants:** Human (architect) + Agent (implementation partner)

### Problem Framing

The context layer must enforce privacy and staleness boundaries *before* context reaches the agent decision pipeline. This is the "Know" phase of Ninebar's "fl of Ninebar's Know→Build→Compound.

**Key requirements from exercise:**
- Structured + unstructured data
- Avoid stale information
- Avoid private information (PII, proprietary)
- Decide what agent can do next

### Design Alternatives Considered

| Approach | Pros | Cons | Decision |
|----------|------|------|----------|
| **Tag-based gates (chosen)** | Explicit, auditable, composable | Requires tagging at ingestion | ✅ Selected |
| Content-based classification (LLM) | Automatic | Non-deterministic, hard to audit | ❌ Rejected |
| Path-based isolation (separate stores) | Simple | Doesn't handle mixed-content documents | ❌ Rejected |
| Time-only decay | Simple | Doesn't distinguish sensitivity types | ❌ Rejected |

### Tag Taxonomy (Final)

```
privacy_tags:
  - pii: "Personal identifiers (emails, phones, names in private contexts)"
  - proprietary: "Company secrets, unreleased features, financials"
  - internal: "Internal-only, not for external agents"
  - public: "Safe for any agent"

staleness_tags:
  - ephemeral: "TTL < 24h (meeting notes, transient state)"
  - short_term: "TTL 1-7 days (task status, sprint data)"
  - medium_term: "TTL 1-30 days (project docs, decisions)"
  - long_term: "TTL 30-365 days (architecture, policies)"
  - evergreen: "No TTL (core schemas, identity)"
```

### Gate Logic (Final)

```python
def can_agent_access(field: ContextField, agent_context: AgentContext) -> GateDecision:
    # Privacy gate
    if field.privacy_tag in (PII, PROPRIETARY):
        if not agent_context.human_approval_granted(field.id):
            return GateDecision.DENY("requires_human_approval")
    
    if field.privacy_tag == INTERNAL and agent_context.is_external:
        return GateDecision.DENY("internal_only")
    
    # Staleness gate
    if field.is_stale():
        if field.staleness_tag == EPHEMERAL:
            return GateDecision.DENY("expired")
        else:
            return GateDecision.WARN("stale_data")
    
    return GateDecision.ALLOW
```

### Human Judgment Applied

1. **Explicit > Implicit**: Tags are declared at ingestion, not inferred. This makes boundaries auditable — Ninebar's "trust > capability" philosophy.
2. **Human-in-the-loop for high-sensitivity**: PII and proprietary *always* require approval, even if stale. No auto-expiry override.
3. **Warn don't block for staleness (non-ephemeral)**: Stale project docs are still useful context; flag them, don't hide them.
4. **Agent context matters**: Internal vs external agent changes gate outcomes — an internal agent sees `internal` tags, external doesn't.

### AI Tool Usage

- **Used for**: Boilerplate gate logic, Pydantic models, test fixtures
- **Human judgment**: Tag taxonomy, gate precedence, "warn vs deny" philosophy, compound loop design
- **Changed manually**: Gate decision enum (added WARN), tag definitions, approval flow

---

## Session 2: [To be filled]

## Session 3: [To be filled]

---

## Audit Guide for Reviewers

1. **Start here**: Read this file to understand design rationale
2. **Check implementation**: `src/context_layer/gates/` matches the gate logic above
3. **Verify tags**: `schemas/room.py` defines the tag enums
4. **Run tests**: `pytest tests/test_gates.py` validates gate behavior
5. **Demo path**: `python -m context_layer.demo` shows gates in action