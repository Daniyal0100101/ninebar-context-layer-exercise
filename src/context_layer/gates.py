"""
Gate implementations for the Context Layer.

Implements privacy gates, staleness gates, and the compound gate
that combines them according to Ninebar's philosophy.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional
from context_layer.schemas import (
    ContextField,
    AgentContext,
    GateDecision,
    GateResult,
    PrivacyTag,
    StalenessTag,
)


class PrivacyGate:
    """
    Privacy gate enforcing Ninebar's "trust > capability" philosophy.

    Explicit tags at ingestion time > implicit classification.
    Human approval required for PII and proprietary data.
    Internal vs external agent context matters.
    """

    # Tags that always require human approval
    APPROVAL_REQUIRED_TAGS = {PrivacyTag.PII, PrivacyTag.PROPRIETARY}

    # Tags that external agents cannot access
    INTERNAL_ONLY_TAGS = {PrivacyTag.INTERNAL, PrivacyTag.PII, PrivacyTag.PROPRIETARY}

    def evaluate(self, field: ContextField, agent: AgentContext) -> GateResult:
        """Evaluate a single field against privacy gates."""
        # PII and Proprietary always require explicit human approval
        if field.privacy_tag in self.APPROVAL_REQUIRED_TAGS:
            if not agent.has_approval(field.id):
                return GateResult(
                    decision=GateDecision.DENY,
                    reason=f"{field.privacy_tag.value} requires human approval",
                    field_id=field.id,
                    tag=field.privacy_tag.value,
                    metadata={"required_approval": True, "agent_external": agent.is_external},
                )
            # Has approval - allow but warn
            return GateResult(
                decision=GateDecision.WARN,
                reason=f"{field.privacy_tag.value} accessed with human approval",
                field_id=field.id,
                tag=field.privacy_tag.value,
                metadata={"approved": True},
            )

        # Internal-only check for external agents
        if field.privacy_tag in self.INTERNAL_ONLY_TAGS and agent.is_external:
            return GateResult(
                decision=GateDecision.DENY,
                reason=f"{field.privacy_tag.value} not accessible to external agents",
                field_id=field.id,
                tag=field.privacy_tag.value,
                metadata={"agent_external": True},
            )

        # Public and approved internal - allow
        return GateResult(
            decision=GateDecision.ALLOW,
            reason=f"Privacy gate passed: {field.privacy_tag.value}",
            field_id=field.id,
            tag=field.privacy_tag.value,
        )

    def evaluate_batch(self, fields: List[ContextField], agent: AgentContext) -> List[GateResult]:
        """Evaluate multiple fields."""
        return [self.evaluate(field, agent) for field in fields]


class StalenessGate:
    """
    Staleness gate with Ninebar's philosophy: warn don't block (except ephemeral).

    Ephemeral data expires hard. Other staleness tags warn but allow access
    because stale project context is still useful.
    """

    def evaluate(self, field: ContextField, agent: AgentContext) -> GateResult:
        """Evaluate a single field against staleness gates."""
        if not field.is_stale():
            return GateResult(
                decision=GateDecision.ALLOW,
                reason=f"Fresh: {field.age_hours():.1f}h old",
                field_id=field.id,
                tag=field.staleness_tag.value,
                metadata={"age_hours": field.age_hours(), "stale": False},
            )

        # Field is stale - apply policy based on staleness tag
        if field.staleness_tag == StalenessTag.EPHEMERAL:
            return GateResult(
                decision=GateDecision.DENY,
                reason=f"Ephemeral data expired: {field.age_hours():.1f}h old (TTL: {field.ttl_hours}h)",
                field_id=field.id,
                tag=field.staleness_tag.value,
                metadata={"age_hours": field.age_hours(), "stale": True, "expired": True},
            )

        # For non-ephemeral: warn but allow
        return GateResult(
            decision=GateDecision.WARN,
            reason=f"Stale {field.staleness_tag.value}: {field.age_hours():.1f}h old (TTL: {field.ttl_hours}h)",
            field_id=field.id,
            tag=field.staleness_tag.value,
            metadata={"age_hours": field.age_hours(), "stale": True, "expired": False},
        )

    def evaluate_batch(self, fields: List[ContextField], agent: AgentContext) -> List[GateResult]:
        """Evaluate multiple fields."""
        return [self.evaluate(field, agent) for field in fields]


@dataclass
class CompoundGateResult:
    """Combined result from privacy and staleness gates."""
    field_id: str
    field_name: str
    privacy_result: GateResult
    staleness_result: GateResult
    final_decision: GateDecision
    final_reason: str

    @property
    def is_allowed(self) -> bool:
        return self.final_decision.is_allowed

    def to_dict(self) -> dict:
        return {
            "field_id": self.field_id,
            "field_name": self.field_name,
            "privacy": {
                "decision": self.privacy_result.decision.value,
                "reason": self.privacy_result.reason,
            },
            "staleness": {
                "decision": self.staleness_result.decision.value,
                "reason": self.staleness_result.reason,
            },
            "final": {
                "decision": self.final_decision.value,
                "reason": self.final_reason,
            },
        }


class CompoundGate:
    """
    Compound gate combining privacy and staleness with Ninebar's precedence:

    1. Privacy DENY always wins (hard boundary)
    2. Staleness DENY wins for ephemeral (hard expiry)
    3. WARN from either produces WARN (allow with flag)
    4. ALLOW from both produces ALLOW
    """

    def __init__(self):
        self.privacy_gate = PrivacyGate()
        self.staleness_gate = StalenessGate()

    def _combine(self, privacy: GateResult, staleness: GateResult, field_name: str) -> CompoundGateResult:
        """Combine two gate results with Ninebar precedence rules."""
        # Hard DENY from privacy always wins
        if privacy.decision == GateDecision.DENY:
            return CompoundGateResult(
                field_id=privacy.field_id,
                field_name=field_name,
                privacy_result=privacy,
                staleness_result=staleness,
                final_decision=GateDecision.DENY,
                final_reason=f"Privacy: {privacy.reason}",
            )

        # Hard DENY from staleness (ephemeral) wins
        if staleness.decision == GateDecision.DENY:
            return CompoundGateResult(
                field_id=staleness.field_id,
                field_name=field_name,
                privacy_result=privacy,
                staleness_result=staleness,
                final_decision=GateDecision.DENY,
                final_reason=f"Staleness: {staleness.reason}",
            )

        # Any WARN produces WARN
        if privacy.decision == GateDecision.WARN or staleness.decision == GateDecision.WARN:
            reasons = []
            if privacy.decision == GateDecision.WARN:
                reasons.append(f"Privacy: {privacy.reason}")
            if staleness.decision == GateDecision.WARN:
                reasons.append(f"Staleness: {staleness.reason}")
            return CompoundGateResult(
                field_id=privacy.field_id,
                field_name=field_name,
                privacy_result=privacy,
                staleness_result=staleness,
                final_decision=GateDecision.WARN,
                final_reason="; ".join(reasons),
            )

        # Both ALLOW
        return CompoundGateResult(
            field_id=privacy.field_id,
            field_name=field_name,
            privacy_result=privacy,
            staleness_result=staleness,
            final_decision=GateDecision.ALLOW,
            final_reason="All gates passed",
        )

    def evaluate(self, field: ContextField, agent: AgentContext) -> CompoundGateResult:
        """Evaluate a single field through both gates."""
        privacy_result = self.privacy_gate.evaluate(field, agent)
        staleness_result = self.staleness_gate.evaluate(field, agent)
        return self._combine(privacy_result, staleness_result, field.name)

    def evaluate_batch(self, fields: List[ContextField], agent: AgentContext) -> List[CompoundGateResult]:
        """Evaluate multiple fields."""
        return [self.evaluate(field, agent) for field in fields]

    def filter_allowed(self, fields: List[ContextField], agent: AgentContext) -> List[ContextField]:
        """Return only fields that pass the compound gate (ALLOW or WARN)."""
        results = self.evaluate_batch(fields, agent)
        return [field for field, result in zip(fields, results) if result.is_allowed]

    def filter_denied(self, fields: List[ContextField], agent: AgentContext) -> List[ContextField]:
        """Return only fields that are denied."""
        results = self.evaluate_batch(fields, agent)
        return [field for field, result in zip(fields, results) if not result.is_allowed]