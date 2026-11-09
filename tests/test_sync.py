"""知乎同步：凭证、适配、签名发布与确认门闩。不访问真实知乎。"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from pathlib import Path

import httpx
import pytest
import respx

from zhihu_search import cli, openapi_credentials, server
from zhihu_search.sync import api, content, media, service
from zhihu_search.sync.api import sign_request

SECRET = "quoted-secret-value"
KEY = "klarkxy"
GRANT = (
    '帮我配置知乎同步助手\n'
    'ZHIHU_OPENAPI_APP_KEY:"klarkxy";\n'
    'ZHIHU_OPENAPI_APP_SECRET:"quoted-secret-value"'
)
ARTICLE = {
    "type": "article",
    "title": "创造力，从何而来？",
    "body": "这是一段足够长的正文，用来通过最短长度。",
    "format": "markdown",
}


def test_authorization_text_round_trip_never_echoes_secret(capsys: pytest.CaptureFixture[str]) -> None:
    path = openapi_credentials.save_authorization(GRANT)
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["ZHIHU_OPENAPI_APP_KEY"] == KEY
    assert saved["ZHIHU_OPENAPI_APP_SECRET"] == SECRET
    assert path.stat().st_mode & 0o777 == 0o600

    status = openapi_credentials.describe()
    assert status["configured"] is True
    assert status["source"] == "file"
    assert status["app_key"] == KEY
    assert SECRET not in json.dumps(status)

    assert cli.main(["--check-openapi"]) == 0
    output = capsys.readouterr().out
    assert "file" in output
    assert KEY in output
    assert SECRET not in output
    assert str(path) not in output


def test_malformed_authorization_is_not_stored() -> None:
    with pytest.raises(openapi_credentials.OpenApiCredentialsError):
        openapi_credentials.save_authorization('说明 ZHIHU_OPENAPI_APP_KEY:"only-key"')
    assert not openapi_credentials.credentials_path().exists()


def test_env_conflicts_with_file_without_revealing_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    openapi_credentials.save_pair(KEY, SECRET)
    monkeypatch.setenv("ZHIHU_OPENAPI_APP_KEY", "other-user")
    monkeypatch.setenv("ZHIHU_OPENAPI_APP_SECRET", "different-secret-value")
    with pytest.raises(openapi_credentials.OpenApiCredentialsError) as caught:
        openapi_credentials.load()
    message = str(caught.value)
    assert "other-user" in message and KEY in message
    assert SECRET not in message
    assert "different-secret-value" not in message


def test_shared_file_is_fallback_and_clear_keeps_it(tmp_path: Path) -> None:
    shared = tmp_path / "shared-openapi.json"
    shared.write_text(
        json.dumps({"ZHIHU_OPENAPI_APP_KEY": KEY, "ZHIHU_OPENAPI_APP_SECRET": SECRET}),
        encoding="utf-8",
    )
    loaded = openapi_credentials.load()
    assert loaded.source == "shared"
    assert openapi_credentials.clear() is False
    assert openapi_credentials.load().source == "shared"


def test_question_mark_and_length_are_not_truncated() -> None:
    short = content.prepare_content({"type": "question", "title": "短", "body": "", "format": "markdown"})
    assert short["can_publish"] is False
    assert short["draft"]["title"] == "短？"
    assert any(issue["code"] == "title.too-short" for issue in short["issues"])

    long_title = "问" * 60
    long = content.prepare_content({"type": "question", "title": long_title, "body": "", "format": "markdown"})
    assert long["draft"]["title"] == long_title + "？"
    assert len(long["draft"]["title"]) == 61
    assert any(issue["code"] == "title.too-long" for issue in long["issues"])


def test_formula_keeps_inner_spaces_and_code_lang() -> None:
    latex = r" \eta = \frac{t_s}{t_s + 2t_p} = \frac{\dfrac{V}{C}}{\dfrac{V}{C} + 2t_p} "
    body = "公式前面有足够的汉字说明。\n\n$$" + latex + "$$\n\n```python\nprint(1)\n```\n\n```jsx\nconst x = 1\n```"
    prepared = content.prepare_content({"type": "article", "title": "公式说明", "body": body, "format": "markdown"})
    html = prepared["html"]
    assert prepared["can_publish"] is True
    assert f'alt="{latex}"' in html
    assert "tex=%20%5Ceta%20" in html
    assert html.endswith is not None
    assert 'lang="python"' in html
    assert 'lang=""' in html
    assert "<code>" not in html.split("<pre", 1)[1].split("</pre>", 1)[0]


def test_pin_link_topics_and_exclusive_media() -> None:
    prepared = content.prepare_content(
        {
            "type": "pin",
            "title": "",
            "body": "今天读完了 #读书笔记# [原文](https://example.com/post)",
            "format": "markdown",
        }
    )
    assert prepared["can_publish"] is True
    html = prepared["html"]
    assert 'class="hash_tag"' in html
    assert 'data-draft-type="text-link"' in html
    assert "<b>" not in html
    request = content.build_publish_request(prepared)
    assert "title" not in request["content"]
    assert request["content"]["comment_permission"] == "all"
    assert request["confirmed"] is True

    conflict = content.prepare_content(
        {
            "type": "pin",
            "title": "",
            "body": "同时有图和卡片。",
            "format": "markdown",
            "images": [{"url": "https://pic1.zhimg.com/v2-abc.png"}],
            "link_card": {"url": "https://example.com"},
        }
    )
    assert any(issue["code"] == "pin.media-linkcard-exclusive" for issue in conflict["issues"])
    with pytest.raises(ValueError):
        content.build_publish_request(conflict)


def test_dangerous_html_is_not_published() -> None:
    prepared = content.prepare_content(
        {
            "type": "article",
            "title": "危险内容示例",
            "body": '<p>可见文字足够长。</p><script>alert(1)</script>',
            "format": "html",
        }
    )
    assert prepared["can_publish"] is False
    assert prepared["html"] == ""
    assert "alert" not in prepared["html"]


def test_article_publish_request_topics_and_statement() -> None:
    prepared = content.prepare_content(
        {
            **ARTICLE,
            "settings": {
                "creation_statement": "ai_creation",
                "topics": [
                    "https://www.zhihu.com/topic/19555547/hot",
                    "https://www.zhihu.com/topic/19555547/hot",
                    "https://example.com/topic/1",
                ],
                "comment_permission": "follower",
            },
        }
    )
    assert any(issue["code"] == "topics.invalid" for issue in prepared["issues"])
    clean = content.prepare_content(
        {
            **ARTICLE,
            "settings": {
                "creation_statement": "ai_creation",
                "topics": ["https://www.zhihu.com/topic/19555547/hot"],
                "table_of_contents_enabled": True,
            },
        }
    )
    request = content.build_publish_request(clean)
    assert request["content"]["creation_statement"] == "ai_creation"
    assert request["content"]["topics"] == [{"topic_id": "", "topic_token": "19555547", "topic_name": ""}]
    assert request["content"]["table_of_contents_enabled"] is True
    assert request["content"]["comment_permission"] == "all"


def test_existing_zhihu_image_can_be_reused() -> None:
    prepared = content.prepare_content(
        {
            "type": "article",
            "title": "配图说明",
            "body": "这里有一张已经在知乎的图片，正文长度足够。\n\n![](https://pic1.zhimg.com/v2-abc.png)",
            "format": "markdown",
        }
    )
    assert prepared["can_publish"] is True
    assert "https://pic1.zhimg.com/v2-abc.png" in prepared["html"]
    assert "data-original-src=\"https://pic1.zhimg.com/v2-abc.png\"" in prepared["html"]


def test_daily_publish_attempt_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ZHIHU_SYNC_DAILY_PUBLISH_LIMIT", "1")
    openapi_credentials.save_pair(KEY, SECRET)

    async def published(*_args: object, **_kwargs: object) -> dict[str, object]:
        return {
            "type": "article",
            "url": "https://zhuanlan.zhihu.com/p/1",
            "content_token": "1",
            "http_status": 200,
        }

    monkeypatch.setattr(service, "publish_prepared", published)
    first = service.save_draft(ARTICLE)
    token = service.prepare_saved(first["id"])["preview_token"]
    _run(service.publish_draft(first["id"], confirmed=True, preview_token=token))
    second = service.save_draft(ARTICLE)
    token = service.prepare_saved(second["id"])["preview_token"]
    with pytest.raises(service.SyncServiceError) as caught:
        _run(service.publish_draft(second["id"], confirmed=True, preview_token=token))
    assert caught.value.code == "rate-limited"
    assert service.get_draft(second["id"]).get("publish_state") is None


def test_video_is_rejected_before_publish() -> None:
    prepared = content.prepare_content(
        {"type": "pin", "title": "", "body": "<video src='clip.mp4'></video>你好", "format": "html"}
    )
    assert content.VIDEO_UNSUPPORTED in " ".join(issue["message"] for issue in prepared["issues"])
    assert prepared["can_publish"] is False


@pytest.mark.asyncio
async def test_publish_signs_headers_and_redacts_secret() -> None:
    openapi_credentials.save_pair(KEY, SECRET)
    with respx.mock(assert_all_called=False) as router:
        route = router.post("https://openapi.zhihu.com/openapi/publish").mock(
            return_value=httpx.Response(
                200,
                json={"status": 1, "msg": f"failed {SECRET}", "data": None},
            )
        )
        prepared = content.prepare_content(ARTICLE)
        with pytest.raises(api.SyncApiError) as caught:
            await api.publish_prepared(prepared)
    request = route.calls[0].request
    assert request.headers["X-App-Key"] == KEY
    assert request.headers["X-Extra-Info"] == ""
    expected = sign_request(
        KEY,
        request.headers["X-Timestamp"],
        request.headers["X-Log-Id"],
        "",
        SECRET,
    )
    assert request.headers["X-Sign"] == expected
    assert hmac.compare_digest(request.headers["X-Sign"], expected)
    assert SECRET not in str(caught.value)
    assert caught.value.definite is True


@pytest.mark.asyncio
async def test_publish_success_requires_status_zero() -> None:
    openapi_credentials.save_pair(KEY, SECRET)
    prepared = content.prepare_content(ARTICLE)
    with respx.mock(assert_all_called=False) as router:
        router.post("https://openapi.zhihu.com/openapi/publish").mock(
            return_value=httpx.Response(
                200,
                json={
                    "status": 0,
                    "msg": "success",
                    "data": {
                        "type": "article",
                        "content_token": "123",
                        "url": "https://zhuanlan.zhihu.com/p/123",
                    },
                },
            )
        )
        published = await api.publish_prepared(prepared)
    assert published["url"] == "https://zhuanlan.zhihu.com/p/123"
    assert published["content_token"] == "123"


def test_publish_refuses_other_hosts(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ZHIHU_PUBLISH_BASE_URL", "https://example.com")
    with pytest.raises(api.SyncApiError) as caught:
        api._allowed_url("/openapi/publish")
    assert caught.value.code == "INVALID_URL"


def test_confirmation_gate_and_uncertain_lock(monkeypatch: pytest.MonkeyPatch) -> None:
    openapi_credentials.save_pair(KEY, SECRET)
    saved = service.save_draft(ARTICLE)
    prepared = service.prepare_saved(saved["id"])
    token = prepared["preview_token"]
    assert token
    with pytest.raises(service.SyncServiceError) as denied:
        _run(service.publish_draft(saved["id"], confirmed=False, preview_token=token))
    assert denied.value.code == "confirmation-required"

    async def uncertain(*_args: object, **_kwargs: object) -> dict[str, object]:
        raise api.SyncApiError("TIMEOUT", "超时", definite=False)

    monkeypatch.setattr(service, "publish_prepared", uncertain)
    with pytest.raises(service.SyncServiceError):
        _run(service.publish_draft(saved["id"], confirmed=True, preview_token=token))
    locked = service.get_draft(saved["id"])
    assert locked["publish_state"] == "uncertain"
    with pytest.raises(service.SyncServiceError) as blocked:
        service.prepare_saved(saved["id"])
    assert blocked.value.code == "publish-locked"


def test_definite_rejection_unlocks_without_echoing_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    openapi_credentials.save_pair(KEY, SECRET)
    saved = service.save_draft(ARTICLE)
    prepared = service.prepare_saved(saved["id"])

    async def rejected(*_args: object, **_kwargs: object) -> dict[str, object]:
        raise api.SyncApiError("UPSTREAM_REJECTED", "发布被拒绝", definite=True)

    monkeypatch.setattr(service, "publish_prepared", rejected)
    with pytest.raises(service.SyncServiceError) as caught:
        _run(service.publish_draft(saved["id"], confirmed=True, preview_token=prepared["preview_token"]))
    assert SECRET not in str(caught.value)
    record = service.get_draft(saved["id"])
    assert "publish_state" not in record
    assert service.prepare_saved(saved["id"])["preview_token"]


def test_cli_json_envelope_and_preview_file(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    body = tmp_path / "draft.md"
    body.write_text(ARTICLE["body"], encoding="utf-8")
    assert cli.main(
        [
            "sync-prepare",
            "--format",
            "json",
            "--type",
            "article",
            "--title",
            ARTICLE["title"],
            "--body-file",
            str(body),
        ]
    ) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["success"] is True
    assert payload["kind"] == "sync_prepare"
    draft_id = payload["data"]["record"]["id"]
    token = payload["data"]["preview_token"]
    output = tmp_path / "out"
    assert cli.main(["sync-preview", draft_id, "--output", str(output), "--format", "json"]) == 0
    preview = json.loads(capsys.readouterr().out)
    path = Path(preview["data"]["preview_path"])
    assert path.is_file()
    assert "尚未发布" in path.read_text(encoding="utf-8")
    assert SECRET not in path.read_text(encoding="utf-8")
    assert cli.main(["sync-publish", draft_id, "--preview-token", token, "--format", "json"]) == 1
    denied = json.loads(capsys.readouterr().out)
    assert denied["success"] is False
    assert "确认" in denied["error"]


@pytest.mark.asyncio
async def test_image_upload_uses_zhihu_url_and_hides_sts() -> None:
    openapi_credentials.save_pair(KEY, SECRET)
    png = bytes.fromhex(
        "89504e470d0a1a0a0000000d49484452" "0000000100000001"
    )
    stolen = "STS-SECRET-VALUE-SHOULD-NOT-LEAK"
    with respx.mock(assert_all_called=False) as router:
        router.post("https://openapi.zhihu.com/openapi/media/uploads").mock(
            return_value=httpx.Response(
                200,
                json={
                    "upload_state": "UPLOADING",
                    "session_key": "sess",
                    "upload_config": {
                        "vendor_code": "ali",
                        "address": {
                            "endpoint": "oss-cn-hangzhou.aliyuncs.com",
                            "bucket_name": "my-bucket",
                            "object_name": "obj/a.png",
                            "is_cname": False,
                        },
                    },
                    "upload_auth": {
                        "access_key_id": "akid",
                        "secret_access_key": stolen,
                        "security_token": stolen,
                        "expiration": 9999999999,
                    },
                    "upload_media": {
                        "commit_address": "https://openapi.zhihu.com/openapi/media/uploads/sess",
                        "key": "obj",
                        "processes": "",
                    },
                },
            )
        )
        router.put("https://my-bucket.oss-cn-hangzhou.aliyuncs.com/obj/a.png").mock(
            return_value=httpx.Response(403, text=f"<Error><Code>{stolen}</Code></Error>")
        )
        router.patch("https://openapi.zhihu.com/openapi/media/uploads/sess").mock(
            return_value=httpx.Response(
                200,
                json={
                    "upload_results": "UPLOAD_SUCCESS",
                    "media_key": "mk",
                    "media_url": {"primary": "https://pic1.zhimg.com/v2-original.png"},
                    "media_meta": {"width": 1, "height": 1},
                },
            )
        )
        router.get("https://openapi.zhihu.com/openapi/media/images/sess/watermark").mock(
            return_value=httpx.Response(404, json={"status": 4, "msg": "missing"})
        )
        with pytest.raises(media.SyncMediaError) as caught:
            await media.upload_image(file_name="a.png", content=png, scene="article")
    assert stolen not in str(caught.value)


def test_rejects_non_aliyun_oss_host() -> None:
    with pytest.raises(media.SyncMediaError):
        media._oss_host("https://evil.example/path")


@pytest.fixture
def restore_compact_tools() -> None:
    yield
    server.configure_mcp_tools("compact")


def test_sync_profile_is_opt_in_and_hides_secrets() -> None:
    assert server.resolve_mcp_tool_names("compact") == server.CORE_MCP_TOOL_NAMES
    assert server.SYNC_MCP_TOOL_NAMES.isdisjoint(server.ALL_MCP_TOOL_NAMES)
    assert server.resolve_mcp_tool_names("sync") == server.CORE_MCP_TOOL_NAMES | server.SYNC_MCP_TOOL_NAMES
    assert server.resolve_mcp_tool_names("full") == server.ALL_MCP_TOOL_NAMES


@pytest.mark.asyncio
async def test_sync_tools_are_hidden_until_profile_selected(restore_compact_tools: None) -> None:
    server.configure_mcp_tools("compact")
    listed = {tool.name for tool in await server.mcp.list_tools()}
    assert listed == server.CORE_MCP_TOOL_NAMES
    server.configure_mcp_tools("sync")
    tools = {tool.name: tool for tool in await server.mcp.list_tools()}
    assert set(tools) == server.CORE_MCP_TOOL_NAMES | server.SYNC_MCP_TOOL_NAMES
    for name, tool in tools.items():
        if not name.startswith("sync_"):
            continue
        schema = json.dumps(tool.parameters)
        assert "app_secret" not in schema
        assert "app_key" not in schema
        assert "access_secret" not in schema
    publish = tools["sync_publish"]
    assert publish.annotations is not None
    assert publish.annotations.destructiveHint is True
    assert publish.annotations.readOnlyHint is False
    result = await server.mcp.call_tool(
        "sync_publish",
        {"draft_id": "missing", "preview_token": "nope", "confirmed": False},
    )
    assert result.is_error is True
    body = json.loads(result.content[0].text)
    assert body["success"] is False
    assert "确认" in body["error"]


def _run(awaitable: object) -> object:
    import asyncio

    return asyncio.run(awaitable)  # type: ignore[arg-type]


def test_sign_matches_sha256() -> None:
    signature = sign_request("app", "10", "log", "", "secret")
    payload = b"app_key:app|ts:10|logid:log|extra_info:"
    digest = hmac.new(b"secret", payload, hashlib.sha256).digest()
    assert signature == base64.b64encode(digest).decode("ascii")
