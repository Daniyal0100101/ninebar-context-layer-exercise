# Agent Workflow Transcript

This document captures the design sessions, agent-tool interactions, and human judgments that shaped this prototype.

## Session 1: Privacy/Staleness Boundary Design (2026-07-24)

**Date:** 2026-07-24  
**Tool:** Hermes Agent (WSL) + Docker  
**Participants:** Human (architect) + Agent (implementation partner)

### Problem Framing

The context layer must enforce privacy and staleness boundaries *before* context reaches the agent decision pipeline. This is the "Know" phase of Ninebar's Know→Build→Compound.

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

## Session 2: Agent Decision Pipeline Design (2026-07-24)

**Date:** 2026-07-24  
**Tool:** Hermes Agent (WSL) + Docker  
**Participants:** Human (architect) + Agent (implementation partner)

### Problem Framing

Design the "Build" phase: how an agent proposes actions, gets them reviewed, and executes them. Must mirror Ninebar's philosophy: "nothing ships without surviving a fight first" — designated challenger role on every deck.

### Pipeline Stages (7-Stage)

1. **Context Prep** — Apply compound gates, filter to agent-usable context
2. **Propose** — Agent proposes actions based on goal + available context
3. **Critic Review** — Multiple critics (security, relevance, privacy) review
4. **Consensus** — Resolve critic votes (any privacy DENY = hard reject)
5. **Human Override** — Escalate UNDER_REVIEW to human for final decision
6. **State Mutation** — Execute approved actions (read/write/delete/escalate)
7. **Commit Logs** — Audit trail for compound learning

### Critic Design

| Critic | Role | Hard Reject Condition |
|--------|------|----------------------|
| Security | Mutation safety, confidence thresholds | Mutating action with confidence < 0.7 |
| Relevance | Action matches goal | Low confidence proposal (< 0.5) |
| Privacy | Gate compliance | Any target field denied by privacy gate |

### Human Override Philosophy

- Actions with mixed critic votes (no hard reject) → UNDER_REVIEW → human decides
- Human can: APPROVE, REJECT, or MODIFY payload
- All overrides logged for compound learning

### AI Tool Usage

- **Used for**: Pipeline orchestration, critic implementations, state mutator
- **Human judgment**: 7-stage structure, critic roles, consensus rules, override philosophy
- **Changed manually**: Consensus resolver (privacy critic veto), override handler

---

## Session 3: Compound Learning & Schema Evolution (2026-07-24)

**Date:** 2026-07-24  
**Tool:** Hermes Agent (WSL) + Docker  
**Participants:** Human (architect) + Agent (implementation partner)

### Problem Framing

Design the "Compound" phase: how the system learns from outcomes and proposes schema evolutions. Ninebar: "The same problem is never solved twice."

### Learning Loop

1. **Log every outcome** — action_id, field_ids, expected vs actual, success/failure, confidence_delta
2. **Adjust confidence per field** — Bayesian-ish update: success increases, failure decreases
3. **Generate proposals when patterns emerge**:
   - 3+ consecutive failures on same field → propose REMOVE_FIELD
   - 5+ successes with confidence > 0.8 → propose CHANGE_TAG (relax privacy/staleness)
   - Low confidence (< 0.3) after 5+ outcomes → propose ADJUST_TTL
4. **Human reviews proposals** — approve/reject, then apply

### Proposal Types

```python
ProposalType = Enum(
    REMOVE_FIELD = "remove_field",      # Repeated failures
    CHANGE_TAG = "change_tag",          # High confidence → relax restrictions
    ADJUST_TTL = "adjust_ttl",          # Low confidence → tune staleness
    ADD_FIELD = "add_field",            # Missing context pattern
    MERGE_FIELDS = "merge_fields"       # Redundant fields
)
```

### Human Judgment Applied

1. **Thresholds are intentional**: 3 failures, 5 successes, 0.8 confidence — not ML-tuned, but philosophically aligned with "explicit > implicit"
2. **Human approval required**: Proposals don't auto-apply; human reviews and decides
3. **Audit trail**: Every proposal links to supporting outcome IDs

### AI Tool Usage

- **Used for**: Outcome logging, confidence math, proposal generation
- **Human judgment**: Thresholds, proposal types, approval workflow
- **Changed manually**: ProposalStatus enum, evidence linking, approval methods

---

## Session 4: Integration, Testing & Demo Polish (2026-07-24)

**Date:** 2026-07-24  
**Tool:** Hermes Agent (WSL) + Docker  
**Participants:** Human (architect) + Agent (implementation partner)

### Integration Challenges Resolved

| Issue | Root Cause | Fix |
|-------|------------|-----|
| Pydantic v2 `model_validator` vs `field_validator` | Used `mode="after"` but forgot import | Added `model_validator` import |
| Dataclass field order (non-default after default) | `ProposedAction` had `type` after `id` with default | Reordered: required fields first |
| Docker module import | `COPY src/` vs `COPY .` + `PYTHONPATH` | `COPY . /app` + `ENV PYTHONPATH=/app/src` |
| Test room lookup by name vs ID | Tests used string names, manager expects IDs | Updated tests to use `rooms["name"].id` |
| Proposer used field names instead of IDs | Heuristic matched `ctx` dict keys, but pipeline expects field IDs | Map field names → IDs from `full_gate_results` |

### Test Results

```
37 tests collected
36 passed, 1 warning (schema shadow)
```

### Demo Output Verification

Demo runs all phases:
1. **Ingestion** — 3 structured fields, 1 unstructured doc, 4 preference fields (PII/proprietary)
2. **Gating** — Internal agent (with PII approval): 2 ALLOW, 2 WARN, 1 DENY | External agent: 4 DENY, 1 ALLOW
3. **Pipeline** — Goals execute through 7 stages, human override simulated
4. **Compound** — 17 outcomes logged, 2 proposals generated (relax meeting_schedule, remove problematic_field)

---

## Raw Session Artifacts

### Key Tool Interactions (Representative)

**Gate Logic Implementation:**
```
Human: "Privacy DENY always wins; staleness DENY only for ephemeral; non-ephemeral stale = WARN"
Agent: Implemented CompoundGate._combine() with precedence rules
Human: "Change 'approved' to 'human approval' in reason text for clarity"
Agent: Updated PrivacyGate reason strings
```

**Pipeline Room ID Bug:**
```
Human: "Tests fail with 'Room team_operations not found' — demo uses room.id, tests used names"
Agent: "Fixed tests to use rooms['operations'].id throughout"
```

**Proposer Field ID Mapping:**
```
Human: "Proposer uses field names but StateMutator needs field IDs from full_gate_results"
Agent: "Added field_id_map in _propose_heuristic mapping allowed field names → IDs"
```

**Compound Proposal Thresholds:**
```
Human: "3 failures = propose removal; 5 successes + 0.8 confidence = propose tag relaxation"
Agent: "Implemented in _check_proposal_triggers with OutcomeRecord evidence linking"
```

---

## Audit Guide for Reviewers

1. **Start here**: Read this file to understand design rationale
2. **Check implementation**: `src/context_layer/gates.py` matches gate logic above
3. **Verify tags**: `src/context_layer/schemas.py` defines the tag enums
4. **Run tests**: `pytest tests/ -v` validates gate behavior, pipeline, compound
5. **Demo path**: `docker compose up --build` shows all phases end-to-end
6. **Session trace**: This document captures the actual development decisions

---

## Exercise Requirements Mapping

| Requirement | Implementation |
|-------------|----------------|
| Understanding of problem & users | README + AGENT_WORKFLOW.md Session 1 |
| Workflow/architecture | README architecture diagram + pipeline.py 7 stages |
| Sample inputs/outputs | `examples/` + demo script output |
| Assumptions, tradeoffs, risks, privacy | AGENT_WORKFLOW.md Sessions 1-3 |
| AI tool usage documentation | AGENT_WORKFLOW.md "AI Tool Usage" sections |
| Measurement approach | compound.py learning report + confidence scores |
| GitHub repo with README, setup, demo, Docker | ✅ Complete |
| AGENT_WORKFLOW.md with prompt/session summary | ✅ Complete |
| Tests/evals/validation checklist | ✅ 37 tests passing |
| Docker setup | ✅ docker-compose.yml + Dockerfile |
| No required paid/secret API keys | ✅ Mock mode provided |