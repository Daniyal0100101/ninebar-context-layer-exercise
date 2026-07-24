"""
Agent Decision Pipeline — the propose→critic→override→commit flow.

This mirrors Ninebar's "Build" phase and AegisFlow's workflow graph pipeline.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Callable
from pydantic import BaseModel, Field

from context_layer.schemas import ContextField, AgentContext, GateDecision
from context_layer.gates import CompoundGate, CompoundGateResult
from context_layer.room import RoomManager


class PipelineStage(str, Enum):
    """Stages in the agent decision pipeline."""
    CONTEXT_PREP = "context_prep"
    PROPOSE = "propose"
    CRITIC_REVIEW = "critic_review"
    RESOLVE_CONSENSUS = "resolve_consensus"
    STATE_MUTATION = "state_mutation"
    COMMIT_LOGS = "commit_logs"


class ActionType(str, Enum):
    """Types of actions an agent can propose."""
    READ = "read"
    WRITE = "write"
    DELETE = "delete"
    EXECUTE = "execute"
    NOTIFY = "notify"
    ESCALATE = "escalate"
    WAIT = "wait"


class ActionStatus(str, Enum):
    """Status of a proposed action."""
    PROPOSED = "proposed"
    UNDER_REVIEW = "under_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    OVERRIDDEN = "overridden"
    EXECUTED = "executed"
    FAILED = "failed"


@dataclass
class ProposedAction:
    """An action proposed by the agent."""
    type: ActionType
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    target_room: str = ""
    target_field_ids: List[str] = field(default_factory=list)
    payload: Dict[str, Any] = field(default_factory=dict)
    reasoning: str = ""
    confidence: float = 0.0
    status: ActionStatus = ActionStatus.PROPOSED
    proposed_at: datetime = field(default_factory=datetime.utcnow)
    reviewed_at: Optional[datetime] = None
    executed_at: Optional[datetime] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class CriticReview:
    """A critic's review of a proposed action."""
    action_id: str
    critic_id: str
    approved: bool
    confidence: float
    concerns: List[str] = field(default_factory=list)
    suggestions: List[str] = field(default_factory=list)
    reviewed_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class HumanOverride:
    """Human override decision."""
    action_id: str
    human_id: str
    decision: str  # "approve", "reject", "modify"
    modified_payload: Optional[Dict[str, Any]] = None
    reason: str = ""
    timestamp: datetime = field(default_factory=datetime.utcnow)


@dataclass
class PipelineResult:
    """Result of a pipeline execution."""
    action: ProposedAction
    context_prep: Dict[str, Any]
    critic_reviews: List[CriticReview] = field(default_factory=list)
    human_override: Optional[HumanOverride] = None
    final_status: ActionStatus = ActionStatus.PROPOSED
    execution_result: Optional[Dict[str, Any]] = None
    logs: List[Dict[str, Any]] = field(default_factory=list)


class ContextPreparer:
    """Stage 1: Prepare context for the agent."""

    def __init__(self, room_manager: RoomManager):
        self.room_manager = room_manager
        self.compound_gate = CompoundGate()

    def prepare(self, room_id: str, agent: AgentContext,
                focus_tags: Optional[Dict[str, List[str]]] = None) -> Dict[str, Any]:
        """
        Prepare filtered context for agent decision making.

        Args:
            room_id: Room to query
            agent: Agent context
            focus_tags: Optional filter for privacy/staleness tags

        Returns:
            Filtered context with gate results for auditability
        """
        # Apply compound gates
        result = self.room_manager.query_room(room_id, agent)

        # Build agent-usable context
        context = self.room_manager.get_agent_context(room_id, agent)

        return {
            "room_id": room_id,
            "room_name": result["room_name"],
            "agent_id": agent.id,
            "context": context["context"],
            "gate_summary": context["gate_summary"],
            "full_gate_results": result["fields"],
        }


class ActionProposer:
    """Stage 2: Agent proposes actions based on context."""

    def __init__(self, llm_fn: Optional[Callable] = None):
        self.llm_fn = llm_fn
        self.proposal_history: List[ProposedAction] = []

    def propose(self, context: Dict[str, Any], goal: str,
                agent: AgentContext) -> List[ProposedAction]:
        """
        Propose actions based on context and goal.

        In mock mode, uses heuristic rules. With LLM, uses the provided function.
        """
        if self.llm_fn:
            return self._propose_with_llm(context, goal, agent)
        return self._propose_heuristic(context, goal, agent)

    def _propose_heuristic(self, context: Dict[str, Any], goal: str,
                           agent: AgentContext) -> List[ProposedAction]:
        """Heuristic-based proposal for demo/mock mode."""
        actions = []
        # Map field names to their IDs from full_gate_results
        field_id_map = {}
        for field_data in context.get("full_gate_results", []):
            if field_data["gate_result"]["final"]["decision"] in ("allow", "warn"):
                field_id_map[field_data["name"]] = field_data["id"]

        # Example heuristic: if goal mentions "meeting", propose reading schedule
        if "meeting" in goal.lower() and "meeting_schedule" in field_id_map:
            actions.append(ProposedAction(
                type=ActionType.READ,
                target_room=context["room_id"],
                target_field_ids=[field_id_map["meeting_schedule"]],
                reasoning="Goal requires meeting context; schedule is available and fresh",
                confidence=0.85,
            ))

        # If goal mentions "preferences", propose reading (with approval note)
        if "preference" in goal.lower() and "communication_style" in field_id_map:
            actions.append(ProposedAction(
                type=ActionType.READ,
                target_room=context["room_id"],
                target_field_ids=[field_id_map["communication_style"]],
                reasoning="Goal requires user preferences; PII field needs human approval",
                confidence=0.70,
            ))

        # If goal mentions "deadline", propose reading project deadlines
        if "deadline" in goal.lower() and "project_deadlines" in field_id_map:
            actions.append(ProposedAction(
                type=ActionType.READ,
                target_room=context["room_id"],
                target_field_ids=[field_id_map["project_deadlines"]],
                reasoning="Goal requires deadline awareness; medium-term data available",
                confidence=0.90,
            ))

        # Default: escalate if no clear action
        if not actions:
            actions.append(ProposedAction(
                type=ActionType.ESCALATE,
                target_room=context["room_id"],
                reasoning=f"No clear action for goal: {goal}",
                confidence=0.30,
            ))

        for action in actions:
            self.proposal_history.append(action)

        return actions

    def _propose_with_llm(self, context: Dict[str, Any], goal: str,
                          agent: AgentContext) -> List[ProposedAction]:
        """LLM-based proposal (placeholder for integration)."""
        # Would call self.llm_fn with context, goal, agent
        # For now, fall back to heuristic
        return self._propose_heuristic(context, goal, agent)


class CriticReviewer:
    """Stage 3: Critic reviews proposed actions."""

    def __init__(self, critic_fn: Optional[Callable] = None):
        self.critic_fn = critic_fn
        self.review_history: List[CriticReview] = []

    def review(self, action: ProposedAction, context: Dict[str, Any],
               agent: AgentContext) -> List[CriticReview]:
        """Review a proposed action from multiple critic perspectives."""
        if self.critic_fn:
            return self._review_with_llm(action, context, agent)
        return self._review_heuristic(action, context, agent)

    def _review_heuristic(self, action: ProposedAction, context: Dict[str, Any],
                          agent: AgentContext) -> List[CriticReview]:
        """Heuristic critic reviews."""
        reviews = []

        # Security critic
        security_concerns = []
        if action.type in (ActionType.WRITE, ActionType.DELETE, ActionType.EXECUTE):
            security_concerns.append("Mutating action requires higher confidence")
        if any("pii" in str(fid).lower() for fid in action.target_field_ids):
            security_concerns.append("PII field access - verify approval")

        reviews.append(CriticReview(
            action_id=action.id,
            critic_id="security_critic",
            approved=len(security_concerns) == 0 or action.confidence > 0.7,
            confidence=0.8 if len(security_concerns) == 0 else 0.5,
            concerns=security_concerns,
            suggestions=["Verify human approval for PII"] if security_concerns else [],
        ))

        # Relevance critic
        relevance_concerns = []
        if action.confidence < 0.5:
            relevance_concerns.append("Low confidence proposal")

        reviews.append(CriticReview(
            action_id=action.id,
            critic_id="relevance_critic",
            approved=action.confidence >= 0.5,
            confidence=action.confidence,
            concerns=relevance_concerns,
            suggestions=["Clarify goal or gather more context"] if relevance_concerns else [],
        ))

        # Privacy critic (check gate results)
        gate_results = context.get("full_gate_results", [])
        privacy_denied = [f for f in gate_results
                         if f["gate_result"]["final"]["decision"] == "deny"
                         and f["id"] in action.target_field_ids]

        if privacy_denied:
            reviews.append(CriticReview(
                action_id=action.id,
                critic_id="privacy_critic",
                approved=False,
                confidence=0.9,
                concerns=[f"Field {f['name']} denied by privacy gate" for f in privacy_denied],
                suggestions=["Obtain human approval or adjust scope"],
            ))

        for review in reviews:
            self.review_history.append(review)

        return reviews

    def _review_with_llm(self, action: ProposedAction, context: Dict[str, Any],
                         agent: AgentContext) -> List[CriticReview]:
        """LLM-based critic review (placeholder)."""
        return self._review_heuristic(action, context, agent)


class ConsensusResolver:
    """Stage 4: Resolve consensus among critics."""

    def resolve(self, action: ProposedAction, reviews: List[CriticReview]) -> ActionStatus:
        """
        Resolve consensus from critic reviews.

        Rules:
        - Any privacy critic DENY → REJECTED
        - All approve → APPROVED
        - Mixed with no hard DENY → UNDER_REVIEW (needs human)
        """
        # Hard reject from privacy critic
        for review in reviews:
            if review.critic_id == "privacy_critic" and not review.approved:
                return ActionStatus.REJECTED

        # All approve
        if all(r.approved for r in reviews):
            return ActionStatus.APPROVED

        # Mixed - needs human
        return ActionStatus.UNDER_REVIEW


class HumanOverrideHandler:
    """Stage 5: Handle human override decisions."""

    def __init__(self):
        self.override_history: List[HumanOverride] = []

    def request_override(self, action: ProposedAction, reviews: List[CriticReview],
                         human_id: str) -> HumanOverride:
        """
        Request human override for an action under review.

        In production, this would integrate with notification systems.
        For demo, we simulate the human decision.
        """
        # Simulate human decision based on action type and concerns
        concerns = []
        for review in reviews:
            concerns.extend(review.concerns)

        if action.type == ActionType.ESCALATE:
            decision = "approve"
            reason = "Escalation approved - human will handle directly"
        elif "PII" in " ".join(concerns):
            decision = "approve"
            reason = "Human grants approval for PII access"
        elif action.confidence < 0.5:
            decision = "reject"
            reason = "Low confidence - human rejects"
        else:
            decision = "approve"
            reason = "Human approves with standard oversight"

        override = HumanOverride(
            action_id=action.id,
            human_id=human_id,
            decision=decision,
            reason=reason,
        )
        self.override_history.append(override)
        return override


class StateMutator:
    """Stage 6: Execute approved actions (mutate state)."""

    def __init__(self, room_manager: RoomManager):
        self.room_manager = room_manager
        self.mutation_log: List[Dict[str, Any]] = []

    def execute(self, action: ProposedAction, override: Optional[HumanOverride] = None) -> Dict[str, Any]:
        """Execute an approved action."""
        if action.type == ActionType.READ:
            return self._execute_read(action)
        elif action.type == ActionType.WRITE:
            return self._execute_write(action, override)
        elif action.type == ActionType.DELETE:
            return self._execute_delete(action, override)
        elif action.type == ActionType.ESCALATE:
            return self._execute_escalate(action)
        else:
            return {"success": False, "error": f"Unsupported action type: {action.type}"}

    def _execute_read(self, action: ProposedAction) -> Dict[str, Any]:
        """Execute read action - return field values."""
        room = self.room_manager.get_room(action.target_room)
        if not room:
            return {"success": False, "error": "Room not found"}

        values = {}
        for fid in action.target_field_ids:
            field = room.get_field(fid)
            if field:
                values[field.name] = field.value

        self.mutation_log.append({
            "action_id": action.id,
            "type": "read",
            "fields_read": list(values.keys()),
            "timestamp": datetime.utcnow().isoformat(),
        })

        return {"success": True, "values": values}

    def _execute_write(self, action: ProposedAction, override: Optional[HumanOverride]) -> Dict[str, Any]:
        """Execute write action."""
        # Check override for sensitive writes
        if override and override.decision != "approve":
            return {"success": False, "error": "Human override rejected"}

        room = self.room_manager.get_room(action.target_room)
        if not room:
            return {"success": False, "error": "Room not found"}

        written = []
        for fid, value in action.payload.items():
            field = room.get_field(fid)
            if field:
                old_value = field.value
                field.value = value
                field.updated_at = datetime.utcnow()
                written.append({"field": field.name, "old": old_value, "new": value})

        self.mutation_log.append({
            "action_id": action.id,
            "type": "write",
            "fields_written": written,
            "override": override.human_id if override else None,
            "timestamp": datetime.utcnow().isoformat(),
        })

        return {"success": True, "written": written}

    def _execute_delete(self, action: ProposedAction, override: Optional[HumanOverride]) -> Dict[str, Any]:
        """Execute delete action."""
        if override and override.decision != "approve":
            return {"success": False, "error": "Human override rejected"}

        room = self.room_manager.get_room(action.target_room)
        if not room:
            return {"success": False, "error": "Room not found"}

        deleted = []
        for fid in action.target_field_ids:
            field = room.get_field(fid)
            if field and room.remove_field(fid):
                deleted.append(field.name)

        self.mutation_log.append({
            "action_id": action.id,
            "type": "delete",
            "fields_deleted": deleted,
            "override": override.human_id if override else None,
            "timestamp": datetime.utcnow().isoformat(),
        })

        return {"success": True, "deleted": deleted}

    def _execute_escalate(self, action: ProposedAction) -> Dict[str, Any]:
        """Execute escalate action - log for human attention."""
        self.mutation_log.append({
            "action_id": action.id,
            "type": "escalate",
            "reason": action.reasoning,
            "timestamp": datetime.utcnow().isoformat(),
        })

        return {"success": True, "escalated": True, "message": "Logged for human attention"}


class CommitLogger:
    """Stage 7: Commit logs and update compound learning."""

    def __init__(self):
        self.audit_log: List[Dict[str, Any]] = []

    def log(self, result: PipelineResult) -> None:
        """Log the complete pipeline result."""
        entry = {
            "action_id": result.action.id,
            "action_type": result.action.type.value,
            "room": result.action.target_room,
            "status": result.final_status.value,
            "proposed_at": result.action.proposed_at.isoformat(),
            "executed_at": result.action.executed_at.isoformat() if result.action.executed_at else None,
            "critic_reviews": [
                {
                    "critic": r.critic_id,
                    "approved": r.approved,
                    "confidence": r.confidence,
                    "concerns": r.concerns,
                }
                for r in result.critic_reviews
            ],
            "human_override": result.human_override.to_dict() if result.human_override else None,
            "execution_result": result.execution_result,
        }
        self.audit_log.append(entry)

    def get_audit_trail(self, action_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get audit trail, optionally filtered by action."""
        if action_id:
            return [e for e in self.audit_log if e["action_id"] == action_id]
        return self.audit_log


class AgentDecisionPipeline:
    """
    Complete agent decision pipeline orchestrating all stages.

    Pipeline: Context Prep → Propose → Critic Review → Consensus →
    Human Override → State Mutation → Commit Logs
    """

    def __init__(self, room_manager: RoomManager, llm_fn: Optional[Callable] = None):
        self.room_manager = room_manager
        self.context_preparer = ContextPreparer(room_manager)
        self.proposer = ActionProposer(llm_fn)
        self.critic = CriticReviewer(llm_fn)
        self.consensus = ConsensusResolver()
        self.override_handler = HumanOverrideHandler()
        self.mutator = StateMutator(room_manager)
        self.logger = CommitLogger()
        self.compound_gate = CompoundGate()

    def run(self, room_id: str, goal: str, agent: AgentContext,
            human_id: str = "human_operator") -> PipelineResult:
        """Run the full pipeline for a goal."""
        logs = []

        # Stage 1: Context Prep
        logs.append({"stage": "context_prep", "timestamp": datetime.utcnow().isoformat()})
        context = self.context_preparer.prepare(room_id, agent)

        # Stage 2: Propose
        logs.append({"stage": "propose", "timestamp": datetime.utcnow().isoformat()})
        actions = self.proposer.propose(context, goal, agent)
        if not actions:
            return PipelineResult(
                action=ProposedAction(type=ActionType.WAIT, target_room=room_id, reasoning="No actions proposed"),
                context_prep=context,
                final_status=ActionStatus.REJECTED,
                logs=logs,
            )

        # Take the highest confidence action
        action = max(actions, key=lambda a: a.confidence)

        # Stage 3: Critic Review
        logs.append({"stage": "critic_review", "timestamp": datetime.utcnow().isoformat()})
        reviews = self.critic.review(action, context, agent)

        # Stage 4: Consensus
        logs.append({"stage": "resolve_consensus", "timestamp": datetime.utcnow().isoformat()})
        status = self.consensus.resolve(action, reviews)

        override = None
        # Stage 5: Human Override (if needed)
        if status == ActionStatus.UNDER_REVIEW:
            logs.append({"stage": "human_override", "timestamp": datetime.utcnow().isoformat()})
            override = self.override_handler.request_override(action, reviews, human_id)
            if override.decision == "approve":
                status = ActionStatus.APPROVED
            elif override.decision == "reject":
                status = ActionStatus.REJECTED
            elif override.decision == "modify" and override.modified_payload:
                action.payload = override.modified_payload
                status = ActionStatus.APPROVED

        # Stage 6: State Mutation
        execution_result = None
        if status == ActionStatus.APPROVED:
            logs.append({"stage": "state_mutation", "timestamp": datetime.utcnow().isoformat()})
            action.status = ActionStatus.EXECUTED
            action.executed_at = datetime.utcnow()
            execution_result = self.mutator.execute(action, override)

        # Stage 7: Commit Logs
        logs.append({"stage": "commit_logs", "timestamp": datetime.utcnow().isoformat()})
        result = PipelineResult(
            action=action,
            context_prep=context,
            critic_reviews=reviews,
            human_override=override,
            final_status=status,
            execution_result=execution_result,
            logs=logs,
        )
        self.logger.log(result)

        return result


# Extend HumanOverride with to_dict
HumanOverride.to_dict = lambda self: {
    "human_id": self.human_id,
    "decision": self.decision,
    "reason": self.reason,
    "modified_payload": self.modified_payload,
    "timestamp": self.timestamp.isoformat(),
}