"""Workflow boundary; see docs/architecture.md before implementation."""


async def run_turn(session_id: str, message: str) -> dict:
    """Load state, clarify or execute tools, then persist the updated state."""
    raise NotImplementedError("Agent execution is not connected yet")
