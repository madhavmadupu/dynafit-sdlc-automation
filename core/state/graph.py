"""
core/state/graph.py
LangGraph StateGraph definition and compilation.
The pipeline: Ingestion → Retrieval → Matching → Classification → [interrupt] → Validation
"""

from __future__ import annotations

import structlog
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph

from core.state.requirement_state import RequirementState

log = structlog.get_logger()


def _route_after_classification(state: RequirementState) -> str:
    """
    Conditional edge: always routes to 'validation'.
    Human review is handled by interrupt_before=['validation'] — LangGraph pauses
    the graph before the validation node runs if there are items to review or conflicts.
    """
    return "validation"


def build_graph(checkpointer=None) -> object:
    """
    Build and compile the DYNAFIT LangGraph StateGraph.

    Args:
        checkpointer: LangGraph checkpointer (MemorySaver for dev, AsyncPostgresSaver for prod).
                      If None, defaults to in-memory MemorySaver.

    Returns:
        Compiled LangGraph graph with interrupt_before=['validation'].

    Usage:
        # Dev / testing:
        graph = build_graph()

        # Production:
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
        async with AsyncPostgresSaver.from_conn_string(settings.POSTGRES_URL) as saver:
            graph = build_graph(checkpointer=saver)
    """
    # Import agent run functions here to avoid circular imports
    from agents.classification import agent as classification_agent
    from agents.ingestion import agent as ingestion_agent
    from agents.matching import agent as matching_agent
    from agents.retrieval import agent as retrieval_agent
    from agents.validation import agent as validation_agent

    if checkpointer is None:
        checkpointer = MemorySaver()
        log.warning("graph.using_memory_saver", note="Use AsyncPostgresSaver in production")

    graph = StateGraph(RequirementState)  # type: ignore[type-var]

    # ── Nodes (one per pipeline phase) ───────────────────────────────────────
    graph.add_node("ingestion", ingestion_agent.run)
    graph.add_node("retrieval", retrieval_agent.run)
    graph.add_node("matching", matching_agent.run)
    graph.add_node("classification", classification_agent.run)
    graph.add_node("validation", validation_agent.run)

    # ── Edges ─────────────────────────────────────────────────────────────────
    graph.set_entry_point("ingestion")
    graph.add_edge("ingestion", "retrieval")
    graph.add_edge("retrieval", "matching")
    graph.add_edge("matching", "classification")
    graph.add_edge("classification", "validation")
    graph.add_edge("validation", END)

    # ── Compile with interrupt_before validation ───────────────────────────────
    # `interrupt_before=['validation']` means LangGraph automatically pauses
    # the graph BEFORE the validation node executes, regardless of state content.
    # The API layer (PATCH /runs/{id}/review) resumes via graph.ainvoke with decisions.
    compiled = graph.compile(
        checkpointer=checkpointer,
        interrupt_before=["validation"],
    )

    log.info(
        "graph.compiled",
        nodes=[
            "ingestion",
            "retrieval",
            "matching",
            "classification",
            "validation",
        ],
    )
    return compiled
