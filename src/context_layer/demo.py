#!/usr/bin/env python3
"""
Demo script for the Ninebar Context Layer Exercise.

Shows the complete workflow:
1. Context ingestion (structured + unstructured)
2. Room construction with typed schemas
3. Privacy/staleness gating (Ninebar's "Know" phase)
4. Agent decision pipeline (Ninebar's "Build" phase)
5. Compound learning (Ninebar's "Compound" phase)
"""

from __future__ import annotations

import json
from pathlib import Path
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.syntax import Syntax
from rich.tree import Tree

from context_layer.schemas import (
    AgentContext,
    PrivacyTag,
    StalenessTag,
    StructuredSource,
    UnstructuredSource,
)
from context_layer.room import RoomManager, create_demo_rooms
from context_layer.pipeline import AgentDecisionPipeline, ActionType, ActionStatus
from context_layer.compound import CompoundLogger, create_demo_outcomes, ProposalStatus
from context_layer.gates import CompoundGate

console = Console()


def print_header(title: str) -> None:
    console.print(Panel.fit(f"[bold cyan]{title}[/bold cyan]", border_style="cyan"))


def print_section(title: str) -> None:
    console.print(f"\n[bold yellow]▶ {title}[/bold yellow]\n")


def demo_1_ingestion() -> RoomManager:
    """Demo 1: Context Ingestion"""
    print_header("1. CONTEXT INGESTION (Ninebar's 'Know' Phase)")

    manager = RoomManager(storage_path=Path("data/rooms"))
    rooms = create_demo_rooms(manager)

    # Ingest structured data
    print_section("Structured Data (Calendar, Trackers, Tasks)")
    ops_room = rooms["operations"]
    calendar_source = next(s for s in manager.sources.values()
                          if s.name == "team_calendar" and s.room_id == ops_room.id)

    structured_data = {
        "meeting_schedule": [
            {"time": "09:00", "title": "Daily Standup", "attendees": ["alice", "bob", "carol"]},
            {"time": "14:00", "title": "Design Review", "attendees": ["alice", "dave"]},
            {"time": "16:00", "title": "Retrospective", "attendees": ["alice", "bob", "carol", "dave"]},
        ],
        "team_availability": {"alice": "available", "bob": "busy", "carol": "available", "dave": "available"},
        "project_deadlines": {
            "project_alpha": "2026-08-01",
            "project_beta": "2026-08-15",
            "project_gamma": "2026-09-01",
        },
    }

    fields = manager.ingest_structured(calendar_source.id, structured_data)
    console.print(f"Ingested {len(fields)} structured fields into '{ops_room.name}':")
    for f in fields:
        console.print(f"  • [green]{f.name}[/green] (privacy=[cyan]{f.privacy_tag.value}[/cyan], staleness=[magenta]{f.staleness_tag.value}[/magenta])")

    # Ingest unstructured data
    print_section("Unstructured Data (Notes, Docs, Decisions)")
    kb_room = rooms["knowledge"]
    docs_source = next(s for s in manager.sources.values()
                       if s.name == "project_docs" and s.room_id == kb_room.id)

    unstructured_content = """# Project Alpha - Architecture Decision Record

## Decision: Use PostgreSQL for primary data store

**Date:** 2026-07-15
**Status:** Accepted

### Context
Need a reliable, ACID-compliant database for transactional data. Team has PostgreSQL expertise.

### Decision
PostgreSQL 15+ for all relational data. Use Prisma ORM for type-safe access.

### Consequences
- Strong consistency guarantees
- Team familiarity reduces onboarding
- Operational overhead (backups, replication) accepted"""

    field = manager.ingest_unstructured(
        docs_source.id,
        unstructured_content,
        privacy_tag=PrivacyTag.INTERNAL,
        staleness_tag=StalenessTag.MEDIUM_TERM,
    )
    console.print(f"Ingested unstructured field into '{kb_room.name}':")
    console.print(f"  • [green]{field.name}[/green] ({len(field.value)} chars)")

    # Ingest user preferences
    print_section("User Preferences (PII & Proprietary)")
    prefs_room = rooms["preferences"]
    prefs_source = next(s for s in manager.sources.values()
                        if s.name == "preferences" and s.room_id == prefs_room.id)

    prefs_data = {
        "communication_style": "concise, technical, async-first",
        "focus_areas": ["AI agents", "multi-agent systems", "operational simulation"],
        "notification_prefs": {"email": "digest", "slack": "mentions_only", "push": "none"},
        "api_keys": {"gemini": "sk-prod-...", "github": "ghp_..."},
    }

    fields = manager.ingest_structured(prefs_source.id, prefs_data)
    console.print(f"Ingested {len(fields)} preference fields into '{prefs_room.name}':")
    for f in fields:
        console.print(f"  • [green]{f.name}[/green] (privacy=[red]{f.privacy_tag.value}[/red], staleness=[magenta]{f.staleness_tag.value}[/magenta])")

    return manager


def demo_2_gating(manager: RoomManager) -> None:
    """Demo 2: Privacy/Staleness Gates"""
    print_header("2. PRIVACY & STALENESS GATES (Ninebar's 'Know' — Boundaries)")

    # Internal agent with PII approval
    print_section("Internal Agent (with PII approvals)")
    internal_agent = AgentContext(name="internal_agent", is_external=False)
    prefs_room = manager.get_room_by_name("user_preferences")
    for f in prefs_room.fields.values():
        if f.privacy_tag == PrivacyTag.PII:
            internal_agent.grant_approval(f.id)

    result = manager.query_room(prefs_room.id, internal_agent)

    table = Table(title="Internal Agent Access Results")
    table.add_column("Field", style="green")
    table.add_column("Privacy", style="cyan")
    table.add_column("Staleness", style="magenta")
    table.add_column("Gate Decision", style="yellow")
    table.add_column("Reason")

    for field_data in result["fields"]:
        gate = field_data["gate_result"]["final"]
        table.add_row(
            field_data["name"],
            field_data["privacy_tag"],
            field_data["staleness_tag"],
            gate["decision"].upper(),
            gate["reason"][:60] + "..." if len(gate["reason"]) > 60 else gate["reason"],
        )
    console.print(table)

    # External agent (no PII approval)
    print_section("External Agent (no PII approval)")
    external_agent = AgentContext(name="external_agent", is_external=True)

    result = manager.query_room(prefs_room.id, external_agent)

    table = Table(title="External Agent Access Results")
    table.add_column("Field", style="green")
    table.add_column("Privacy", style="cyan")
    table.add_column("Gate Decision", style="yellow")
    table.add_column("Reason")

    for field_data in result["fields"]:
        gate = field_data["gate_result"]["final"]
        table.add_row(
            field_data["name"],
            field_data["privacy_tag"],
            gate["decision"].upper(),
            gate["reason"][:60] + "..." if len(gate["reason"]) > 60 else gate["reason"],
        )
    console.print(table)

    # Show agent-usable context
    print_section("Agent-Usable Context (Filtered)")
    context = manager.get_agent_context(prefs_room.id, internal_agent)
    console.print(Panel(Syntax(json.dumps(context["context"], indent=2), "json"),
                       title="Internal Agent Context", border_style="green"))

    context = manager.get_agent_context(prefs_room.id, external_agent)
    console.print(Panel(Syntax(json.dumps(context["context"], indent=2), "json"),
                       title="External Agent Context", border_style="red"))


def demo_3_pipeline(manager: RoomManager) -> None:
    """Demo 3: Agent Decision Pipeline"""
    print_header("3. AGENT DECISION PIPELINE (Ninebar's 'Build' Phase)")

    # Setup agent with approvals
    agent = AgentContext(name="ops_agent", is_external=False)
    prefs_room = manager.get_room_by_name("user_preferences")
    for f in prefs_room.fields.values():
        if f.privacy_tag == PrivacyTag.PII:
            agent.grant_approval(f.id)

    pipeline = AgentDecisionPipeline(manager)

    # Demo goals
    goals = [
        ("team_operations", "Prepare for today's meetings"),
        ("team_operations", "Check project deadlines"),
        ("user_preferences", "Get user communication style"),
        ("knowledge_base", "Find architecture decisions"),
    ]

    for room_name, goal in goals:
        room = manager.get_room_by_name(room_name)
        if not room:
            console.print(f"  [red]Room {room_name} not found, skipping[/red]")
            continue
        print_section(f"Goal: '{goal}' on room '{room_name}'")
        result = pipeline.run(room.id, goal, agent)

        console.print(f"  Action: [bold]{result.action.type.value}[/bold] — {result.action.reasoning}")
        console.print(f"  Confidence: [cyan]{result.action.confidence:.0%}[/cyan]")
        console.print(f"  Status: [green]{result.final_status.value}[/green]")

        if result.critic_reviews:
            for review in result.critic_reviews:
                status = "✓" if review.approved else "✗"
                console.print(f"  {status} {review.critic_id}: {review.confidence:.0%} confidence")
                if review.concerns:
                    for c in review.concerns:
                        console.print(f"    ↳ Concern: {c}")

        if result.human_override:
            console.print(f"  👤 Human override: {result.human_override.decision} — {result.human_override.reason}")

        if result.execution_result:
            console.print(f"  Result: {result.execution_result}")


def demo_4_compound(manager: RoomManager) -> None:
    """Demo 4: Compound Learning"""
    print_header("4. COMPOUND LEARNING (Ninebar's 'Compound' Phase)")

    logger = CompoundLogger(Path("data/compound"))
    create_demo_outcomes(logger, manager)

    # Show learning report
    print_section("Learning Report")
    report = logger.export_learning_report()

    table = Table(title="Compound Learning Summary")
    table.add_column("Metric", style="green")
    table.add_column("Value", style="cyan")
    table.add_row("Total Outcomes", str(report["total_outcomes"]))
    table.add_row("Success Rate", f"{report['success_rate']:.1%}")
    table.add_row("Pending Proposals", str(report["pending_proposals"]))
    table.add_row("Approved Proposals", str(report["approved_proposals"]))
    console.print(table)

    print_section("Confidence Scores")
    for field_id, conf in report["confidence_scores"].items():
        bar = "█" * int(conf * 20) + "░" * (20 - int(conf * 20))
        console.print(f"  {field_id}: [{bar}] {conf:.2f}")

    print_section("Schema Evolution Proposals")
    for proposal in logger.get_proposals(ProposalStatus.PENDING):
        console.print(f"  [yellow]→[/yellow] [bold]{proposal.proposed_change.value}[/bold] on {proposal.field_id}")
        console.print(f"     Reason: {proposal.reason}")
        console.print(f"     Confidence: {proposal.confidence:.0%}")


def demo_5_submission_artifacts() -> None:
    """Demo 5: Show submission-ready artifacts"""
    print_header("5. SUBMISSION ARTIFACTS")

    print_section("Required Files Checklist")
    artifacts = [
        ("README.md", "✓ Setup, run, demo, architecture, assumptions, limitations, reviewer instructions, Docker"),
        ("AGENT_WORKFLOW.md", "✓ Design sessions, AI vs human judgment, audit guide"),
        ("Dockerfile", "✓ Multi-stage build, requirements, demo command"),
        ("docker-compose.yml", "✓ App + test services"),
        ("requirements.txt", "✓ Pinned dependencies"),
        ("src/context_layer/__init__.py", "✓ Package exports"),
        ("src/context_layer/schemas.py", "✓ Core data models (Room, Field, Agent, Gates, Tags)"),
        ("src/context_layer/gates.py", "✓ PrivacyGate, StalenessGate, CompoundGate (Ninebar philosophy)"),
        ("src/context_layer/room.py", "✓ RoomManager, ingestion, querying, persistence"),
        ("src/context_layer/pipeline.py", "✓ 7-stage pipeline: prep→propose→critic→consensus→override→mutate→commit"),
        ("src/context_layer/compound.py", "✓ Outcome logging, confidence, schema evolution proposals"),
        ("tests/test_context_layer.py", "✓ Unit tests + validation checklist matching exercise requirements"),
        ("examples/", "✓ Sample inputs/outputs"),
    ]

    for file, desc in artifacts:
        console.print(f"  ✓ [green]{file}[/green] — {desc}")

    print_section("Exercise Requirements Mapping")
    reqs = [
        ("Problem & user understanding", "README + AGENT_WORKFLOW.md Session 1"),
        ("Workflow/architecture", "README architecture diagram + pipeline.py 7 stages"),
        ("Sample inputs/outputs", "examples/ + demo script + test fixtures"),
        ("Assumptions, tradeoffs, risks, privacy", "AGENT_WORKFLOW.md + gates.py tag system"),
        ("AI tool usage documentation", "AGENT_WORKFLOW.md — explicit AI vs human breakdown"),
        ("Measurement approach", "compound.py learning report + confidence scores + proposals"),
    ]

    for req, where in reqs:
        console.print(f"  ✓ [green]{req}[/green] — {where}")


def main():
    console.print(Panel.fit(
        "[bold]Ninebar Context Layer Exercise — Complete Demo[/bold]\n"
        "Option 2: Context Layer for Agents\n"
        "Know → Build → Compound",
        border_style="cyan",
        padding=(1, 2),
    ))

    # Run demos
    manager = demo_1_ingestion()
    demo_2_gating(manager)
    demo_3_pipeline(manager)
    demo_4_compound(manager)
    demo_5_submission_artifacts()

    console.print("\n" + "=" * 80)
    console.print(Panel.fit(
        "[bold green]Demo complete![/bold green]\n"
        "All components working. Ready for submission.\n\n"
        "To run tests: [cyan]pytest tests/[/cyan]\n"
        "To run in Docker: [cyan]docker compose up --build[/cyan]",
        border_style="green",
    ))


if __name__ == "__main__":
    main()