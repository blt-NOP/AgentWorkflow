from typing import Protocol


class SessionStore(Protocol):
    """A later implementation must isolate sessions and overwrite corrected facts."""

    async def load(self, session_id: str) -> dict: ...

    async def save(self, session_id: str, state: dict) -> None: ...

    async def clear(self, session_id: str) -> None: ...
