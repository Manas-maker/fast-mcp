from mcp import types
import pytest

from fast_mcp.router import BaseToolRouter, KeywordTagRouter


def test_base_tool_router_cannot_be_instantiated():
    with pytest.raises(TypeError):
        BaseToolRouter()  # type: ignore[abstract]


def test_keyword_tag_router_empty_inputs():
    router = KeywordTagRouter()
    candidates = [
        {"name": "tool_a", "description": "Does something", "tags": ["a"]},
        {"name": "tool_b", "description": "Does something else", "tags": ["b"]},
    ]

    # Empty query string
    assert router.select_tools("", candidates) == []
    # Whitespace query
    assert router.select_tools("   ", candidates) == []
    # Punctuation only query
    assert router.select_tools("!@#$%", candidates) == []
    # Empty candidate tools
    assert router.select_tools("something", []) == []


def test_keyword_tag_router_filters_zero_overlap():
    router = KeywordTagRouter()
    candidates = [
        {"name": "create_invoice", "description": "Create a billing invoice", "tags": ["billing"]},
        {"name": "list_invoices", "description": "List existing billing invoices", "tags": ["billing"]},
        {"name": "send_email", "description": "Send notification email", "tags": ["notifications"]},
    ]

    results = router.select_tools("invoice", candidates)
    names = [r["name"] for r in results]

    assert "create_invoice" in names
    assert "list_invoices" in names
    assert "send_email" not in names


def test_keyword_tag_router_ranking_name_vs_tag_vs_description():
    router = KeywordTagRouter()
    candidates = [
        {
            "name": "export_data",
            "description": "Export reports for user account",
            "tags": ["export"],
        },
        {
            "name": "get_user",
            "description": "Fetch detailed information",
            "tags": ["general"],
        },
        {
            "name": "account_info",
            "description": "Information handler",
            "tags": ["user"],
        },
    ]

    results = router.select_tools("user", candidates)
    names = [r["name"] for r in results]

    # Name match ("get_user") should rank highest,
    # then tag match ("account_info" with tag "user"),
    # then description match ("export_data" with "user" in description).
    assert names[0] == "get_user"
    assert names[1] == "account_info"
    assert names[2] == "export_data"


def test_keyword_tag_router_exact_match_priority():
    router = KeywordTagRouter()
    candidates = [
        {"name": "get_user_preferences", "description": "Get preferences"},
        {"name": "get_user", "description": "Get user"},
        {"name": "get_user_role", "description": "Get role"},
    ]

    results = router.select_tools("get_user", candidates)
    assert len(results) == 3
    assert results[0]["name"] == "get_user"


def test_keyword_tag_router_multi_token_overlap():
    router = KeywordTagRouter()
    candidates = [
        {"name": "delete_user", "description": "Delete a user account", "tags": ["admin"]},
        {
            "name": "create_user_profile",
            "description": "Create a new user profile with settings",
            "tags": ["admin", "users"],
        },
        {"name": "audit_logs", "description": "Audit logging", "tags": ["logs"]},
    ]

    results = router.select_tools("create user profile", candidates)
    # create_user_profile matches all three tokens
    assert len(results) == 2
    assert results[0]["name"] == "create_user_profile"
    assert results[1]["name"] == "delete_user"


def test_keyword_tag_router_case_insensitivity_and_casing_conventions():
    router = KeywordTagRouter()
    candidates = [
        {"name": "getUserProfile", "description": "Retrieves profile", "tags": []},
        {"name": "get_user_history", "description": "History log", "tags": []},
        {"name": "get-user-settings", "description": "Settings", "tags": []},
    ]

    # Uppercase query
    results_upper = router.select_tools("USER", candidates)
    assert len(results_upper) == 3

    # Mixed-case tokens
    results_profile = router.select_tools("UserProfile", candidates)
    assert results_profile[0]["name"] == "getUserProfile"


def test_keyword_tag_router_plurals():
    router = KeywordTagRouter()
    candidates = [
        {"name": "get_user", "description": "Fetch user by ID", "tags": ["user"]},
        {"name": "list_products", "description": "Catalog", "tags": ["inventory"]},
    ]

    # Search with plural
    results = router.select_tools("users", candidates)
    assert len(results) == 1
    assert results[0]["name"] == "get_user"

    # Candidate with plural, search with singular
    candidates_plural = [
        {"name": "list_orders", "description": "List all customer orders", "tags": ["orders"]},
    ]
    results_order = router.select_tools("order", candidates_plural)
    assert len(results_order) == 1
    assert results_order[0]["name"] == "list_orders"


def test_keyword_tag_router_top_k_limiting():
    candidates = [
        {"name": f"tool_{i}", "description": f"Tool number {i} for user operations", "tags": ["user"]}
        for i in range(10)
    ]

    # Configured on router
    router = KeywordTagRouter(top_k=3)
    results = router.select_tools("user", candidates)
    assert len(results) == 3

    # Overridden per call
    results_custom = router.select_tools("user", candidates, top_k=5)
    assert len(results_custom) == 5

    # top_k=None returns all
    results_all = router.select_tools("user", candidates, top_k=None)
    assert len(results_all) == 10


def test_keyword_tag_router_candidate_types():
    router = KeywordTagRouter()

    # types.Tool candidate
    mcp_tool = types.Tool(
        name="calculate_tax",
        description="Calculates sales tax for cart",
        inputSchema={"type": "object"},
    )

    # Custom object candidate
    class CustomCandidate:
        def __init__(self, name: str, description: str, tags: list[str]) -> None:
            self.name = name
            self.description = description
            self.tags = tags

    custom_cand = CustomCandidate("generate_invoice", "Generate billing PDF", ["finance", "tax"])

    results = router.select_tools("tax", [mcp_tool, custom_cand])
    assert len(results) == 2
    assert mcp_tool in results
    assert custom_cand in results


@pytest.mark.asyncio
async def test_keyword_tag_router_sync_and_async_invocation():
    router = KeywordTagRouter()
    candidates = [{"name": "ping", "description": "Ping test", "tags": ["health"]}]

    # Sync call
    res_sync = router.select_tools("ping", candidates)
    assert len(res_sync) == 1
    assert res_sync[0]["name"] == "ping"

    # Async call
    res_async = await router.select_tools("ping", candidates)
    assert len(res_async) == 1
    assert res_async[0]["name"] == "ping"


@pytest.mark.asyncio
async def test_custom_router_implementation():
    class ReverseAlphabeticalRouter(BaseToolRouter):
        async def select_tools(
            self,
            query: str,
            candidate_tools: list,
            top_k: int | None = None,
        ) -> list:
            # Custom logic: return candidates sorted by name reversed
            return sorted(candidate_tools, key=lambda t: t["name"], reverse=True)

    router = ReverseAlphabeticalRouter()
    candidates = [{"name": "alpha"}, {"name": "charlie"}, {"name": "bravo"}]
    results = await router.select_tools("query", candidates)
    assert [r["name"] for r in results] == ["charlie", "bravo", "alpha"]


def test_keyword_tag_router_meta_tags_and_empty_candidate():
    router = KeywordTagRouter()

    class MetaCandidate:
        def __init__(self) -> None:
            self.name = "meta_tool"
            self.description = "Tool with meta dict"
            self.meta = {"tags": ["analytics"]}

    class EmptyCandidate:
        pass

    results = router.select_tools("analytics", [MetaCandidate(), EmptyCandidate()])
    assert len(results) == 1
    assert results[0].name == "meta_tool"
