from __future__ import annotations

from abc import ABC, abstractmethod
import re
from typing import Any

_UNSET = object()


class ToolSelectionResult(list):
    """A list of selected tools that also supports direct awaiting."""

    def __await__(self):
        async def _coro():
            return self

        return _coro().__await__()


class BaseToolRouter(ABC):
    """Abstract interface defining tool selection and ranking for dynamic tool discovery."""

    @abstractmethod
    def select_tools(
        self,
        query: str,
        candidate_tools: list[Any],
        top_k: int | None = None,
    ) -> list[Any] | Any:
        """Filter and rank candidate tools based on query intent.

        May be implemented as synchronous or asynchronous method.
        """
        pass


def _tokenize(text: str | None) -> set[str]:
    """Tokenize text into lowercased words, splitting camelCase, snake_case, and kebab-case."""
    if not text:
        return set()

    # Split camelCase words (e.g. getUserProfile -> get User Profile)
    camel_split = re.sub(r"([a-z])([A-Z])", r"\1 \2", str(text))

    # Extract all alphanumeric sequences
    words = re.findall(r"[a-zA-Z0-9]+", camel_split.lower())
    tokens: set[str] = set()

    for w in words:
        tokens.add(w)
        # Normalize simple English plurals (e.g. users -> user)
        if len(w) > 3 and w.endswith("s"):
            tokens.add(w[:-1])

    return tokens


def _extract_tool_metadata(tool: Any) -> tuple[str, str, list[str]]:
    """Extract name, description, and tags from various tool representations."""
    name = ""
    description = ""
    tags: list[str] = []

    if isinstance(tool, dict):
        name = str(tool.get("name") or "")
        description = str(tool.get("description") or "")
        raw_tags = tool.get("tags") or []
        if isinstance(raw_tags, (list, tuple, set)):
            tags = [str(t) for t in raw_tags]
    else:
        name = str(getattr(tool, "name", "") or "")
        description = str(getattr(tool, "description", "") or "")

        raw_tags = None
        if hasattr(tool, "tags"):
            raw_tags = getattr(tool, "tags")
        elif hasattr(tool, "route") and getattr(tool.route, "tags", None):
            raw_tags = getattr(tool.route, "tags")
        elif hasattr(tool, "meta") and isinstance(tool.meta, dict):
            raw_tags = tool.meta.get("tags")

        if raw_tags and isinstance(raw_tags, (list, tuple, set)):
            tags = [str(t) for t in raw_tags]

    return name, description, tags


def _score_tool(
    tool: Any,
    query_str: str,
    query_tokens: set[str],
) -> float:
    """Compute relevance score for a candidate tool against the query."""
    name, description, tags = _extract_tool_metadata(tool)
    if not name and not description and not tags:
        return 0.0

    name_clean = name.lower().replace("-", "_").strip()
    query_clean = query_str.lower().replace("-", "_").strip()

    name_tokens = _tokenize(name)
    desc_tokens = _tokenize(description)
    tag_tokens: set[str] = set()
    for t in tags:
        tag_tokens.update(_tokenize(t))

    score = 0.0
    matched_any = False

    # Exact name match gets highest boost
    if query_clean and (query_clean == name_clean):
        score += 30.0
        matched_any = True
    elif query_clean and (query_clean in name_clean or name_clean in query_clean):
        score += 15.0
        matched_any = True

    # Exact tag match
    for t in tags:
        t_clean = t.lower().replace("-", "_").strip()
        if query_clean and query_clean == t_clean:
            score += 8.0
            matched_any = True
            break

    # Keyword overlap scoring: Name > Tag > Description
    for q in query_tokens:
        token_matched = False
        if q in name_tokens:
            score += 10.0
            token_matched = True
        if q in tag_tokens:
            score += 5.0
            token_matched = True
        if q in desc_tokens:
            score += 2.0
            token_matched = True

        if token_matched:
            matched_any = True

    if not matched_any:
        return 0.0

    return score


class KeywordTagRouter(BaseToolRouter):
    """Zero-dependency tool router ranking candidates by keyword and tag overlap."""

    def __init__(self, top_k: int | None = None, min_score: float = 0.0) -> None:
        self.top_k = top_k
        self.min_score = min_score

    def select_tools(
        self,
        query: str,
        candidate_tools: list[Any],
        top_k: int | None | object = _UNSET,
    ) -> ToolSelectionResult:
        q_tokens = _tokenize(query)
        if not q_tokens or not candidate_tools:
            return ToolSelectionResult([])

        scored_candidates: list[tuple[float, str, Any]] = []
        for tool in candidate_tools:
            s = _score_tool(tool, query, q_tokens)
            if s > self.min_score:
                name, _, _ = _extract_tool_metadata(tool)
                scored_candidates.append((s, name, tool))

        # Sort descending by score, then ascending by name for deterministic tie breaking
        scored_candidates.sort(key=lambda item: (-item[0], item[1]))

        selected = [item[2] for item in scored_candidates]
        limit = self.top_k if top_k is _UNSET else top_k
        if limit is not None:
            selected = selected[:limit]

        return ToolSelectionResult(selected)
