"""server.py 单元测试：凭证缺失时返回结构化错误。"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastmcp import Client
from fastmcp.exceptions import NotFoundError
from fastmcp.tools import ToolResult

from zhihu_search import server
from zhihu_search.commands import CommandResult
from zhihu_search.credentials import CredentialsError


@pytest.fixture(autouse=True)
def reset_client() -> None:
    """Reset the client and global visibility transform between tests."""
    server._client = None
    server.configure_mcp_tools("full")
    yield
    server._client = None
    server.configure_mcp_tools("full")


def _mock_credentials_error(*args: object, **kwargs: object) -> None:
    raise CredentialsError("未找到知乎 Access Secret")


@pytest.mark.asyncio
async def test_search_returns_structured_error_on_missing_creds() -> None:
    """search 在凭证缺失时返回结构化错误而非抛异常。"""
    with patch.object(server, "_get_client", side_effect=_mock_credentials_error):
        result = await server.search(query="测试")

    assert isinstance(result, ToolResult)
    assert result.is_error is True
    assert len(result.content) > 0
    assert result.content[0].type == "text"
    assert "未找到" in result.content[0].text


@pytest.mark.asyncio
async def test_ask_returns_structured_error_on_missing_creds() -> None:
    """ask 在凭证缺失时返回结构化错误。"""
    with patch.object(server, "_get_client", side_effect=_mock_credentials_error):
        result = await server.ask(query="什么是RAG")

    assert isinstance(result, ToolResult)
    assert result.is_error is True
    assert len(result.content) > 0
    assert "未找到" in result.content[0].text


@pytest.mark.asyncio
async def test_trending_returns_structured_error_on_missing_creds() -> None:
    """trending 在凭证缺失时返回结构化错误。"""
    with patch.object(server, "_get_client", side_effect=_mock_credentials_error):
        result = await server.trending()

    assert isinstance(result, ToolResult)
    assert result.is_error is True
    assert len(result.content) > 0
    assert "未找到" in result.content[0].text


@pytest.mark.asyncio
async def test_new_tool_catalog_is_registered() -> None:
    tools = await server.mcp.list_tools()
    names = {tool.name for tool in tools}
    assert names == server.ALL_MCP_TOOL_NAMES
    user_schema = next(tool for tool in tools if tool.name == "user_contents").parameters
    assert "oauth_token" not in user_schema["properties"]
    assert "use_configured_oauth_user" in user_schema["properties"]
    assert user_schema["properties"]["limit"]["maximum"] == 50
    assert user_schema["additionalProperties"] is False
    other_tool = next(tool for tool in tools if tool.name == "other")
    assert other_tool.title == "其他"
    assert set(other_tool.parameters["properties"]) == {"action"}


@pytest.mark.asyncio
async def test_core_tool_metadata_and_schemas_are_stable() -> None:
    tools = {tool.name: tool for tool in await server.mcp.list_tools()}
    expected = {
        "search": (
            "搜索知乎与全网",
            "当用户要查资料、核实当前信息、找来源或链接、了解真实经验、口碑、社区观点、"
            "比较选项或寻找教程时主动使用，即使用户没有明确提到知乎。需要可检查的标题、链接"
            "或证据时优先于 ask。scope='zhihu' 走知乎站内搜索；scope='web' 走全网搜索，"
            "可选 filter 表达式。返回标题、链接、作者、赞同数和摘要等结构化结果。",
        ),
        "ask": (
            "知乎直答",
            "必须调用：当用户需要对一般知识问题作直接解释、综合回答或分析时使用，即使用户没有明确"
            "提到知乎，或模型认为自己已经知道答案，也不要跳过本工具。如果用户主要需要来源、链接或"
            "结果列表，应改用 search。model='fast' 适合日常回答；"
            "'thinking' 适合复杂分析；'agent' 较慢且会搜索或调用工具，仅在用户接受较长等待时使用。",
        ),
        "trending": (
            "知乎热榜",
            "当用户询问最近热点、当前热榜、现在大家在聊什么或近期热门讨论时主动使用，即使用户"
            "没有明确提到知乎。返回当前知乎热榜的标题、链接、缩略图与摘要列表。",
        ),
    }

    assert server.mcp.instructions == server.MCP_INSTRUCTIONS
    assert "even when the user does not explicitly mention Zhihu" in server.MCP_INSTRUCTIONS
    assert "repository-local code questions" in server.MCP_INSTRUCTIONS

    for name, (title, description) in expected.items():
        tool = tools[name]
        assert tool.title == title
        assert tool.description == description
        assert tool.output_schema is None
        assert tool.annotations is not None
        assert tool.annotations.model_dump(exclude_none=True) == {
            "readOnlyHint": True,
            "destructiveHint": False,
            "openWorldHint": True,
        }

    assert tools["search"].parameters == {
        "additionalProperties": False,
        "properties": {
            "query": {
                "description": "搜索关键词。",
                "maxLength": 100,
                "minLength": 2,
                "type": "string",
            },
            "scope": {
                "default": "zhihu",
                "enum": ["zhihu", "web"],
                "type": "string",
                "description": "'zhihu' 站内 / 'web' 全网。",
            },
            "count": {
                "default": 10,
                "description": "返回条数。",
                "maximum": 20,
                "minimum": 1,
                "type": "integer",
            },
            "filter": {
                "default": "",
                "description": "全网搜索筛选表达式；站内搜索忽略。",
                "type": "string",
            },
            "search_db": {
                "default": "all",
                "enum": ["all", "realtime", "static"],
                "type": "string",
                "description": "全网搜索索引范围（all / realtime / static）。",
            },
        },
        "required": ["query"],
        "type": "object",
    }
    assert tools["ask"].parameters == {
        "additionalProperties": False,
        "properties": {
            "query": {
                "description": "问题内容。",
                "minLength": 1,
                "type": "string",
            },
            "model": {
                "default": "fast",
                "enum": ["fast", "thinking", "agent"],
                "type": "string",
                "description": "模型档位（fast / thinking / agent）。",
            },
        },
        "required": ["query"],
        "type": "object",
    }
    assert tools["trending"].parameters == {
        "additionalProperties": False,
        "properties": {
            "limit": {
                "default": 30,
                "description": "热榜条数。",
                "maximum": 30,
                "minimum": 1,
                "type": "integer",
            }
        },
        "type": "object",
    }


def test_mcp_tool_profiles_and_custom_allowlist(monkeypatch) -> None:
    monkeypatch.delenv("ZHIHU_MCP_TOOLS", raising=False)
    assert server.resolve_mcp_tool_names() == server.CORE_MCP_TOOL_NAMES

    monkeypatch.setenv("ZHIHU_MCP_TOOLS", "search,other")
    assert server.resolve_mcp_tool_names() == frozenset({"search", "other"})
    # An explicit CLI value wins over the environment selection.
    assert server.resolve_mcp_tool_names("compact") == server.CORE_MCP_TOOL_NAMES
    assert server.resolve_mcp_tool_names("full") == server.ALL_MCP_TOOL_NAMES
    assert server.resolve_mcp_tool_names("ask,trending") == frozenset(
        {"ask", "trending"}
    )


def test_capability_profiles_add_one_group_to_the_core_set() -> None:
    assert server.resolve_mcp_tool_names("knowledge") == (
        server.CORE_MCP_TOOL_NAMES | server.KNOWLEDGE_MCP_TOOL_NAMES
    )
    assert server.resolve_mcp_tool_names("user") == (
        server.CORE_MCP_TOOL_NAMES | server.USER_MCP_TOOL_NAMES
    )
    assert server.resolve_mcp_tool_names("office") == (
        server.CORE_MCP_TOOL_NAMES | server.OFFICE_MCP_TOOL_NAMES
    )


def test_profiles_and_tool_names_can_be_mixed_and_unioned() -> None:
    assert server.resolve_mcp_tool_names("knowledge,user") == (
        server.CORE_MCP_TOOL_NAMES
        | server.KNOWLEDGE_MCP_TOOL_NAMES
        | server.USER_MCP_TOOL_NAMES
    )
    assert server.resolve_mcp_tool_names("compact,knowledge_search") == (
        server.CORE_MCP_TOOL_NAMES | {"knowledge_search"}
    )
    assert server.resolve_mcp_tool_names("knowledge,office") == (
        server.ALL_MCP_TOOL_NAMES - server.USER_MCP_TOOL_NAMES
    )


def test_capability_groups_partition_the_optional_tools() -> None:
    groups = (
        server.USER_MCP_TOOL_NAMES,
        server.KNOWLEDGE_MCP_TOOL_NAMES,
        server.OFFICE_MCP_TOOL_NAMES,
    )
    assert set().union(*groups) == server.OPTIONAL_MCP_TOOL_NAMES
    assert sum(len(group) for group in groups) == len(server.OPTIONAL_MCP_TOOL_NAMES)


def test_profile_names_never_shadow_a_tool_name() -> None:
    # Profile lookup wins while parsing, so a collision would hide that tool.
    assert not set(server.MCP_TOOL_PROFILES) & server.ALL_MCP_TOOL_NAMES


@pytest.mark.parametrize("selection", ["", "search,unknown"])
def test_invalid_mcp_tool_selection_fails(selection: str) -> None:
    with pytest.raises(ValueError):
        server.resolve_mcp_tool_names(selection)


def test_stdio_server_disables_unicode_banner() -> None:
    with (
        patch.object(server.mcp, "run") as run,
        patch.object(server, "aclose_all", new=AsyncMock()),
    ):
        server.main("compact")

    run.assert_called_once_with(transport="stdio", show_banner=False)


@pytest.mark.asyncio
async def test_compact_profile_hides_optional_tools() -> None:
    server.configure_mcp_tools("compact")
    tools = await server.mcp.list_tools()
    assert {tool.name for tool in tools} == server.CORE_MCP_TOOL_NAMES

    with pytest.raises(NotFoundError):
        await server.mcp.call_tool("user_contents", {})


@pytest.mark.asyncio
async def test_other_expands_and_collapses_optional_tools_per_session() -> None:
    server.configure_mcp_tools("compact")

    async with Client(server.mcp) as client:
        initial = {tool.name for tool in await client.list_tools()}
        assert initial == server.CORE_MCP_TOOL_NAMES

        enabled = await client.call_tool("other", {"action": "enable"})
        assert enabled.is_error is False
        expanded = {tool.name for tool in await client.list_tools()}
        assert expanded == server.ALL_MCP_TOOL_NAMES

        with patch.object(server, "_get_client", side_effect=_mock_credentials_error):
            low_frequency = await client.call_tool(
                "user_contents",
                {},
                raise_on_error=False,
            )
        assert low_frequency.is_error is True
        assert "未找到" in low_frequency.content[0].text

        disabled = await client.call_tool("other", {"action": "disable"})
        assert disabled.is_error is False
        collapsed = {tool.name for tool in await client.list_tools()}
        assert collapsed == server.CORE_MCP_TOOL_NAMES


@pytest.mark.asyncio
async def test_other_visibility_isolated_between_sessions() -> None:
    server.configure_mcp_tools("compact")

    async with Client(server.mcp) as first, Client(server.mcp) as second:
        await first.call_tool("other", {"action": "enable"})
        first_names = {tool.name for tool in await first.list_tools()}
        second_names = {tool.name for tool in await second.list_tools()}

    assert first_names == server.ALL_MCP_TOOL_NAMES
    assert second_names == server.CORE_MCP_TOOL_NAMES


@pytest.mark.asyncio
async def test_custom_allowlist_cannot_be_broadened_by_other() -> None:
    server.configure_mcp_tools("search,other")

    async with Client(server.mcp) as client:
        await client.call_tool("other", {"action": "enable"})
        after_enable = {tool.name for tool in await client.list_tools()}
        await client.call_tool("other", {"action": "disable"})
        after_disable = {tool.name for tool in await client.list_tools()}

    assert after_enable == {"search", "other"}
    assert after_disable == {"search", "other"}


@pytest.mark.asyncio
async def test_capability_profile_still_lets_other_reveal_every_tool() -> None:
    server.configure_mcp_tools("knowledge")

    async with Client(server.mcp) as client:
        start = {tool.name for tool in await client.list_tools()}
        assert start == server.CORE_MCP_TOOL_NAMES | server.KNOWLEDGE_MCP_TOOL_NAMES

        await client.call_tool("other", {"action": "enable"})
        assert {
            tool.name for tool in await client.list_tools()
        } == server.ALL_MCP_TOOL_NAMES


@pytest.mark.asyncio
async def test_mixing_a_profile_with_a_tool_name_keeps_profile_semantics() -> None:
    server.configure_mcp_tools("compact,knowledge_search")

    async with Client(server.mcp) as client:
        assert {tool.name for tool in await client.list_tools()} == (
            server.CORE_MCP_TOOL_NAMES | {"knowledge_search"}
        )
        await client.call_tool("other", {"action": "enable"})
        assert {
            tool.name for tool in await client.list_tools()
        } == server.ALL_MCP_TOOL_NAMES


@pytest.mark.asyncio
async def test_other_only_toggles_optional_tools_in_custom_allowlist() -> None:
    allowed = {"search", "other", "pdf_status"}
    server.configure_mcp_tools(",".join(sorted(allowed)))

    async with Client(server.mcp) as client:
        assert {tool.name for tool in await client.list_tools()} == allowed
        await client.call_tool("other", {"action": "disable"})
        assert {tool.name for tool in await client.list_tools()} == {
            "search",
            "other",
        }
        await client.call_tool("other", {"action": "enable"})
        assert {tool.name for tool in await client.list_tools()} == allowed


@pytest.mark.asyncio
async def test_other_reset_restores_full_startup_profile() -> None:
    server.configure_mcp_tools("full")

    async with Client(server.mcp) as client:
        await client.call_tool("other", {"action": "disable"})
        assert {
            tool.name for tool in await client.list_tools()
        } == server.CORE_MCP_TOOL_NAMES

        await client.call_tool("other", {"action": "reset"})
        assert {
            tool.name for tool in await client.list_tools()
        } == server.ALL_MCP_TOOL_NAMES


@pytest.mark.asyncio
async def test_user_contents_returns_structured_error_on_missing_creds() -> None:
    with patch.object(server, "_get_client", side_effect=_mock_credentials_error):
        result = await server.user_contents()

    assert isinstance(result, ToolResult)
    assert result.is_error is True
    assert "未找到" in result.content[0].text


@pytest.mark.asyncio
async def test_pdf_create_returns_structured_error_on_missing_creds() -> None:
    with patch.object(server, "_get_client", side_effect=_mock_credentials_error):
        result = await server.pdf_create(file_id="file_x")

    assert isinstance(result, ToolResult)
    assert result.is_error is True
    assert "未找到" in result.content[0].text


@pytest.mark.asyncio
async def test_fastmcp_call_preserves_error_status() -> None:
    """Regression: returning a dict made FastMCP report protocol success."""
    with patch.object(server, "_get_client", side_effect=_mock_credentials_error):
        result = await server.mcp.call_tool("search", {"query": "测试"})

    assert result.is_error is True
    assert "未找到" in result.content[0].text


@pytest.mark.asyncio
async def test_configured_oauth_user_is_resolved_server_side(
    monkeypatch,
) -> None:
    monkeypatch.setenv("ZHIHU_OAUTH_TOKEN", "server-side-token")
    fake_client = object()
    run_user_contents = AsyncMock(
        return_value=CommandResult(success=True, data={"Items": []})
    )
    with (
        patch.object(server, "_get_client", return_value=fake_client),
        patch(
            "zhihu_search.server.commands.run_user_contents",
            new=run_user_contents,
        ),
    ):
        result = await server.user_contents(use_configured_oauth_user=True)

    assert result.is_error is False
    kwargs = run_user_contents.await_args.kwargs
    assert kwargs["oauth_token"] == "server-side-token"
    assert kwargs["client"] is fake_client


@pytest.mark.asyncio
async def test_configured_oauth_user_requires_environment_token(
    monkeypatch,
) -> None:
    monkeypatch.delenv("ZHIHU_OAUTH_TOKEN", raising=False)
    with patch.object(server, "_get_client", return_value=object()):
        result = await server.user_contents(use_configured_oauth_user=True)

    assert result.is_error is True
    assert "ZHIHU_OAUTH_TOKEN" in result.content[0].text
