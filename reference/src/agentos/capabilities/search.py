"""
Search capability — DuckDuckGo Instant Answer API with mock fallback.

Uses https://api.duckduckgo.com/?q=QUERY&format=json&no_html=1
No API key required. Falls back to mock data when the API is unreachable.
"""
import json
import urllib.request
import urllib.error
import urllib.parse
from ..models import PlannedTask
from typing import Any

DDG_API_URL = "https://api.duckduckgo.com/"

def _fetch_ddg(query: str, sources: list[str] | None = None) -> str:
    """
    Query DuckDuckGo Instant Answer API.
    Returns formatted markdown-like text.
    """
    params = {
        "q": query,
        "format": "json",
        "no_html": "1",
        "skip_disambig": "1",
    }
    url = DDG_API_URL + "?" + urllib.parse.urlencode(params)

    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Agent-OS/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, urllib.error.HTTPError, OSError, json.JSONDecodeError):
        return _mock_fallback(query)

    return _format_ddg_response(data, query)


def _format_ddg_response(data: dict, query: str) -> str:
    """Format DuckDuckGo API response into readable text."""
    lines = [f"【Search Results】\nQuery: {query}\n"]

    # Abstract (Answer)
    abstract = data.get("Abstract", "") or ""
    if abstract:
        lines.append(f"▸ Summary: {abstract}\n")

    # Definition
    definition = data.get("Definition", "") or ""
    if definition:
        lines.append(f"▸ Definition: {definition}\n")

    # Infobox
    infobox = data.get("Infobox", None)
    if infobox and isinstance(infobox, dict):
        content = infobox.get("content", []) or []
        if content:
            lines.append("▸ Info:\n")
            for item in content:
                label = item.get("label", "") or ""
                val = item.get("value", "") or ""
                if label and val:
                    lines.append(f"   • {label}: {val}\n")

    # Related topics (first 3)
    related = data.get("RelatedTopics", []) or []
    if related:
        lines.append("\n▸ Related Topics:\n")
        count = 0
        for topic in related:
            if count >= 3:
                break
            text = topic.get("Text", "") or ""
            if text:
                lines.append(f"   • {text}\n")
                count += 1

    # Results from the API
    results = data.get("Results", []) or []
    if results:
        lines.append("\n▸ Results:\n")
        for i, r in enumerate(results[:5], 1):
            text = r.get("Text", "") or ""
            first_url = r.get("FirstURL", "") or ""
            if text:
                lines.append(f"  {i}. {text}\n")
            if first_url:
                lines.append(f"     {first_url}\n")

    if not abstract and not definition and not infobox and not related and not results:
        return _mock_fallback(query)

    return "\n".join(lines).strip()


def _mock_fallback(query: str) -> str:
    """Mock fallback when DuckDuckGo API is unavailable."""
    return (
        f"【Search Results】\n"
        f"Query: {query}\n\n"
        f"1. {query} — latest developments summary\n"
        f"2. {query} — industry analysis\n"
        f"3. Related market data\n\n"
        "(Note: DuckDuckGo API was unavailable; showing fallback mock data)"
    )


def search(task: PlannedTask, context: dict[str, Any]) -> str:
    query = task.params.get("query", "")
    sources = task.params.get("sources", None)
    return _fetch_ddg(query, sources)
