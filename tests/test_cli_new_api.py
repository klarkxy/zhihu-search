"""CLI coverage for the expanded Zhihu API catalog."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest

from zhihu_search import cli
from zhihu_search.commands import CommandResult


def test_parser_accepts_user_contents_contract() -> None:
    args = cli._build_parser().parse_args(
        [
            "user-contents",
            "--content-type",
            "zvideo",
            "--offset",
            "next-20",
            "--limit",
            "25",
            "--sort-field",
            "like_count",
            "--sort-order",
            "asc",
            "--oauth-token",
            "oauth-x",
            "--format",
            "json",
        ]
    )
    assert args.command == "user-contents"
    assert args.content_type == "zvideo"
    assert args.offset == "next-20"
    assert args.limit == 25
    assert args.oauth_token == "oauth-x"


def test_parser_accepts_mcp_tool_profile() -> None:
    args = cli._build_parser().parse_args(["serve", "--tools", "search,other"])
    assert args.command == "serve"
    assert args.tools == "search,other"


def test_serve_passes_tool_selection_to_server() -> None:
    with patch("zhihu_search.server.main") as server_main:
        exit_code = cli.main(["serve", "--tools", "full"])

    assert exit_code == 0
    server_main.assert_called_once_with(tool_selection="full")


def test_serve_reports_invalid_tool_selection(capsys) -> None:
    with patch(
        "zhihu_search.server.main",
        side_effect=ValueError("未知 MCP 工具：missing"),
    ):
        exit_code = cli.main(["serve", "--tools", "missing"])

    assert exit_code == 2
    assert "MCP 工具配置错误" in capsys.readouterr().err


def test_parser_requires_one_favlist_identifier() -> None:
    parser = cli._build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["favlist-contents"])
    with pytest.raises(SystemExit):
        parser.parse_args(
            ["favlist-contents", "--url-token", "1", "--id", "2"]
        )


def test_user_contents_json_dispatch(capsys) -> None:
    run_user_contents = AsyncMock(
        return_value=CommandResult(
            success=True,
            data={"Items": [], "Paging": {"IsEnd": True, "Totals": 0}},
        )
    )
    with patch.object(cli.commands, "run_user_contents", new=run_user_contents):
        exit_code = cli.main(
            [
                "user-contents",
                "--content-type",
                "answer",
                "--offset",
                "20",
                "--oauth-token",
                "oauth-x",
                "--format",
                "json",
            ]
        )

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["kind"] == "user_contents"
    kwargs = run_user_contents.await_args.kwargs
    assert kwargs["content_type"] == "answer"
    assert kwargs["offset"] == "20"
    assert kwargs["oauth_token"] == "oauth-x"


def test_pdf_upload_dispatches_local_path(capsys) -> None:
    run_pdf_upload = AsyncMock(
        return_value=CommandResult(
            success=True,
            data={"file_id": "file_123"},
        )
    )
    with patch.object(cli.commands, "run_pdf_upload", new=run_pdf_upload):
        exit_code = cli.main(["pdf-upload", "example.pdf", "--format", "json"])

    assert exit_code == 0
    assert json.loads(capsys.readouterr().out)["data"]["file_id"] == "file_123"
    assert run_pdf_upload.await_args.kwargs["file_path"] == "example.pdf"


def test_oauth_url_uses_documented_parameter_names(capsys) -> None:
    exit_code = cli.main(
        [
            "oauth-url",
            "app 1",
            "https://example.com/callback?a=1",
        ]
    )
    output = capsys.readouterr().out.strip()
    assert exit_code == 0
    assert output.startswith("https://openapi.zhihu.com/authorize?")
    assert "app_id=app+1" in output
    assert "redirect_uri=https%3A%2F%2Fexample.com%2Fcallback%3Fa%3D1" in output
    assert "response_type=code" in output
    assert "state=" not in output
    assert "scope=" not in output


def test_oauth_token_prefers_environment_app_key(monkeypatch, capsys) -> None:
    monkeypatch.setenv("ZHIHU_OAUTH_APP_KEY", "secret-from-env")
    exchange = AsyncMock(
        return_value={
            "access_token": "oauth-token",
            "token_type": "Bearer",
            "expires_in": 3600,
        }
    )
    with patch("zhihu_search.oauth.exchange_access_token", new=exchange):
        exit_code = cli.main(
            [
                "oauth-token",
                "app-id",
                "https://example.com/callback",
                "authorization-code",
            ]
        )

    assert exit_code == 0
    assert json.loads(capsys.readouterr().out)["access_token"] == "oauth-token"
    assert exchange.await_args.kwargs["app_key"] == "secret-from-env"


def test_oauth_token_fails_cleanly_without_app_key(monkeypatch, capsys) -> None:
    monkeypatch.delenv("ZHIHU_OAUTH_APP_KEY", raising=False)
    exit_code = cli.main(
        [
            "oauth-token",
            "app-id",
            "https://example.com/callback",
            "authorization-code",
        ]
    )
    captured = capsys.readouterr()
    assert exit_code == 1
    assert "ZHIHU_OAUTH_APP_KEY" in captured.err
