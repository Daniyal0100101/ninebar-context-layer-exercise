# Sample Input 1: Team Meeting Preparation

## Goal
Prepare context for daily standup meeting.

## Structured Data (Calendar/Trackers)
```json
{
  "meeting_schedule": [
    {"time": "09:00", "title": "Daily Standup", "attendees": ["alice", "bob", "carol"]},
    {"time": "14:00", "title": "Design Review", "attendees": ["alice", "dave"]},
    {"time": "16:00", "title": "Retrospective", "attendees": ["alice", "bob", "carol", "dave"]}
  ],
  "team_availability": {"alice": "available", "bob": "busy", "carol": "available", "dave": "available"},
  "project_deadlines": {"project_alpha": "2026-08-01", "project_beta": "2026-08-15", "project_gamma": "2026-09-01"}
}
```

## Unstructured Data (Notes/Docs)
```markdown
# Project Alpha - Architecture Decision Record

## Decision: Use PostgreSQL for primary data store

**Date:** 2026-07-15
**Status:** Accepted

### Context
Need a reliable, ACID-compliant database for Project Alpha's transactional data.
Team has PostgreSQL expertise.

### Decision
PostgreSQL 15+ for all relational data. Use Prisma ORM for type-safe access.

### Consequences
- Strong consistency guarantees
- Team familiarity reduces onboarding
- Operational overhead (backups, replication) accepted
```

## Expected Output (Internal Agent Context)
```json
{
  "room_id": "team_operations",
  "context": {
    "meeting_schedule": [...],
    "team_availability": {...},
    "project_deadlines": {...}
  },
  "gate_summary": {"total": 3, "allowed": 3, "denied": 0}
}
```

---

# Sample Input 2: User Preference Access

## Goal
Get user communication preferences for personalization.

## Structured Data (User Preferences)
```json
{
  "communication_style": "concise, technical, async-first",
  "focus_areas": ["AI agents", "multi-agent systems", "operational simulation"],
  "notification_prefs": {"email": "digest", "slack": "mentions_only", "push": "none"},
  "api_keys": {"gemini": "sk-prod-...", "github": "ghp_..."}
}
```

## Expected Output (Internal Agent - with PII approval)
```json
{
  "room_id": "user_preferences",
  "context": {
    "communication_style": "concise, technical, async-first",
    "focus_areas": ["AI agents", "multi-agent systems", "operational simulation"],
    "notification_prefs": {"email": "digest", "slack": "mentions_only", "push": "none"}
  },
  "gate_summary": {"total": 4, "allowed": 3, "denied": 1}
}
```

## Expected Output (External Agent - no PII approval)
```json
{
  "room_id": "user_preferences",
  "context": {},
  "gate_summary": {"total": 4, "allowed": 0, "denied": 4}
}
```

---

# Sample Input 3: Knowledge Base Query

## Goal
Find architecture decisions for database selection.

## Unstructured Data (Project Docs)
```markdown
# Project Alpha - Architecture Decision Record

## Decision: Use PostgreSQL for primary data store

**Date:** 2026-07-15
**Status:** Accepted

### Context
Need a reliable, ACID-compliant database for Project Alpha's transactional data.
Team has PostgreSQL expertise.

### Decision
PostgreSQL 15+ for all relational data. Use Prisma ORM for type-safe access.

### Consequences
- Strong consistency guarantees
- Team familiarity reduces onboarding
- Operational overhead (backups, replication) accepted
```

## Expected Output (Internal Agent)
```json
{
  "room_id": "knowledge_base",
  "context": {
    "project_docs_20260724_180603": "# Project Alpha - Architecture Decision Record\n\n## Decision: Use PostgreSQL for primary data store\n\n**Date:** 2026-07-15\n**Status:** Accepted\n\n### Context\nNeed a reliable, ACID-compliant database for Project Alpha's transactional data.\nTeam has PostgreSQL expertise.\n\n### Decision\nPostgreSQL 15+ for all relational data. Use Prisma ORM for type-safe access.\n\n### Consequences\n- Strong consistency guarantees\n- Team familiarity reduces onboarding\n- Operational overhead (backups, replication) accepted"
  },
  "gate_summary": {"total": 1, "allowed": 1, "denied": 0}
}
```

---

# Sample Gate Decision Outputs

## Internal Agent (with PII approvals)
| Field | Privacy | Staleness | Decision | Reason |
|-------|---------|-----------|----------|--------|
| communication_style | PII | long_term | **WARN** | PII accessed with human approval |
| focus_areas | INTERNAL | medium_term | **ALLOW** | All gates passed |
| notification_prefs | PII | long_term | **WARN** | PII accessed with human approval |
| api_keys | PROPRIETARY | evergreen | **DENY** | Proprietary requires human approval |

## External Agent (no approvals)
| Field | Privacy | Decision | Reason |
|-------|---------|----------|--------|
| communication_style | PII | **DENY** | PII requires human approval |
| focus_areas | INTERNAL | **DENY** | Internal not accessible to external agents |
| notification_prefs | PII | **DENY** | PII requires human approval |
| api_keys | PROPRIETARY | **DENY** | Proprietary requires human approval |

## Ephemeral Data (expired)
| Field | Staleness | Age | Decision | Reason |
|-------|-----------|-----|----------|--------|
| meeting_schedule | EPHEMERAL | 25h (TTL=12h) | **DENY** | Ephemeral data expired |