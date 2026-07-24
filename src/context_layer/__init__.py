"""
Context Layer for Agents — Ninebar Work Simulation Exercise

A system for agents to access structured and unstructured data with
privacy gates, staleness awareness, and auditability.
"""

from .schemas import (
    ContextField,
    ContextRoom,
    PrivacyTag,
    StalenessTag,
    GateDecision,
    AgentContext,
    StructuredSource,
    UnstructuredSource,
)
from .gates import PrivacyGate, StalenessGate, CompoundGate
from .room import RoomManager

__all__ = [
    "ContextField",
    "ContextRoom",
    "PrivacyTag",
    "StalenessTag",
    "GateDecision",
    "AgentContext",
    "StructuredSource",
    "UnstructuredSource",
    "PrivacyGate",
    "StalenessGate",
    "CompoundGate",
    "RoomManager",
]

__version__ = "0.1.0"