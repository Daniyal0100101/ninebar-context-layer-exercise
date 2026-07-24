"""
Compound Learning Module — the "Compound" phase of Ninebar's Know→Build→Compound.

Tracks action outcomes, adjusts confidence, and proposes room schema evolutions
when patterns emerge (repeated failures → remove field; high confidence → relax tags).
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from context_layer.schemas import PrivacyTag, StalenessTag


class OutcomeStatus(str, Enum):
    SUCCESS = "success"
    FAILURE = "failure"
    PARTIAL = "partial"


class ProposalStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    IMPLEMENTED = "implemented"


class ProposalType(str, Enum):
    REMOVE_FIELD = "remove_field"
    CHANGE_TAG = "change_tag"
    ADJUST_TTL = "adjust_ttl"
    ADD_FIELD = "add_field"
    MERGE_FIELDS = "merge_fields"


@dataclass
class OutcomeRecord:
    """Record of an action outcome for compound learning."""
    action_id: str
    action_type: str
    room_id: str
    field_ids: List[str]
    expected_result: str
    actual_result: str
    success: bool
    confidence_delta: float = 0.1
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    timestamp: datetime = field(default_factory=datetime.utcnow)
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def status(self) -> OutcomeStatus:
        return OutcomeStatus.SUCCESS if self.success else OutcomeStatus.FAILURE


@dataclass
class EvolutionProposal:
    """Proposal for room/schema evolution based on outcome patterns."""
    proposed_change: ProposalType
    field_id: str
    room_id: str
    reason: str
    confidence: float
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    evidence: List[str] = field(default_factory=list)
    status: ProposalStatus = ProposalStatus.PENDING
    created_at: datetime = field(default_factory=datetime.utcnow)
    reviewed_at: Optional[datetime] = None
    human_reviewer: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def approve(self, reviewer: str) -> None:
        self.status = ProposalStatus.APPROVED
        self.reviewed_at = datetime.utcnow()
        self.human_reviewer = reviewer

    def reject(self, reviewer: str, reason: str = "") -> None:
        self.status = ProposalStatus.REJECTED
        self.reviewed_at = datetime.utcnow()
        self.human_reviewer = reviewer
        self.metadata["rejection_reason"] = reason


class CompoundLogger:
    """
    Logs outcomes and generates evolution proposals.

    Ninebar philosophy: "The same problem is never solved twice."
    Confidence adjustments and proposals are the compound mechanism.
    """

    def __init__(self, storage_path: Optional[Path] = None):
        self.outcomes: List[OutcomeRecord] = []
        self.proposals: List[EvolutionProposal] = []
        self.field_confidence: Dict[str, float] = {}  # field_id -> confidence (0-1)
        self.storage_path = storage_path or Path("data/compound")
        self.storage_path.mkdir(parents=True, exist_ok=True)

        # Thresholds for proposal generation
        self.failure_threshold = 3  # 3 failures → propose removal
        self.success_threshold = 5  # 5 successes → propose tag relaxation
        self.confidence_min = 0.1
        self.confidence_max = 0.95

    def log_outcome(self, outcome: OutcomeRecord) -> None:
        """Log an outcome and update confidence, generate proposals if needed."""
        self.outcomes.append(outcome)

        for field_id in outcome.field_ids:
            self._update_confidence(field_id, outcome.success)
            self._check_proposal_triggers(field_id, outcome.room_id)

        self._persist()

    def _update_confidence(self, field_id: str, success: bool) -> None:
        """Update field confidence based on outcome."""
        current = self.field_confidence.get(field_id, 0.5)
        delta = self.outcomes[-1].confidence_delta if self.outcomes else 0.1

        if success:
            new_confidence = min(current + delta, self.confidence_max)
        else:
            new_confidence = max(current - delta, self.confidence_min)

        self.field_confidence[field_id] = new_confidence

    def _check_proposal_triggers(self, field_id: str, room_id: str) -> None:
        """Check if outcome patterns warrant a schema evolution proposal."""
        field_outcomes = [o for o in self.outcomes if field_id in o.field_ids]
        if not field_outcomes:
            return

        recent_failures = sum(1 for o in field_outcomes[-self.failure_threshold:] if not o.success)
        recent_successes = sum(1 for o in field_outcomes[-self.success_threshold:] if o.success)

        confidence = self.field_confidence.get(field_id, 0.5)

        # Repeated failures → propose removal
        if recent_failures >= self.failure_threshold:
            self._add_proposal(
                proposal_type=ProposalType.REMOVE_FIELD,
                field_id=field_id,
                room_id=room_id,
                reason=f"{recent_failures} consecutive failures on field {field_id}",
                confidence=1.0 - confidence,
                evidence=[f"Action {o.action_id} failed: {o.actual_result}" for o in field_outcomes[-self.failure_threshold:]],
            )

        # High confidence + many successes → propose tag relaxation
        elif recent_successes >= self.success_threshold and confidence > 0.8:
            # Find the field to know current tags
            self._add_proposal(
                proposal_type=ProposalType.CHANGE_TAG,
                field_id=field_id,
                room_id=room_id,
                reason=f"High confidence ({confidence:.2f}) after {recent_successes} successes — consider relaxing privacy/staleness tags",
                confidence=confidence,
                evidence=[f"Action {o.action_id} succeeded" for o in field_outcomes[-self.success_threshold:]],
            )

        # Low confidence + mixed → propose TTL adjustment
        elif confidence < 0.3 and len(field_outcomes) >= 5:
            self._add_proposal(
                proposal_type=ProposalType.ADJUST_TTL,
                field_id=field_id,
                room_id=room_id,
                reason=f"Low confidence ({confidence:.2f}) — adjust TTL or staleness tag",
                confidence=1.0 - confidence,
                evidence=[f"Action {o.action_id}: {'success' if o.success else 'failure'}" for o in field_outcomes[-5:]],
            )

    def _add_proposal(self, proposal_type: ProposalType, field_id: str, room_id: str,
                      reason: str, confidence: float, evidence: List[str]) -> None:
        """Add a proposal if not already pending for same field/type."""
        existing = next((p for p in self.proposals
                        if p.field_id == field_id
                        and p.proposed_change == proposal_type
                        and p.status == ProposalStatus.PENDING), None)
        if existing:
            return

        proposal = EvolutionProposal(
            proposed_change=proposal_type,
            field_id=field_id,
            room_id=room_id,
            reason=reason,
            confidence=confidence,
            evidence=evidence,
        )
        self.proposals.append(proposal)

    def get_confidence(self, field_id: str) -> float:
        return self.field_confidence.get(field_id, 0.5)

    def get_proposals(self, status: Optional[ProposalStatus] = None) -> List[EvolutionProposal]:
        if status:
            return [p for p in self.proposals if p.status == status]
        return self.proposals

    def export_learning_report(self) -> Dict[str, Any]:
        """Export a learning report for the submission."""
        if not self.outcomes:
            return {
                "total_outcomes": 0,
                "success_rate": 0.0,
                "confidence_scores": {},
                "pending_proposals": 0,
                "approved_proposals": 0,
                "rejected_proposals": 0,
            }

        successes = sum(1 for o in self.outcomes if o.success)
        return {
            "total_outcomes": len(self.outcomes),
            "success_rate": successes / len(self.outcomes),
            "confidence_scores": self.field_confidence.copy(),
            "pending_proposals": len(self.get_proposals(ProposalStatus.PENDING)),
            "approved_proposals": len(self.get_proposals(ProposalStatus.APPROVED)),
            "rejected_proposals": len(self.get_proposals(ProposalStatus.REJECTED)),
            "proposals_by_type": {
                pt.value: len([p for p in self.proposals if p.proposed_change == pt])
                for pt in ProposalType
            },
        }

    def _persist(self) -> None:
        """Persist outcomes and proposals to disk."""
        # Outcomes
        outcomes_file = self.storage_path / "outcomes.json"
        with open(outcomes_file, "w") as f:
            json.dump([o.__dict__ for o in self.outcomes], f, indent=2, default=str)

        # Proposals
        proposals_file = self.storage_path / "proposals.json"
        with open(proposals_file, "w") as f:
            json.dump([p.__dict__ for p in self.proposals], f, indent=2, default=str)

        # Confidence
        confidence_file = self.storage_path / "confidence.json"
        with open(confidence_file, "w") as f:
            json.dump(self.field_confidence, f, indent=2)

    def load(self) -> None:
        """Load from disk."""
        outcomes_file = self.storage_path / "outcomes.json"
        if outcomes_file.exists():
            with open(outcomes_file) as f:
                data = json.load(f)
                for d in data:
                    d["timestamp"] = datetime.fromisoformat(d["timestamp"])
                    self.outcomes.append(OutcomeRecord(**d))

        proposals_file = self.storage_path / "proposals.json"
        if proposals_file.exists():
            with open(proposals_file) as f:
                data = json.load(f)
                for d in data:
                    d["created_at"] = datetime.fromisoformat(d["created_at"])
                    if d.get("reviewed_at"):
                        d["reviewed_at"] = datetime.fromisoformat(d["reviewed_at"])
                    self.proposals.append(EvolutionProposal(**d))

        confidence_file = self.storage_path / "confidence.json"
        if confidence_file.exists():
            with open(confidence_file) as f:
                self.field_confidence = json.load(f)


def create_demo_outcomes(logger: CompoundLogger, manager=None) -> None:
    """Create demo outcomes showing the compound loop in action."""
    # Successful reads on team_operations fields
    for i in range(6):
        logger.log_outcome(OutcomeRecord(
            action_id=f"read_schedule_{i}",
            action_type="read",
            room_id="team_operations",
            field_ids=["meeting_schedule"],
            expected_result="Schedule retrieved",
            actual_result="Schedule retrieved",
            success=True,
            confidence_delta=0.05,
        ))

    # Successful reads on project_deadlines
    for i in range(4):
        logger.log_outcome(OutcomeRecord(
            action_id=f"read_deadline_{i}",
            action_type="read",
            room_id="team_operations",
            field_ids=["project_deadlines"],
            expected_result="Deadlines retrieved",
            actual_result="Deadlines retrieved",
            success=True,
            confidence_delta=0.05,
        ))

    # Failures on a problematic field
    for i in range(3):
        logger.log_outcome(OutcomeRecord(
            action_id=f"write_bad_field_{i}",
            action_type="write",
            room_id="knowledge_base",
            field_ids=["problematic_field"],
            expected_result="Updated",
            actual_result="Validation error: schema mismatch",
            success=False,
            confidence_delta=0.15,
        ))

    # Mixed outcomes on preferences
    for i in range(3):
        logger.log_outcome(OutcomeRecord(
            action_id=f"read_prefs_{i}",
            action_type="read",
            room_id="user_preferences",
            field_ids=["focus_areas"],
            expected_result="Preferences retrieved",
            actual_result="Preferences retrieved",
            success=True,
            confidence_delta=0.05,
        ))

    # One failure on PII field (even with approval)
    logger.log_outcome(OutcomeRecord(
        action_id="read_pii_fail",
        action_type="read",
        room_id="user_preferences",
        field_ids=["communication_style"],
        expected_result="Style retrieved",
        actual_result="Partial: truncated for privacy",
        success=False,
        confidence_delta=0.1,
    ))


if __name__ == "__main__":
    # Quick demo
    logger = CompoundLogger(Path("data/compound"))
    create_demo_outcomes(logger)

    report = logger.export_learning_report()
    print("Learning Report:")
    print(f"  Total outcomes: {report['total_outcomes']}")
    print(f"  Success rate: {report['success_rate']:.1%}")
    print(f"  Pending proposals: {report['pending_proposals']}")

    for proposal in logger.get_proposals():
        print(f"  Proposal: {proposal.proposed_change.value} on {proposal.field_id} — {proposal.reason}")