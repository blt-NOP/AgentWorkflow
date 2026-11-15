from ..config import Settings


class ModelClient:
    def __init__(self, settings: Settings):
        self.settings = settings

    async def complete(self, messages: list[dict], tools: list[dict] | None = None) -> dict:
        """Future provider adapter; credentials must only be used on the backend."""
        raise NotImplementedError("Model transport is not implemented")
