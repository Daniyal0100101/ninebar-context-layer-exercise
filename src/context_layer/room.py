"""
Room Manager — core logic for building and managing context rooms.

Handles ingestion from structured and unstructured sources, normalization
into typed rooms, and provides the agent-facing query interface.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Union

from context_layer.schemas import (
    ContextField,
    ContextRoom,
    StructuredSource,
    UnstructuredSource,
    AgentContext,
    PrivacyTag,
    StalenessTag,
)
from context_layer.gates import CompoundGate, CompoundGateResult


class RoomManager:
    """
    Manages context rooms: creation, ingestion, querying, and gating.

    This is the main entry point for agents to access contextual data.
    """

    def __init__(self, storage_path: Optional[Path] = None):
        self.rooms: Dict[str, ContextRoom] = {}
        self.sources: Dict[str, Union[StructuredSource, UnstructuredSource]] = {}
        self.compound_gate = CompoundGate()
        self.storage_path = storage_path or Path("data/rooms")
        self.storage_path.mkdir(parents=True, exist_ok=True)

    # Room management
    def create_room(self, name: str, description: str = "") -> ContextRoom:
        """Create a new context room."""
        room = ContextRoom(name=name, description=description)
        self.rooms[room.id] = room
        return room

    def get_room(self, room_id: str) -> Optional[ContextRoom]:
        return self.rooms.get(room_id)

    def get_room_by_name(self, name: str) -> Optional[ContextRoom]:
        for room in self.rooms.values():
            if room.name == name:
                return room
        return None

    def list_rooms(self) -> List[ContextRoom]:
        return list(self.rooms.values())

    # Source management
    def register_structured_source(self, source: StructuredSource) -> None:
        self.sources[source.id] = source

    def register_unstructured_source(self, source: UnstructuredSource) -> None:
        self.sources[source.id] = source

    def get_source(self, source_id: str) -> Optional[Union[StructuredSource, UnstructuredSource]]:
        return self.sources.get(source_id)

    # Ingestion: Structured
    def ingest_structured(self, source_id: str, data: Dict[str, Any]) -> List[ContextField]:
        """Ingest structured data from a registered source."""
        source = self.sources.get(source_id)
        if not source or source.source_type != "structured":
            raise ValueError(f"Source {source_id} not found or not structured")

        room = self.rooms.get(source.room_id)
        if not room:
            raise ValueError(f"Room {source.room_id} not found")

        fields = []
        for key, value in data.items():
            # Determine privacy/staleness from schema or defaults
            field_def = source.schema.get(key, {})
            privacy = PrivacyTag(field_def.get("privacy_tag", "internal"))
            staleness = StalenessTag(field_def.get("staleness_tag", "medium_term"))
            ttl = field_def.get("ttl_hours")

            field = ContextField(
                name=key,
                value=value,
                source_id=source_id,
                privacy_tag=privacy,
                staleness_tag=staleness,
                ttl_hours=ttl,
                metadata={"ingested_at": datetime.utcnow().isoformat()},
            )
            room.add_field(field)
            fields.append(field)

        return fields

    # Ingestion: Unstructured (simplified - real impl would use NLP/embeddings)
    def ingest_unstructured(self, source_id: str, content: str,
                            privacy_tag: PrivacyTag = PrivacyTag.INTERNAL,
                            staleness_tag: StalenessTag = StalenessTag.MEDIUM_TERM) -> ContextField:
        """Ingest unstructured text as a single context field."""
        source = self.sources.get(source_id)
        if not source or source.source_type != "unstructured":
            raise ValueError(f"Source {source_id} not found or not unstructured")

        room = self.rooms.get(source.room_id)
        if not room:
            raise ValueError(f"Room {source.room_id} not found")

        field = ContextField(
            name=f"{source.name}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}",
            value=content,
            source_id=source_id,
            privacy_tag=privacy_tag,
            staleness_tag=staleness_tag,
            metadata={
                "content_type": "text",
                "ingested_at": datetime.utcnow().isoformat(),
                "char_count": len(content),
            },
        )
        room.add_field(field)
        return field

    # Agent query interface
    def query_room(self, room_id: str, agent: AgentContext,
                   privacy_tags: Optional[Set[PrivacyTag]] = None,
                   staleness_tags: Optional[Set[StalenessTag]] = None) -> Dict[str, Any]:
        """
        Query a room for an agent, applying compound gates.

        Returns accessible fields with gate results for auditability.
        """
        room = self.rooms.get(room_id)
        if not room:
            raise ValueError(f"Room {room_id} not found")

        # Filter by tags if specified
        candidate_fields = list(room.fields.values())
        if privacy_tags:
            candidate_fields = [f for f in candidate_fields if f.privacy_tag in privacy_tags]
        if staleness_tags:
            candidate_fields = [f for f in candidate_fields if f.staleness_tag in staleness_tags]

        # Apply compound gate
        gate_results = self.compound_gate.evaluate_batch(candidate_fields, agent)
        allowed_fields = [f for f, r in zip(candidate_fields, gate_results) if r.is_allowed]

        # Build response
        return {
            "room_id": room_id,
            "room_name": room.name,
            "agent_id": agent.id,
            "total_fields": len(room.fields),
            "candidate_fields": len(candidate_fields),
            "allowed_fields": len(allowed_fields),
            "denied_fields": len(candidate_fields) - len(allowed_fields),
            "fields": [
                {
                    "id": f.id,
                    "name": f.name,
                    "value": f.value,
                    "privacy_tag": f.privacy_tag.value,
                    "staleness_tag": f.staleness_tag.value,
                    "age_hours": round(f.age_hours(), 2),
                    "gate_result": r.to_dict(),
                }
                for f, r in zip(candidate_fields, gate_results)
            ],
            "allowed_field_ids": [f.id for f in allowed_fields],
        }

    def get_agent_context(self, room_id: str, agent: AgentContext) -> Dict[str, Any]:
        """Get the filtered context an agent can actually use."""
        result = self.query_room(room_id, agent)
        # Return only allowed fields' values
        allowed = {}
        for field_data in result["fields"]:
            if field_data["gate_result"]["final"]["decision"] in ("allow", "warn"):
                allowed[field_data["name"]] = field_data["value"]
        return {
            "room_id": room_id,
            "room_name": result["room_name"],
            "agent_id": agent.id,
            "context": allowed,
            "gate_summary": {
                "total": result["total_fields"],
                "allowed": result["allowed_fields"],
                "denied": result["denied_fields"],
            },
        }

    # Persistence
    def save_room(self, room_id: str) -> Path:
        """Save a room to disk."""
        room = self.rooms.get(room_id)
        if not room:
            raise ValueError(f"Room {room_id} not found")

        file_path = self.storage_path / f"{room_id}.json"
        with open(file_path, "w") as f:
            json.dump(room.model_dump(mode="json"), f, indent=2, default=str)
        return file_path

    def load_room(self, room_id: str) -> ContextRoom:
        """Load a room from disk."""
        file_path = self.storage_path / f"{room_id}.json"
        if not file_path.exists():
            raise ValueError(f"Room file {file_path} not found")

        with open(file_path) as f:
            data = json.load(f)
        room = ContextRoom.model_validate(data)
        self.rooms[room.id] = room
        return room

    def save_all(self) -> List[Path]:
        """Save all rooms."""
        return [self.save_room(rid) for rid in self.rooms.keys()]


def create_demo_rooms(manager: RoomManager) -> Dict[str, ContextRoom]:
    """Create demo rooms for the exercise."""
    # Room 1: Team Operations
    ops_room = manager.create_room(
        name="team_operations",
        description="Structured team data: calendar, tasks, trackers"
    )

    ops_source = StructuredSource(
        name="team_calendar",
        room_id=ops_room.id,
        schema={
            "meeting_schedule": {"privacy_tag": "internal", "staleness_tag": "ephemeral"},
            "team_availability": {"privacy_tag": "internal", "staleness_tag": "short_term"},
            "project_deadlines": {"privacy_tag": "internal", "staleness_tag": "medium_term"},
        }
    )
    manager.register_structured_source(ops_source)

    # Room 2: Knowledge Base
    kb_room = manager.create_room(
        name="knowledge_base",
        description="Unstructured knowledge: docs, notes, decisions"
    )

    kb_source = UnstructuredSource(
        name="project_docs",
        room_id=kb_room.id,
        content_types=["markdown", "pdf"],
        processing_hints={"extract_decisions": True, "extract_action_items": True}
    )
    manager.register_unstructured_source(kb_source)

    # Room 3: User Preferences
    prefs_room = manager.create_room(
        name="user_preferences",
        description="User preferences and privacy settings"
    )

    prefs_source = StructuredSource(
        name="preferences",
        room_id=prefs_room.id,
        schema={
            "communication_style": {"privacy_tag": "pii", "staleness_tag": "long_term"},
            "focus_areas": {"privacy_tag": "internal", "staleness_tag": "medium_term"},
            "notification_prefs": {"privacy_tag": "pii", "staleness_tag": "long_term"},
            "api_keys": {"privacy_tag": "proprietary", "staleness_tag": "evergreen"},
        }
    )
    manager.register_structured_source(prefs_source)

    return {
        "operations": ops_room,
        "knowledge": kb_room,
        "preferences": prefs_room,
    }