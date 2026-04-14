"""Web search tool using DuckDuckGo (no API key needed)."""

from __future__ import annotations

import re
from html import unescape
from typing import Any

import httpx

from autonoma.executor.tools.base import BaseTool


class WebSearchTool(BaseTool):
    """Search the web using DuckDuckGo."""

    @property
    def name(self) -> str:
        return "web_search"

    @property
    def description(self) -> str:
        return (
            "Search the web for current information. Use this when you need "
            "up-to-date facts, news, documentation, or any information you "
            "don't already know."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The search query",
                },
            },
            "required": ["query"],
        }

    async def execute(self, params: dict[str, Any]) -> str:
        query = params.get("query", "")
        if not query:
            return "Error: No search query provided."

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                # Use DuckDuckGo HTML search
                response = await client.get(
                    "https://html.duckduckgo.com/html/",
                    params={"q": query},
                    headers={"User-Agent": "Autonoma/0.1"},
                    follow_redirects=True,
                )
                response.raise_for_status()
                return self._parse_results(response.text, query)
        except httpx.HTTPError as e:
            return f"Search error: {e}"

    def _parse_results(self, html: str, query: str) -> str:
        """Extract search results from DuckDuckGo HTML response."""
        results = []

        # Extract result snippets
        snippet_pattern = re.compile(
            r'class="result__snippet"[^>]*>(.*?)</a>', re.DOTALL
        )
        title_pattern = re.compile(
            r'class="result__a"[^>]*>(.*?)</a>', re.DOTALL
        )
        url_pattern = re.compile(
            r'class="result__url"[^>]*>(.*?)</a>', re.DOTALL
        )

        snippets = snippet_pattern.findall(html)
        titles = title_pattern.findall(html)
        urls = url_pattern.findall(html)

        for i in range(min(5, len(titles))):
            title = self._clean_html(titles[i]) if i < len(titles) else ""
            snippet = self._clean_html(snippets[i]) if i < len(snippets) else ""
            url = self._clean_html(urls[i]).strip() if i < len(urls) else ""

            if title:
                results.append(f"**{title}**\n{url}\n{snippet}\n")

        if not results:
            return f"No results found for: {query}"

        return f"Search results for: {query}\n\n" + "\n".join(results)

    @staticmethod
    def _clean_html(text: str) -> str:
        """Strip HTML tags and decode entities."""
        text = re.sub(r"<[^>]+>", "", text)
        return unescape(text).strip()
