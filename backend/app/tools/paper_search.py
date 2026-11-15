async def search_papers(query: str, limit: int = 5) -> list[dict]:
    """Return verifiable paper metadata and links from a future search provider."""
    raise NotImplementedError("Choose and integrate a paper search provider")
