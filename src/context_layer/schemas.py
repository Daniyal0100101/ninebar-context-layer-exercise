"""
Core schemas for the Context Layer.

Defines the data models for context fields, rooms, privacy/staleness tags,
agent context, and gate decisions.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Union
from pydantic import BaseModel, Field, field_validator, model_validator


class PrivacyTag(str, Enum):
    """Privacy classification for context fields."""
    PUBLIC = "public"           # Safe for any agent
    INTERNAL = "internal"       # Internal-only, not for external agents
    PII = "pii"                 # Personal identifiers (requires human approval)
    PROPRIETARY = "proprietary" # Company secrets (requires human approval)


class StalenessTag(str, Enum):
    """Staleness classification based on TTL."""
    EPHEMERAL = "ephemeral"         # TTL < 24h
    SHORT_TERM = "short_term"       # TTL 1-7 days
    MEDIUM_TERM = "medium_term"     # TTL 1-30 days
    LONG_TERM = "long_term"         # TTL 30-365 days
    EVERGREEN = "evergreen"         # No TTL


class GateDecision(str, Enum):
    """Result of a gate check."""
    ALLOW = "allow"
    WARN = "warn"       # Allow but flag
    DENY = "deny"       # Block access

    @property
    def is_allowed(self) -> bool:
        return self in (GateDecision.ALLOW, GateDecision.WARN)


class GateResult(BaseModel):
    """Result of a gate evaluation."""
    decision: GateDecision
    reason: str
    field_id: str
    tag: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ContextField(BaseModel):
    """A single piece of context with privacy and staleness metadata."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    name: str
    value: Any
    source_id: str
    privacy_tag: PrivacyTag = PrivacyTag.INTERNAL
    staleness_tag: StalenessTag = StalenessTag.MEDIUM_TERM
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    ttl_hours: Optional[int] = Field(default=None)
    tags: Set[str] = Field(default_factory=set)
    metadata: Dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def set_default_ttl(self) -> "ContextField":
        if self.ttl_hours is None:
            if self.staleness_tag == StalenessTag.EPHEMERAL:
                self.ttl_hours = 12
            elif self.staleness_tag == StalenessTag.SHORT_TERM:
                self.ttl_hours = 72
            elif self.staleness_tag == StalenessTag.MEDIUM_TERM:
                self.ttl_hours = 720  # 30 days
            elif self.staleness_tag == StalenessTag.LONG_TERM:
                self.ttl_hours = 8760  # 365 days
            # EVERGREEN stays None
        return self

    def is_stale(self) -> bool:
        """Check if the field has exceeded its TTL."""
        if self.ttl_hours is None:
            return False
        expiry = self.updated_at + timedelta(hours=self.ttl_hours)
        return datetime.utcnow() > expiry

    def age_hours(self) -> float:
        """Age of the field in hours."""
        return (datetime.utcnow() - self.updated_at).total_seconds() / 3600


class ContextRoom(BaseModel):
    """A named collection of context fields (a 'room' in Ninebar terminology)."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    name: str
    description: str = ""
    fields: Dict[str, ContextField] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    metadata: Dict[str, Any] = Field(default_factory=dict)

    def add_field(self, field: ContextField) -> None:
        self.fields[field.id] = field
        self.updated_at = datetime.utcnow()

    def get_field(self, field_id: str) -> Optional[ContextField]:
        return self.fields.get(field_id)

    def remove_field(self, field_id: str) -> bool:
        if field_id in self.fields:
            del self.fields[field_id]
            self.updated_at = datetime.utcnow()
            return True
        return False

    def fields_by_tag(self, privacy_tag: Optional[PrivacyTag] = None,
                      staleness_tag: Optional[StalenessTag] = None) -> List[ContextField]:
        result = []
        for field in self.fields.values():
            if privacy_tag and field.privacy_tag != privacy_tag:
                continue
            if staleness_tag and field.staleness_tag != staleness_tag:
                continue
            result.append(field)
        return result


class AgentContext(BaseModel):
    """Context about the agent requesting access."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    name: str
    is_external: bool = False
    permissions: Set[str] = Field(default_factory=set)
    human_approvals: Set[str] = Field(default_factory=set)  # field_ids approved
    metadata: Dict[str, Any] = Field(default_factory=dict)

    def has_approval(self, field_id: str) -> bool:
        return field_id in self.human_approvals

    def grant_approval(self, field_id: str) -> None:
        self.human_approvals.add(field_id)

    def revoke_approval(self, field_id: str) -> None:
        self.human_approvals.discard(field_id)


class SourceBase(BaseModel):
    """Base class for context sources."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    name: str
    source_type: str
    room_id: str
    enabled: bool = True
    metadata: Dict[str, Any] = Field(default_factory=dict)


class StructuredSource(SourceBase):
    """Structured data source (trackers, records, tasks, calendar)."""
    source_type: str = "structured"
    schema: Dict[str, Any] = Field(default_factory=dict)  # Expected field definitions
    sync_interval_seconds: int = 300  # 5 minutes default


class UnstructuredSource(SourceBase):
    """Unstructured data source (notes, docs, emails, messages, PDFs)."""
    source_type: str = "unstructured"
    content_types: List[str] = Field(default_factory=list)  # e.g., ["markdown", "pdf", "email"]
    processing_hints: Dict[str, Any] = Field(default_factory=dict)


class SampleInput(BaseModel):
    """Sample input for validation/demo."""
    name: str
    description: str
    structured_data: Optional[Dict[str, Any]] = None
    unstructured_text: Optional[str] = None
    expected_fields: List[str] = Field(default_factory=list)


class SampleOutput(BaseModel):
    """Sample output for validation/demo."""
    name: str
    description: str
    room_name: str
    expected_fields: List[str] = Field(default_factory=list)
    gate_results: List[GateResult] = Field(default_factory=list)